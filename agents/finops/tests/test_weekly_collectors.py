"""Tests for the weekly Azure data collector agents:
subscription_discovery, estate_inventory, advisor_collector,
metrics_collector, and cost_data_collector.

All Azure SDK calls are fully mocked.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest

from azure.core.exceptions import HttpResponseError


# ─────────────────────────────────────────────────────────────────────────────
# SubscriptionDiscoveryAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestSubscriptionDiscoveryAgent:
    def _make_sub(self, sub_id="sub1", display_name="Sub One",
                  tenant_id="tenant1", tags=None, state="Enabled"):
        sub = Mock()
        sub.subscription_id = sub_id
        sub.display_name = display_name
        sub.tenant_id = tenant_id
        sub.tags = tags or {}
        sub.state = state
        return sub

    def _make_child(self, child_type: str, name: str):
        child = Mock()
        child.type = child_type
        child.name = name
        return child

    def test_discover_from_explicit_subscription(self):
        from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent

        mock_sub = self._make_sub()
        mock_client = Mock()
        mock_client.subscriptions.get.return_value = mock_sub

        with patch("agents.weekly.subscription_discovery.SubscriptionClient", return_value=mock_client), \
             patch("agents.weekly.subscription_discovery._make_credential"):
            agent = SubscriptionDiscoveryAgent(subscription_ids=["sub1"])
            result = agent.discover()

        assert len(result) == 1
        assert result[0]["subscription_id"] == "sub1"
        assert result[0]["name"] == "Sub One"

    def test_discover_http_error_logged_and_skipped(self):
        from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent

        with patch("agents.weekly.subscription_discovery.SubscriptionClient"), \
             patch("agents.weekly.subscription_discovery._make_credential"):
            agent = SubscriptionDiscoveryAgent(subscription_ids=["sub1"])
            # Patch the retried method directly so tenacity doesn't kick in
            with patch.object(agent, "_get_subscription_detail", side_effect=HttpResponseError(message="403")):
                result = agent.discover()

        assert result == []

    def test_discover_from_management_group_subscription_child(self):
        from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent

        sub_child = self._make_child("/subscriptions", "sub1")
        mg = Mock()
        mg.children = [sub_child]

        mock_mg_client = Mock()
        mock_mg_client.management_groups.get.return_value = mg

        mock_sub_client = Mock()
        mock_sub_client.subscriptions.get.return_value = self._make_sub()

        with patch("agents.weekly.subscription_discovery.ManagementGroupsAPI", return_value=mock_mg_client), \
             patch("agents.weekly.subscription_discovery.SubscriptionClient", return_value=mock_sub_client), \
             patch("agents.weekly.subscription_discovery._make_credential"):
            agent = SubscriptionDiscoveryAgent(management_group_ids=["mg-root"])
            result = agent.discover()

        assert len(result) == 1
        assert result[0]["management_group_path"] == "mg-root"

    def test_discover_from_management_group_child_mg(self):
        """Nested management group → recurses into child MG."""
        from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent

        child_mg = self._make_child("/providers/Microsoft.Management/managementGroups", "mg-child")
        sub_child = self._make_child("/subscriptions", "sub1")

        root_mg = Mock()
        root_mg.children = [child_mg]
        child_mg_obj = Mock()
        child_mg_obj.children = [sub_child]

        mock_mg_client = Mock()
        mock_mg_client.management_groups.get.side_effect = [root_mg, child_mg_obj]

        mock_sub_client = Mock()
        mock_sub_client.subscriptions.get.return_value = self._make_sub()

        with patch("agents.weekly.subscription_discovery.ManagementGroupsAPI", return_value=mock_mg_client), \
             patch("agents.weekly.subscription_discovery.SubscriptionClient", return_value=mock_sub_client), \
             patch("agents.weekly.subscription_discovery._make_credential"):
            agent = SubscriptionDiscoveryAgent(management_group_ids=["mg-root"])
            result = agent.discover()

        assert len(result) == 1

    def test_discover_mg_http_error_logged(self):
        from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent

        mock_mg_client = Mock()
        mock_mg_client.management_groups.get.side_effect = HttpResponseError(message="404")

        with patch("agents.weekly.subscription_discovery.ManagementGroupsAPI", return_value=mock_mg_client), \
             patch("agents.weekly.subscription_discovery._make_credential"):
            agent = SubscriptionDiscoveryAgent(management_group_ids=["mg-root"])
            result = agent.discover()

        assert result == []

    def test_owner_tag_extracted(self):
        from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent

        mock_sub = self._make_sub(tags={"owner": "finops-team"})
        mock_client = Mock()
        mock_client.subscriptions.get.return_value = mock_sub

        with patch("agents.weekly.subscription_discovery.SubscriptionClient", return_value=mock_client), \
             patch("agents.weekly.subscription_discovery._make_credential"):
            agent = SubscriptionDiscoveryAgent(subscription_ids=["sub1"])
            result = agent.discover()

        assert result[0]["owner"] == "finops-team"

    def test_empty_inputs_returns_empty(self):
        from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent

        with patch("agents.weekly.subscription_discovery._make_credential"):
            agent = SubscriptionDiscoveryAgent()
            result = agent.discover()

        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# EstateInventoryAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestEstateInventoryAgent:
    def test_collect_empty_subscription_ids(self):
        from agents.weekly.estate_inventory import EstateInventoryAgent
        agent = EstateInventoryAgent(credential=Mock())
        result = agent.collect([])
        assert result == []

    def test_collect_single_page(self):
        from agents.weekly.estate_inventory import EstateInventoryAgent

        mock_response = Mock()
        mock_response.data = [{"resource_id": "/sub/rg/res1", "type": "Microsoft.Compute/virtualMachines"}]
        mock_response.skip_token = None
        mock_response.result_truncated = None

        mock_client = Mock()
        mock_client.resources.return_value = mock_response

        with patch("agents.weekly.estate_inventory.ResourceGraphClient", return_value=mock_client):
            agent = EstateInventoryAgent(credential=Mock())
            result = agent.collect(["sub1"])

        assert len(result) == 1

    def test_collect_multiple_pages(self):
        from agents.weekly.estate_inventory import EstateInventoryAgent

        page1 = Mock()
        page1.data = [{"resource_id": "/sub/rg/res1"}]
        page1.skip_token = "token123"
        page1.result_truncated = None

        page2 = Mock()
        page2.data = [{"resource_id": "/sub/rg/res2"}]
        page2.skip_token = None
        page2.result_truncated = None

        mock_client = Mock()
        mock_client.resources.side_effect = [page1, page2]

        with patch("agents.weekly.estate_inventory.ResourceGraphClient", return_value=mock_client):
            agent = EstateInventoryAgent(credential=Mock())
            result = agent.collect(["sub1"])

        assert len(result) == 2

    def test_collect_http_error_returns_partial(self):
        from agents.weekly.estate_inventory import EstateInventoryAgent

        mock_client = Mock()

        with patch("agents.weekly.estate_inventory.ResourceGraphClient", return_value=mock_client):
            agent = EstateInventoryAgent(credential=Mock())
            # Patch the retried method to raise HttpResponseError directly (bypass tenacity)
            with patch.object(agent, "_query_page", side_effect=HttpResponseError(message="500")):
                result = agent.collect(["sub1"])

        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# AdvisorCollector
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvisorCollector:
    def _make_advisor_rec(self, category="Cost", resource_id="/sub1/rg/vm1", impact="High"):
        rec = Mock()
        rec.id = "/advisors/rec1"
        rec.category = category
        rec.impact = impact
        rec.resource_metadata = Mock()
        rec.resource_metadata.resource_id = resource_id
        rec.impacted_field = "Microsoft.Compute/virtualMachines"
        rec.impacted_value = "my-vm"
        rec.short_description = Mock()
        rec.short_description.problem = "VM underutilised"
        rec.short_description.solution = "Downsize VM"
        rec.extended_properties = {}
        rec.potential_benefits = "30% cost savings"
        rec.recommendation_type_id = "rightsizing"
        rec.last_updated = "2025-01-01"
        return rec

    def test_collect_returns_recommendations(self):
        from agents.weekly.advisor_collector import AdvisorCollector

        mock_client = Mock()
        mock_client.recommendations.list.return_value = [
            self._make_advisor_rec("Cost"),
            self._make_advisor_rec("OperationalExcellence"),
        ]

        with patch("agents.weekly.advisor_collector.AdvisorManagementClient", return_value=mock_client):
            agent = AdvisorCollector(credential=Mock())
            result = agent.collect(["sub1"])

        assert len(result) == 2
        assert result[0]["category"] == "Cost"

    def test_collect_excludes_security_by_default(self):
        from agents.weekly.advisor_collector import AdvisorCollector

        mock_client = Mock()
        mock_client.recommendations.list.return_value = [
            self._make_advisor_rec("Security"),
        ]

        with patch("agents.weekly.advisor_collector.AdvisorManagementClient", return_value=mock_client):
            agent = AdvisorCollector(credential=Mock())
            result = agent.collect(["sub1"])

        assert result == []

    def test_collect_includes_security_when_enabled(self):
        from agents.weekly.advisor_collector import AdvisorCollector

        mock_client = Mock()
        mock_client.recommendations.list.return_value = [
            self._make_advisor_rec("Security"),
        ]

        with patch("agents.weekly.advisor_collector.AdvisorManagementClient", return_value=mock_client):
            agent = AdvisorCollector(credential=Mock())
            result = agent.collect(["sub1"], include_security=True)

        assert len(result) == 1

    def test_collect_http_error_skips_subscription(self):
        from agents.weekly.advisor_collector import AdvisorCollector

        mock_client = Mock()

        with patch("agents.weekly.advisor_collector.AdvisorManagementClient", return_value=mock_client):
            agent = AdvisorCollector(credential=Mock())
            # Patch the retried method directly to bypass tenacity
            with patch.object(agent, "_collect_for_subscription", side_effect=HttpResponseError(message="403")):
                result = agent.collect(["sub1"])

        assert result == []

    def test_collect_multiple_subscriptions(self):
        from agents.weekly.advisor_collector import AdvisorCollector

        mock_client = Mock()
        mock_client.recommendations.list.return_value = [self._make_advisor_rec()]

        with patch("agents.weekly.advisor_collector.AdvisorManagementClient", return_value=mock_client):
            agent = AdvisorCollector(credential=Mock())
            result = agent.collect(["sub1", "sub2"])

        assert len(result) == 2

    def test_collect_normalises_fields(self):
        from agents.weekly.advisor_collector import AdvisorCollector

        mock_client = Mock()
        mock_client.recommendations.list.return_value = [self._make_advisor_rec()]

        with patch("agents.weekly.advisor_collector.AdvisorManagementClient", return_value=mock_client):
            agent = AdvisorCollector(credential=Mock())
            result = agent.collect(["sub1"])

        rec = result[0]
        assert "advisor_id" in rec
        assert "category" in rec
        assert "resource_id" in rec
        assert "problem" in rec
        assert "solution" in rec


# ─────────────────────────────────────────────────────────────────────────────
# MetricsCollector
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsCollector:
    def _make_metric_response(self, metric_name="Percentage CPU", avg_value=12.5):
        dp = Mock()
        dp.average = avg_value
        dp.maximum = avg_value * 1.5

        ts = Mock()
        ts.data = [dp]

        metric = Mock()
        metric.name = Mock()
        metric.name.value = metric_name
        metric.timeseries = [ts]

        response = Mock()
        response.value = [metric]
        return response

    def test_collect_returns_metrics(self):
        from agents.weekly.metrics_collector import MetricsCollector

        resources = [{
            "resource_id": "/subscriptions/sub1/rg/vm1",
            "type": "microsoft.compute/virtualmachines",
            "subscription_id": "sub1",
        }]

        mock_client = Mock()
        mock_client.metrics.list.return_value = self._make_metric_response()

        with patch("agents.weekly.metrics_collector.MonitorManagementClient", return_value=mock_client):
            agent = MetricsCollector(credential=Mock())
            result = agent.collect(resources, windows=[30])

        assert "/subscriptions/sub1/rg/vm1" in result

    def test_collect_unknown_resource_type_skipped(self):
        from agents.weekly.metrics_collector import MetricsCollector

        resources = [{
            "resource_id": "/subscriptions/sub1/rg/unknown1",
            "type": "microsoft.unknown/thing",
            "subscription_id": "sub1",
        }]

        mock_client = Mock()
        with patch("agents.weekly.metrics_collector.MonitorManagementClient", return_value=mock_client):
            agent = MetricsCollector(credential=Mock())
            result = agent.collect(resources, windows=[30])

        assert result == {}

    def test_collect_http_error_skips_resource(self):
        from agents.weekly.metrics_collector import MetricsCollector

        resources = [{
            "resource_id": "/subscriptions/sub1/rg/vm_err",
            "type": "microsoft.compute/virtualmachines",
            "subscription_id": "sub1",
        }]

        mock_client = Mock()
        with patch("agents.weekly.metrics_collector.MonitorManagementClient", return_value=mock_client):
            agent = MetricsCollector(credential=Mock())
            # Patch the retried method to raise HttpResponseError directly
            with patch.object(agent, "_query_resource_metrics", side_effect=HttpResponseError(message="429")):
                result = agent.collect(resources, windows=[30])

        # Should handle gracefully
        assert isinstance(result, dict)

    def test_collect_multiple_windows(self):
        from agents.weekly.metrics_collector import MetricsCollector

        rid = "/subscriptions/sub1/rg/vm_multi"
        resources = [{"resource_id": rid, "type": "microsoft.compute/virtualmachines", "subscription_id": "sub1"}]

        mock_client = Mock()
        mock_client.metrics.list.return_value = self._make_metric_response()

        with patch("agents.weekly.metrics_collector.MonitorManagementClient", return_value=mock_client):
            agent = MetricsCollector(credential=Mock())
            result = agent.collect(resources, windows=[7, 30])

        # Should have been called for each window
        assert mock_client.metrics.list.call_count == 2

    def test_collect_empty_resources(self):
        from agents.weekly.metrics_collector import MetricsCollector

        agent = MetricsCollector(credential=Mock())
        result = agent.collect([], windows=[30])
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# CostDataCollector
# ─────────────────────────────────────────────────────────────────────────────

class TestCostDataCollector:
    def test_collect_from_api(self):
        from agents.weekly.cost_data_collector import CostDataCollector

        mock_response = Mock()
        mock_response.columns = [
            Mock(name="UsageDate"),
            Mock(name="ResourceId"),
            Mock(name="ResourceType"),
            Mock(name="ResourceGroupName"),
            Mock(name="ServiceName"),
            Mock(name="MeterCategory"),
            Mock(name="totalCost"),
        ]
        # columns have .name attribute
        for col in mock_response.columns:
            col.name = col.name  # already set as Mock attribute
        # Actually set .name properly
        col_names = ["UsageDate", "ResourceId", "ResourceType",
                     "ResourceGroupName", "ServiceName", "MeterCategory", "totalCost"]
        mock_response.columns = [Mock() for _ in col_names]
        for col, name in zip(mock_response.columns, col_names):
            col.name = name
        mock_response.rows = [["20250101", "/sub1/rg/vm1", "Microsoft.Compute/virtualMachines",
                                "rg1", "Virtual Machines", "Compute", 25.50]]

        mock_client = Mock()
        mock_client.query.usage.return_value = mock_response

        with patch("agents.weekly.cost_data_collector.CostManagementClient", return_value=mock_client), \
             patch.dict("os.environ", {}, clear=False):
            agent = CostDataCollector(credential=Mock())
            result = agent.collect(["sub1"], days=30)

        assert len(result) == 1
        assert result[0]["subscription_id"] == "sub1"
        assert result[0]["cost"] == 25.50

    def test_collect_http_error_skips_subscription(self):
        from agents.weekly.cost_data_collector import CostDataCollector

        mock_client = Mock()

        with patch("agents.weekly.cost_data_collector.CostManagementClient", return_value=mock_client):
            agent = CostDataCollector(credential=Mock())
            # Patch the retried method directly to bypass tenacity
            with patch.object(agent, "_query_subscription_costs", side_effect=HttpResponseError(message="500")):
                result = agent.collect(["sub1"])

        assert result == []

    def test_parse_cost_csv(self):
        from agents.weekly.cost_data_collector import CostDataCollector

        csv_text = (
            "SubscriptionId,Date,ResourceId,ResourceType,ResourceGroup,"
            "ServiceName,MeterCategory,PreTaxCost,Currency\n"
            "sub1,20250101,/sub1/rg/vm1,Microsoft.Compute/virtualMachines,"
            "rg1,VMs,Compute,100.50,GBP\n"
        )
        agent = CostDataCollector(credential=Mock())
        result = agent._parse_cost_csv(csv_text)
        assert len(result) == 1
        assert result[0]["cost"] == 100.50
        assert result[0]["currency"] == "GBP"

    def test_parse_cost_csv_empty(self):
        from agents.weekly.cost_data_collector import CostDataCollector

        agent = CostDataCollector(credential=Mock())
        result = agent._parse_cost_csv("SubscriptionId,Date\n")
        assert result == []

    def test_collect_from_blob_when_env_set(self):
        from agents.weekly.cost_data_collector import CostDataCollector

        csv_content = (
            "SubscriptionId,Date,ResourceId,ResourceType,ResourceGroup,"
            "ServiceName,MeterCategory,PreTaxCost,Currency\n"
            "sub1,20250101,/sub1/rg/vm1,vm,rg1,VMs,Compute,10.0,GBP\n"
        )

        mock_blob_data = Mock()
        mock_blob_data.readall.return_value = csv_content.encode()

        mock_blob = Mock()
        mock_blob.name = "export.csv"
        from datetime import timedelta
        mock_blob.last_modified = datetime.now(timezone.utc)  # fresh blob

        mock_container_client = Mock()
        mock_container_client.list_blobs.return_value = [mock_blob]
        mock_container_client.download_blob.return_value = mock_blob_data

        mock_container_item = {"name": "costs"}

        mock_blob_service = Mock()
        mock_blob_service.list_containers.return_value = [mock_container_item]
        mock_blob_service.get_container_client.return_value = mock_container_client

        # BlobServiceClient is imported lazily inside the function; patch the class so that
        # calling it (instantiating) returns mock_blob_service
        mock_blob_cls = Mock(return_value=mock_blob_service)

        with patch("azure.storage.blob.BlobServiceClient", mock_blob_cls), \
             patch.dict("os.environ", {"COST_EXPORT_STORAGE_ACCOUNT": "mystorageacct"}):
            agent = CostDataCollector(credential=Mock())
            result = agent.collect(["sub1"], days=30)

        assert len(result) >= 1

    def test_collect_fallback_when_blob_fails(self):
        from agents.weekly.cost_data_collector import CostDataCollector

        mock_response = Mock()
        mock_response.columns = []
        mock_response.rows = []

        mock_api_client = Mock()
        mock_api_client.query.usage.return_value = mock_response

        # BlobServiceClient constructor raises → trigger fallback to API
        mock_blob_cls = Mock(side_effect=Exception("blob error"))

        with patch("azure.storage.blob.BlobServiceClient", mock_blob_cls), \
             patch("agents.weekly.cost_data_collector.CostManagementClient", return_value=mock_api_client), \
             patch.dict("os.environ", {"COST_EXPORT_STORAGE_ACCOUNT": "mystorageacct"}):
            agent = CostDataCollector(credential=Mock())
            result = agent.collect(["sub1"], days=30)

        # Should have fallen back to API
        assert isinstance(result, list)
