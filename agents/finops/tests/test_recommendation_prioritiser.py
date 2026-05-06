"""Tests for agents.weekly.recommendation_prioritiser — RecommendationPrioritiser."""

from __future__ import annotations

from datetime import datetime

import pytest

from agents.weekly.recommendation_prioritiser import (
    RecommendationPrioritiser,
    _assign_action_category,
    _compute_priority_score,
    _confidence_score,
    _effort_inverse_score,
    _risk_inverse_score,
    _reversibility_score,
    _saving_score,
)
from models.recommendation import Recommendation, RecommendationCollection


def _make_rec(**overrides) -> Recommendation:
    """Factory for creating test recommendations."""
    defaults = dict(
        id=f"test.{id(overrides)}",
        agent="test",
        subscription_id="sub-1",
        subscription_name="Test Sub",
        resource_id="/sub/1/res",
        resource_type="microsoft.compute/virtualmachines",
        resource_name="vm1",
        resource_group="rg1",
        location="uksouth",
        recommendation_type="rightsize",
        confidence="high",
        risk="low",
        effort="low",
        reversibility="high",
        estimated_monthly_saving=100.0,
        evidence=[],
        action={"mode": "advisory", "requires_approval": False, "rollback": ""},
        created_at=datetime(2024, 1, 1),
    )
    defaults.update(overrides)
    return Recommendation(**defaults)


class TestScoreHelpers:
    """Unit tests for individual score helper functions."""

    def test_saving_score_large_saving(self):
        assert _saving_score(2000.0) == 40.0

    def test_saving_score_medium_saving(self):
        score = _saving_score(500.0)
        assert 20.0 <= score <= 35.0

    def test_saving_score_zero(self):
        assert _saving_score(0.0) >= 0.0

    def test_confidence_score_high(self):
        assert _confidence_score("high") == 20.0

    def test_confidence_score_medium(self):
        assert _confidence_score("medium") < 20.0

    def test_confidence_score_low(self):
        assert _confidence_score("low") < _confidence_score("medium")

    def test_effort_inverse_low_effort_highest(self):
        assert _effort_inverse_score("low") > _effort_inverse_score("medium")
        assert _effort_inverse_score("medium") > _effort_inverse_score("high")

    def test_risk_inverse_low_risk_highest(self):
        assert _risk_inverse_score("low") > _risk_inverse_score("medium")
        assert _risk_inverse_score("medium") > _risk_inverse_score("high")

    def test_reversibility_high_highest(self):
        assert _reversibility_score("high") > _reversibility_score("medium")
        assert _reversibility_score("medium") > _reversibility_score("low")

    def test_total_score_max(self):
        """Perfect recommendation should score near 100."""
        rec = _make_rec(
            estimated_monthly_saving=2000.0,
            confidence="high",
            risk="low",
            effort="low",
            reversibility="high",
        )
        score = _compute_priority_score(rec)
        assert score == pytest.approx(40.0 + 20.0 + 15.0 + 15.0 + 10.0)


class TestActionCategoryAssignment:
    """Tests for _assign_action_category."""

    def test_auto_fix_candidate(self):
        rec = _make_rec(
            estimated_monthly_saving=600.0,
            risk="low",
            confidence="high",
            effort="low",
        )
        assert _assign_action_category(rec) == "auto_fix_candidate"

    def test_finance_approval_required(self):
        rec = _make_rec(
            estimated_monthly_saving=2500.0,
            risk="low",
            confidence="high",
            effort="low",
        )
        assert _assign_action_category(rec) == "finance_approval_required"

    def test_create_pr(self):
        rec = _make_rec(
            estimated_monthly_saving=200.0,
            risk="low",
            confidence="medium",
            effort="low",
        )
        assert _assign_action_category(rec) == "create_pr"

    def test_needs_owner_review_low_confidence(self):
        rec = _make_rec(
            estimated_monthly_saving=150.0,
            risk="low",
            confidence="low",
            effort="low",
        )
        assert _assign_action_category(rec) == "needs_owner_review"

    def test_needs_owner_review_high_risk(self):
        rec = _make_rec(
            estimated_monthly_saving=150.0,
            risk="high",
            confidence="high",
            effort="low",
        )
        assert _assign_action_category(rec) == "needs_owner_review"

    def test_suppressed_status_preserved(self):
        rec = _make_rec(status="suppressed")
        assert _assign_action_category(rec) == "suppressed"

    def test_accepted_waste_status_preserved(self):
        rec = _make_rec(status="accepted_waste")
        assert _assign_action_category(rec) == "accepted_waste"

    def test_small_saving_creates_issue(self):
        rec = _make_rec(
            estimated_monthly_saving=20.0,
            risk="low",
            confidence="high",
            effort="low",
        )
        assert _assign_action_category(rec) == "create_issue"


class TestPrioritiser:
    """Integration tests for RecommendationPrioritiser.prioritise()."""

    def test_returns_recommendation_collection(self):
        prioritiser = RecommendationPrioritiser()
        recs = [_make_rec(id=f"r{i}", estimated_monthly_saving=float(i * 100)) for i in range(5)]
        result = prioritiser.prioritise(recs)
        assert isinstance(result, RecommendationCollection)

    def test_empty_list_returns_empty_collection(self):
        prioritiser = RecommendationPrioritiser()
        result = prioritiser.prioritise([])
        assert len(result) == 0

    def test_sorted_by_priority_descending(self):
        prioritiser = RecommendationPrioritiser()
        recs = [
            _make_rec(id="low", estimated_monthly_saving=10.0),
            _make_rec(id="high", estimated_monthly_saving=2000.0),
            _make_rec(id="mid", estimated_monthly_saving=500.0),
        ]
        result = prioritiser.prioritise(recs)
        scores = [r.priority_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_priority_score_populated(self):
        prioritiser = RecommendationPrioritiser()
        recs = [_make_rec()]
        result = prioritiser.prioritise(recs)
        assert result.items[0].priority_score > 0.0

    def test_action_category_populated(self):
        prioritiser = RecommendationPrioritiser()
        recs = [_make_rec(estimated_monthly_saving=600.0, risk="low", confidence="high")]
        result = prioritiser.prioritise(recs)
        assert "category" in result.items[0].action

    def test_all_recs_get_category(self):
        prioritiser = RecommendationPrioritiser()
        recs = [
            _make_rec(id=f"r{i}", estimated_monthly_saving=float(i * 50))
            for i in range(10)
        ]
        result = prioritiser.prioritise(recs)
        for rec in result:
            assert "category" in rec.action

    def test_mixed_recommendation_types(self):
        prioritiser = RecommendationPrioritiser()
        recs = [
            _make_rec(recommendation_type="rightsize", estimated_monthly_saving=300.0),
            _make_rec(recommendation_type="waste", estimated_monthly_saving=50.0),
            _make_rec(recommendation_type="tagging", estimated_monthly_saving=0.0),
        ]
        result = prioritiser.prioritise(recs)
        assert len(result) == 3

    def test_high_saving_ranked_first(self):
        prioritiser = RecommendationPrioritiser()
        recs = [
            _make_rec(id="small", estimated_monthly_saving=10.0),
            _make_rec(id="large", estimated_monthly_saving=5000.0),
        ]
        result = prioritiser.prioritise(recs)
        assert result.items[0].id == "large"

    def test_suppressed_recs_preserved(self):
        prioritiser = RecommendationPrioritiser()
        recs = [_make_rec(status="suppressed")]
        result = prioritiser.prioritise(recs)
        assert result.items[0].action.get("category") == "suppressed"
