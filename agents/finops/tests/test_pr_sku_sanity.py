"""Tests for agents.pr.sku_sanity — PRSKUSanityAgent."""

from __future__ import annotations

import json
import pytest

from agents.pr.sku_sanity import PRSKUSanityAgent


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


class TestOversizedVM:
    """Tests for oversized VM detection in non-prod environments."""

    @pytest.mark.parametrize("size", [
        "Standard_D8s_v3",
        "Standard_D16s_v3",
        "Standard_E8s_v4",
        "Standard_M32",
    ])
    def test_oversized_vm_in_dev_flagged(self, tmp_path, size):
        """Oversized VMs in dev/test should be flagged."""
        plan = _plan_with([_change("azurerm_linux_virtual_machine", "vm1", {
            "size": size,
            "location": "uksouth",
            "resource_group_name": "rg-dev",
            "tags": {"environment": "dev"},
        })])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) >= 1
        assert any(r.recommendation_type == "sku" for r in recs)

    def test_small_vm_in_dev_not_flagged(self, tmp_path):
        """Standard_D2s_v3 in dev should not be flagged as oversized."""
        plan = _plan_with([_change("azurerm_linux_virtual_machine", "vm1", {
            "size": "Standard_D2s_v3",
            "location": "uksouth",
            "resource_group_name": "rg-dev",
            "tags": {"environment": "dev"},
        })])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        sku_recs = [r for r in recs if r.recommendation_type == "sku"]
        assert len(sku_recs) == 0

    def test_oversized_vm_in_prod_not_flagged(self, tmp_path):
        """Oversized VMs in production should not be flagged."""
        plan = _plan_with([_change("azurerm_linux_virtual_machine", "vm1", {
            "size": "Standard_D16s_v3",
            "location": "uksouth",
            "resource_group_name": "rg-prod",
            "tags": {"environment": "production"},
        })], workspace="production")
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        sku_recs = [r for r in recs if r.recommendation_type == "sku" and "Oversized VM" in str(r.evidence)]
        assert len(sku_recs) == 0

    def test_environment_inferred_from_workspace(self, tmp_path):
        """Environment should be inferred from workspace when tags are missing."""
        plan = _plan_with([_change("azurerm_linux_virtual_machine", "vm1", {
            "size": "Standard_D8s_v3",
            "location": "uksouth",
            "resource_group_name": "rg",
            "tags": {},
        })], workspace="test")
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        assert any(r.recommendation_type == "sku" for r in recs)


class TestPremiumDiskInDevTest:
    """Tests for premium disk tier detection in non-prod."""

    @pytest.mark.parametrize("storage_type", ["Premium_LRS", "Premium_ZRS", "UltraSSD_LRS"])
    def test_premium_disk_in_dev_flagged(self, tmp_path, storage_type):
        """Premium disks in dev/test should be flagged."""
        plan = _plan_with([_change("azurerm_managed_disk", "disk1", {
            "storage_account_type": storage_type,
            "location": "uksouth",
            "resource_group_name": "rg-dev",
            "tags": {"environment": "test"},
        })])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        assert any(r.recommendation_type == "sku" for r in recs)

    def test_standard_disk_in_dev_not_flagged(self, tmp_path):
        """Standard_LRS in dev should not be flagged."""
        plan = _plan_with([_change("azurerm_managed_disk", "disk1", {
            "storage_account_type": "Standard_LRS",
            "location": "uksouth",
            "resource_group_name": "rg-dev",
            "tags": {"environment": "dev"},
        })])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        disk_recs = [r for r in recs if r.resource_type == "azurerm_managed_disk" and r.recommendation_type == "sku"]
        assert len(disk_recs) == 0

    def test_premium_disk_in_prod_not_flagged(self, tmp_path):
        """Premium disks in production are acceptable."""
        plan = _plan_with([_change("azurerm_managed_disk", "disk1", {
            "storage_account_type": "Premium_LRS",
            "location": "uksouth",
            "resource_group_name": "rg-prod",
            "tags": {"environment": "production"},
        })], workspace="production")
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        disk_recs = [r for r in recs if r.resource_type == "azurerm_managed_disk" and r.recommendation_type == "sku"]
        assert len(disk_recs) == 0


class TestAKSMinCount:
    """Tests for AKS min_count check in non-prod."""

    def test_aks_high_min_count_in_dev_flagged(self, tmp_path):
        """AKS default_node_pool min_count > 3 in non-prod should be flagged."""
        plan = _plan_with([_change("azurerm_kubernetes_cluster", "aks1", {
            "location": "uksouth",
            "resource_group_name": "rg-dev",
            "tags": {"environment": "dev"},
            "default_node_pool": [{"min_count": 5, "vm_size": "Standard_D2s_v3"}],
        })])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        assert any(r.recommendation_type == "sku" for r in recs)

    def test_aks_low_min_count_in_dev_not_flagged(self, tmp_path):
        """AKS min_count <= 3 in non-prod should not be flagged."""
        plan = _plan_with([_change("azurerm_kubernetes_cluster", "aks1", {
            "location": "uksouth",
            "resource_group_name": "rg-dev",
            "tags": {"environment": "dev"},
            "default_node_pool": [{"min_count": 2, "vm_size": "Standard_D2s_v3"}],
        })])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        aks_recs = [r for r in recs if r.resource_type == "azurerm_kubernetes_cluster" and r.recommendation_type == "sku"]
        assert len(aks_recs) == 0

    def test_aks_high_min_count_in_prod_not_flagged(self, tmp_path):
        """AKS min_count > 3 in production is acceptable."""
        plan = _plan_with([_change("azurerm_kubernetes_cluster", "aks1", {
            "location": "uksouth",
            "resource_group_name": "rg-prod",
            "tags": {"environment": "production"},
            "default_node_pool": [{"min_count": 5, "vm_size": "Standard_D4s_v3"}],
        })], workspace="production")
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        aks_recs = [r for r in recs if r.resource_type == "azurerm_kubernetes_cluster" and r.recommendation_type == "sku"]
        assert len(aks_recs) == 0


class TestExpensiveAppServicePlan:
    """Tests for expensive App Service Plan detection."""

    def test_expensive_asp_without_autoscale_flagged(self, tmp_path):
        """P2v3 App Service Plan without autoscale should be flagged."""
        plan = _plan_with([_change("azurerm_service_plan", "asp1", {
            "sku_name": "P2v3",
            "location": "uksouth",
            "resource_group_name": "rg",
            "tags": {"environment": "production"},
        })], workspace="production")
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        assert any(r.recommendation_type == "sku" for r in recs)

    def test_standard_asp_not_flagged(self, tmp_path):
        """S1 App Service Plan should not be flagged."""
        plan = _plan_with([_change("azurerm_service_plan", "asp1", {
            "sku_name": "S1",
            "location": "uksouth",
            "resource_group_name": "rg",
            "tags": {"environment": "production"},
        })])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        asp_recs = [r for r in recs if r.resource_type == "azurerm_service_plan" and r.recommendation_type == "sku"]
        assert len(asp_recs) == 0


class TestNoOpExclusion:
    """Tests that no-op resources are excluded."""

    def test_noop_vm_not_flagged(self, tmp_path):
        """VM with no-op action should not generate any SKU recommendations."""
        plan = _plan_with([_change("azurerm_linux_virtual_machine", "vm1", {
            "size": "Standard_D16s_v3",
            "location": "uksouth",
            "resource_group_name": "rg",
            "tags": {"environment": "dev"},
        }, action="no-op")])
        agent = PRSKUSanityAgent()
        recs = agent.analyse(_write_plan(tmp_path, plan))
        assert len(recs) == 0
