"""Tests for the Report Agent."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.weekly.report import ReportAgent
from agents.weekly.recommendation_prioritiser import RecommendationPrioritiser
from models.recommendation import Recommendation, RecommendationCollection


def _make_rec(
    rec_type: str = "rightsize",
    saving: float = 100.0,
    risk: str = "low",
    effort: str = "low",
    confidence: str = "high",
    owner: str = "team-a",
    env: str = "production",
    sub_id: str = "sub1",
    sub_name: str = "Test Sub",
    resource_name: str = "myres",
    resource_type: str = "Microsoft.Compute/virtualMachines",
    status: str = "open",
) -> Recommendation:
    return Recommendation(
        id=f"finops.test.{rec_type}.{id(rec_type)}",
        agent=f"weekly.{rec_type}",
        subscription_id=sub_id,
        subscription_name=sub_name,
        resource_id=f"/subscriptions/{sub_id}/rg/{resource_name}",
        resource_type=resource_type,
        resource_name=resource_name,
        resource_group="rg1",
        location="uksouth",
        owner=owner,
        environment=env,
        recommendation_type=rec_type,
        current_state={"sku": "Standard_D8s_v5"},
        recommended_state={"sku": "Standard_D4s_v5"},
        estimated_monthly_saving=saving,
        currency="GBP",
        confidence=confidence,
        risk=risk,
        effort=effort,
        reversibility="high",
        evidence=[{"source": "test"}],
        action={
            "mode": "advisory",
            "requires_approval": False,
            "rollback": "revert",
            "title": f"Test recommendation {rec_type}",
            "category": "create_issue",
        },
        status=status,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_collection(*recs: Recommendation) -> RecommendationCollection:
    prioritiser = RecommendationPrioritiser()
    return prioritiser.prioritise(list(recs))


REPORT_AGENT = ReportAgent()


class TestExecutiveSummary:
    def test_summary_contains_total_saving(self):
        rec = _make_rec(saving=500.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "500" in report
        assert "Executive Summary" in report

    def test_summary_contains_recommendation_count(self):
        recs = [_make_rec() for _ in range(3)]
        col = _make_collection(*recs)
        report = REPORT_AGENT.generate(col)
        assert "3" in report

    def test_summary_contains_date(self):
        col = _make_collection(_make_rec())
        report = REPORT_AGENT.generate(col)
        # Should contain current year
        assert "2026" in report or "2025" in report

    def test_recommendations_by_type_section(self):
        waste_rec = _make_rec(rec_type="waste", saving=200.0)
        rightsize_rec = _make_rec(rec_type="rightsize", saving=100.0)
        col = _make_collection(waste_rec, rightsize_rec)
        report = REPORT_AGENT.generate(col)
        assert "waste" in report
        assert "rightsize" in report


class TestSavingsBySubscription:
    def test_savings_by_sub_section(self):
        rec = _make_rec(sub_id="sub-abc", sub_name="My Subscription", saving=300.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "My Subscription" in report
        assert "sub-abc" in report

    def test_multiple_subscriptions(self):
        rec1 = _make_rec(sub_id="sub1", sub_name="Sub One", saving=100.0)
        rec2 = _make_rec(sub_id="sub2", sub_name="Sub Two", saving=200.0)
        col = _make_collection(rec1, rec2)
        report = REPORT_AGENT.generate(col)
        assert "Sub One" in report
        assert "Sub Two" in report

    def test_no_recs_no_subscription_section(self):
        col = RecommendationCollection()
        report = REPORT_AGENT.generate(col)
        assert "Savings by Subscription" not in report


class TestSavingsByOwner:
    def test_savings_by_owner_section(self):
        rec = _make_rec(owner="platform-team", saving=400.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "platform-team" in report

    def test_unknown_owner_shown(self):
        rec = _make_rec(owner="", saving=100.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "unknown" in report.lower() or "Owner" in report


class TestTop10:
    def test_top_10_section_present(self):
        recs = [_make_rec(saving=float(i * 10)) for i in range(5)]
        col = _make_collection(*recs)
        report = REPORT_AGENT.generate(col)
        assert "Top 10" in report

    def test_at_most_10_shown(self):
        recs = [_make_rec(saving=float(i)) for i in range(15)]
        col = _make_collection(*recs)
        report = REPORT_AGENT.generate(col)
        # Count "###" headings in the top 10 section (each recommendation gets one)
        assert "Top 10" in report

    def test_no_recs_no_top_section(self):
        col = RecommendationCollection()
        report = REPORT_AGENT.generate(col)
        assert "Top 10" not in report


class TestQuickWins:
    def test_quick_wins_section_present(self):
        rec = _make_rec(saving=100.0, effort="low", risk="low")
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "Quick Wins" in report

    def test_high_effort_not_in_quick_wins(self):
        rec = _make_rec(saving=100.0, effort="high", risk="low")
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "Quick Wins" not in report

    def test_cheap_rec_not_in_quick_wins(self):
        rec = _make_rec(saving=10.0, effort="low", risk="low")
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "Quick Wins" not in report


class TestHighRisk:
    def test_high_risk_section_present(self):
        rec = _make_rec(risk="high", saving=50.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "High-Risk" in report

    def test_high_saving_appears_in_high_risk(self):
        rec = _make_rec(risk="low", saving=2000.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "High-Risk" in report

    def test_low_risk_low_saving_not_in_high_risk(self):
        rec = _make_rec(risk="low", saving=50.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "High-Risk" not in report


class TestReservationSection:
    def test_reservation_section_present(self):
        rec = _make_rec(rec_type="reserve", saving=200.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "Reservation" in report

    def test_no_reservation_recs_no_section(self):
        rec = _make_rec(rec_type="rightsize", saving=200.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "Reservation" not in report


class TestWasteSection:
    def test_waste_section_present(self):
        rec = _make_rec(rec_type="waste", saving=50.0)
        rec.current_state["waste_classification"] = "safe_to_delete"
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "Waste" in report

    def test_no_waste_recs_no_section(self):
        rec = _make_rec(rec_type="rightsize", saving=50.0)
        col = _make_collection(rec)
        report = REPORT_AGENT.generate(col)
        assert "Waste" not in report


class TestPreviousRecommendations:
    def test_unresolved_previous_section(self):
        prev_rec = _make_rec(saving=100.0, status="open")
        prev_rec.id = "finops.prev.001"
        current_rec = _make_rec(saving=200.0)
        col = _make_collection(current_rec)
        report = REPORT_AGENT.generate(col, previous_recommendations=[prev_rec])
        assert "Unresolved" in report

    def test_resolved_previous_not_shown(self):
        prev_rec = _make_rec(saving=100.0, status="resolved")
        prev_rec.id = "finops.prev.002"
        current_rec = _make_rec(saving=200.0)
        col = _make_collection(current_rec)
        report = REPORT_AGENT.generate(col, previous_recommendations=[prev_rec])
        assert "Unresolved" not in report

    def test_new_anomalies_section(self):
        prev_rec = _make_rec(rec_type="anomaly", saving=50.0)
        prev_rec.id = "finops.old.anomaly"
        new_anomaly = _make_rec(rec_type="anomaly", saving=50.0)
        new_anomaly.id = "finops.new.anomaly"
        col = _make_collection(new_anomaly)
        report = REPORT_AGENT.generate(col, previous_recommendations=[prev_rec])
        assert "Newly Detected" in report

    def test_no_previous_recs_no_unresolved(self):
        col = _make_collection(_make_rec())
        report = REPORT_AGENT.generate(col, previous_recommendations=None)
        assert "Unresolved" not in report


class TestReportStructure:
    def test_report_is_markdown_string(self):
        col = _make_collection(_make_rec())
        report = REPORT_AGENT.generate(col)
        assert isinstance(report, str)
        assert "#" in report

    def test_empty_collection_produces_report(self):
        col = RecommendationCollection()
        report = REPORT_AGENT.generate(col)
        assert isinstance(report, str)
        assert "Executive Summary" in report
