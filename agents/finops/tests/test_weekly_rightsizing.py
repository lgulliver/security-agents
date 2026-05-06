"""Tests for the Rightsizing Agent."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agents.weekly.rightsizing import (
    RightsizingAgent,
    _extract_vcpu_count,
    _get_metric,
)
from models.recommendation import Recommendation


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_resource(
    res_type: str,
    resource_id: str = "/subscriptions/sub1/resourceGroups/rg1/providers/test/myres",
    name: str = "myres",
    sku: dict | str | None = None,
    tags: dict | None = None,
) -> dict:
    return {
        "resource_id": resource_id,
        "type": res_type,
        "name": name,
        "location": "uksouth",
        "subscription_id": "sub1",
        "subscription_name": "Test Sub",
        "resource_group": "rg1",
        "tags": tags or {"owner": "platform", "environment": "production"},
        "sku": sku or {},
        "properties": {},
    }


def _make_metrics(resource_id: str, metric_key: str, window: int, value: float) -> dict:
    return {resource_id: {metric_key: {window: value}}}


# ─────────────────────────────────────────────────────────────────────────────
# Unit helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractVcpuCount:
    def test_standard_d4(self):
        assert _extract_vcpu_count("Standard_D4s_v3") == 4

    def test_standard_e8(self):
        assert _extract_vcpu_count("Standard_E8s_v4") == 8

    def test_standard_b2(self):
        assert _extract_vcpu_count("Standard_B2ms") == 2

    def test_none_returns_zero(self):
        assert _extract_vcpu_count(None) == 0

    def test_empty_string_returns_zero(self):
        assert _extract_vcpu_count("") == 0

    def test_unparseable_returns_zero(self):
        assert _extract_vcpu_count("BasicA1") == 0


class TestGetMetric:
    def test_returns_value(self):
        metrics = {"rid1": {"cpu_avg": {30: 7.5}}}
        assert _get_metric(metrics, "rid1", "cpu_avg", 30) == 7.5

    def test_missing_resource_returns_none(self):
        assert _get_metric({}, "rid1", "cpu_avg", 30) is None

    def test_missing_metric_returns_none(self):
        metrics = {"rid1": {}}
        assert _get_metric(metrics, "rid1", "cpu_avg", 30) is None

    def test_missing_window_returns_none(self):
        metrics = {"rid1": {"cpu_avg": {7: 5.0}}}
        assert _get_metric(metrics, "rid1", "cpu_avg", 30) is None


# ─────────────────────────────────────────────────────────────────────────────
# RightsizingAgent — VM checks
# ─────────────────────────────────────────────────────────────────────────────

class TestRightsizingVM:
    AGENT = RightsizingAgent(subscription_id="sub1", subscription_name="Test")

    def test_underused_vm_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, name="vm1",
                              sku={"name": "Standard_D8s_v5"})
        metrics = {rid: {
            "Percentage CPU_avg": {30: 3.0},  # 3.0 < threshold/2 (5.0) → high confidence
            "Percentage CPU_p95": {30: 25.0},
        }}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1
        rec = recs[0]
        assert rec.recommendation_type == "rightsize"
        assert rec.confidence == "high"  # avg < threshold/2
        assert rec.estimated_monthly_saving > 0

    def test_well_used_vm_not_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, name="vm2",
                              sku={"name": "Standard_D4s_v3"})
        metrics = {rid: {"Percentage CPU_avg": {30: 55.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert recs == []

    def test_no_metrics_skips_vm(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm3"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid)
        recs = self.AGENT.analyse([res], {}, [])
        assert recs == []

    def test_underused_vm_medium_confidence(self):
        """avg CPU between threshold/2 and threshold → medium confidence."""
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm4"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, sku={"name": "Standard_D4s_v3"})
        metrics = {rid: {"Percentage CPU_avg": {30: 8.0}}}  # 8 < 10 but > 5
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1
        assert recs[0].confidence == "medium"

    def test_advisor_hint_added_to_evidence(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm5"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, sku={"name": "Standard_D8s_v3"})
        metrics = {rid: {"Percentage CPU_avg": {30: 3.0}, "Percentage CPU_p95": {30: 10.0}}}
        advisor = [{"resource_id": rid, "category": "Cost", "solution": "Downsize VM"}]
        recs = self.AGENT.analyse([res], metrics, advisor)
        assert len(recs) == 1
        evidence_sources = [e.get("source") for e in recs[0].evidence]
        assert "azure_advisor" in evidence_sources

    def test_vmss_also_checked(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/vmss1"
        res = _make_resource("microsoft.compute/virtualmachinescalesets", resource_id=rid,
                              sku={"name": "Standard_D4s_v3"})
        metrics = {rid: {"Percentage CPU_avg": {30: 4.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1


# ─────────────────────────────────────────────────────────────────────────────
# App Service Plan
# ─────────────────────────────────────────────────────────────────────────────

class TestRightsizingASP:
    AGENT = RightsizingAgent()

    def test_underused_asp_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan1"
        res = _make_resource("microsoft.web/serverfarms", resource_id=rid, sku={"name": "P2v3"})
        metrics = {rid: {"CpuPercentage_avg": {30: 5.0}, "MemoryPercentage_avg": {30: 20.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1
        assert recs[0].recommendation_type == "rightsize"

    def test_busy_asp_not_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan2"
        res = _make_resource("microsoft.web/serverfarms", resource_id=rid)
        metrics = {rid: {"CpuPercentage_avg": {30: 70.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert recs == []

    def test_no_metrics_skips_asp(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan3"
        res = _make_resource("microsoft.web/serverfarms", resource_id=rid)
        recs = self.AGENT.analyse([res], {}, [])
        assert recs == []


# ─────────────────────────────────────────────────────────────────────────────
# SQL Database
# ─────────────────────────────────────────────────────────────────────────────

class TestRightsizingSQL:
    AGENT = RightsizingAgent()

    def test_underused_sql_dtu_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Sql/servers/s1/databases/db1"
        res = _make_resource("microsoft.sql/servers/databases", resource_id=rid)
        metrics = {rid: {"dtu_consumption_percent_avg": {30: 5.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1

    def test_underused_sql_cpu_fallback(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Sql/servers/s1/databases/db2"
        res = _make_resource("microsoft.sql/servers/databases", resource_id=rid)
        metrics = {rid: {"cpu_percent_avg": {30: 3.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1

    def test_busy_sql_not_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Sql/servers/s1/databases/db3"
        res = _make_resource("microsoft.sql/servers/databases", resource_id=rid)
        metrics = {rid: {"dtu_consumption_percent_avg": {30: 80.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert recs == []

    def test_no_metrics_skips_sql(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Sql/servers/s1/databases/db4"
        res = _make_resource("microsoft.sql/servers/databases", resource_id=rid)
        recs = self.AGENT.analyse([res], {}, [])
        assert recs == []


# ─────────────────────────────────────────────────────────────────────────────
# Flexible DB
# ─────────────────────────────────────────────────────────────────────────────

class TestRightsizingFlexibleDB:
    AGENT = RightsizingAgent()

    def test_underused_postgres_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg1"
        res = _make_resource("microsoft.dbforpostgresql/flexibleservers", resource_id=rid)
        metrics = {rid: {"cpu_percent_avg": {30: 4.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1
        assert recs[0].recommendation_type == "rightsize"

    def test_underused_mysql_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.DBforMySQL/flexibleServers/mysql1"
        res = _make_resource("microsoft.dbformysql/flexibleservers", resource_id=rid)
        metrics = {rid: {"cpu_percent_avg": {30: 2.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1

    def test_busy_db_not_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg2"
        res = _make_resource("microsoft.dbforpostgresql/flexibleservers", resource_id=rid)
        metrics = {rid: {"cpu_percent_avg": {30: 60.0}}}
        recs = self.AGENT.analyse([res], metrics, [])
        assert recs == []


# ─────────────────────────────────────────────────────────────────────────────
# Redis
# ─────────────────────────────────────────────────────────────────────────────

class TestRightsizingRedis:
    AGENT = RightsizingAgent()

    def test_underused_redis_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Cache/Redis/cache1"
        res = _make_resource("microsoft.cache/redis", resource_id=rid)
        metrics = {rid: {
            "percentProcessorTime_avg": {30: 5.0},
            "usedmemorypercentage_avg": {30: 20.0},
        }}
        recs = self.AGENT.analyse([res], metrics, [])
        assert len(recs) == 1
        assert recs[0].risk == "low"

    def test_high_cpu_redis_not_flagged(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Cache/Redis/cache2"
        res = _make_resource("microsoft.cache/redis", resource_id=rid)
        metrics = {rid: {
            "percentProcessorTime_avg": {30: 80.0},
            "usedmemorypercentage_avg": {30: 20.0},
        }}
        recs = self.AGENT.analyse([res], metrics, [])
        assert recs == []

    def test_missing_metrics_skips_redis(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Cache/Redis/cache3"
        res = _make_resource("microsoft.cache/redis", resource_id=rid)
        recs = self.AGENT.analyse([res], {}, [])
        assert recs == []


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate / misc
# ─────────────────────────────────────────────────────────────────────────────

class TestRightsizingAgentMisc:
    def test_unknown_resource_type_skipped(self):
        res = _make_resource("microsoft.something/else")
        agent = RightsizingAgent()
        recs = agent.analyse([res], {}, [])
        assert recs == []

    def test_recommendation_has_required_fields(self):
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm_r"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, sku={"name": "Standard_D8s_v3"})
        metrics = {rid: {"Percentage CPU_avg": {30: 3.0}}}
        agent = RightsizingAgent(subscription_id="sub1", subscription_name="MySub")
        recs = agent.analyse([res], metrics, [])
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec, Recommendation)
        assert rec.agent == "weekly.rightsizing"
        assert rec.subscription_id == "sub1"
        assert rec.estimated_monthly_saving >= 0
        assert rec.currency == "GBP"
        assert rec.reversibility == "high"
        assert rec.effort == "medium"

    def test_custom_thresholds(self):
        """Agent respects custom CPU thresholds."""
        rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vmT"
        res = _make_resource("microsoft.compute/virtualmachines", resource_id=rid, sku={"name": "Standard_D4s_v3"})
        # With default threshold (10%), 15% should NOT be flagged
        default_agent = RightsizingAgent()
        metrics = {rid: {"Percentage CPU_avg": {30: 15.0}}}
        assert default_agent.analyse([res], metrics, []) == []
        # With custom threshold (20%), 15% SHOULD be flagged
        custom_agent = RightsizingAgent(cpu_avg_threshold=20.0)
        recs = custom_agent.analyse([res], metrics, [])
        assert len(recs) == 1

    def test_empty_resources_returns_empty(self):
        agent = RightsizingAgent()
        assert agent.analyse([], {}, []) == []
