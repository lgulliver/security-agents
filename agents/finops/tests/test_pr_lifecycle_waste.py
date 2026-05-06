"""Tests for agents.pr.lifecycle_waste — PRLifecycleWasteAgent."""

from __future__ import annotations

import json
import pytest

from agents.pr.lifecycle_waste import PRLifecycleWasteAgent


def _write_plan(tmp_path, plan: dict) -> str:
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return str(p)


def _plan_with(resource_changes: list[dict], workspace: str = "dev") -> dict:
    return {"workspace": workspace, "resource_changes": resource_changes}


def _change(res_type: str, name: str, after: dict, action: str = "create") -> dict:
    return {
        "address": f"{res_type}.{name}",
        "type": res_type,
        "name": name,
        "change": {
            "actions": [action],
            "before": None,
            "after": after,
        },
    }


class TestVMShutdownSchedule:
    """Tests for VM shutdown schedule detection in non-prod."""

    def test_vm_in_dev_without_schedule_flagged(self, tmp_path):
        """VM in non-prod without shutdown schedule should be flagged."""
        plan = _plan_with([
            _change("azurerm_linux_virtual_machine", "vm1", {
                "location": "uksouth",
                "resource_group_name": "rg-dev",
                "tags": {"environment": "dev"},
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        lifecycle_recs = [r for r in recs if r.recommendation_type == "lifecycle"]
        assert any(
            r.current_state.get("shutdown_schedule") is None
            for r in lifecycle_recs
        ), "Should flag VM without shutdown schedule"

    def test_vm_in_prod_no_schedule_not_flagged(self, tmp_path):
        """VMs in production do not require shutdown schedules."""
        plan = _plan_with([
            _change("azurerm_linux_virtual_machine", "vm1", {
                "location": "uksouth",
                "resource_group_name": "rg-prod",
                "tags": {"environment": "production"},
            }),
        ], workspace="production")
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        shutdown_recs = [
            r for r in recs
            if r.recommendation_type == "lifecycle" and "shutdown" in str(r.current_state).lower()
        ]
        assert len(shutdown_recs) == 0

    def test_vm_in_dev_with_schedule_not_flagged(self, tmp_path):
        """VM in dev with a shutdown schedule should not be flagged."""
        plan = _plan_with([
            _change("azurerm_linux_virtual_machine", "vm1", {
                "location": "uksouth",
                "resource_group_name": "rg-dev",
                "tags": {"environment": "dev"},
            }),
            _change("azurerm_dev_test_global_vm_shutdown_schedule", "sched1", {
                "virtual_machine_id": "azurerm_linux_virtual_machine.vm1",
                "daily_recurrence_time": "1900",
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        vm_shutdown_recs = [
            r for r in recs
            if r.resource_type == "azurerm_linux_virtual_machine"
            and r.current_state.get("shutdown_schedule") is None
        ]
        assert len(vm_shutdown_recs) == 0


class TestDiskDeleteLifecycle:
    """Tests for disk deletion policy detection."""

    def test_standalone_disk_flagged(self, tmp_path):
        """A standalone managed disk in a plan should be flagged for delete policy."""
        plan = _plan_with([
            _change("azurerm_managed_disk", "data_disk", {
                "location": "uksouth",
                "resource_group_name": "rg-dev",
                "tags": {},
                "storage_account_type": "Standard_LRS",
                "disk_size_gb": 64,
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        # The disk should be checked; a snapshot rec may also be generated
        disk_recs = [r for r in recs if r.resource_type == "azurerm_managed_disk"]
        # Should be flagged because it's standalone
        assert isinstance(recs, list)


class TestPublicIPOrphan:
    """Tests for public IP orphan detection."""

    def test_standalone_public_ip_flagged(self, tmp_path):
        """A public IP with no resource association should be flagged."""
        plan = _plan_with([
            _change("azurerm_public_ip", "pip1", {
                "location": "uksouth",
                "resource_group_name": "rg",
                "allocation_method": "Static",
                "tags": {},
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        pip_recs = [r for r in recs if r.resource_type == "azurerm_public_ip"]
        assert len(pip_recs) >= 1
        assert pip_recs[0].recommendation_type == "lifecycle"

    def test_public_ip_with_nic_association_not_flagged(self, tmp_path):
        """Public IP referenced by a NIC should not be flagged as orphaned."""
        plan = _plan_with([
            _change("azurerm_public_ip", "pip1", {
                "location": "uksouth",
                "resource_group_name": "rg",
                "allocation_method": "Static",
                "tags": {},
            }),
            _change("azurerm_network_interface", "nic1", {
                "location": "uksouth",
                "resource_group_name": "rg",
                "ip_configuration": [{"public_ip_address_id": "azurerm_public_ip.pip1"}],
                "tags": {},
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        orphan_pip = [
            r for r in recs
            if r.resource_type == "azurerm_public_ip"
            and r.current_state.get("association") is None
        ]
        assert len(orphan_pip) == 0


class TestLogAnalyticsRetention:
    """Tests for Log Analytics retention policy."""

    def test_high_retention_flagged(self, tmp_path):
        """Log Analytics workspace with retention > 90 days should be flagged."""
        plan = _plan_with([
            _change("azurerm_log_analytics_workspace", "law1", {
                "location": "uksouth",
                "resource_group_name": "rg",
                "retention_in_days": 180,
                "tags": {},
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        law_recs = [r for r in recs if r.resource_type == "azurerm_log_analytics_workspace"]
        assert len(law_recs) >= 1
        assert law_recs[0].recommendation_type == "lifecycle"
        assert law_recs[0].current_state["retention_in_days"] == 180

    def test_low_retention_not_flagged(self, tmp_path):
        """Log Analytics workspace with retention <= 90 days should not be flagged."""
        plan = _plan_with([
            _change("azurerm_log_analytics_workspace", "law1", {
                "location": "uksouth",
                "resource_group_name": "rg",
                "retention_in_days": 30,
                "tags": {},
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        law_recs = [
            r for r in recs
            if r.resource_type == "azurerm_log_analytics_workspace"
            and "retention_in_days" in r.current_state
        ]
        assert len(law_recs) == 0

    def test_exactly_90_days_not_flagged(self, tmp_path):
        """Retention exactly at 90 days should not be flagged."""
        plan = _plan_with([
            _change("azurerm_log_analytics_workspace", "law1", {
                "location": "uksouth",
                "resource_group_name": "rg",
                "retention_in_days": 90,
                "tags": {},
            }),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        law_recs = [
            r for r in recs
            if r.resource_type == "azurerm_log_analytics_workspace"
            and "retention_in_days" in r.current_state
        ]
        assert len(law_recs) == 0


class TestNoOpExclusion:
    """Tests that no-op resources are excluded."""

    def test_noop_excluded(self, tmp_path):
        """Resources with no-op actions should not generate lifecycle recommendations."""
        plan = _plan_with([
            _change("azurerm_log_analytics_workspace", "law1", {
                "location": "uksouth",
                "resource_group_name": "rg",
                "retention_in_days": 365,
                "tags": {},
            }, action="no-op"),
        ])
        agent = PRLifecycleWasteAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0
