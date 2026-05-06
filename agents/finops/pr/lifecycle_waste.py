"""PR Lifecycle/Waste Agent — detects lifecycle management issues in Terraform plans.

Checks Terraform plan JSON for resources that lack proper lifecycle controls,
such as VMs without shutdown schedules, disks without delete policies,
snapshots without retention, and orphaned networking resources.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

NON_PROD_ENVIRONMENTS = {
    "dev", "development", "test", "testing", "staging", "non-prod", "nonprod",
    "sandbox", "preview", "temporary", "ephemeral",
}

LOG_ANALYTICS_RETENTION_THRESHOLD_DAYS = 90
EXPENSIVE_LOG_CATEGORIES = {"AuditEvent", "AllMetrics", "kube-audit", "StorageRead", "StorageWrite"}


def _detect_environment(tags: dict, workspace: str) -> str:
    """Detect environment from resource tags or Terraform workspace name."""
    env = tags.get("environment", tags.get("env", "")).lower()
    if env:
        return env
    return workspace.lower()


def _is_non_prod(environment: str) -> bool:
    """Return True if the environment is non-production."""
    return environment.lower() in NON_PROD_ENVIRONMENTS or any(
        kw in environment.lower() for kw in NON_PROD_ENVIRONMENTS
    )


class PRLifecycleWasteAgent:
    """Analyses a Terraform plan JSON for lifecycle and waste management issues.

    Detects missing shutdown schedules, improper disk deletion policies,
    retention gaps, and potential orphaned resources.
    """

    AGENT_NAME = "pr.lifecycle_waste"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
    ) -> None:
        """Initialise the Lifecycle/Waste agent.

        Args:
            subscription_id: Azure subscription ID.
            subscription_name: Azure subscription name.
            currency: Output currency code.
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency
        # Track resources added in this plan for orphan detection
        self._added_resources: dict[str, dict] = {}

    def analyse(self, plan_json_path: str) -> list[Recommendation]:
        """Analyse a Terraform plan JSON file for lifecycle/waste issues.

        Args:
            plan_json_path: Path to the Terraform plan JSON file.

        Returns:
            List of Recommendation objects for lifecycle/waste issues found.
        """
        with open(plan_json_path, "r", encoding="utf-8") as fh:
            plan = json.load(fh)

        workspace = plan.get("workspace", "default")
        resource_changes: list[dict] = plan.get("resource_changes", [])
        recommendations: list[Recommendation] = []

        # First pass: build index of added resources
        for change in resource_changes:
            actions = change.get("change", {}).get("actions", [])
            if "create" in actions or "update" in actions:
                res_type = change.get("type", "")
                res_name = change.get("name", "")
                after = change.get("change", {}).get("after") or {}
                self._added_resources[f"{res_type}.{res_name}"] = after

        # Second pass: check each resource
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
                plan=plan,
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
        plan: dict,
    ) -> list[Recommendation]:
        """Check a single resource for lifecycle/waste concerns."""
        recs: list[Recommendation] = []
        is_np = _is_non_prod(environment)
        base_args = dict(
            res_type=res_type,
            res_name=res_name,
            location=location,
            resource_group=resource_group,
            owner=owner,
            environment=environment,
            tags=tags,
        )

        # VM without shutdown schedule in non-prod
        if res_type in (
            "azurerm_linux_virtual_machine",
            "azurerm_windows_virtual_machine",
            "azurerm_virtual_machine",
        ) and is_np:
            # Look for an azurerm_dev_test_schedule or azurerm_dev_test_global_vm_shutdown_schedule
            has_schedule = self._plan_has_shutdown_schedule(res_name, plan)
            if not has_schedule:
                recs.append(self._make_rec(
                    **base_args,
                    title=f"VM in non-prod has no shutdown schedule: {res_name}",
                    current_state={"shutdown_schedule": None},
                    recommended_state={"shutdown_schedule": "19:00 UTC daily via azurerm_dev_test_global_vm_shutdown_schedule"},
                    rationale="VMs in non-prod without a shutdown schedule waste compute budget overnight/weekends.",
                    estimated_saving=50.0,
                    rec_type="lifecycle",
                ))

        # Managed disk without delete action on VM delete
        if res_type == "azurerm_managed_disk":
            # Standalone disk — check if a VM in the plan attaches it without delete_data_disks_on_termination
            attached_to_vm = self._disk_attached_to_vm_without_delete(res_name, plan)
            if attached_to_vm:
                recs.append(self._make_rec(
                    **base_args,
                    title=f"Managed disk may not be deleted when VM is terminated: {res_name}",
                    current_state={"delete_data_disks_on_termination": False},
                    recommended_state={"delete_data_disks_on_termination": True},
                    rationale="Data disks that survive VM deletion become orphaned and incur ongoing costs.",
                    estimated_saving=15.0,
                    rec_type="lifecycle",
                ))

        # Snapshot without retention policy
        if res_type == "azurerm_snapshot":
            # If the snapshot resource has no incremental_enabled or no associated policy reference
            incremental = after.get("incremental_enabled", False)
            recs.append(self._make_rec(
                **base_args,
                title=f"Snapshot without explicit retention policy: {res_name}",
                current_state={"retention_policy": None, "incremental_enabled": incremental},
                recommended_state={"retention_policy": "Use Azure Backup policy or add lifecycle management"},
                rationale="Snapshots without a retention policy accumulate indefinitely and waste storage budget.",
                estimated_saving=5.0,
                rec_type="lifecycle",
            ))

        # Diagnostic settings with expensive log categories
        if res_type == "azurerm_monitor_diagnostic_setting":
            logs = after.get("log", []) or []
            enabled_expensive = []
            for log_entry in logs:
                cat = log_entry.get("category", "")
                if cat in EXPENSIVE_LOG_CATEGORIES and log_entry.get("enabled", False):
                    enabled_expensive.append(cat)
            if enabled_expensive:
                recs.append(self._make_rec(
                    **base_args,
                    title=f"Diagnostic setting enables expensive log categories: {', '.join(enabled_expensive)}",
                    current_state={"enabled_categories": enabled_expensive},
                    recommended_state={"enabled_categories": "Review and disable unnecessary high-volume categories"},
                    rationale=f"Log categories {enabled_expensive} can generate high Log Analytics ingestion costs.",
                    estimated_saving=20.0,
                    rec_type="lifecycle",
                ))

        # Log Analytics retention > 90 days
        if res_type == "azurerm_log_analytics_workspace":
            retention = after.get("retention_in_days", 30)
            if isinstance(retention, int) and retention > LOG_ANALYTICS_RETENTION_THRESHOLD_DAYS:
                recs.append(self._make_rec(
                    **base_args,
                    title=f"Log Analytics retention is {retention} days (> {LOG_ANALYTICS_RETENTION_THRESHOLD_DAYS})",
                    current_state={"retention_in_days": retention},
                    recommended_state={"retention_in_days": LOG_ANALYTICS_RETENTION_THRESHOLD_DAYS},
                    rationale=f"Retention of {retention} days increases Log Analytics storage costs significantly.",
                    estimated_saving=30.0,
                    rec_type="lifecycle",
                ))

        # App Service Plan with no apps
        if res_type in ("azurerm_app_service_plan", "azurerm_service_plan"):
            has_apps = self._asp_has_apps(res_name, plan)
            if not has_apps:
                recs.append(self._make_rec(
                    **base_args,
                    title=f"App Service Plan has no associated apps in this plan: {res_name}",
                    current_state={"apps": []},
                    recommended_state={"action": "Add apps or remove the App Service Plan"},
                    rationale="An App Service Plan with no apps wastes compute budget.",
                    estimated_saving=50.0,
                    rec_type="lifecycle",
                ))

        # Public IPs that may become orphaned
        if res_type == "azurerm_public_ip":
            is_associated = self._public_ip_has_association(res_name, plan)
            if not is_associated:
                recs.append(self._make_rec(
                    **base_args,
                    title=f"Public IP may have no resource association: {res_name}",
                    current_state={"association": None},
                    recommended_state={"action": "Associate with a NIC, Load Balancer, or NAT Gateway"},
                    rationale="Unassociated public IPs still incur a small hourly charge and represent waste.",
                    estimated_saving=3.0,
                    rec_type="lifecycle",
                ))

        # NICs that may become orphaned
        if res_type == "azurerm_network_interface":
            is_attached = self._nic_is_attached(res_name, plan)
            if not is_attached:
                recs.append(self._make_rec(
                    **base_args,
                    title=f"NIC may not be attached to any VM: {res_name}",
                    current_state={"vm_attachment": None},
                    recommended_state={"action": "Ensure NIC is used or remove it"},
                    rationale="Orphaned NICs represent clutter and can incur indirect costs.",
                    estimated_saving=0.0,
                    rec_type="lifecycle",
                ))

        return recs

    # ------------------------------------------------------------------ helpers

    def _plan_has_shutdown_schedule(self, vm_name: str, plan: dict) -> bool:
        """Return True if the plan includes a shutdown schedule for the given VM."""
        for change in plan.get("resource_changes", []):
            rtype = change.get("type", "")
            after = change.get("change", {}).get("after") or {}
            if rtype in (
                "azurerm_dev_test_global_vm_shutdown_schedule",
                "azurerm_dev_test_schedule",
            ):
                vm_id_ref = after.get("virtual_machine_id", "")
                if vm_name.lower() in vm_id_ref.lower():
                    return True
        return False

    def _disk_attached_to_vm_without_delete(self, disk_name: str, plan: dict) -> bool:
        """Return True if the disk is attached to a VM that doesn't set delete_data_disks_on_termination."""
        for change in plan.get("resource_changes", []):
            rtype = change.get("type", "")
            if rtype not in ("azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine", "azurerm_virtual_machine"):
                continue
            after = change.get("change", {}).get("after") or {}
            storage_os = after.get("storage_os_disk", [{}])
            if isinstance(storage_os, list):
                storage_os = storage_os[0] if storage_os else {}
            delete_data = after.get("delete_data_disks_on_termination", True)
            data_disks = after.get("storage_data_disk", [])
            for dd in (data_disks if isinstance(data_disks, list) else []):
                if disk_name.lower() in dd.get("name", "").lower() and not delete_data:
                    return True
        return False

    def _asp_has_apps(self, asp_name: str, plan: dict) -> bool:
        """Return True if the plan defines any app on this App Service Plan."""
        app_types = {
            "azurerm_linux_web_app", "azurerm_windows_web_app",
            "azurerm_linux_function_app", "azurerm_windows_function_app",
            "azurerm_app_service", "azurerm_function_app",
        }
        for change in plan.get("resource_changes", []):
            if change.get("type", "") not in app_types:
                continue
            after = change.get("change", {}).get("after") or {}
            plan_id = after.get("service_plan_id", after.get("app_service_plan_id", ""))
            if asp_name.lower() in plan_id.lower():
                return True
        return False

    def _public_ip_has_association(self, pip_name: str, plan: dict) -> bool:
        """Return True if the public IP is referenced by any other resource in the plan."""
        for change in plan.get("resource_changes", []):
            if change.get("type", "") == "azurerm_public_ip":
                continue
            after = change.get("change", {}).get("after") or {}
            after_str = json.dumps(after)
            if pip_name.lower() in after_str.lower():
                return True
        return False

    def _nic_is_attached(self, nic_name: str, plan: dict) -> bool:
        """Return True if the NIC is referenced by a VM in the plan."""
        for change in plan.get("resource_changes", []):
            rtype = change.get("type", "")
            if "virtual_machine" not in rtype:
                continue
            after = change.get("change", {}).get("after") or {}
            nics = after.get("network_interface_ids", [])
            for nic_ref in (nics if isinstance(nics, list) else []):
                if nic_name.lower() in nic_ref.lower():
                    return True
        return False

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
        rec_type: str = "lifecycle",
    ) -> Recommendation:
        """Create a Recommendation object for a lifecycle/waste finding."""
        return Recommendation(
            id=f"finops.pr.lifecycle_waste.{uuid.uuid4().hex[:8]}",
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
            effort="low",
            reversibility="high",
            evidence=[{"rationale": rationale, "title": title}],
            action={
                "mode": "advisory",
                "requires_approval": False,
                "rollback": f"Revert lifecycle change for {res_type}.{res_name}",
            },
            created_at=datetime.now(timezone.utc),
            tags=tags,
        )
