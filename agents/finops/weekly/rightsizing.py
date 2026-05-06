"""Rightsizing Agent — identifies over-provisioned Azure resources.

Consumes inventory, metrics, and Advisor data to produce rightsizing
recommendations with savings estimates, evidence, and rollback guidance.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

# Default thresholds (overridable via constructor)
DEFAULT_CPU_AVG_THRESHOLD = 10.0   # %
DEFAULT_CPU_P95_THRESHOLD = 40.0   # %
DEFAULT_MEM_AVG_THRESHOLD = 40.0   # %
DEFAULT_WINDOW_DAYS = 30


# Approximate monthly cost per vCore/tier (USD, rough estimates for sizing guidance)
VM_DOWNSIZE_SAVING_PER_VCPU = 15.0   # USD/month saved per vCPU reduced
ASP_DOWNSIZE_SAVING = 80.0           # USD/month saved per SKU tier reduction


def _get_metric(metrics: dict, resource_id: str, metric_key: str, window: int) -> float | None:
    """Safely retrieve a metric value from the metrics dict."""
    return metrics.get(resource_id, {}).get(metric_key, {}).get(window)


def _extract_vcpu_count(sku: str | None) -> int:
    """Attempt to extract vCPU count from a VM SKU name."""
    if not sku:
        return 0
    import re
    # Match patterns like Standard_D4s_v3, Standard_E8s_v4
    m = re.search(r"_[A-Z](\d+)", sku)
    if m:
        return int(m.group(1))
    return 0


class RightsizingAgent:
    """Identifies over-provisioned Azure resources and suggests downsizes.

    Consumes the output of EstateInventoryAgent, MetricsCollector, and
    AdvisorCollector to produce rightsizing Recommendation objects.
    """

    AGENT_NAME = "weekly.rightsizing"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        cpu_avg_threshold: float = DEFAULT_CPU_AVG_THRESHOLD,
        cpu_p95_threshold: float = DEFAULT_CPU_P95_THRESHOLD,
        mem_avg_threshold: float = DEFAULT_MEM_AVG_THRESHOLD,
        currency: str = "GBP",
        usd_to_gbp: float = 0.79,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> None:
        """Initialise the Rightsizing agent.

        Args:
            subscription_id: Azure subscription ID (for metadata).
            subscription_name: Azure subscription name.
            cpu_avg_threshold: Average CPU % below which we flag for downsize.
            cpu_p95_threshold: p95 CPU % below which we flag for downsize.
            mem_avg_threshold: Average memory % below which we flag for downsize.
            currency: Output currency code.
            usd_to_gbp: USD to GBP conversion rate.
            window_days: Metric window to use for analysis.
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.cpu_avg_threshold = cpu_avg_threshold
        self.cpu_p95_threshold = cpu_p95_threshold
        self.mem_avg_threshold = mem_avg_threshold
        self.currency = currency
        self.usd_to_gbp = usd_to_gbp
        self.window_days = window_days

    def analyse(
        self,
        resources: list[dict],
        metrics: dict,
        advisor: list[dict],
    ) -> list[Recommendation]:
        """Analyse resources for rightsizing opportunities.

        Args:
            resources: List of resource dicts from EstateInventoryAgent.
            metrics: Dict from MetricsCollector (resource_id → metric → window → value).
            advisor: List of Advisor dicts from AdvisorCollector.

        Returns:
            List of Recommendation objects.
        """
        advisor_index = {a["resource_id"]: a for a in advisor if a.get("category") == "Cost"}
        recommendations: list[Recommendation] = []

        for res in resources:
            res_type = (res.get("type") or "").lower()
            resource_id = res.get("resource_id", "")
            tags: dict = res.get("tags") or {}
            owner = tags.get("owner", "")
            environment = tags.get("environment", "")

            if res_type in ("microsoft.compute/virtualmachines", "microsoft.compute/virtualmachinescalesets"):
                recs = self._check_vm(res, metrics, advisor_index)
                recommendations.extend(recs)
            elif res_type == "microsoft.web/serverfarms":
                recs = self._check_app_service_plan(res, metrics, advisor_index)
                recommendations.extend(recs)
            elif res_type == "microsoft.sql/servers/databases":
                recs = self._check_sql_database(res, metrics, advisor_index)
                recommendations.extend(recs)
            elif res_type in (
                "microsoft.dbforpostgresql/flexibleservers",
                "microsoft.dbformysql/flexibleservers",
            ):
                recs = self._check_flexible_db(res, metrics, advisor_index)
                recommendations.extend(recs)
            elif res_type == "microsoft.cache/redis":
                recs = self._check_redis(res, metrics, advisor_index)
                recommendations.extend(recs)

        return recommendations

    def _check_vm(self, res: dict, metrics: dict, advisor_index: dict) -> list[Recommendation]:
        """Check a VM or VMSS for rightsizing opportunities."""
        resource_id = res.get("resource_id", "")
        cpu_avg = _get_metric(metrics, resource_id, "Percentage CPU_avg", self.window_days)
        cpu_p95 = _get_metric(metrics, resource_id, "Percentage CPU_p95", self.window_days)

        if cpu_avg is None:
            return []

        is_underused = cpu_avg < self.cpu_avg_threshold and (cpu_p95 is None or cpu_p95 < self.cpu_p95_threshold)
        if not is_underused:
            return []

        sku_info = res.get("sku") or {}
        current_sku = sku_info.get("name", "") if isinstance(sku_info, dict) else str(sku_info)
        vcpus = _extract_vcpu_count(current_sku)
        estimated_saving_gbp = max(0.0, (vcpus / 2) * VM_DOWNSIZE_SAVING_PER_VCPU * self.usd_to_gbp)

        advisor_hint = advisor_index.get(resource_id, {})
        evidence = [
            {
                "source": "azure_monitor",
                "cpu_avg_%": cpu_avg,
                "cpu_p95_%": cpu_p95,
                "window_days": self.window_days,
            }
        ]
        if advisor_hint:
            evidence.append({"source": "azure_advisor", "solution": advisor_hint.get("solution", "")})

        confidence = "high" if cpu_avg < (self.cpu_avg_threshold / 2) else "medium"
        tags: dict = res.get("tags") or {}

        return [self._make_rec(
            res=res,
            title=f"Underutilised VM/VMSS: avg CPU {cpu_avg:.1f}%",
            current_state={"sku": current_sku, "cpu_avg_%": cpu_avg, "cpu_p95_%": cpu_p95},
            recommended_state={"action": "Downsize to smaller SKU or use Spot/Burstable instances"},
            estimated_saving=estimated_saving_gbp,
            confidence=confidence,
            risk="medium",
            evidence=evidence,
            tags=tags,
        )]

    def _check_app_service_plan(self, res: dict, metrics: dict, advisor_index: dict) -> list[Recommendation]:
        """Check an App Service Plan for rightsizing opportunities."""
        resource_id = res.get("resource_id", "")
        cpu_avg = _get_metric(metrics, resource_id, "CpuPercentage_avg", self.window_days)
        mem_avg = _get_metric(metrics, resource_id, "MemoryPercentage_avg", self.window_days)

        if cpu_avg is None:
            return []

        if cpu_avg >= self.cpu_avg_threshold:
            return []

        tags: dict = res.get("tags") or {}
        sku_info = res.get("sku") or {}
        current_sku = sku_info.get("name", "") if isinstance(sku_info, dict) else str(sku_info)

        return [self._make_rec(
            res=res,
            title=f"Underutilised App Service Plan: avg CPU {cpu_avg:.1f}%",
            current_state={"sku": current_sku, "cpu_avg_%": cpu_avg, "mem_avg_%": mem_avg},
            recommended_state={"action": "Downsize App Service Plan SKU tier"},
            estimated_saving=ASP_DOWNSIZE_SAVING * self.usd_to_gbp,
            confidence="medium",
            risk="medium",
            evidence=[{"source": "azure_monitor", "cpu_avg_%": cpu_avg, "mem_avg_%": mem_avg}],
            tags=tags,
        )]

    def _check_sql_database(self, res: dict, metrics: dict, advisor_index: dict) -> list[Recommendation]:
        """Check an Azure SQL database for rightsizing opportunities."""
        resource_id = res.get("resource_id", "")
        dtu_avg = _get_metric(metrics, resource_id, "dtu_consumption_percent_avg", self.window_days)
        cpu_avg = _get_metric(metrics, resource_id, "cpu_percent_avg", self.window_days)

        utilisation = dtu_avg or cpu_avg
        if utilisation is None or utilisation >= self.cpu_avg_threshold:
            return []

        tags: dict = res.get("tags") or {}
        return [self._make_rec(
            res=res,
            title=f"Underutilised Azure SQL: utilisation {utilisation:.1f}%",
            current_state={"utilisation_%": utilisation},
            recommended_state={"action": "Reduce DTU/vCore count or switch to serverless tier"},
            estimated_saving=50.0 * self.usd_to_gbp,
            confidence="medium",
            risk="medium",
            evidence=[{"source": "azure_monitor", "utilisation_%": utilisation}],
            tags=tags,
        )]

    def _check_flexible_db(self, res: dict, metrics: dict, advisor_index: dict) -> list[Recommendation]:
        """Check a PostgreSQL/MySQL Flexible Server for rightsizing."""
        resource_id = res.get("resource_id", "")
        cpu_avg = _get_metric(metrics, resource_id, "cpu_percent_avg", self.window_days)

        if cpu_avg is None or cpu_avg >= self.cpu_avg_threshold:
            return []

        tags: dict = res.get("tags") or {}
        return [self._make_rec(
            res=res,
            title=f"Underutilised Flexible DB: avg CPU {cpu_avg:.1f}%",
            current_state={"cpu_avg_%": cpu_avg},
            recommended_state={"action": "Reduce compute tier or vCore count"},
            estimated_saving=40.0 * self.usd_to_gbp,
            confidence="medium",
            risk="medium",
            evidence=[{"source": "azure_monitor", "cpu_avg_%": cpu_avg}],
            tags=tags,
        )]

    def _check_redis(self, res: dict, metrics: dict, advisor_index: dict) -> list[Recommendation]:
        """Check an Azure Cache for Redis for rightsizing."""
        resource_id = res.get("resource_id", "")
        cpu_avg = _get_metric(metrics, resource_id, "percentProcessorTime_avg", self.window_days)
        mem_avg = _get_metric(metrics, resource_id, "usedmemorypercentage_avg", self.window_days)

        if cpu_avg is None or mem_avg is None:
            return []
        if cpu_avg >= self.cpu_avg_threshold or mem_avg >= self.mem_avg_threshold:
            return []

        tags: dict = res.get("tags") or {}
        return [self._make_rec(
            res=res,
            title=f"Underutilised Redis: CPU {cpu_avg:.1f}%, memory {mem_avg:.1f}%",
            current_state={"cpu_avg_%": cpu_avg, "memory_avg_%": mem_avg},
            recommended_state={"action": "Downsize Redis cache tier or capacity"},
            estimated_saving=30.0 * self.usd_to_gbp,
            confidence="medium",
            risk="low",
            evidence=[{"source": "azure_monitor", "cpu_avg_%": cpu_avg, "mem_avg_%": mem_avg}],
            tags=tags,
        )]

    def _make_rec(
        self,
        res: dict,
        title: str,
        current_state: dict,
        recommended_state: dict,
        estimated_saving: float,
        confidence: str,
        risk: str,
        evidence: list[dict],
        tags: dict,
    ) -> Recommendation:
        """Create a Recommendation from a resource and analysis data."""
        return Recommendation(
            id=f"finops.weekly.rightsizing.{uuid.uuid4().hex[:8]}",
            agent=self.AGENT_NAME,
            subscription_id=res.get("subscription_id", self.subscription_id),
            subscription_name=res.get("subscription_name", self.subscription_name),
            resource_id=res.get("resource_id", ""),
            resource_type=res.get("type", ""),
            resource_name=res.get("name", ""),
            resource_group=res.get("resource_group", ""),
            location=res.get("location", ""),
            owner=tags.get("owner", ""),
            environment=tags.get("environment", ""),
            recommendation_type="rightsize",
            current_state=current_state,
            recommended_state=recommended_state,
            estimated_monthly_saving=round(estimated_saving, 2),
            currency=self.currency,
            confidence=confidence,
            risk=risk,
            effort="medium",
            reversibility="high",
            evidence=evidence,
            action={
                "mode": "advisory",
                "requires_approval": True,
                "rollback": f"Resize back to original SKU via Azure Portal or Terraform",
                "title": title,
            },
            created_at=datetime.now(timezone.utc),
            tags=tags,
        )
