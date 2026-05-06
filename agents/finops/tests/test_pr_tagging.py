"""Tests for agents.pr.tagging — PRTaggingAgent."""

from __future__ import annotations

import json
import pytest

from agents.pr.tagging import PRTaggingAgent


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_plan(resources: list[dict]) -> dict:
    """Helper to build a minimal Terraform plan dict."""
    return {
        "workspace": "default",
        "resource_changes": resources,
    }


def _resource_change(
    res_type: str,
    name: str,
    tags: dict,
    location: str = "uksouth",
    rg: str = "rg-test",
    action: str = "create",
) -> dict:
    """Build a Terraform resource_change dict."""
    return {
        "address": f"{res_type}.{name}",
        "type": res_type,
        "name": name,
        "change": {
            "actions": [action],
            "before": None,
            "after": {
                "location": location,
                "resource_group_name": rg,
                "tags": tags,
            },
            "after_unknown": {},
        },
    }


def _write_plan(tmp_path, plan: dict) -> str:
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return str(p)


# ─── Tests: required tags ────────────────────────────────────────────────────

class TestRequiredTags:
    """Tests for required tag enforcement."""

    def test_all_required_tags_present(self, tmp_path):
        """Resource with all required tags should appear in compliant list."""
        tags = {
            "owner": "alice",
            "service": "web",
            "product": "shop",
            "environment": "production",
            "cost_center": "cc-001",
            "criticality": "high",
            "managed_by": "terraform",
        }
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", tags)])
        agent = PRTaggingAgent()
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0
        assert "azurerm_linux_virtual_machine.vm1" in summary["compliant"]

    def test_missing_owner_tag(self, tmp_path):
        """Resource missing 'owner' tag should generate a recommendation."""
        tags = {
            "service": "web",
            "product": "shop",
            "environment": "production",
            "cost_center": "cc-001",
            "criticality": "high",
            "managed_by": "terraform",
        }
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", tags)])
        agent = PRTaggingAgent()
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 1
        assert "owner" in recs[0].current_state["missing_required"]
        assert "azurerm_linux_virtual_machine.vm1" in summary["missing"]

    def test_multiple_missing_tags(self, tmp_path):
        """Resource missing multiple tags should report all missing in one recommendation."""
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", {})])
        agent = PRTaggingAgent()
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 1
        missing = recs[0].current_state["missing_required"]
        assert "owner" in missing
        assert "service" in missing

    def test_no_op_resources_excluded(self, tmp_path):
        """Resources with no-op action should not generate recommendations."""
        tags = {}  # Even with missing tags
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", tags, action="no-op")])
        agent = PRTaggingAgent()
        recs, _ = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0

    def test_skip_resource_types_excluded(self, tmp_path):
        """Resource types in SKIP_RESOURCE_TYPES should not be checked."""
        plan = _make_plan([_resource_change("azurerm_role_assignment", "ra1", {})])
        agent = PRTaggingAgent()
        recs, _ = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0

    def test_non_azurerm_resources_excluded(self, tmp_path):
        """Non-azurerm resources should not be checked."""
        plan = _make_plan([_resource_change("random_password", "pw1", {})])
        agent = PRTaggingAgent()
        recs, _ = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0

    def test_custom_required_tags(self, tmp_path):
        """Custom required tags should override defaults."""
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", {"team": "eng"})])
        agent = PRTaggingAgent(required_tags=["team"])
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0
        assert "azurerm_linux_virtual_machine.vm1" in summary["compliant"]


# ─── Tests: conditional expiry_date tag ─────────────────────────────────────

class TestConditionalExpiryDate:
    """Tests for expiry_date conditional tag for ephemeral environments."""

    @pytest.mark.parametrize("env", ["test", "sandbox", "preview", "temporary", "ephemeral", "dev"])
    def test_missing_expiry_date_in_ephemeral_env(self, tmp_path, env):
        """Resources in ephemeral environments without expiry_date should be flagged."""
        tags = {
            "owner": "alice",
            "service": "web",
            "product": "shop",
            "environment": env,
            "cost_center": "cc-001",
            "criticality": "low",
            "managed_by": "terraform",
        }
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", tags)])
        agent = PRTaggingAgent()
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))

        # Should have conditional missing for expiry_date
        conditional_recs = [r for r in recs if r.current_state.get("missing_conditional")]
        assert len(conditional_recs) >= 1
        assert "expiry_date" in conditional_recs[0].current_state["missing_conditional"]
        assert "azurerm_linux_virtual_machine.vm1" in summary["conditional_missing"]

    def test_expiry_date_present_in_ephemeral_env(self, tmp_path):
        """Resource in ephemeral env with expiry_date should be compliant."""
        tags = {
            "owner": "alice",
            "service": "web",
            "product": "shop",
            "environment": "test",
            "cost_center": "cc-001",
            "criticality": "low",
            "managed_by": "terraform",
            "expiry_date": "2025-12-31",
        }
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", tags)])
        agent = PRTaggingAgent()
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0
        assert "azurerm_linux_virtual_machine.vm1" in summary["compliant"]

    def test_no_expiry_date_required_in_production(self, tmp_path):
        """Production resources should NOT require expiry_date."""
        tags = {
            "owner": "alice",
            "service": "web",
            "product": "shop",
            "environment": "production",
            "cost_center": "cc-001",
            "criticality": "high",
            "managed_by": "terraform",
        }
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", tags)])
        agent = PRTaggingAgent()
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0


# ─── Tests: advisory vs blocking mode ───────────────────────────────────────

class TestTaggingMode:
    """Tests for advisory vs blocking mode behaviour."""

    def test_advisory_mode_action(self, tmp_path):
        """Advisory mode recommendations should have mode='advisory'."""
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", {})])
        agent = PRTaggingAgent(mode="advisory")
        recs, _ = agent.analyse(_write_plan(tmp_path, plan))
        assert recs[0].action["mode"] == "advisory"
        assert recs[0].action["requires_approval"] is False

    def test_blocking_mode_action(self, tmp_path):
        """Blocking mode recommendations should have mode='blocking'."""
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", {})])
        agent = PRTaggingAgent(mode="blocking")
        recs, _ = agent.analyse(_write_plan(tmp_path, plan))
        assert recs[0].action["mode"] == "blocking"
        assert recs[0].action["requires_approval"] is True

    def test_recommendation_type_is_tagging(self, tmp_path):
        """Tagging recommendations should have recommendation_type='tagging'."""
        plan = _make_plan([_resource_change("azurerm_linux_virtual_machine", "vm1", {})])
        agent = PRTaggingAgent()
        recs, _ = agent.analyse(_write_plan(tmp_path, plan))
        assert recs[0].recommendation_type == "tagging"

    def test_multiple_resources(self, tmp_path):
        """Multiple resources in a plan should each be evaluated independently."""
        full_tags = {
            "owner": "alice",
            "service": "web",
            "product": "shop",
            "environment": "production",
            "cost_center": "cc-001",
            "criticality": "high",
            "managed_by": "terraform",
        }
        plan = _make_plan([
            _resource_change("azurerm_linux_virtual_machine", "vm1", {}),          # Missing all
            _resource_change("azurerm_linux_virtual_machine", "vm2", full_tags),   # Compliant
        ])
        agent = PRTaggingAgent()
        recs, summary = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 1
        assert len(summary["compliant"]) == 1
        assert len(summary["missing"]) == 1
