"""PR SKU Sanity Agent — flags over-provisioned or inappropriate SKUs in Terraform plans.

Analyses Terraform plan JSON and raises recommendations when resources use
SKUs that are inappropriate for the detected environment (e.g. Premium disks
in dev/test, oversized VMs in non-prod).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

# VM sizes considered oversized for non-prod environments (D8s and above)
OVERSIZED_VM_PREFIXES = (
    "Standard_D8",
    "Standard_D16",
    "Standard_D32",
    "Standard_D48",
    "Standard_D64",
    "Standard_E8",
    "Standard_E16",
    "Standard_E32",
    "Standard_E48",
    "Standard_E64",
    "Standard_F8",
    "Standard_F16",
    "Standard_F32",
    "Standard_M",
    "Standard_L",
    "Standard_G",
    "Standard_H",
    "Standard_N",
)

NON_PROD_ENVIRONMENTS = {
    "dev", "development", "test", "testing", "staging", "non-prod", "nonprod",
    "sandbox", "preview", "temporary", "ephemeral",
}

EXPENSIVE_ASP_SKUS = {"P2v3", "P3v3", "P4v3", "P5v3", "I1v2", "I2v2", "I3v2"}

PREMIUM_DISK_TIERS = {"Premium_LRS", "Premium_ZRS", "UltraSSD_LRS"}

PREMIUM_SQL_TIERS = {"Premium", "BusinessCritical", "Hyperscale"}
PREMIUM_REDIS_SKUS = {"Premium"}
PREMIUM_COSMOS_SKUS = {"Provisioned"}


def _detect_environment(tags: dict, workspace: str) -> str:
    """Detect environment from resource tags or Terraform workspace name."""
    env = tags.get("environment", tags.get("env", "")).lower()
    if env:
        return env
    ws = workspace.lower()
    for non_prod in NON_PROD_ENVIRONMENTS:
        if non_prod in ws:
            return non_prod
    return workspace.lower()


def _is_non_prod(environment: str) -> bool:
    """Return True if the environment is non-production."""
    return environment.lower() in NON_PROD_ENVIRONMENTS or any(
        kw in environment.lower() for kw in NON_PROD_ENVIRONMENTS
    )


class PRSKUSanityAgent:
    """Analyses a Terraform plan JSON for SKU-related FinOps concerns.

    Flags oversized VMs, premium disks, expensive App Service Plans, AKS
    over-scaling, and premium database tiers in non-production environments.
    """

    AGENT_NAME = "pr.sku_sanity"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
    ) -> None:
        """Initialise the SKU Sanity agent.

        Args:
            subscription_id: Azure subscription ID (for metadata).
            subscription_name: Azure subscription name.
            currency: Output currency code.
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency

    def analyse(self, plan_json_path: str) -> list[Recommendation]:
        """Analyse a Terraform plan JSON file for SKU sanity issues.

        Args:
            plan_json_path: Path to the Terraform plan JSON file.

        Returns:
            List of Recommendation objects for SKU issues found.
        """
        with open(plan_json_path, "r", encoding="utf-8") as fh:
            plan = json.load(fh)

        workspace = plan.get("workspace", "default")
        resource_changes: list[dict] = plan.get("resource_changes", [])
        recommendations: list[Recommendation] = []

        for change in resource_changes:
            actions = change.get("change", {}).get("actions", [])
            if not actions or actions == ["no-op"]:
                continue

            res_type = change.get("type", "")
            res_name = change.get("name", "")
            after: dict = change.get("change", {}).get("after") or {}
            tags: dict = after.get("tags") or {}
            location = after.get("location", "uksouth")
            resource_group = after.get("resource_group_name", "")
            environment = _detect_environment(tags, workspace)
            owner = tags.get("owner", "")

            recs = self._check_resource(
                res_type=res_type,
                res_name=res_name,
                after=after,
                tags=tags,
                location=location,
                resource_group=resource_group,
                environment=environment,
                owner=owner,
            )
            recommendations.extend(recs)

        return recommendations

    def _check_resource(
        self,
        res_type: str,
        res_name: str,
        after: dict,
        tags: dict,
        location: str,
        resource_group: str,
        environment: str,
        owner: str,
    ) -> list[Recommendation]:
        """Check a single resource for SKU concerns."""
        recs: list[Recommendation] = []
        is_np = _is_non_prod(environment)

        # VMs / VMSS
        if res_type in (
            "azurerm_linux_virtual_machine",
            "azurerm_windows_virtual_machine",
            "azurerm_virtual_machine",
        ):
            vm_size = after.get("size", after.get("vm_size", ""))
            if is_np and vm_size and any(vm_size.startswith(p) for p in OVERSIZED_VM_PREFIXES):
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"Oversized VM in non-prod: {vm_size}",
                    current_state={"vm_size": vm_size},
                    recommended_state={"vm_size": "Standard_D2s_v3 or smaller"},
                    rationale=f"VM size {vm_size} is oversized for a non-prod environment ({environment}).",
                    estimated_saving=200.0,
                ))

        # VMSS
        if res_type in (
            "azurerm_linux_virtual_machine_scale_set",
            "azurerm_windows_virtual_machine_scale_set",
        ):
            vm_size = after.get("sku", {}).get("name", "") if isinstance(after.get("sku"), dict) else after.get("sku", "")
            if is_np and vm_size and any(vm_size.startswith(p) for p in OVERSIZED_VM_PREFIXES):
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"Oversized VMSS in non-prod: {vm_size}",
                    current_state={"sku": vm_size},
                    recommended_state={"sku": "Standard_D2s_v3 or smaller"},
                    rationale=f"VMSS SKU {vm_size} is oversized for non-prod ({environment}).",
                    estimated_saving=150.0,
                ))

        # Managed disks
        if res_type == "azurerm_managed_disk":
            storage_type = after.get("storage_account_type", "")
            if is_np and storage_type in PREMIUM_DISK_TIERS:
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"Premium disk tier in non-prod: {storage_type}",
                    current_state={"storage_account_type": storage_type},
                    recommended_state={"storage_account_type": "Standard_LRS"},
                    rationale=f"Premium disk {storage_type} is unnecessary in non-prod ({environment}).",
                    estimated_saving=30.0,
                ))

        # App Service Plans
        if res_type in ("azurerm_app_service_plan", "azurerm_service_plan"):
            sku_name = after.get("sku_name", "")
            sku_tier = after.get("sku", {}).get("tier", "") if isinstance(after.get("sku"), dict) else ""
            effective_sku = sku_name or sku_tier
            has_autoscale = after.get("maximum_elastic_worker_count", 0) > 1
            if effective_sku in EXPENSIVE_ASP_SKUS and not has_autoscale:
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"Expensive App Service Plan without autoscale: {effective_sku}",
                    current_state={"sku": effective_sku, "autoscale": False},
                    recommended_state={"autoscale": True, "or_downsize": "P1v3"},
                    rationale=f"App Service Plan {effective_sku} is expensive and has no autoscale configured.",
                    estimated_saving=100.0,
                ))

        # AKS
        if res_type == "azurerm_kubernetes_cluster":
            default_pool = after.get("default_node_pool", [{}])
            if isinstance(default_pool, list):
                default_pool = default_pool[0] if default_pool else {}
            min_count = default_pool.get("min_count", 0) or 0
            if is_np and min_count > 3:
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"AKS default node pool min_count={min_count} is high for non-prod",
                    current_state={"min_count": min_count},
                    recommended_state={"min_count": 1},
                    rationale=f"AKS min_count={min_count} in non-prod ({environment}) wastes compute.",
                    estimated_saving=80.0 * (min_count - 1),
                ))

        # Azure SQL
        if res_type == "azurerm_mssql_database":
            sku_name = after.get("sku_name", "")
            if is_np and any(tier in sku_name for tier in PREMIUM_SQL_TIERS):
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"Premium SQL tier in non-prod: {sku_name}",
                    current_state={"sku_name": sku_name},
                    recommended_state={"sku_name": "GP_S_Gen5_1 (serverless)"},
                    rationale=f"SQL tier {sku_name} is unnecessarily expensive in non-prod ({environment}).",
                    estimated_saving=120.0,
                ))

        # Redis
        if res_type == "azurerm_redis_cache":
            family = after.get("family", "")
            sku_name = after.get("sku_name", "")
            if is_np and sku_name in PREMIUM_REDIS_SKUS:
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"Premium Redis SKU in non-prod: {sku_name} (family={family})",
                    current_state={"sku_name": sku_name, "family": family},
                    recommended_state={"sku_name": "Basic", "family": "C"},
                    rationale=f"Redis Premium SKU is unnecessary in non-prod ({environment}).",
                    estimated_saving=50.0,
                ))

        # Expiry date for ephemeral environments
        env_lower = environment.lower()
        if env_lower in {"sandbox", "preview", "temporary", "ephemeral", "test", "non-prod"}:
            if "expiry_date" not in (tags or {}):
                recs.append(self._make_rec(
                    res_type=res_type,
                    res_name=res_name,
                    location=location,
                    resource_group=resource_group,
                    owner=owner,
                    environment=environment,
                    tags=tags,
                    title=f"Missing expiry_date tag for ephemeral environment: {environment}",
                    current_state={"tags": tags},
                    recommended_state={"tags": {**tags, "expiry_date": "YYYY-MM-DD"}},
                    rationale=f"Resource in ephemeral environment '{environment}' has no expiry_date tag.",
                    estimated_saving=0.0,
                    rec_type="tagging",
                ))

        return recs

    def _make_rec(
        self,
        res_type: str,
        res_name: str,
        location: str,
        resource_group: str,
        owner: str,
        environment: str,
        tags: dict,
        title: str,
        current_state: dict,
        recommended_state: dict,
        rationale: str,
        estimated_saving: float,
        rec_type: str = "sku",
    ) -> Recommendation:
        """Create a Recommendation object for a SKU finding."""
        return Recommendation(
            id=f"finops.pr.sku_sanity.{uuid.uuid4().hex[:8]}",
            agent=self.AGENT_NAME,
            subscription_id=self.subscription_id,
            subscription_name=self.subscription_name,
            resource_id=f"{resource_group}/{res_type}.{res_name}",
            resource_type=res_type,
            resource_name=res_name,
            resource_group=resource_group,
            location=location,
            owner=owner,
            environment=environment,
            recommendation_type=rec_type,
            current_state=current_state,
            recommended_state=recommended_state,
            estimated_monthly_saving=estimated_saving,
            currency=self.currency,
            confidence="high",
            risk="low",
            effort="medium",
            reversibility="high",
            evidence=[{"rationale": rationale}],
            action={
                "mode": "advisory",
                "requires_approval": False,
                "rollback": f"Revert SKU change for {res_type}.{res_name}",
            },
            created_at=datetime.now(timezone.utc),
            tags=tags,
        )
