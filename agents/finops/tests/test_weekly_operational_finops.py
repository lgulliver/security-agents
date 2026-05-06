"""Tests for the Operational FinOps Agent."""

from __future__ import annotations

import pytest

from agents.weekly.operational_finops import OperationalFinOpsAgent
from models.recommendation import Recommendation


def _make_resource(res_type: str, name: str = "myres", resource_id: str | None = None,
                   tags: dict | None = None, sku: dict | str | None = None,
                   properties: dict | None = None) -> dict:
    return {
        "resource_id": resource_id or f"/subscriptions/sub1/rg1/providers/{res_type}/{name}",
        "type": res_type,
        "name": name,
        "location": "uksouth",
        "subscription_id": "sub1",
        "subscription_name": "Test Sub",
        "resource_group": "rg1",
        "tags": tags or {},
        "sku": sku or {},
        "properties": properties or {},
    }


AGENT = OperationalFinOpsAgent(subscription_id="sub1", subscription_name="Test")


class TestOperationalAgentInit:
    def test_defaults(self):
        a = OperationalFinOpsAgent()
        assert a.subscription_id == ""
        assert a.currency == "GBP"

    def test_custom_params(self):
        a = OperationalFinOpsAgent(subscription_id="s1", subscription_name="Sub", currency="USD")
        assert a.currency == "USD"


class TestASPAutoscale:
    def test_asp_without_autoscale_flagged(self):
        res = _make_resource("microsoft.web/serverfarms", name="plan1", sku={"name": "P2v3"})
        recs = AGENT.analyse([res], {}, [])
        assert len(recs) == 1
        assert recs[0].recommendation_type == "operational"
        assert recs[0].current_state["autoscale"] is False

    def test_free_tier_asp_skipped(self):
        res = _make_resource("microsoft.web/serverfarms", name="plan2", sku={"name": "F1"})
        recs = AGENT.analyse([res], {}, [])
        assert recs == []

    def test_dynamic_tier_asp_skipped(self):
        res = _make_resource("microsoft.web/serverfarms", name="plan3", sku={"name": "D1"})
        recs = AGENT.analyse([res], {}, [])
        assert recs == []

    def test_asp_with_no_sku_skipped(self):
        res = _make_resource("microsoft.web/serverfarms", name="plan4", sku={})
        recs = AGENT.analyse([res], {}, [])
        assert recs == []

    def test_asp_with_string_sku(self):
        res = _make_resource("microsoft.web/serverfarms", name="plan5", sku="S1")
        recs = AGENT.analyse([res], {}, [])
        assert len(recs) == 1


class TestAKS:
    def test_aks_without_autoscaler_flagged(self):
        res = _make_resource("microsoft.containerservice/managedclusters", name="aks1",
                              properties={"agentPoolProfiles": [{"enableAutoScaling": False}]})
        recs = AGENT.analyse([res], {}, [])
        cluster_recs = [r for r in recs if "no cluster autoscaler" in r.action.get("title", "")]
        assert len(cluster_recs) == 1

    def test_aks_with_autoscaler_not_flagged_for_autoscaler(self):
        res = _make_resource("microsoft.containerservice/managedclusters", name="aks2",
                              properties={"agentPoolProfiles": [{"enableAutoScaling": True}]})
        recs = AGENT.analyse([res], {}, [])
        autoscaler_recs = [r for r in recs if "no cluster autoscaler" in r.action.get("title", "")]
        assert autoscaler_recs == []

    def test_aks_poor_bin_packing_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/Microsoft.ContainerService/managedClusters/aks3"
        res = _make_resource("microsoft.containerservice/managedclusters", name="aks3",
                              resource_id=rid, properties={"agentPoolProfiles": [{"enableAutoScaling": True}]})
        metrics = {rid: {"node_cpu_usage_percentage_avg": {30: 10.0}}}
        recs = AGENT.analyse([res], metrics, [])
        bin_pack_recs = [r for r in recs if "bin-packing" in r.action.get("title", "")]
        assert len(bin_pack_recs) == 1

    def test_aks_good_bin_packing_not_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/Microsoft.ContainerService/managedClusters/aks4"
        res = _make_resource("microsoft.containerservice/managedclusters", name="aks4",
                              resource_id=rid, properties={"agentPoolProfiles": [{"enableAutoScaling": True}]})
        metrics = {rid: {"node_cpu_usage_percentage_avg": {30: 65.0}}}
        recs = AGENT.analyse([res], metrics, [])
        bin_pack_recs = [r for r in recs if "bin-packing" in r.action.get("title", "")]
        assert bin_pack_recs == []

    def test_aks_no_agent_pool_profiles(self):
        res = _make_resource("microsoft.containerservice/managedclusters", name="aks5",
                              properties={})
        recs = AGENT.analyse([res], {}, [])
        # no autoscaler since no profiles → should flag
        cluster_recs = [r for r in recs if "no cluster autoscaler" in r.action.get("title", "")]
        assert len(cluster_recs) == 1


class TestLogAnalytics:
    def test_high_ingestion_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/microsoft.operationalinsights/workspaces/ws1"
        res = _make_resource("microsoft.operationalinsights/workspaces", name="ws1", resource_id=rid)
        # avg_daily_cost > 50 (threshold)
        cost_data = [{"resource_id": rid, "cost": 60.0}] * 5
        recs = AGENT.analyse([res], {}, cost_data)
        ingestion_recs = [r for r in recs if "High Log Analytics ingestion" in r.action.get("title", "")]
        assert len(ingestion_recs) == 1

    def test_low_ingestion_not_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/microsoft.operationalinsights/workspaces/ws2"
        res = _make_resource("microsoft.operationalinsights/workspaces", name="ws2", resource_id=rid)
        cost_data = [{"resource_id": rid, "cost": 1.0}]
        recs = AGENT.analyse([res], {}, cost_data)
        ingestion_recs = [r for r in recs if "High Log Analytics ingestion" in r.action.get("title", "")]
        assert ingestion_recs == []

    def test_excessive_retention_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/microsoft.operationalinsights/workspaces/ws3"
        res = _make_resource("microsoft.operationalinsights/workspaces", name="ws3", resource_id=rid,
                              properties={"retentionInDays": 365})
        cost_data = [{"resource_id": rid, "cost": 5.0}]
        recs = AGENT.analyse([res], {}, cost_data)
        retention_recs = [r for r in recs if "retention" in r.action.get("title", "").lower()]
        assert len(retention_recs) == 1

    def test_default_retention_not_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/microsoft.operationalinsights/workspaces/ws4"
        res = _make_resource("microsoft.operationalinsights/workspaces", name="ws4", resource_id=rid,
                              properties={"retentionInDays": 30})
        cost_data = [{"resource_id": rid, "cost": 5.0}]
        recs = AGENT.analyse([res], {}, cost_data)
        retention_recs = [r for r in recs if "retention" in r.action.get("title", "").lower()]
        assert retention_recs == []

    def test_workspace_no_cost_data_skipped(self):
        res = _make_resource("microsoft.operationalinsights/workspaces", name="ws5")
        recs = AGENT.analyse([res], {}, [])
        assert recs == []


class TestStorageRedundancy:
    def test_gzrs_in_dev_flagged(self):
        res = _make_resource("microsoft.storage/storageaccounts", name="st1",
                              sku={"name": "GZRS"}, tags={"environment": "dev"})
        recs = AGENT.analyse([res], {}, [])
        assert len(recs) == 1
        assert recs[0].recommended_state.get("redundancy") == "LRS"

    def test_ragrs_in_test_flagged(self):
        res = _make_resource("microsoft.storage/storageaccounts", name="st2",
                              sku={"name": "RAGRS"}, tags={"environment": "test"})
        recs = AGENT.analyse([res], {}, [])
        assert len(recs) == 1

    def test_lrs_in_non_prod_not_flagged(self):
        res = _make_resource("microsoft.storage/storageaccounts", name="st3",
                              sku={"name": "LRS"}, tags={"environment": "dev"})
        recs = AGENT.analyse([res], {}, [])
        assert recs == []

    def test_gzrs_in_production_not_flagged(self):
        res = _make_resource("microsoft.storage/storageaccounts", name="st4",
                              sku={"name": "GZRS"}, tags={"environment": "production"})
        recs = AGENT.analyse([res], {}, [])
        assert recs == []


class TestGatewayUsage:
    def test_high_cost_firewall_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/Microsoft.Network/azureFirewalls/fw1"
        res = _make_resource("microsoft.network/azurefirewalls", name="fw1", resource_id=rid)
        # daily cost 10 → monthly 300 > threshold 200
        cost_data = [{"resource_id": rid, "cost": 10.0}]
        recs = AGENT.analyse([res], {}, cost_data)
        assert len(recs) == 1
        assert "Azure Firewall" in recs[0].action.get("title", "")

    def test_cheap_gateway_not_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/Microsoft.Network/azureFirewalls/fw2"
        res = _make_resource("microsoft.network/azurefirewalls", name="fw2", resource_id=rid)
        cost_data = [{"resource_id": rid, "cost": 1.0}]
        recs = AGENT.analyse([res], {}, cost_data)
        assert recs == []

    def test_high_cost_app_gateway_flagged(self):
        rid = "/subscriptions/sub1/rg1/providers/Microsoft.Network/applicationGateways/agw1"
        res = _make_resource("microsoft.network/applicationgateways", name="agw1", resource_id=rid)
        cost_data = [{"resource_id": rid, "cost": 10.0}]
        recs = AGENT.analyse([res], {}, cost_data)
        assert len(recs) == 1
        assert "Application Gateway" in recs[0].action.get("title", "")


class TestOperationalMisc:
    def test_empty_resources(self):
        assert AGENT.analyse([], {}, []) == []

    def test_unknown_type_skipped(self):
        res = _make_resource("microsoft.unknown/thing", name="x")
        recs = AGENT.analyse([res], {}, [])
        assert recs == []

    def test_recommendation_fields(self):
        res = _make_resource("microsoft.web/serverfarms", name="plan_f",
                              sku={"name": "P3v3"},
                              tags={"owner": "team-b", "environment": "production"})
        agent = OperationalFinOpsAgent(subscription_id="sub1", subscription_name="Sub")
        recs = agent.analyse([res], {}, [])
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec, Recommendation)
        assert rec.agent == "weekly.operational_finops"
        assert rec.recommendation_type == "operational"
        assert rec.owner == "team-b"
        assert rec.effort == "medium"
        assert rec.reversibility == "high"
