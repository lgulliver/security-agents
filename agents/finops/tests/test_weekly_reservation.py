"""Tests for the Reservation Agent."""

from __future__ import annotations

import pytest

from agents.weekly.reservation import ReservationAgent
from models.recommendation import Recommendation


def _make_resource(res_type: str, resource_id: str | None = None,
                   name: str = "myres", tags: dict | None = None) -> dict:
    return {
        "resource_id": resource_id or f"/subscriptions/sub1/rg1/{name}",
        "type": res_type,
        "name": name,
        "location": "uksouth",
        "subscription_id": "sub1",
        "subscription_name": "Test Sub",
        "resource_group": "rg1",
        "tags": tags or {"owner": "platform", "environment": "production"},
        "sku": {},
    }


def _make_cost_data(resource_id: str, daily_cost: float = 10.0, n_days: int = 30) -> list[dict]:
    return [
        {"resource_id": resource_id, "cost": daily_cost, "date": f"2025-01-{i+1:02d}"}
        for i in range(n_days)
    ]


class TestReservationAgentInit:
    def test_defaults(self):
        a = ReservationAgent()
        assert a.min_monthly_cost == 50.0
        assert a.currency == "GBP"

    def test_custom_params(self):
        a = ReservationAgent(subscription_id="s1", min_monthly_cost=100.0)
        assert a.min_monthly_cost == 100.0


class TestReservationRI:
    AGENT = ReservationAgent()

    def test_vm_ri_recommendation_produced(self):
        rid = "/subscriptions/sub1/rg1/vm-prod"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, name="vm-prod")
        cost_data = _make_cost_data(rid, daily_cost=10.0)  # ~237 GBP/month
        recs = self.AGENT.analyse([res], cost_data, {})
        assert len(recs) == 1
        rec = recs[0]
        assert rec.recommendation_type == "reserve"
        assert rec.estimated_monthly_saving > 0
        assert rec.current_state["billing"] == "pay_as_you_go"
        assert rec.recommended_state["billing"] == "1yr_reserved"

    def test_sql_ri_recommendation_produced(self):
        rid = "/subscriptions/sub1/rg1/db1"
        res = _make_resource("microsoft.sql/servers/databases", resource_id=rid, name="db1")
        cost_data = _make_cost_data(rid, daily_cost=10.0)
        recs = self.AGENT.analyse([res], cost_data, {})
        assert len(recs) >= 1
        assert all(r.recommendation_type == "reserve" for r in recs)

    def test_redis_ri_recommendation_produced(self):
        rid = "/subscriptions/sub1/rg1/cache1"
        res = _make_resource("microsoft.cache/redis", resource_id=rid, name="cache1")
        cost_data = _make_cost_data(rid, daily_cost=8.0)
        recs = self.AGENT.analyse([res], cost_data, {})
        assert len(recs) >= 1


class TestReservationSkipNonProd:
    AGENT = ReservationAgent()

    @pytest.mark.parametrize("env", ["dev", "test", "sandbox", "preview", "staging", "development"])
    def test_non_prod_environment_skipped(self, env: str):
        rid = f"/subscriptions/sub1/rg1/vm-{env}"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, name=f"vm-{env}",
                              tags={"environment": env})
        cost_data = _make_cost_data(rid, daily_cost=20.0)
        recs = self.AGENT.analyse([res], cost_data, {})
        assert recs == []


class TestReservationSkipCheap:
    AGENT = ReservationAgent(min_monthly_cost=500.0)

    def test_cheap_resource_skipped(self):
        rid = "/subscriptions/sub1/rg1/cheap-vm"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid)
        # Very cheap — monthly cost << 500
        cost_data = _make_cost_data(rid, daily_cost=0.1)
        recs = self.AGENT.analyse([res], cost_data, {})
        assert recs == []


class TestReservationSkipNoCostData:
    def test_no_cost_data_skipped(self):
        rid = "/subscriptions/sub1/rg1/vm-nocost"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid)
        recs = ReservationAgent().analyse([res], [], {})
        assert recs == []


class TestReservationUnstableWorkload:
    def test_unstable_workload_skipped(self):
        """High coefficient of variation → skip reservation."""
        rid = "/subscriptions/sub1/rg1/vm-spiky"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid)
        # Very spiky costs: alternating 0.01 and 200
        cost_data = [
            {"resource_id": rid, "cost": 200.0 if i % 2 == 0 else 0.01, "date": f"2025-01-{i+1:02d}"}
            for i in range(30)
        ]
        recs = ReservationAgent().analyse([res], cost_data, {})
        assert recs == []


class TestSavingsPlanEligible:
    def test_aks_cluster_savings_plan_produced(self):
        """AKS is savings-plan-eligible but not in RESERVABLE_TYPES."""
        rid = "/subscriptions/sub1/rg1/aks1"
        res = _make_resource("microsoft.containerservice/managedclusters", resource_id=rid,
                              name="aks1", tags={"environment": "production"})
        cost_data = _make_cost_data(rid, daily_cost=15.0)
        recs = ReservationAgent().analyse([res], cost_data, {})
        # AKS is in SAVINGS_PLAN_ELIGIBLE but not RESERVABLE_TYPES → savings plan rec
        sp_recs = [r for r in recs if "savings_plan" in r.recommended_state.get("billing", "")]
        assert len(sp_recs) == 1


class TestReservationRecommendationFields:
    def test_recommendation_fields(self):
        rid = "/subscriptions/sub1/rg1/vm-fields"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, name="vm-fields",
                              tags={"owner": "team-a", "environment": "production"})
        cost_data = _make_cost_data(rid, daily_cost=12.0)
        recs = ReservationAgent(subscription_id="sub1", subscription_name="My Sub").analyse(
            [res], cost_data, {}
        )
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec, Recommendation)
        assert rec.agent == "weekly.reservation"
        assert rec.confidence == "medium"
        assert rec.risk == "low"
        assert rec.effort == "low"
        assert rec.reversibility == "medium"
        assert rec.owner == "team-a"

    def test_empty_resources_returns_empty(self):
        assert ReservationAgent().analyse([], [], {}) == []
