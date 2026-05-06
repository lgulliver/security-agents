"""Tests for the PR review and weekly analysis entrypoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from models.recommendation import Recommendation, RecommendationCollection


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_rec(
    rec_type: str = "tagging",
    saving: float = 0.0,
    action_mode: str = "advisory",
) -> Recommendation:
    return Recommendation(
        id=f"finops.test.{rec_type}.001",
        agent=f"pr.{rec_type}",
        subscription_id="sub1",
        subscription_name="Test",
        resource_id="/subscriptions/sub1/rg/res1",
        resource_type="azurerm_linux_virtual_machine",
        resource_name="myvm",
        resource_group="rg1",
        location="uksouth",
        owner="platform",
        environment="production",
        recommendation_type=rec_type,
        current_state={"sku": "Standard_D8s_v5"},
        recommended_state={"sku": "Standard_D4s_v5"},
        estimated_monthly_saving=saving,
        currency="GBP",
        confidence="high",
        risk="low",
        effort="low",
        reversibility="high",
        evidence=[{"source": "test"}],
        action={
            "mode": action_mode,
            "requires_approval": False,
            "rollback": "revert",
            "title": f"Test {rec_type}",
            "category": "create_issue",
        },
        status="open",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_collection(*recs) -> RecommendationCollection:
    from agents.weekly.recommendation_prioritiser import RecommendationPrioritiser
    return RecommendationPrioritiser().prioritise(list(recs))


# ─────────────────────────────────────────────────────────────────────────────
# PR Review entrypoint
# ─────────────────────────────────────────────────────────────────────────────

class TestPRReviewParser:
    def test_build_parser_returns_parser(self):
        from entrypoints.pr_review import build_parser
        parser = build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_requires_plan_json(self):
        from entrypoints.pr_review import build_parser
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_defaults(self):
        from entrypoints.pr_review import build_parser
        parser = build_parser()
        args = parser.parse_args(["--plan-json", "tfplan.json"])
        assert args.mode == "advisory"
        assert args.output_format == "markdown"
        assert args.pr_number == 0


class TestBuildPRMarkdown:
    def test_returns_markdown_string(self):
        from entrypoints.pr_review import _build_pr_markdown
        col = _make_collection(_make_rec("tagging", 50.0))
        result = _build_pr_markdown(col, "", {}, "advisory")
        assert isinstance(result, str)
        assert "FinOps PR Review" in result

    def test_includes_cost_summary(self):
        from entrypoints.pr_review import _build_pr_markdown
        col = _make_collection()
        result = _build_pr_markdown(col, "## Cost Summary\n\nNo changes.", {}, "advisory")
        assert "Cost Summary" in result

    def test_includes_tagging_summary(self):
        from entrypoints.pr_review import _build_pr_markdown
        col = _make_collection()
        tagging_summary = {
            "missing": ["res1", "res2"],
            "conditional_missing": ["res3"],
            "compliant": ["res4"],
        }
        result = _build_pr_markdown(col, "", tagging_summary, "advisory")
        assert "Tagging Summary" in result
        assert "2" in result  # 2 missing

    def test_includes_top_findings_table(self):
        from entrypoints.pr_review import _build_pr_markdown
        rec = _make_rec("tagging", 100.0)
        col = _make_collection(rec)
        result = _build_pr_markdown(col, "", {}, "advisory")
        assert "Top Findings" in result


class TestPRReviewRun:
    def _mock_plan_file(self, tmp_path, content: dict | None = None) -> str:
        plan_file = tmp_path / "tfplan.json"
        plan_file.write_text(json.dumps(content or {"resource_changes": []}))
        return str(plan_file)

    def test_run_advisory_mode_returns_0(self, tmp_path):
        from entrypoints.pr_review import run, build_parser

        plan_path = self._mock_plan_file(tmp_path)
        args = build_parser().parse_args([
            "--plan-json", plan_path,
            "--mode", "advisory",
        ])

        with patch("entrypoints.pr_review.PRCostDiffAgent") as mock_cost, \
             patch("entrypoints.pr_review.PRSKUSanityAgent") as mock_sku, \
             patch("entrypoints.pr_review.PRTaggingAgent") as mock_tag, \
             patch("entrypoints.pr_review.PRLifecycleWasteAgent") as mock_lifecycle:

            mock_cost.return_value.analyse.return_value = ([], "")
            mock_sku.return_value.analyse.return_value = []
            mock_tag.return_value.analyse.return_value = ([], {})
            mock_lifecycle.return_value.analyse.return_value = []

            exit_code = run(args)

        assert exit_code == 0

    def test_run_blocking_mode_with_blocking_finding_returns_1(self, tmp_path):
        from entrypoints.pr_review import run, build_parser

        plan_path = self._mock_plan_file(tmp_path)
        args = build_parser().parse_args([
            "--plan-json", plan_path,
            "--mode", "blocking",
        ])

        blocking_rec = _make_rec("tagging", 0.0, action_mode="blocking")

        with patch("entrypoints.pr_review.PRCostDiffAgent") as mock_cost, \
             patch("entrypoints.pr_review.PRSKUSanityAgent") as mock_sku, \
             patch("entrypoints.pr_review.PRTaggingAgent") as mock_tag, \
             patch("entrypoints.pr_review.PRLifecycleWasteAgent") as mock_lifecycle:

            mock_cost.return_value.analyse.return_value = ([], "")
            mock_sku.return_value.analyse.return_value = []
            mock_tag.return_value.analyse.return_value = ([blocking_rec], {})
            mock_lifecycle.return_value.analyse.return_value = []

            exit_code = run(args)

        assert exit_code == 1

    def test_run_json_output_format(self, tmp_path, capsys):
        from entrypoints.pr_review import run, build_parser

        plan_path = self._mock_plan_file(tmp_path)
        args = build_parser().parse_args([
            "--plan-json", plan_path,
            "--output-format", "json",
        ])

        with patch("entrypoints.pr_review.PRCostDiffAgent") as mock_cost, \
             patch("entrypoints.pr_review.PRSKUSanityAgent") as mock_sku, \
             patch("entrypoints.pr_review.PRTaggingAgent") as mock_tag, \
             patch("entrypoints.pr_review.PRLifecycleWasteAgent") as mock_lifecycle:

            mock_cost.return_value.analyse.return_value = ([], "")
            mock_sku.return_value.analyse.return_value = []
            mock_tag.return_value.analyse.return_value = ([], {})
            mock_lifecycle.return_value.analyse.return_value = []

            exit_code = run(args)
            captured = capsys.readouterr()

        assert exit_code == 0
        # JSON output should be a valid JSON array
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)

    def test_run_agent_failure_handled_gracefully(self, tmp_path):
        from entrypoints.pr_review import run, build_parser

        plan_path = self._mock_plan_file(tmp_path)
        args = build_parser().parse_args(["--plan-json", plan_path])

        with patch("entrypoints.pr_review.PRCostDiffAgent") as mock_cost, \
             patch("entrypoints.pr_review.PRSKUSanityAgent") as mock_sku, \
             patch("entrypoints.pr_review.PRTaggingAgent") as mock_tag, \
             patch("entrypoints.pr_review.PRLifecycleWasteAgent") as mock_lifecycle:

            mock_cost.return_value.analyse.side_effect = Exception("parse error")
            mock_sku.return_value.analyse.side_effect = Exception("sku error")
            mock_tag.return_value.analyse.side_effect = Exception("tag error")
            mock_lifecycle.return_value.analyse.side_effect = Exception("lifecycle error")

            # Should not raise, should return 0 in advisory mode
            exit_code = run(args)

        assert exit_code == 0

    def test_run_posts_pr_comment_when_tokens_provided(self, tmp_path):
        from entrypoints.pr_review import run, build_parser

        plan_path = self._mock_plan_file(tmp_path)
        args = build_parser().parse_args([
            "--plan-json", plan_path,
            "--github-token", "ghp_test",
            "--repo", "owner/repo",
            "--pr-number", "7",
        ])

        with patch("entrypoints.pr_review.PRCostDiffAgent") as mock_cost, \
             patch("entrypoints.pr_review.PRSKUSanityAgent") as mock_sku, \
             patch("entrypoints.pr_review.PRTaggingAgent") as mock_tag, \
             patch("entrypoints.pr_review.PRLifecycleWasteAgent") as mock_lifecycle, \
             patch("entrypoints.pr_review.GitHubIntegrationAgent") as mock_gh_cls:

            mock_cost.return_value.analyse.return_value = ([], "")
            mock_sku.return_value.analyse.return_value = []
            mock_tag.return_value.analyse.return_value = ([], {})
            mock_lifecycle.return_value.analyse.return_value = []
            mock_gh_cls.return_value.post_pr_comment.return_value = None

            run(args)

        mock_gh_cls.return_value.post_pr_comment.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Weekly Analysis entrypoint
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeklyAnalysisParser:
    def test_build_parser_returns_parser(self):
        from entrypoints.weekly_analysis import build_parser
        parser = build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_defaults(self):
        from entrypoints.weekly_analysis import build_parser
        parser = build_parser()
        args = parser.parse_args([])
        assert args.output_dir == "./reports"
        assert args.create_issues is False
        assert args.cost_lookback_days == 30


class TestBuildIssueBody:
    def test_build_issue_body_contains_rec_fields(self):
        from entrypoints.weekly_analysis import _build_issue_body
        rec = _make_rec("rightsize", 250.0)
        rec.subscription_name = "MySub"
        body = _build_issue_body(rec)
        assert "rightsize" in body
        assert "myvm" in body
        assert "250" in body


class TestWeeklyAnalysisRun:
    def _make_run_mocks(self):
        """Return a dict of mock patches for all agents."""
        return {
            "discovery": Mock(return_value=Mock(discover=Mock(return_value=[
                {"subscription_id": "sub1", "name": "Sub One", "tenant_id": "t1",
                 "management_group_path": "", "tags": {}, "owner": ""}
            ]))),
            "inventory": Mock(return_value=Mock(collect=Mock(return_value=[]))),
            "cost": Mock(return_value=Mock(collect=Mock(return_value=[]))),
            "advisor": Mock(return_value=Mock(collect=Mock(return_value=[]))),
            "metrics": Mock(return_value=Mock(collect=Mock(return_value={}))),
            "rightsizing": Mock(return_value=Mock(analyse=Mock(return_value=[]))),
            "reservation": Mock(return_value=Mock(analyse=Mock(return_value=[]))),
            "waste": Mock(return_value=Mock(analyse=Mock(return_value=[]))),
            "operational": Mock(return_value=Mock(analyse=Mock(return_value=[]))),
            "anomaly": Mock(return_value=Mock(analyse=Mock(return_value=[]))),
        }

    def test_run_returns_0_on_success(self, tmp_path):
        from entrypoints.weekly_analysis import run, build_parser

        args = build_parser().parse_args([
            "--subscription-ids", "sub1",
            "--output-dir", str(tmp_path),
        ])

        mocks = self._make_run_mocks()

        with patch("entrypoints.weekly_analysis.SubscriptionDiscoveryAgent", mocks["discovery"]), \
             patch("entrypoints.weekly_analysis.EstateInventoryAgent", mocks["inventory"]), \
             patch("entrypoints.weekly_analysis.CostDataCollector", mocks["cost"]), \
             patch("entrypoints.weekly_analysis.AdvisorCollector", mocks["advisor"]), \
             patch("entrypoints.weekly_analysis.MetricsCollector", mocks["metrics"]), \
             patch("entrypoints.weekly_analysis.RightsizingAgent", mocks["rightsizing"]), \
             patch("entrypoints.weekly_analysis.ReservationAgent", mocks["reservation"]), \
             patch("entrypoints.weekly_analysis.WasteOrphanAgent", mocks["waste"]), \
             patch("entrypoints.weekly_analysis.OperationalFinOpsAgent", mocks["operational"]), \
             patch("entrypoints.weekly_analysis.AnomalyTrendAgent", mocks["anomaly"]):

            exit_code = run(args)

        assert exit_code == 0

    def test_run_writes_report_to_disk(self, tmp_path):
        from entrypoints.weekly_analysis import run, build_parser

        args = build_parser().parse_args([
            "--subscription-ids", "sub1",
            "--output-dir", str(tmp_path),
        ])

        mocks = self._make_run_mocks()

        with patch("entrypoints.weekly_analysis.SubscriptionDiscoveryAgent", mocks["discovery"]), \
             patch("entrypoints.weekly_analysis.EstateInventoryAgent", mocks["inventory"]), \
             patch("entrypoints.weekly_analysis.CostDataCollector", mocks["cost"]), \
             patch("entrypoints.weekly_analysis.AdvisorCollector", mocks["advisor"]), \
             patch("entrypoints.weekly_analysis.MetricsCollector", mocks["metrics"]), \
             patch("entrypoints.weekly_analysis.RightsizingAgent", mocks["rightsizing"]), \
             patch("entrypoints.weekly_analysis.ReservationAgent", mocks["reservation"]), \
             patch("entrypoints.weekly_analysis.WasteOrphanAgent", mocks["waste"]), \
             patch("entrypoints.weekly_analysis.OperationalFinOpsAgent", mocks["operational"]), \
             patch("entrypoints.weekly_analysis.AnomalyTrendAgent", mocks["anomaly"]):

            run(args)

        # Report file should have been written
        report_files = list(tmp_path.glob("finops-report-*.md"))
        assert len(report_files) == 1

    def test_run_returns_1_when_no_subscriptions(self, tmp_path):
        from entrypoints.weekly_analysis import run, build_parser

        args = build_parser().parse_args(["--output-dir", str(tmp_path)])

        discovery_mock = Mock(return_value=Mock(discover=Mock(return_value=[])))

        with patch("entrypoints.weekly_analysis.SubscriptionDiscoveryAgent", discovery_mock):
            exit_code = run(args)

        assert exit_code == 1

    def test_run_handles_discovery_failure_with_fallback(self, tmp_path):
        from entrypoints.weekly_analysis import run, build_parser

        args = build_parser().parse_args([
            "--subscription-ids", "sub1",
            "--output-dir", str(tmp_path),
        ])

        # Discovery fails → falls back to explicit sub IDs
        discovery_mock = Mock(return_value=Mock(discover=Mock(side_effect=Exception("auth error"))))

        mocks = self._make_run_mocks()
        mocks["discovery"] = discovery_mock

        with patch("entrypoints.weekly_analysis.SubscriptionDiscoveryAgent", discovery_mock), \
             patch("entrypoints.weekly_analysis.EstateInventoryAgent", mocks["inventory"]), \
             patch("entrypoints.weekly_analysis.CostDataCollector", mocks["cost"]), \
             patch("entrypoints.weekly_analysis.AdvisorCollector", mocks["advisor"]), \
             patch("entrypoints.weekly_analysis.MetricsCollector", mocks["metrics"]), \
             patch("entrypoints.weekly_analysis.RightsizingAgent", mocks["rightsizing"]), \
             patch("entrypoints.weekly_analysis.ReservationAgent", mocks["reservation"]), \
             patch("entrypoints.weekly_analysis.WasteOrphanAgent", mocks["waste"]), \
             patch("entrypoints.weekly_analysis.OperationalFinOpsAgent", mocks["operational"]), \
             patch("entrypoints.weekly_analysis.AnomalyTrendAgent", mocks["anomaly"]):

            exit_code = run(args)

        # Falls back to explicit sub IDs
        assert exit_code == 0

    def test_run_agent_failures_handled_gracefully(self, tmp_path):
        from entrypoints.weekly_analysis import run, build_parser

        args = build_parser().parse_args([
            "--subscription-ids", "sub1",
            "--output-dir", str(tmp_path),
        ])

        discovery_mock = Mock(return_value=Mock(discover=Mock(return_value=[
            {"subscription_id": "sub1", "name": "Sub One", "tenant_id": "t1",
             "management_group_path": "", "tags": {}, "owner": ""}
        ])))

        failing_mock = Mock(return_value=Mock(
            collect=Mock(side_effect=Exception("Azure auth error")),
            analyse=Mock(side_effect=Exception("Azure auth error")),
        ))

        with patch("entrypoints.weekly_analysis.SubscriptionDiscoveryAgent", discovery_mock), \
             patch("entrypoints.weekly_analysis.EstateInventoryAgent", failing_mock), \
             patch("entrypoints.weekly_analysis.CostDataCollector", failing_mock), \
             patch("entrypoints.weekly_analysis.AdvisorCollector", failing_mock), \
             patch("entrypoints.weekly_analysis.MetricsCollector", failing_mock), \
             patch("entrypoints.weekly_analysis.RightsizingAgent", failing_mock), \
             patch("entrypoints.weekly_analysis.ReservationAgent", failing_mock), \
             patch("entrypoints.weekly_analysis.WasteOrphanAgent", failing_mock), \
             patch("entrypoints.weekly_analysis.OperationalFinOpsAgent", failing_mock), \
             patch("entrypoints.weekly_analysis.AnomalyTrendAgent", failing_mock):

            # Should not raise
            exit_code = run(args)

        assert exit_code == 0

    def test_run_creates_github_issues_when_configured(self, tmp_path):
        from entrypoints.weekly_analysis import run, build_parser

        args = build_parser().parse_args([
            "--subscription-ids", "sub1",
            "--output-dir", str(tmp_path),
            "--github-token", "ghp_test",
            "--repo", "owner/repo",
            "--create-issues",
        ])

        mocks = self._make_run_mocks()

        with patch("entrypoints.weekly_analysis.SubscriptionDiscoveryAgent", mocks["discovery"]), \
             patch("entrypoints.weekly_analysis.EstateInventoryAgent", mocks["inventory"]), \
             patch("entrypoints.weekly_analysis.CostDataCollector", mocks["cost"]), \
             patch("entrypoints.weekly_analysis.AdvisorCollector", mocks["advisor"]), \
             patch("entrypoints.weekly_analysis.MetricsCollector", mocks["metrics"]), \
             patch("entrypoints.weekly_analysis.RightsizingAgent", mocks["rightsizing"]), \
             patch("entrypoints.weekly_analysis.ReservationAgent", mocks["reservation"]), \
             patch("entrypoints.weekly_analysis.WasteOrphanAgent", mocks["waste"]), \
             patch("entrypoints.weekly_analysis.OperationalFinOpsAgent", mocks["operational"]), \
             patch("entrypoints.weekly_analysis.AnomalyTrendAgent", mocks["anomaly"]), \
             patch("entrypoints.weekly_analysis.GitHubIntegrationAgent") as mock_gh:

            mock_gh.return_value.create_issue.return_value = 42
            run(args)

        # With no recommendations to create issues for, create_issue may not be called
        # But the integration path was executed
        assert mock_gh.called


class TestCreateGitHubIssues:
    def test_create_issues_for_top_candidates(self, tmp_path):
        from entrypoints.weekly_analysis import _create_github_issues, build_parser

        args = build_parser().parse_args([
            "--subscription-ids", "sub1",
            "--output-dir", str(tmp_path),
            "--github-token", "ghp_test",
            "--repo", "owner/repo",
            "--create-issues",
        ])

        rec = _make_rec("rightsize", 500.0)
        rec.action["category"] = "auto_fix_candidate"
        from agents.weekly.recommendation_prioritiser import RecommendationPrioritiser
        collection = RecommendationPrioritiser().prioritise([rec])

        with patch("entrypoints.weekly_analysis.GitHubIntegrationAgent") as mock_gh_cls:
            mock_gh_cls.return_value.create_issue.return_value = 10
            _create_github_issues(collection, args)

        mock_gh_cls.return_value.create_issue.assert_called()

    def test_create_issues_gh_failure_logged(self, tmp_path):
        from entrypoints.weekly_analysis import _create_github_issues, build_parser

        args = build_parser().parse_args([
            "--subscription-ids", "sub1",
            "--output-dir", str(tmp_path),
            "--github-token", "ghp_test",
            "--repo", "owner/repo",
            "--create-issues",
        ])

        rec = _make_rec("rightsize", 500.0)
        rec.action["category"] = "auto_fix_candidate"
        from agents.weekly.recommendation_prioritiser import RecommendationPrioritiser
        collection = RecommendationPrioritiser().prioritise([rec])

        with patch("entrypoints.weekly_analysis.GitHubIntegrationAgent") as mock_gh_cls:
            mock_gh_cls.return_value.create_issue.side_effect = Exception("API error")
            # Should not raise
            _create_github_issues(collection, args)
