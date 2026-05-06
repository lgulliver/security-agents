"""Tests for the Waste/Orphan Agent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agents.weekly.waste_orphan import WasteOrphanAgent
from models.recommendation import Recommendation


def _make_res(res_type: str, name: str = "myres", resource_id: str | None = None,
              properties: dict | None = None, tags: dict | None = None) -> dict:
    return {
        "resource_id": resource_id or f"/subscriptions/sub1/resourceGroups/rg1/providers/{res_type}/{name}",
        "type": res_type,
        "name": name,
        "location": "uksouth",
        "subscription_id": "sub1",
        "subscription_name": "Test",
        "resource_group": "rg1",
        "tags": tags or {},
        "properties": properties or {},
    }


class TestWasteOrphanAgentInit:
    def test_defaults(self):
        agent = WasteOrphanAgent()
        assert agent.subscription_id == ""
        assert agent.snapshot_age_days == 90

    def test_custom_params(self):
        agent = WasteOrphanAgent(subscription_id="s1", subscription_name="My Sub",
                                 currency="USD", snapshot_age_days=30)
        assert agent.subscription_id == "s1"
        assert agent.snapshot_age_days == 30


class TestCheckDisk:
    AGENT = WasteOrphanAgent()

    def test_unattached_disk_flagged(self):
        res = _make_res("microsoft.compute/disks", name="disk1",
                        properties={"diskState": "Unattached"})
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert recs[0].recommendation_type == "waste"
        assert "safe_to_delete" in recs[0].current_state.get("waste_classification", "")

    def test_attached_disk_not_flagged(self):
        res = _make_res("microsoft.compute/disks", name="disk2",
                        properties={"diskState": "Attached"})
        recs = self.AGENT.analyse([res], [])
        assert recs == []

    def test_disk_with_managed_by_not_flagged(self):
        res = _make_res("microsoft.compute/disks", name="disk3",
                        properties={"diskState": "Unattached", "managedBy": "/subscriptions/sub1/rg/vm1"})
        recs = self.AGENT.analyse([res], [])
        assert recs == []


class TestCheckNIC:
    AGENT = WasteOrphanAgent()

    def test_orphaned_nic_flagged(self):
        res = _make_res("microsoft.network/networkinterfaces", name="nic1",
                        properties={"virtualMachine": {}})
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert "needs_owner_review" in recs[0].current_state.get("waste_classification", "")

    def test_attached_nic_not_flagged(self):
        res = _make_res("microsoft.network/networkinterfaces", name="nic2",
                        properties={"virtualMachine": {"id": "/subscriptions/sub1/rg/vm1"}})
        recs = self.AGENT.analyse([res], [])
        assert recs == []


class TestCheckPublicIP:
    AGENT = WasteOrphanAgent()

    def test_unassociated_public_ip_flagged(self):
        res = _make_res("microsoft.network/publicipaddresses", name="ip1",
                        properties={})
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert "safe_to_delete" in recs[0].current_state.get("waste_classification", "")

    def test_associated_via_ip_config_not_flagged(self):
        res = _make_res("microsoft.network/publicipaddresses", name="ip2",
                        properties={"ipConfiguration": {"id": "/subscriptions/sub1/rg/nic1"}})
        recs = self.AGENT.analyse([res], [])
        assert recs == []

    def test_associated_via_nat_gw_not_flagged(self):
        res = _make_res("microsoft.network/publicipaddresses", name="ip3",
                        properties={"natGateway": {"id": "nat1"}})
        recs = self.AGENT.analyse([res], [])
        assert recs == []

    def test_associated_via_lb_not_flagged(self):
        res = _make_res("microsoft.network/publicipaddresses", name="ip4",
                        properties={"loadBalancerFrontendIpConfiguration": {"id": "lb1"}})
        recs = self.AGENT.analyse([res], [])
        assert recs == []


class TestCheckVM:
    AGENT = WasteOrphanAgent()

    def test_stopped_not_deallocated_flagged(self):
        res = _make_res("microsoft.compute/virtualmachines", name="vm1",
                        properties={"extended": {"instanceView": {
                            "powerState": {"code": "PowerState/stopped"}}}})
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert "needs_owner_review" in recs[0].current_state.get("waste_classification", "")
        assert recs[0].risk == "medium"

    def test_running_vm_not_flagged(self):
        res = _make_res("microsoft.compute/virtualmachines", name="vm2",
                        properties={"extended": {"instanceView": {
                            "powerState": {"code": "PowerState/running"}}}})
        recs = self.AGENT.analyse([res], [])
        assert recs == []

    def test_deallocated_vm_not_flagged(self):
        res = _make_res("microsoft.compute/virtualmachines", name="vm3",
                        properties={"extended": {"instanceView": {
                            "powerState": {"code": "PowerState/deallocated"}}}})
        recs = self.AGENT.analyse([res], [])
        assert recs == []


class TestCheckSnapshot:
    AGENT = WasteOrphanAgent(snapshot_age_days=90)

    def test_old_snapshot_flagged(self):
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        res = _make_res("microsoft.compute/snapshots", name="snap1",
                        properties={"timeCreated": old_date})
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert recs[0].current_state["age_days"] >= 100

    def test_recent_snapshot_not_flagged(self):
        recent_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        res = _make_res("microsoft.compute/snapshots", name="snap2",
                        properties={"timeCreated": recent_date})
        recs = self.AGENT.analyse([res], [])
        assert recs == []

    def test_snapshot_missing_time_skipped(self):
        res = _make_res("microsoft.compute/snapshots", name="snap3", properties={})
        recs = self.AGENT.analyse([res], [])
        assert recs == []

    def test_snapshot_invalid_time_skipped(self):
        res = _make_res("microsoft.compute/snapshots", name="snap4",
                        properties={"timeCreated": "not-a-date"})
        recs = self.AGENT.analyse([res], [])
        assert recs == []


class TestCheckLoadBalancer:
    AGENT = WasteOrphanAgent()

    def test_lb_no_backend_pools_flagged(self):
        res = _make_res("microsoft.network/loadbalancers", name="lb1",
                        properties={"backendAddressPools": []})
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert "needs_owner_review" in recs[0].current_state.get("waste_classification", "")

    def test_lb_with_backend_pools_not_flagged(self):
        res = _make_res("microsoft.network/loadbalancers", name="lb2",
                        properties={"backendAddressPools": [{"id": "pool1"}]})
        recs = self.AGENT.analyse([res], [])
        assert recs == []


class TestCheckNATGateway:
    AGENT = WasteOrphanAgent()

    def test_nat_gw_no_subnets_flagged(self):
        res = _make_res("microsoft.network/natgateways", name="nat1",
                        properties={"subnets": []})
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert "needs_owner_review" in recs[0].current_state.get("waste_classification", "")

    def test_nat_gw_with_subnets_not_flagged(self):
        res = _make_res("microsoft.network/natgateways", name="nat2",
                        properties={"subnets": [{"id": "subnet1"}]})
        recs = self.AGENT.analyse([res], [])
        assert recs == []


class TestCheckAppServicePlan:
    AGENT = WasteOrphanAgent()

    def test_empty_asp_flagged(self):
        asp_id = "/subscriptions/sub1/resourceGroups/rg1/providers/microsoft.web/serverfarms/plan1"
        res = _make_res("microsoft.web/serverfarms", name="plan1", resource_id=asp_id)
        # No apps reference this ASP ID
        recs = self.AGENT.analyse([res], [])
        assert len(recs) == 1
        assert "safe_to_delete" in recs[0].current_state.get("waste_classification", "")

    def test_asp_with_app_not_flagged(self):
        asp_id = "/subscriptions/sub1/resourceGroups/rg1/providers/microsoft.web/serverfarms/plan2"
        asp = _make_res("microsoft.web/serverfarms", name="plan2", resource_id=asp_id)
        # App that contains the ASP ID in its resource ID
        app_id = f"{asp_id}/sites/app1"
        app = _make_res("microsoft.web/sites", name="app1", resource_id=app_id)
        recs = self.AGENT.analyse([asp, app], [])
        # The ASP should not be flagged as empty
        asp_recs = [r for r in recs if r.resource_name == "plan2"]
        assert asp_recs == []


class TestCheckLogAnalytics:
    AGENT = WasteOrphanAgent()

    def test_underused_workspace_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg1/providers/microsoft.operationalinsights/workspaces/ws1"
        res = _make_res("microsoft.operationalinsights/workspaces", name="ws1", resource_id=rid)
        cost_data = [{"resource_id": rid, "cost": 0.5}]
        recs = self.AGENT.analyse([res], cost_data)
        assert len(recs) == 1

    def test_workspace_no_cost_data_skipped(self):
        res = _make_res("microsoft.operationalinsights/workspaces", name="ws2")
        recs = self.AGENT.analyse([res], [])
        assert recs == []

    def test_expensive_workspace_not_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg1/providers/microsoft.operationalinsights/workspaces/ws3"
        res = _make_res("microsoft.operationalinsights/workspaces", name="ws3", resource_id=rid)
        # avg daily cost > threshold * 3
        cost_data = [{"resource_id": rid, "cost": 50.0}] * 10
        recs = self.AGENT.analyse([res], cost_data)
        assert recs == []


class TestWasteOrphanAgentMisc:
    def test_unknown_resource_type_skipped(self):
        res = _make_res("microsoft.unknown/thing", name="thing1")
        agent = WasteOrphanAgent()
        recs = agent.analyse([res], [])
        assert recs == []

    def test_recommendation_fields_populated(self):
        res = _make_res("microsoft.compute/disks", name="disk_f",
                        properties={"diskState": "Unattached"},
                        tags={"owner": "ops", "environment": "production"})
        agent = WasteOrphanAgent(subscription_id="s1", subscription_name="Sub1")
        recs = agent.analyse([res], [])
        assert len(recs) == 1
        rec = recs[0]
        assert rec.agent == "weekly.waste_orphan"
        assert rec.owner == "ops"
        assert rec.environment == "production"
        assert rec.currency == "GBP"

    def test_empty_resources_returns_empty(self):
        agent = WasteOrphanAgent()
        assert agent.analyse([], []) == []
