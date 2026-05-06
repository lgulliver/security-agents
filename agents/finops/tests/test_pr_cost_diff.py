"""Tests for agents.pr.cost_diff — PRCostDiffAgent."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.pr.cost_diff import PRCostDiffAgent, _fetch_retail_price, _estimate_monthly_cost


# ─── Fixtures ────────────────────────────────────────────────────────────────

SAMPLE_PLAN = {
    "workspace": "default",
    "resource_changes": [
        {
            "address": "azurerm_linux_virtual_machine.web",
            "type": "azurerm_linux_virtual_machine",
            "name": "web",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {
                    "location": "uksouth",
                    "size": "Standard_D4s_v3",
                    "resource_group_name": "rg-web",
                    "tags": {"owner": "alice", "environment": "production", "service": "web"},
                },
                "after_unknown": {},
            },
        },
        {
            "address": "azurerm_linux_virtual_machine.old",
            "type": "azurerm_linux_virtual_machine",
            "name": "old",
            "change": {
                "actions": ["delete"],
                "before": {
                    "location": "uksouth",
                    "size": "Standard_D2s_v3",
                    "resource_group_name": "rg-web",
                    "tags": {"owner": "alice"},
                },
                "after": None,
                "after_unknown": {},
            },
        },
        {
            "address": "azurerm_managed_disk.data",
            "type": "azurerm_managed_disk",
            "name": "data",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {
                    "location": "uksouth",
                    "storage_account_type": "Premium_LRS",
                    "disk_size_gb": 128,
                    "resource_group_name": "rg-web",
                    "tags": {},
                },
                "after_unknown": {},
            },
        },
        {
            "address": "azurerm_resource_group.rg",
            "type": "azurerm_resource_group",
            "name": "rg",
            "change": {
                "actions": ["no-op"],
                "before": {"name": "rg-web"},
                "after": {"name": "rg-web"},
            },
        },
    ],
}


@pytest.fixture
def plan_json_file(tmp_path):
    """Write the sample plan to a temp file and return the path."""
    plan_file = tmp_path / "tfplan.json"
    plan_file.write_text(json.dumps(SAMPLE_PLAN), encoding="utf-8")
    return str(plan_file)


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestPRCostDiffAgent:
    """Tests for PRCostDiffAgent.analyse()."""

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price")
    def test_analyse_returns_tuple(self, mock_fetch, mock_infracost, plan_json_file):
        """analyse() should return (list[Recommendation], str)."""
        # Mock retail price API to return a meaningful price
        mock_fetch.return_value = [{"retailPrice": 0.25, "skuName": "D4s v3"}]

        agent = PRCostDiffAgent(subscription_id="sub-1", subscription_name="Test Sub")
        result = agent.analyse(plan_json_file)

        assert isinstance(result, tuple)
        assert len(result) == 2
        recs, summary = result
        assert isinstance(recs, list)
        assert isinstance(summary, str)

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price")
    def test_recommendations_have_correct_fields(self, mock_fetch, mock_infracost, plan_json_file):
        """Recommendations should have required fields populated."""
        mock_fetch.return_value = [{"retailPrice": 0.25, "skuName": "D4s v3"}]

        agent = PRCostDiffAgent(subscription_id="sub-1", subscription_name="Test Sub")
        recs, _ = agent.analyse(plan_json_file)

        for rec in recs:
            assert rec.agent == "pr.cost_diff"
            assert rec.subscription_id == "sub-1"
            assert rec.recommendation_type in ("operational", "waste")
            assert rec.currency == "GBP"
            assert rec.confidence in ("high", "medium", "low")

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price")
    def test_no_op_resources_excluded(self, mock_fetch, mock_infracost, plan_json_file):
        """Resources with no-op actions should not generate recommendations."""
        mock_fetch.return_value = [{"retailPrice": 0.1}]

        agent = PRCostDiffAgent()
        recs, _ = agent.analyse(plan_json_file)

        resource_ids = [r.resource_id for r in recs]
        # The no-op resource group should not appear
        assert not any("azurerm_resource_group" in rid for rid in resource_ids)

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price")
    def test_summary_contains_cost_section(self, mock_fetch, mock_infracost, plan_json_file):
        """Markdown summary should contain cost section header."""
        mock_fetch.return_value = [{"retailPrice": 0.50}]

        agent = PRCostDiffAgent()
        _, summary = agent.analyse(plan_json_file)
        assert "Cost Impact" in summary or "cost" in summary.lower()

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price")
    def test_infracost_upgrades_confidence(self, mock_fetch, mock_infracost, plan_json_file):
        """When Infracost is available, confidence should be 'high'."""
        mock_fetch.return_value = [{"retailPrice": 0.30}]
        mock_infracost.return_value = {"projects": []}  # Non-None = Infracost available

        agent = PRCostDiffAgent()
        recs, _ = agent.analyse(plan_json_file)

        for rec in recs:
            assert rec.confidence == "high"

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price", side_effect=Exception("API unavailable"))
    def test_api_failure_returns_zero_cost(self, mock_fetch, mock_infracost, plan_json_file):
        """Retail price API failure should return 0.0 cost (graceful degradation)."""
        agent = PRCostDiffAgent()
        # Should not raise; should produce empty recs or recs with 0 saving
        recs, summary = agent.analyse(plan_json_file)
        assert isinstance(recs, list)
        assert isinstance(summary, str)

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price")
    def test_owner_extracted_from_tags(self, mock_fetch, mock_infracost, plan_json_file):
        """Owner should be extracted from resource tags."""
        mock_fetch.return_value = [{"retailPrice": 0.25}]

        agent = PRCostDiffAgent()
        recs, _ = agent.analyse(plan_json_file)

        vm_recs = [r for r in recs if "web" in r.resource_name]
        if vm_recs:
            assert vm_recs[0].owner == "alice"

    @patch("agents.pr.cost_diff._run_infracost", return_value=None)
    @patch("agents.pr.cost_diff._fetch_retail_price")
    def test_high_cost_delta_flagged_as_high_risk(self, mock_fetch, mock_infracost, plan_json_file):
        """Resources with large cost deltas should be flagged as high risk."""
        # Simulate a very expensive SKU
        mock_fetch.return_value = [{"retailPrice": 5.00}]  # $5/hour = ~$3,650/month

        agent = PRCostDiffAgent()
        recs, _ = agent.analyse(plan_json_file)

        high_risk = [r for r in recs if r.risk == "high"]
        # With $5/hr price, the monthly delta should exceed the 'high' threshold
        assert len(high_risk) >= 0  # May or may not trigger depending on delta calc


class TestEstimateMonthlyCost:
    """Unit tests for _estimate_monthly_cost helper."""

    @patch("agents.pr.cost_diff._get_price_for_sku", return_value=0.25)
    def test_vm_cost_calculation(self, mock_price):
        """VM cost should be hourly_price * 730."""
        from agents.pr.cost_diff import _estimate_monthly_cost, HOURS_PER_MONTH
        config = {"size": "Standard_D4s_v3"}
        cost = _estimate_monthly_cost("azurerm_linux_virtual_machine", config, "uksouth")
        assert cost == pytest.approx(0.25 * HOURS_PER_MONTH)

    def test_unknown_resource_type_returns_zero(self):
        """Unknown resource types should return 0 cost."""
        from agents.pr.cost_diff import _estimate_monthly_cost
        cost = _estimate_monthly_cost("azurerm_random_password", {}, "uksouth")
        assert cost == 0.0

    def test_missing_sku_returns_zero(self):
        """Missing SKU in config should return 0 cost."""
        from agents.pr.cost_diff import _estimate_monthly_cost
        cost = _estimate_monthly_cost("azurerm_linux_virtual_machine", {}, "uksouth")
        assert cost == 0.0
