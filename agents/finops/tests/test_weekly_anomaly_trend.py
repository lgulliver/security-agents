"""Tests for the Anomaly/Trend Agent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agents.weekly.anomaly_trend import AnomalyTrendAgent
from models.recommendation import Recommendation


def _make_dates(n: int, start_offset_days: int = 0) -> list[str]:
    """Return n consecutive date strings starting from today - n - start_offset_days."""
    base = datetime.now(timezone.utc) - timedelta(days=n + start_offset_days)
    return [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def _make_cost_data(dates: list[str], cost: float = 100.0,
                    service: str = "Virtual Machines",
                    subscription_id: str = "sub1",
                    resource_id: str = "/subscriptions/sub1/rg/res1") -> list[dict]:
    return [
        {
            "date": d,
            "cost": cost,
            "service_name": service,
            "subscription_id": subscription_id,
            "resource_id": resource_id,
        }
        for d in dates
    ]


AGENT = AnomalyTrendAgent(subscription_id="sub1", subscription_name="Test Sub")


class TestAnomalyTrendAgentInit:
    def test_defaults(self):
        a = AnomalyTrendAgent()
        assert a.wow_spike_threshold == 0.20
        assert a.budget_burn_threshold == 0.85
        assert a.currency == "GBP"

    def test_custom_params(self):
        a = AnomalyTrendAgent(subscription_id="s1", wow_spike_threshold=0.1)
        assert a.wow_spike_threshold == 0.1


class TestNotEnoughData:
    def test_less_than_8_days_returns_empty(self):
        dates = _make_dates(7)
        cost_data = _make_cost_data(dates)
        recs = AGENT.analyse(cost_data, [])
        assert recs == []

    def test_exactly_8_days_runs(self):
        dates = _make_dates(8)
        cost_data = _make_cost_data(dates)
        # Should run without error (even if no anomalies found)
        recs = AGENT.analyse(cost_data, [])
        assert isinstance(recs, list)


class TestWoWSpike:
    def test_wow_spike_detected(self):
        """Last 7 days cost significantly more than prior 7 days."""
        dates_prior = _make_dates(7, start_offset_days=7)
        dates_recent = _make_dates(7)
        cost_data = (
            _make_cost_data(dates_prior, cost=100.0)
            + _make_cost_data(dates_recent, cost=200.0)  # 100% increase
        )
        recs = AGENT.analyse(cost_data, [])
        spike_recs = [r for r in recs if "WoW" in r.action.get("title", "")]
        assert len(spike_recs) >= 1
        assert spike_recs[0].recommendation_type == "anomaly"
        assert spike_recs[0].confidence == "high"

    def test_no_spike_within_threshold(self):
        """Small increase below threshold should not trigger spike."""
        dates = _make_dates(14)
        # 10% increase — below default 20% threshold
        cost_data = (
            _make_cost_data(dates[:7], cost=100.0)
            + _make_cost_data(dates[7:], cost=108.0)
        )
        recs = AGENT.analyse(cost_data, [])
        spike_recs = [r for r in recs if "WoW" in r.action.get("title", "")]
        assert spike_recs == []

    def test_zero_prior_spend_no_spike(self):
        """Zero prior spend should not cause division error."""
        dates = _make_dates(14)
        cost_data = (
            _make_cost_data(dates[:7], cost=0.0)
            + _make_cost_data(dates[7:], cost=100.0)
        )
        # Should not raise, might not produce spike rec
        recs = AGENT.analyse(cost_data, [])
        assert isinstance(recs, list)

    def test_fewer_than_14_days_no_wow(self):
        """Less than 14 days can't do WoW comparison."""
        dates = _make_dates(10)
        cost_data = _make_cost_data(dates, cost=100.0)
        recs = AGENT.analyse(cost_data, [])
        spike_recs = [r for r in recs if "WoW" in r.action.get("title", "")]
        assert spike_recs == []


class TestNewServiceDetection:
    def test_new_service_detected(self):
        dates = _make_dates(14)
        # Old service present throughout
        old_cost = _make_cost_data(dates[:14], cost=50.0, service="Storage")
        # New service only in last 7 days
        new_cost = _make_cost_data(dates[7:], cost=10.0, service="Azure OpenAI")
        recs = AGENT.analyse(old_cost + new_cost, [])
        new_svc_recs = [r for r in recs if "New service" in r.action.get("title", "")]
        assert len(new_svc_recs) >= 1

    def test_existing_service_not_flagged_as_new(self):
        dates = _make_dates(14)
        cost_data = _make_cost_data(dates, cost=50.0, service="Compute")
        recs = AGENT.analyse(cost_data, [])
        new_svc_recs = [r for r in recs if "New service" in r.action.get("title", "")]
        assert new_svc_recs == []

    def test_very_cheap_new_service_not_flagged(self):
        """New services costing < 1 GBP should be ignored."""
        dates = _make_dates(14)
        old_cost = _make_cost_data(dates[:14], cost=50.0, service="Storage")
        new_cost = _make_cost_data(dates[7:], cost=0.01, service="New Tiny Service")
        recs = AGENT.analyse(old_cost + new_cost, [])
        new_svc_recs = [r for r in recs if "New Tiny Service" in r.action.get("title", "")]
        assert new_svc_recs == []


class TestResourceAnomalies:
    def test_resource_spike_detected(self):
        dates = _make_dates(14)
        rid = "/subscriptions/sub1/rg/res_spike"
        prior = [{"date": d, "cost": 10.0, "service_name": "compute",
                  "subscription_id": "sub1", "resource_id": rid} for d in dates[:7]]
        recent = [{"date": d, "cost": 50.0, "service_name": "compute",
                   "subscription_id": "sub1", "resource_id": rid} for d in dates[7:]]
        recs = AGENT.analyse(prior + recent, [])
        resource_recs = [r for r in recs if "Resource cost spike" in r.action.get("title", "")]
        assert len(resource_recs) >= 1

    def test_cheap_resource_spike_not_flagged(self):
        """Resources with < £5 total cost in last 7 days are too noisy."""
        dates = _make_dates(14)
        rid = "/subscriptions/sub1/rg/cheap_res"
        prior = [{"date": d, "cost": 0.1, "service_name": "compute",
                  "subscription_id": "sub1", "resource_id": rid} for d in dates[:7]]
        recent = [{"date": d, "cost": 0.5, "service_name": "compute",
                   "subscription_id": "sub1", "resource_id": rid} for d in dates[7:]]
        recs = AGENT.analyse(prior + recent, [])
        resource_recs = [r for r in recs if rid.split("/")[-1] in r.action.get("title", "")]
        assert resource_recs == []

    def test_at_most_20_resource_anomalies(self):
        """Large number of anomalies capped at 20."""
        dates = _make_dates(14)
        entries = []
        for i in range(30):
            rid = f"/subscriptions/sub1/rg/res{i}"
            entries += [{"date": d, "cost": 10.0, "service_name": "s",
                         "subscription_id": "sub1", "resource_id": rid} for d in dates[:7]]
            entries += [{"date": d, "cost": 100.0, "service_name": "s",
                         "subscription_id": "sub1", "resource_id": rid} for d in dates[7:]]
        recs = AGENT.analyse(entries, [])
        resource_recs = [r for r in recs if r.resource_type == ""]
        assert len(resource_recs) <= 20


class TestBudgetBurn:
    def test_budget_burn_alert_triggered(self):
        dates = _make_dates(14)
        # Daily spend of 100, monthly budget = 500 → forecast ~3000 >> 500
        cost_data = _make_cost_data(dates, cost=100.0)
        subscriptions = [{
            "subscription_id": "sub1",
            "name": "Test Sub",
            "owner": "platform",
            "tags": {"monthly_budget": "500"},
        }]
        recs = AGENT.analyse(cost_data, subscriptions)
        burn_recs = [r for r in recs if "burn rate" in r.action.get("title", "").lower()]
        assert len(burn_recs) >= 1

    def test_budget_within_limits_no_alert(self):
        dates = _make_dates(14)
        # Very low spend vs high budget
        cost_data = _make_cost_data(dates, cost=1.0)
        subscriptions = [{
            "subscription_id": "sub1",
            "name": "Test Sub",
            "owner": "platform",
            "tags": {"monthly_budget": "10000"},
        }]
        recs = AGENT.analyse(cost_data, subscriptions)
        burn_recs = [r for r in recs if "burn rate" in r.action.get("title", "").lower()]
        assert burn_recs == []

    def test_invalid_budget_tag_ignored(self):
        dates = _make_dates(14)
        cost_data = _make_cost_data(dates, cost=100.0)
        subscriptions = [{
            "subscription_id": "sub1",
            "name": "Test Sub",
            "tags": {"monthly_budget": "not-a-number"},
        }]
        # Should not raise
        recs = AGENT.analyse(cost_data, subscriptions)
        assert isinstance(recs, list)

    def test_no_budget_tag_no_alert(self):
        dates = _make_dates(14)
        cost_data = _make_cost_data(dates, cost=999.0)
        subscriptions = [{"subscription_id": "sub1", "name": "Test", "tags": {}}]
        recs = AGENT.analyse(cost_data, subscriptions)
        burn_recs = [r for r in recs if "burn rate" in r.action.get("title", "").lower()]
        assert burn_recs == []


class TestAnomalyRecommendationFields:
    def test_recommendation_type_is_anomaly(self):
        dates = _make_dates(14)
        cost_data = (
            _make_cost_data(dates[:7], cost=100.0)
            + _make_cost_data(dates[7:], cost=300.0)
        )
        recs = AGENT.analyse(cost_data, [])
        for rec in recs:
            assert rec.recommendation_type == "anomaly"

    def test_recommendation_agent_name(self):
        dates = _make_dates(14)
        cost_data = (
            _make_cost_data(dates[:7], cost=100.0)
            + _make_cost_data(dates[7:], cost=300.0)
        )
        recs = AGENT.analyse(cost_data, [])
        for rec in recs:
            assert rec.agent == "weekly.anomaly_trend"

    def test_recommendation_effort_is_low(self):
        dates = _make_dates(14)
        cost_data = (
            _make_cost_data(dates[:7], cost=100.0)
            + _make_cost_data(dates[7:], cost=300.0)
        )
        recs = AGENT.analyse(cost_data, [])
        for rec in recs:
            assert rec.effort == "low"
