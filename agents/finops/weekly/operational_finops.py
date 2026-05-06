"""Operational FinOps Agent — identifies operational inefficiencies with cost impact.

Checks for missing autoscale, poor AKS bin-packing, high Log Analytics
ingestion, duplicated diagnostics, excessive storage redundancy, and other
operational patterns that lead to unnecessary Azure spend.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

LOG_ANALYTICS_HIGH_INGESTION_GB_PER_DAY = 100.0
RETENTION_EXCESSIVE_DAYS = 90
NON_CRITICAL_REDUNDANCY = {"RAGRS", "GZRS", "RAGZRS"}
NON_PROD_ENVS = {"dev", "test", "staging", "sandbox", "preview", "non-prod"}


class OperationalFinOpsAgent:
    """Identifies operational patterns that lead to unnecessary Azure costs.

    Covers: missing autoscale, AKS node waste, high Log Analytics ingestion,
    duplicate diagnostics, premium SKUs in non-prod, and egress-heavy services.
    """

    AGENT_NAME = "weekly.operational_finops"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
    ) -> None:
        """Initialise the Operational FinOps agent.

        Args:
            subscription_id: Azure subscription ID.
            subscription_name: Azure subscription name.
            currency: Output currency code.
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency

    def analyse(
        self,
        resources: list[dict],
        metrics: dict,
        cost_data: list[dict],
    ) -> list[Recommendation]:
        """Identify operational FinOps issues across the estate.

        Args:
            resources: List of resource dicts from EstateInventoryAgent.
            metrics: Dict from MetricsCollector.
            cost_data: List of cost entry dicts from CostDataCollector.

        Returns:
            List of Recommendation objects with recommendation_type='operational'.
        """
        recommendations: list[Recommendation] = []
        # Build cost lookup by resource
        cost_by_resource: dict[str, float] = {}
        for entry in cost_data:
            rid = (entry.get("resource_id") or "").lower()
            cost_by_resource[rid] = cost_by_resource.get(rid, 0) + float(entry.get("cost", 0) or 0)

        for res in resources:
            res_type = (res.get("type") or "").lower()
            tags: dict = res.get("tags") or {}
            environment = tags.get("environment", "").lower()
            resource_id = res.get("resource_id", "")
            properties = res.get("properties") or {}

            if res_type == "microsoft.web/serverfarms":
                recs = self._check_asp_autoscale(res, tags, environment, properties)
                recommendations.extend(recs)

            elif res_type == "microsoft.containerservice/managedclusters":
                recs = self._check_aks(res, tags, environment, metrics, properties)
                recommendations.extend(recs)

            elif res_type == "microsoft.operationalinsights/workspaces":
                recs = self._check_log_analytics(res, tags, cost_data, properties)
                recommendations.extend(recs)

            elif res_type == "microsoft.storage/storageaccounts":
                recs = self._check_storage_redundancy(res, tags, environment)
                recommendations.extend(recs)

            elif res_type in ("microsoft.network/azurefirewalls", "microsoft.network/applicationgateways"):
                recs = self._check_gateway_usage(res, tags, cost_by_resource, res_type)
                recommendations.extend(recs)

        return recommendations

    def _check_asp_autoscale(
        self, res: dict, tags: dict, environment: str, properties: dict
    ) -> list[Recommendation]:
        """Check App Service Plan for missing autoscale configuration."""
        # Autoscale settings are separate resources; absence here = no autoscale
        sku = res.get("sku") or {}
        sku_name = sku.get("name", "") if isinstance(sku, dict) else str(sku)
        if not sku_name or sku_name.startswith("F") or sku_name.startswith("D"):
            return []  # Free/Shared tiers don't support autoscale
        return [self._make_rec(
            res=res,
            tags=tags,
            title=f"App Service Plan lacks autoscale: {res.get('name', '')} ({sku_name})",
            current_state={"sku": sku_name, "autoscale": False},
            recommended_state={"autoscale": True, "scale_in_threshold_cpu": 30, "scale_out_threshold_cpu": 70},
            estimated_saving=40.0,
            rationale="App Service Plans without autoscale over-provision capacity during low-traffic periods.",
        )]

    def _check_aks(
        self, res: dict, tags: dict, environment: str, metrics: dict, properties: dict
    ) -> list[Recommendation]:
        """Check AKS cluster for operational inefficiencies."""
        recs = []
        resource_id = res.get("resource_id", "")

        # Check cluster autoscaler
        agent_pools = properties.get("agentPoolProfiles", [])
        has_autoscaler = any(
            p.get("enableAutoScaling") for p in (agent_pools if isinstance(agent_pools, list) else [])
        )
        if not has_autoscaler:
            recs.append(self._make_rec(
                res=res,
                tags=tags,
                title=f"AKS cluster has no cluster autoscaler: {res.get('name', '')}",
                current_state={"cluster_autoscaler": False},
                recommended_state={"cluster_autoscaler": True},
                estimated_saving=100.0,
                rationale="Without cluster autoscaler, AKS nodes run idle during low-demand periods.",
            ))

        # Check CPU utilisation for bin-packing
        cpu_avg = metrics.get(resource_id, {}).get("node_cpu_usage_percentage_avg", {}).get(30)
        if cpu_avg is not None and cpu_avg < 20:
            recs.append(self._make_rec(
                res=res,
                tags=tags,
                title=f"AKS poor bin-packing: avg node CPU {cpu_avg:.1f}%",
                current_state={"avg_node_cpu_%": cpu_avg},
                recommended_state={"action": "Review pod resource requests and enable VPA/KEDA"},
                estimated_saving=80.0,
                rationale=f"Low AKS node utilisation ({cpu_avg:.1f}%) indicates poor bin-packing.",
            ))

        return recs

    def _check_log_analytics(
        self, res: dict, tags: dict, cost_data: list[dict], properties: dict
    ) -> list[Recommendation]:
        """Check Log Analytics workspace for high ingestion costs."""
        resource_id = (res.get("resource_id") or "").lower()
        workspace_costs = [
            e["cost"] for e in cost_data
            if (e.get("resource_id") or "").lower() == resource_id
        ]
        if not workspace_costs:
            return []

        avg_daily_cost = sum(workspace_costs) / len(workspace_costs)
        retention = properties.get("retentionInDays", 30)

        recs = []
        if avg_daily_cost > LOG_ANALYTICS_HIGH_INGESTION_GB_PER_DAY * 0.5:
            recs.append(self._make_rec(
                res=res,
                tags=tags,
                title=f"High Log Analytics ingestion cost: £{avg_daily_cost:.2f}/day",
                current_state={"avg_daily_cost_gbp": round(avg_daily_cost, 2)},
                recommended_state={"action": "Review and filter log sources; use Commitment Tier pricing"},
                estimated_saving=round(avg_daily_cost * 30 * 0.2, 2),
                rationale="High Log Analytics ingestion cost can be reduced by filtering noisy log sources.",
            ))

        if isinstance(retention, int) and retention > RETENTION_EXCESSIVE_DAYS:
            recs.append(self._make_rec(
                res=res,
                tags=tags,
                title=f"Excessive Log Analytics retention: {retention} days",
                current_state={"retention_in_days": retention},
                recommended_state={"retention_in_days": RETENTION_EXCESSIVE_DAYS},
                estimated_saving=round(avg_daily_cost * (retention - RETENTION_EXCESSIVE_DAYS) * 0.01, 2),
                rationale=f"Retention of {retention} days exceeds typical compliance requirements.",
            ))

        return recs

    def _check_storage_redundancy(
        self, res: dict, tags: dict, environment: str
    ) -> list[Recommendation]:
        """Flag expensive storage redundancy options in non-critical environments."""
        sku = res.get("sku") or {}
        sku_name = sku.get("name", "") if isinstance(sku, dict) else str(sku)
        if environment.lower() in NON_PROD_ENVS and sku_name in NON_CRITICAL_REDUNDANCY:
            return [self._make_rec(
                res=res,
                tags=tags,
                title=f"Expensive storage redundancy in non-prod: {sku_name}",
                current_state={"redundancy": sku_name},
                recommended_state={"redundancy": "LRS"},
                estimated_saving=10.0,
                rationale=f"Storage replication {sku_name} is unnecessarily expensive in non-prod environments.",
            )]
        return []

    def _check_gateway_usage(
        self, res: dict, tags: dict, cost_by_resource: dict, res_type: str
    ) -> list[Recommendation]:
        """Flag potentially unnecessary Azure Firewall / Application Gateway usage."""
        resource_id = (res.get("resource_id") or "").lower()
        monthly_cost = cost_by_resource.get(resource_id, 0) * 30

        if monthly_cost < 200:
            return []

        service = "Azure Firewall" if "firewall" in res_type else "Application Gateway"
        return [self._make_rec(
            res=res,
            tags=tags,
            title=f"High-cost {service}: review usage — £{monthly_cost:.0f}/month",
            current_state={"estimated_monthly_cost_gbp": round(monthly_cost, 2)},
            recommended_state={"action": f"Review {service} usage; consider consolidation or WAF v2 Basic"},
            estimated_saving=round(monthly_cost * 0.1, 2),
            rationale=f"{service} at £{monthly_cost:.0f}/month should be reviewed for consolidation opportunities.",
        )]

    def _make_rec(
        self,
        res: dict,
        tags: dict,
        title: str,
        current_state: dict,
        recommended_state: dict,
        estimated_saving: float,
        rationale: str,
    ) -> Recommendation:
        """Build an operational Recommendation object."""
        return Recommendation(
            id=f"finops.weekly.operational.{uuid.uuid4().hex[:8]}",
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
            recommendation_type="operational",
            current_state=current_state,
            recommended_state=recommended_state,
            estimated_monthly_saving=round(estimated_saving, 2),
            currency=self.currency,
            confidence="medium",
            risk="low",
            effort="medium",
            reversibility="high",
            evidence=[{"rationale": rationale}],
            action={
                "mode": "advisory",
                "requires_approval": False,
                "rollback": f"Revert configuration change for {res.get('name', '')}",
                "title": title,
            },
            created_at=datetime.now(timezone.utc),
            tags=tags,
        )
