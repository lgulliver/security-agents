"""PR Cost Diff Agent — analyses Terraform plan JSON for cost impact.

Parses resource_changes from a Terraform plan JSON, queries the Azure Retail
Prices API to estimate costs, and returns Recommendation objects plus a
markdown summary.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

RETAIL_PRICES_API = "https://prices.azure.com/api/retail/prices"

# Mapping from Terraform resource type to Azure service family / service name
# for querying the Retail Prices API.
RESOURCE_TYPE_MAP: dict[str, dict[str, str]] = {
    "azurerm_linux_virtual_machine": {"serviceName": "Virtual Machines", "serviceFamily": "Compute"},
    "azurerm_windows_virtual_machine": {"serviceName": "Virtual Machines", "serviceFamily": "Compute"},
    "azurerm_virtual_machine": {"serviceName": "Virtual Machines", "serviceFamily": "Compute"},
    "azurerm_linux_virtual_machine_scale_set": {"serviceName": "Virtual Machines", "serviceFamily": "Compute"},
    "azurerm_windows_virtual_machine_scale_set": {"serviceName": "Virtual Machines", "serviceFamily": "Compute"},
    "azurerm_kubernetes_cluster": {"serviceName": "Azure Kubernetes Service", "serviceFamily": "Compute"},
    "azurerm_managed_disk": {"serviceName": "Storage", "serviceFamily": "Storage"},
    "azurerm_app_service_plan": {"serviceName": "App Service", "serviceFamily": "Compute"},
    "azurerm_service_plan": {"serviceName": "App Service", "serviceFamily": "Compute"},
    "azurerm_mssql_server": {"serviceName": "SQL Database", "serviceFamily": "Databases"},
    "azurerm_mssql_database": {"serviceName": "SQL Database", "serviceFamily": "Databases"},
    "azurerm_postgresql_flexible_server": {"serviceName": "Azure Database for PostgreSQL", "serviceFamily": "Databases"},
    "azurerm_mysql_flexible_server": {"serviceName": "Azure Database for MySQL", "serviceFamily": "Databases"},
    "azurerm_redis_cache": {"serviceName": "Azure Cache for Redis", "serviceFamily": "Databases"},
    "azurerm_nat_gateway": {"serviceName": "NAT Gateway", "serviceFamily": "Networking"},
    "azurerm_firewall": {"serviceName": "Azure Firewall", "serviceFamily": "Networking"},
    "azurerm_application_gateway": {"serviceName": "Application Gateway", "serviceFamily": "Networking"},
    "azurerm_log_analytics_workspace": {"serviceName": "Log Analytics", "serviceFamily": "Management and Governance"},
    "azurerm_storage_account": {"serviceName": "Storage", "serviceFamily": "Storage"},
    "azurerm_public_ip": {"serviceName": "IP Addresses", "serviceFamily": "Networking"},
    "azurerm_lb": {"serviceName": "Load Balancer", "serviceFamily": "Networking"},
}

# Approximate monthly hours (730h/month)
HOURS_PER_MONTH = 730.0


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_retail_price(filter_query: str) -> list[dict]:
    """Fetch prices from Azure Retail Prices API with retry/backoff.

    Args:
        filter_query: OData filter string for the API.

    Returns:
        List of price item dicts from the API response.
    """
    params = {"api-version": "2023-01-01-preview", "$filter": filter_query}
    resp = requests.get(RETAIL_PRICES_API, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("Items", [])


def _get_price_for_sku(service_name: str, sku_name: str, location: str, price_type: str = "Consumption") -> float:
    """Look up the retail price for a given SKU in a given location.

    Args:
        service_name: Azure service name (e.g. 'Virtual Machines').
        sku_name: SKU name (e.g. 'D2s v3').
        location: Azure region (e.g. 'UK South').
        price_type: 'Consumption' or 'Reservation'.

    Returns:
        Hourly retail price in USD. 0.0 if not found.
    """
    try:
        odata_filter = (
            f"serviceName eq '{service_name}' "
            f"and armSkuName eq '{sku_name}' "
            f"and armRegionName eq '{_normalise_location(location)}' "
            f"and priceType eq '{price_type}' "
            f"and currencyCode eq 'USD'"
        )
        items = _fetch_retail_price(odata_filter)
        if items:
            # Prefer the lowest non-zero retail price
            prices = [item.get("retailPrice", 0.0) for item in items if item.get("retailPrice", 0.0) > 0]
            return min(prices) if prices else 0.0
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch retail price for %s / %s: %s", service_name, sku_name, exc)
    return 0.0


def _normalise_location(location: str) -> str:
    """Normalise an Azure location string to arm region name format."""
    return location.lower().replace(" ", "")


def _extract_sku(resource_type: str, config: dict) -> str:
    """Extract the SKU/size from a resource configuration dict."""
    for key in ("size", "sku_name", "sku", "vm_size", "node_vm_size", "tier"):
        val = config.get(key)
        if val and isinstance(val, str):
            return val
    return ""


def _estimate_monthly_cost(resource_type: str, config: dict, location: str) -> float:
    """Estimate the monthly cost (USD) for a single resource.

    Args:
        resource_type: Terraform resource type.
        config: The resource's 'after' (or 'before') configuration dict.
        location: Azure region string.

    Returns:
        Estimated monthly cost in USD.
    """
    mapping = RESOURCE_TYPE_MAP.get(resource_type)
    if not mapping:
        return 0.0

    sku = _extract_sku(resource_type, config)
    if not sku:
        return 0.0

    hourly = _get_price_for_sku(mapping["serviceName"], sku, location)
    return hourly * HOURS_PER_MONTH


def _run_infracost(plan_json_path: str) -> dict | None:
    """Run Infracost CLI if available, return parsed JSON output or None."""
    api_key = os.environ.get("INFRACOST_API_KEY")
    if not api_key:
        return None
    try:
        result = subprocess.run(
            ["infracost", "breakdown", "--path", plan_json_path, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "INFRACOST_API_KEY": api_key},
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        logger.warning("Infracost returned non-zero exit code: %s", result.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.warning("Infracost not available or failed: %s", exc)
    return None


class PRCostDiffAgent:
    """Analyses a Terraform plan JSON for cost impact and produces recommendations.

    Parses resource_changes, queries the Azure Retail Prices API for matched
    resource types, and returns a list of Recommendation objects plus a
    markdown summary string.
    """

    AGENT_NAME = "pr.cost_diff"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
        usd_to_gbp: float = 0.79,
    ) -> None:
        """Initialise the agent.

        Args:
            subscription_id: Azure subscription ID (for metadata).
            subscription_name: Azure subscription name.
            currency: Output currency code.
            usd_to_gbp: Conversion rate from USD to GBP (approximate).
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency
        self.usd_to_gbp = usd_to_gbp

    def analyse(self, plan_json_path: str) -> tuple[list[Recommendation], str]:
        """Analyse a Terraform plan JSON file for cost impact.

        Args:
            plan_json_path: Path to the Terraform plan JSON file.

        Returns:
            Tuple of (list of Recommendation objects, markdown summary string).
        """
        with open(plan_json_path, "r", encoding="utf-8") as fh:
            plan = json.load(fh)

        resource_changes: list[dict] = plan.get("resource_changes", [])
        workspace = plan.get("workspace", "default")

        # Try Infracost first for richer data
        infracost_data = _run_infracost(plan_json_path)

        recommendations: list[Recommendation] = []
        cost_drivers: list[dict] = []
        total_add = 0.0
        total_remove = 0.0

        for change in resource_changes:
            actions: list[str] = change.get("change", {}).get("actions", [])
            if not actions or actions == ["no-op"]:
                continue

            res_type = change.get("type", "")
            res_name = change.get("name", "")
            res_address = change.get("address", f"{res_type}.{res_name}")
            change_data = change.get("change", {})
            before: dict = change_data.get("before") or {}
            after: dict = change_data.get("after") or {}

            location = after.get("location", before.get("location", "uksouth"))
            tags = after.get("tags") or before.get("tags") or {}
            owner = tags.get("owner", "")
            environment = tags.get("environment", workspace)
            resource_group = after.get("resource_group_name", before.get("resource_group_name", ""))

            cost_before = 0.0
            cost_after = 0.0

            if "delete" in actions or "create" in actions or "update" in actions:
                if before:
                    cost_before = _estimate_monthly_cost(res_type, before, location)
                if after:
                    cost_after = _estimate_monthly_cost(res_type, after, location)

            delta_usd = cost_after - cost_before
            delta_gbp = delta_usd * self.usd_to_gbp

            if abs(delta_usd) < 0.01 and res_type not in RESOURCE_TYPE_MAP:
                continue

            if delta_usd > 0:
                total_add += delta_usd
            else:
                total_remove += abs(delta_usd)

            cost_drivers.append(
                {
                    "resource": res_address,
                    "type": res_type,
                    "action": "+".join(actions),
                    "monthly_delta_usd": round(delta_usd, 2),
                    "monthly_delta_gbp": round(delta_gbp, 2),
                }
            )

            if abs(delta_gbp) < 1.0:
                continue

            rec_type = "waste" if delta_gbp > 0 and "delete" in actions else "operational"
            risk = "high" if abs(delta_gbp) > 500 else "medium" if abs(delta_gbp) > 100 else "low"
            confidence = "medium"

            # If Infracost data available, upgrade confidence
            if infracost_data:
                confidence = "high"

            rec = Recommendation(
                id=f"finops.pr.cost_diff.{uuid.uuid4().hex[:8]}",
                agent=self.AGENT_NAME,
                subscription_id=self.subscription_id,
                subscription_name=self.subscription_name,
                resource_id=res_address,
                resource_type=res_type,
                resource_name=res_name,
                resource_group=resource_group,
                location=location,
                owner=owner,
                environment=environment,
                recommendation_type=rec_type,
                current_state={"monthly_cost_gbp": round(cost_before * self.usd_to_gbp, 2), "config": before},
                recommended_state={"monthly_cost_gbp": round(cost_after * self.usd_to_gbp, 2), "config": after},
                estimated_monthly_saving=round(max(0.0, -delta_gbp), 2),
                currency=self.currency,
                confidence=confidence,
                risk=risk,
                effort="low",
                reversibility="medium",
                evidence=[
                    {
                        "source": "azure_retail_prices_api",
                        "cost_before_usd": round(cost_before, 2),
                        "cost_after_usd": round(cost_after, 2),
                        "delta_usd": round(delta_usd, 2),
                    }
                ],
                action={
                    "mode": "advisory",
                    "requires_approval": False,
                    "rollback": f"Revert Terraform changes for {res_address}",
                },
                created_at=datetime.now(timezone.utc),
                tags=tags,
            )
            recommendations.append(rec)

        summary = self._build_markdown_summary(
            resource_changes, cost_drivers, total_add, total_remove, infracost_data
        )
        return recommendations, summary

    def _build_markdown_summary(
        self,
        resource_changes: list[dict],
        cost_drivers: list[dict],
        total_add: float,
        total_remove: float,
        infracost_data: dict | None,
    ) -> str:
        """Build a markdown summary of the cost diff analysis."""
        net_usd = total_add - total_remove
        net_gbp = net_usd * self.usd_to_gbp

        lines = [
            "## 💰 PR Cost Impact Analysis",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| New monthly cost | +${total_add:.2f} USD (+£{total_add * self.usd_to_gbp:.2f} GBP) |",
            f"| Removed monthly cost | -${total_remove:.2f} USD (-£{total_remove * self.usd_to_gbp:.2f} GBP) |",
            f"| **Net monthly delta** | **{'+'if net_gbp >= 0 else ''}£{net_gbp:.2f} GBP** |",
            "",
        ]

        if infracost_data:
            lines += ["_Cost data powered by Infracost._", ""]

        # Top cost drivers
        top_drivers = sorted(cost_drivers, key=lambda x: abs(x["monthly_delta_gbp"]), reverse=True)[:10]
        if top_drivers:
            lines += [
                "### Top Cost Drivers",
                "",
                "| Resource | Action | Monthly Delta (GBP) |",
                "| --- | --- | --- |",
            ]
            for d in top_drivers:
                sign = "+" if d["monthly_delta_gbp"] >= 0 else ""
                lines.append(f"| `{d['resource']}` | {d['action']} | {sign}£{d['monthly_delta_gbp']:.2f} |")
            lines.append("")

        # Risk annotations
        high_risk = [d for d in cost_drivers if abs(d["monthly_delta_gbp"]) > 500]
        if high_risk:
            lines += ["### ⚠️ High-Risk Cost Changes", ""]
            for d in high_risk:
                lines.append(f"- `{d['resource']}`: {d['action']} — £{d['monthly_delta_gbp']:.2f}/month")
            lines.append("")

        return "\n".join(lines)
