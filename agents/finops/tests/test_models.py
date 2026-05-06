"""Tests for models.recommendation — Recommendation and RecommendationCollection."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from models.recommendation import Recommendation, RecommendationCollection


def _make_rec(**overrides) -> Recommendation:
    """Factory helper to create a valid Recommendation with sensible defaults."""
    defaults = dict(
        id="finops.test.001",
        agent="test_agent",
        subscription_id="sub-123",
        subscription_name="My Subscription",
        resource_id="/subscriptions/sub-123/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
        resource_type="microsoft.compute/virtualmachines",
        resource_name="vm1",
        resource_group="rg1",
        location="uksouth",
        owner="alice",
        environment="production",
        recommendation_type="rightsize",
        current_state={"sku": "Standard_D8s_v3"},
        recommended_state={"sku": "Standard_D4s_v3"},
        estimated_monthly_saving=150.0,
        currency="GBP",
        confidence="high",
        risk="low",
        effort="medium",
        reversibility="high",
        evidence=[{"source": "azure_monitor", "cpu_avg_%": 5.0}],
        action={"mode": "advisory", "requires_approval": False, "rollback": "revert"},
        created_at=datetime(2024, 1, 15, 10, 0, 0),
    )
    defaults.update(overrides)
    return Recommendation(**defaults)


class TestRecommendationCreation:
    """Test Recommendation model creation and validation."""

    def test_valid_recommendation(self):
        rec = _make_rec()
        assert rec.id == "finops.test.001"
        assert rec.agent == "test_agent"
        assert rec.estimated_monthly_saving == 150.0
        assert rec.currency == "GBP"
        assert rec.status == "open"
        assert rec.priority_score == 0.0

    def test_default_currency_is_gbp(self):
        rec = _make_rec()
        assert rec.currency == "GBP"

    def test_default_status_is_open(self):
        rec = _make_rec()
        assert rec.status == "open"

    def test_default_priority_score_is_zero(self):
        rec = _make_rec()
        assert rec.priority_score == 0.0

    def test_empty_tags_default(self):
        rec = _make_rec()
        assert rec.tags == {}

    def test_custom_tags(self):
        rec = _make_rec(tags={"env": "prod", "owner": "alice"})
        assert rec.tags["env"] == "prod"

    def test_invalid_recommendation_type_raises(self):
        with pytest.raises(ValidationError):
            _make_rec(recommendation_type="invalid_type")

    def test_all_valid_recommendation_types(self):
        valid_types = ["rightsize", "reserve", "waste", "operational", "anomaly", "tagging", "sku", "lifecycle"]
        for rtype in valid_types:
            rec = _make_rec(recommendation_type=rtype)
            assert rec.recommendation_type == rtype

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValidationError):
            _make_rec(confidence="very_high")

    def test_invalid_risk_raises(self):
        with pytest.raises(ValidationError):
            _make_rec(risk="critical")

    def test_invalid_effort_raises(self):
        with pytest.raises(ValidationError):
            _make_rec(effort="trivial")

    def test_invalid_reversibility_raises(self):
        with pytest.raises(ValidationError):
            _make_rec(reversibility="none")

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            _make_rec(status="pending")

    def test_negative_saving_raises(self):
        with pytest.raises(ValidationError):
            _make_rec(estimated_monthly_saving=-10.0)

    def test_optional_expires_at_none(self):
        rec = _make_rec()
        assert rec.expires_at is None

    def test_expires_at_can_be_set(self):
        dt = datetime(2025, 12, 31)
        rec = _make_rec(expires_at=dt)
        assert rec.expires_at == dt

    def test_evidence_list(self):
        rec = _make_rec(evidence=[{"source": "a"}, {"source": "b"}])
        assert len(rec.evidence) == 2

    def test_all_level_values(self):
        for level in ("high", "medium", "low"):
            rec = _make_rec(confidence=level, risk=level, effort=level, reversibility=level)
            assert rec.confidence == level


class TestRecommendationCollection:
    """Test RecommendationCollection helpers."""

    def _collection(self) -> RecommendationCollection:
        return RecommendationCollection([
            _make_rec(id="r1", agent="agent_a", owner="alice", environment="production",
                      estimated_monthly_saving=200.0, recommendation_type="rightsize"),
            _make_rec(id="r2", agent="agent_b", owner="bob", environment="staging",
                      estimated_monthly_saving=50.0, recommendation_type="waste"),
            _make_rec(id="r3", agent="agent_a", owner="alice", environment="production",
                      estimated_monthly_saving=300.0, recommendation_type="reserve"),
            _make_rec(id="r4", agent="agent_c", owner="carol", environment="dev",
                      estimated_monthly_saving=10.0, recommendation_type="tagging", status="suppressed"),
        ])

    def test_total_saving(self):
        col = self._collection()
        assert col.total_saving == pytest.approx(560.0)

    def test_len(self):
        col = self._collection()
        assert len(col) == 4

    def test_by_agent(self):
        col = self._collection()
        by_agent = col.by_agent()
        assert len(by_agent["agent_a"]) == 2
        assert len(by_agent["agent_b"]) == 1

    def test_by_owner(self):
        col = self._collection()
        by_owner = col.by_owner()
        assert len(by_owner["alice"]) == 2
        assert len(by_owner["bob"]) == 1

    def test_by_environment(self):
        col = self._collection()
        by_env = col.by_environment()
        assert len(by_env["production"]) == 2
        assert len(by_env["staging"]) == 1

    def test_filter_by_status_open(self):
        col = self._collection()
        open_recs = col.filter_by_status("open")
        assert len(open_recs) == 3

    def test_filter_by_status_suppressed(self):
        col = self._collection()
        suppressed = col.filter_by_status("suppressed")
        assert len(suppressed) == 1

    def test_filter_by_type(self):
        col = self._collection()
        waste = col.filter_by_type("waste")
        assert len(waste) == 1
        assert waste.items[0].id == "r2"

    def test_empty_collection(self):
        col = RecommendationCollection()
        assert len(col) == 0
        assert col.total_saving == 0.0

    def test_append(self):
        col = RecommendationCollection()
        rec = _make_rec(id="new")
        col.append(rec)
        assert len(col) == 1

    def test_extend(self):
        col = RecommendationCollection()
        col.extend([_make_rec(id="a"), _make_rec(id="b")])
        assert len(col) == 2

    def test_sorted_by_priority(self):
        col = RecommendationCollection([
            _make_rec(id="low", priority_score=10.0),
            _make_rec(id="high", priority_score=80.0),
            _make_rec(id="mid", priority_score=50.0),
        ])
        sorted_col = col.sorted_by_priority()
        ids = [r.id for r in sorted_col]
        assert ids == ["high", "mid", "low"]

    def test_to_markdown_table_empty(self):
        col = RecommendationCollection()
        table = col.to_markdown_table()
        assert "_No recommendations._" in table

    def test_to_markdown_table_with_items(self):
        col = self._collection()
        table = col.to_markdown_table()
        assert "rightsize" in table
        assert "alice" in table
        assert "|" in table

    def test_iter(self):
        col = self._collection()
        ids = [r.id for r in col]
        assert "r1" in ids
        assert "r4" in ids

    def test_repr(self):
        col = self._collection()
        r = repr(col)
        assert "RecommendationCollection" in r
