"""Waste/Orphan Agent — identifies wasteful and orphaned Azure resources.

Detects unattached disks, orphaned NICs, stopped VMs, old snapshots, idle
load balancers, and other common sources of Azure waste.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

SNAPSHOT_AGE_THRESHOLD_DAYS = 90
LOG_ANALYTICS_UNDERUSE_THRESHOLD_GB_PER_DAY = 1.0


def _get_tag(tags: dict | None, key: str, default: str = "") -> str:
    return (tags or {}).get(key, default)


class WasteOrphanAgent:
    """Identifies wasteful and orphaned resources across the Azure estate.

    Each finding is classified as: safe_to_delete, needs_owner_review, risky,
    or ignore.
    """

    AGENT_NAME = "weekly.waste_orphan"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
        snapshot_age_days: int = SNAPSHOT_AGE_THRESHOLD_DAYS,
    ) -> None:
        """Initialise the Waste/Orphan agent.

        Args:
            subscription_id: Azure subscription ID.
            subscription_name: Azure subscription name.
            currency: Output currency code.
            snapshot_age_days: Age threshold for flagging old snapshots.
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency
        self.snapshot_age_days = snapshot_age_days

    def analyse(self, resources: list[dict], cost_data: list[dict]) -> list[Recommendation]:
        """Identify wasteful and orphaned resources.

        Args:
            resources: List of resource dicts from EstateInventoryAgent.
            cost_data: List of cost entry dicts from CostDataCollector.

        Returns:
            List of Recommendation objects with recommendation_type='waste'.
        """
        # Build a set of resource IDs referenced in the cost data
        cost_resource_ids = {(e.get("resource_id") or "").lower() for e in cost_data}

        recommendations: list[Recommendation] = []
        now = datetime.now(timezone.utc)

        for res in resources:
            res_type = (res.get("type") or "").lower()
            resource_id = res.get("resource_id", "")
            tags: dict = res.get("tags") or {}
            properties = res.get("properties") or {}

            recs = []

            if res_type == "microsoft.compute/disks":
                recs = self._check_disk(res, tags, properties)
            elif res_type == "microsoft.network/networkinterfaces":
                recs = self._check_nic(res, tags, properties)
            elif res_type == "microsoft.network/publicipaddresses":
                recs = self._check_public_ip(res, tags, properties)
            elif res_type == "microsoft.compute/virtualmachines":
                recs = self._check_vm(res, tags, properties)
            elif res_type == "microsoft.compute/snapshots":
                recs = self._check_snapshot(res, tags, properties, now)
            elif res_type == "microsoft.network/loadbalancers":
                recs = self._check_load_balancer(res, tags, properties)
            elif res_type == "microsoft.network/natgateways":
                recs = self._check_nat_gateway(res, tags, properties)
            elif res_type == "microsoft.web/serverfarms":
                recs = self._check_app_service_plan(res, tags, properties, resources)
            elif res_type == "microsoft.operationalinsights/workspaces":
                recs = self._check_log_analytics(res, tags, properties, cost_data)

            recommendations.extend(recs)

        return recommendations

    def _check_disk(self, res: dict, tags: dict, properties: dict) -> list[Recommendation]:
        """Flag unattached managed disks."""
        disk_state = str(properties.get("diskState", "")).lower()
        if disk_state not in ("unattached", ""):
            return []
        managed_by = res.get("managed_by") or properties.get("managedBy")
        if managed_by:
            return []
        return [self._make_rec(
            res=res,
            title=f"Unattached managed disk: {res.get('name', '')}",
            classification="safe_to_delete",
            current_state={"disk_state": disk_state},
            recommended_state={"action": "Delete unattached disk or verify intended use"},
            estimated_saving=10.0,
            risk="low",
            rationale="Unattached managed disks incur storage costs without providing value.",
        )]

    def _check_nic(self, res: dict, tags: dict, properties: dict) -> list[Recommendation]:
        """Flag orphaned NICs (not attached to any VM)."""
        vm_id = properties.get("virtualMachine", {})
        if vm_id:
            return []
        return [self._make_rec(
            res=res,
            title=f"Orphaned NIC: {res.get('name', '')}",
            classification="needs_owner_review",
            current_state={"virtual_machine": None},
            recommended_state={"action": "Delete orphaned NIC or attach to a VM"},
            estimated_saving=1.0,
            risk="low",
            rationale="Orphaned NICs represent clutter and potential configuration drift.",
        )]

    def _check_public_ip(self, res: dict, tags: dict, properties: dict) -> list[Recommendation]:
        """Flag unassociated public IPs."""
        ip_config = properties.get("ipConfiguration")
        nat_gw = properties.get("natGateway")
        linked_lb = properties.get("loadBalancerFrontendIpConfiguration")
        if ip_config or nat_gw or linked_lb:
            return []
        return [self._make_rec(
            res=res,
            title=f"Unassociated Public IP: {res.get('name', '')}",
            classification="safe_to_delete",
            current_state={"association": None},
            recommended_state={"action": "Delete unassociated public IP"},
            estimated_saving=3.0,
            risk="low",
            rationale="Unassociated public IPs still incur hourly charges.",
        )]

    def _check_vm(self, res: dict, tags: dict, properties: dict) -> list[Recommendation]:
        """Flag stopped-but-not-deallocated VMs."""
        power_state = str(properties.get("extended", {}).get("instanceView", {}).get("powerState", {}).get("code", "")).lower()
        if "stopped" in power_state and "deallocated" not in power_state:
            return [self._make_rec(
                res=res,
                title=f"VM is stopped but not deallocated: {res.get('name', '')}",
                classification="needs_owner_review",
                current_state={"power_state": power_state},
                recommended_state={"action": "Deallocate VM to stop compute charges"},
                estimated_saving=30.0,
                risk="medium",
                rationale="Stopped (not deallocated) VMs continue to incur compute charges.",
            )]
        return []

    def _check_snapshot(self, res: dict, tags: dict, properties: dict, now: datetime) -> list[Recommendation]:
        """Flag old snapshots beyond the retention threshold."""
        time_created_str = properties.get("timeCreated", "")
        if not time_created_str:
            return []
        try:
            from dateutil import parser as dtparser
            parsed = dtparser.parse(time_created_str)
            # Normalise to a naive UTC datetime for arithmetic
            created = parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.replace(tzinfo=None)
            now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
            age_days = (now_naive - created).days
        except Exception:  # noqa: BLE001
            return []

        if age_days <= self.snapshot_age_days:
            return []

        return [self._make_rec(
            res=res,
            title=f"Old snapshot ({age_days}d): {res.get('name', '')}",
            classification="safe_to_delete",
            current_state={"age_days": age_days, "time_created": time_created_str},
            recommended_state={"action": f"Delete snapshots older than {self.snapshot_age_days} days"},
            estimated_saving=5.0,
            risk="low",
            rationale=f"Snapshot is {age_days} days old (threshold: {self.snapshot_age_days}d).",
        )]

    def _check_load_balancer(self, res: dict, tags: dict, properties: dict) -> list[Recommendation]:
        """Flag load balancers with no backend pools."""
        backend_pools = properties.get("backendAddressPools", [])
        if backend_pools:
            return []
        return [self._make_rec(
            res=res,
            title=f"Idle Load Balancer (no backend pools): {res.get('name', '')}",
            classification="needs_owner_review",
            current_state={"backend_pools": 0},
            recommended_state={"action": "Delete idle load balancer or add backend pool"},
            estimated_saving=15.0,
            risk="low",
            rationale="Load balancers with no backend pools still incur hourly charges.",
        )]

    def _check_nat_gateway(self, res: dict, tags: dict, properties: dict) -> list[Recommendation]:
        """Flag NAT gateways with no subnet associations."""
        subnets = properties.get("subnets", [])
        if subnets:
            return []
        return [self._make_rec(
            res=res,
            title=f"Idle NAT Gateway (no subnet associations): {res.get('name', '')}",
            classification="needs_owner_review",
            current_state={"subnets": 0},
            recommended_state={"action": "Delete idle NAT gateway or associate with a subnet"},
            estimated_saving=30.0,
            risk="low",
            rationale="NAT Gateways with no subnet associations incur hourly charges.",
        )]

    def _check_app_service_plan(
        self, res: dict, tags: dict, properties: dict, all_resources: list[dict]
    ) -> list[Recommendation]:
        """Flag empty App Service Plans."""
        asp_id = (res.get("resource_id") or "").lower()
        app_types = {
            "microsoft.web/sites",
            "microsoft.web/functionapps",
        }
        has_apps = any(
            (r.get("type") or "").lower() in app_types
            and asp_id in (r.get("resource_id") or "").lower()
            for r in all_resources
        )
        if has_apps:
            return []
        return [self._make_rec(
            res=res,
            title=f"Empty App Service Plan: {res.get('name', '')}",
            classification="safe_to_delete",
            current_state={"apps": 0},
            recommended_state={"action": "Delete empty App Service Plan"},
            estimated_saving=50.0,
            risk="low",
            rationale="App Service Plans with no apps still incur compute costs.",
        )]

    def _check_log_analytics(
        self, res: dict, tags: dict, properties: dict, cost_data: list[dict]
    ) -> list[Recommendation]:
        """Flag underused Log Analytics workspaces."""
        resource_id = (res.get("resource_id") or "").lower()
        workspace_costs = [
            e["cost"] for e in cost_data
            if (e.get("resource_id") or "").lower() == resource_id
        ]
        if not workspace_costs:
            return []

        avg_daily_cost = sum(workspace_costs) / len(workspace_costs)
        if avg_daily_cost > LOG_ANALYTICS_UNDERUSE_THRESHOLD_GB_PER_DAY * 3:
            # Not underused
            return []

        retention = (properties.get("retentionInDays") or 30)
        return [self._make_rec(
            res=res,
            title=f"Underused Log Analytics workspace: {res.get('name', '')}",
            classification="needs_owner_review",
            current_state={"avg_daily_cost_gbp": round(avg_daily_cost, 2), "retention_days": retention},
            recommended_state={"action": "Review data sources and reduce retention period"},
            estimated_saving=round(avg_daily_cost * 30 * 0.3, 2),
            risk="low",
            rationale="Low-ingestion Log Analytics workspace may be consolidatable.",
        )]

    def _make_rec(
        self,
        res: dict,
        title: str,
        classification: str,
        current_state: dict,
        recommended_state: dict,
        estimated_saving: float,
        risk: str,
        rationale: str,
    ) -> Recommendation:
        """Build a waste Recommendation object."""
        tags: dict = res.get("tags") or {}
        return Recommendation(
            id=f"finops.weekly.waste_orphan.{uuid.uuid4().hex[:8]}",
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
            recommendation_type="waste",
            current_state={**current_state, "waste_classification": classification},
            recommended_state=recommended_state,
            estimated_monthly_saving=estimated_saving,
            currency=self.currency,
            confidence="high",
            risk=risk,
            effort="low",
            reversibility="high",
            evidence=[{"rationale": rationale, "waste_classification": classification}],
            action={
                "mode": "advisory",
                "requires_approval": classification != "safe_to_delete",
                "rollback": f"Restore resource {res.get('name', '')} from backup if needed",
                "title": title,
            },
            created_at=datetime.now(timezone.utc),
            tags=tags,
        )
