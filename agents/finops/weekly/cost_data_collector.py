"""Cost Data Collector — collects Azure cost data for FinOps analysis.

Prefers reading from Cost Management export blobs when the
COST_EXPORT_STORAGE_ACCOUNT environment variable is set; falls back to the
Cost Management Query API for daily/monthly granularity.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    ExportType,
    GranularityType,
    QueryAggregation,
    QueryColumnType,
    QueryDataset,
    QueryDefinition,
    QueryFilter,
    QueryGrouping,
    QueryTimePeriod,
    TimeframeType,
)
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_BLOB_ENV_VAR = "COST_EXPORT_STORAGE_ACCOUNT"


class CostDataCollector:
    """Collects Azure cost data per subscription for FinOps analysis.

    Prefers blob-based Cost Management exports for performance; falls back to
    the Cost Management Query API when no export storage account is configured.
    """

    def __init__(self, credential: Any | None = None) -> None:
        """Initialise the Cost Data Collector.

        Args:
            credential: Azure credential; defaults to DefaultAzureCredential.
        """
        self.credential = credential or DefaultAzureCredential()

    def collect(self, subscription_ids: list[str], days: int = 30) -> list[dict]:
        """Collect cost data for the given subscriptions over the past N days.

        Args:
            subscription_ids: List of Azure subscription IDs.
            days: Number of historical days to collect (default 30).

        Returns:
            List of cost entry dicts with keys: subscription_id, date,
            resource_id, resource_type, resource_group, service_name,
            meter_category, cost, currency, tags.
        """
        storage_account = os.environ.get(_BLOB_ENV_VAR)
        if storage_account:
            logger.info("Attempting to read cost exports from storage account: %s", storage_account)
            try:
                return self._collect_from_blob(storage_account, subscription_ids, days)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read cost exports from blob, falling back to API: %s", exc)

        return self._collect_from_api(subscription_ids, days)

    def _collect_from_blob(
        self, storage_account: str, subscription_ids: list[str], days: int
    ) -> list[dict]:
        """Read cost data from Cost Management export blobs.

        Args:
            storage_account: Name of the Azure Storage account hosting exports.
            subscription_ids: Subscriptions to collect data for.
            days: Lookback period in days.

        Returns:
            List of cost entry dicts.
        """
        from azure.storage.blob import BlobServiceClient

        account_url = f"https://{storage_account}.blob.core.windows.net"
        blob_client = BlobServiceClient(account_url=account_url, credential=self.credential)
        results: list[dict] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        for container in blob_client.list_containers():
            container_name = container["name"]
            try:
                cc = blob_client.get_container_client(container_name)
                for blob in cc.list_blobs():
                    if blob.last_modified:
                        # Normalise to aware UTC for comparison
                        lm = blob.last_modified
                        if lm.tzinfo is None:
                            lm = lm.replace(tzinfo=timezone.utc)
                        if lm < cutoff:
                            continue
                    if not blob.name.endswith(".csv"):
                        continue
                    data = cc.download_blob(blob.name).readall().decode("utf-8")
                    results.extend(self._parse_cost_csv(data))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error reading blob container %s: %s", container_name, exc)

        return results

    def _parse_cost_csv(self, csv_text: str) -> list[dict]:
        """Parse a Cost Management export CSV into a list of cost entry dicts."""
        import csv
        import io

        entries: list[dict] = []
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            entries.append({
                "subscription_id": row.get("SubscriptionId", row.get("subscriptionId", "")),
                "date": row.get("Date", row.get("UsageDate", "")),
                "resource_id": row.get("ResourceId", row.get("resourceId", "")),
                "resource_type": row.get("ResourceType", row.get("resourceType", "")),
                "resource_group": row.get("ResourceGroup", row.get("resourceGroup", "")),
                "service_name": row.get("ServiceName", row.get("serviceName", "")),
                "meter_category": row.get("MeterCategory", row.get("meterCategory", "")),
                "cost": float(row.get("PreTaxCost", row.get("CostInBillingCurrency", row.get("cost", 0))) or 0),
                "currency": row.get("Currency", row.get("BillingCurrencyCode", "GBP")),
                "tags": {},
            })
        return entries

    def _collect_from_api(self, subscription_ids: list[str], days: int) -> list[dict]:
        """Collect cost data via the Cost Management Query API.

        Args:
            subscription_ids: List of Azure subscription IDs.
            days: Lookback period in days.

        Returns:
            List of cost entry dicts.
        """
        results: list[dict] = []
        for sub_id in subscription_ids:
            try:
                entries = self._query_subscription_costs(sub_id, days)
                results.extend(entries)
            except HttpResponseError as exc:
                logger.error("Cost Management API failed for subscription %s: %s", sub_id, exc)
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _query_subscription_costs(self, subscription_id: str, days: int) -> list[dict]:
        """Query cost data for a single subscription using Cost Management API.

        Args:
            subscription_id: Azure subscription ID.
            days: Number of days of history to retrieve.

        Returns:
            List of cost entry dicts.
        """
        client = CostManagementClient(credential=self.credential)
        scope = f"/subscriptions/{subscription_id}"
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        query = QueryDefinition(
            type=ExportType.ACTUAL_COST,
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date,
            ),
            dataset=QueryDataset(
                granularity=GranularityType.DAILY,
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                },
                grouping=[
                    QueryGrouping(type=QueryColumnType.DIMENSION, name="ResourceId"),
                    QueryGrouping(type=QueryColumnType.DIMENSION, name="ResourceType"),
                    QueryGrouping(type=QueryColumnType.DIMENSION, name="ResourceGroupName"),
                    QueryGrouping(type=QueryColumnType.DIMENSION, name="ServiceName"),
                    QueryGrouping(type=QueryColumnType.DIMENSION, name="MeterCategory"),
                ],
            ),
        )

        response = client.query.usage(scope=scope, parameters=query)
        entries: list[dict] = []
        columns = [col.name for col in (response.columns or [])]

        for row in (response.rows or []):
            row_dict = dict(zip(columns, row))
            entries.append({
                "subscription_id": subscription_id,
                "date": str(row_dict.get("UsageDate", row_dict.get("BillingMonth", ""))),
                "resource_id": row_dict.get("ResourceId", ""),
                "resource_type": row_dict.get("ResourceType", ""),
                "resource_group": row_dict.get("ResourceGroupName", ""),
                "service_name": row_dict.get("ServiceName", ""),
                "meter_category": row_dict.get("MeterCategory", ""),
                "cost": float(row_dict.get("totalCost", row_dict.get("PreTaxCost", 0)) or 0),
                "currency": "GBP",
                "tags": {},
            })

        return entries
