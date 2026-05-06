"""Metrics Collector — collects Azure Monitor metrics for FinOps rightsizing.

Uses azure-mgmt-monitor to collect CPU, memory, disk IOPS, network I/O, and
database utilisation metrics across configurable time windows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.monitor.models import AggregationType
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

BATCH_SIZE = 20  # Max resources per metrics query batch

# Map of Azure resource type to the metrics we care about
RESOURCE_METRICS: dict[str, list[str]] = {
    "microsoft.compute/virtualmachines": [
        "Percentage CPU",
        "Available Memory Bytes",
        "Disk Read Bytes",
        "Disk Write Bytes",
        "Disk Read Operations/Sec",
        "Disk Write Operations/Sec",
        "Network In Total",
        "Network Out Total",
    ],
    "microsoft.compute/virtualmachinescalesets": [
        "Percentage CPU",
        "Available Memory Bytes",
        "Network In Total",
        "Network Out Total",
    ],
    "microsoft.containerservice/managedclusters": [
        "node_cpu_usage_percentage",
        "node_memory_working_set_percentage",
        "kube_node_status_condition",
    ],
    "microsoft.web/serverfarms": [
        "CpuPercentage",
        "MemoryPercentage",
        "DiskQueueLength",
        "HttpQueueLength",
    ],
    "microsoft.web/sites": [
        "CpuTime",
        "MemoryWorkingSet",
        "Requests",
    ],
    "microsoft.sql/servers/databases": [
        "cpu_percent",
        "dtu_consumption_percent",
        "storage_percent",
        "connection_successful",
    ],
    "microsoft.dbforpostgresql/flexibleservers": [
        "cpu_percent",
        "memory_percent",
        "storage_percent",
        "active_connections",
    ],
    "microsoft.dbformysql/flexibleservers": [
        "cpu_percent",
        "memory_percent",
        "storage_percent",
        "active_connections",
    ],
    "microsoft.cache/redis": [
        "percentProcessorTime",
        "usedmemorypercentage",
        "connectedclients",
        "operationsPerSecond",
    ],
}


def _window_to_timedelta(window_days: int) -> timedelta:
    return timedelta(days=window_days)


class MetricsCollector:
    """Collects Azure Monitor metrics for a list of resources across time windows.

    Batches metric queries (up to 20 resources per call) and returns a nested
    dict: resource_id → metric_name → window_days → aggregated_value.
    """

    def __init__(self, credential: Any | None = None) -> None:
        """Initialise the Metrics Collector.

        Args:
            credential: Azure credential; defaults to DefaultAzureCredential.
        """
        self.credential = credential or DefaultAzureCredential()

    def collect(
        self,
        resources: list[dict],
        windows: list[int] | None = None,
    ) -> dict:
        """Collect metrics for the given resources across all time windows.

        Args:
            resources: List of resource dicts with at least 'resource_id' and 'type'.
            windows: List of lookback window sizes in days (default [7, 30, 60, 90]).

        Returns:
            Dict mapping resource_id → metric_name → window_days → value.
        """
        if windows is None:
            windows = [7, 30, 60, 90]

        result: dict[str, dict[str, dict[int, float]]] = {}

        # Group resources by subscription and type for efficient batching
        grouped: dict[str, list[dict]] = {}
        for res in resources:
            sub_id = res.get("subscription_id", "")
            grouped.setdefault(sub_id, []).append(res)

        for sub_id, sub_resources in grouped.items():
            client = MonitorManagementClient(credential=self.credential, subscription_id=sub_id)
            for window in windows:
                for i in range(0, len(sub_resources), BATCH_SIZE):
                    batch = sub_resources[i : i + BATCH_SIZE]
                    self._collect_batch(client, batch, window, result)

        return result

    def _collect_batch(
        self,
        client: MonitorManagementClient,
        resources: list[dict],
        window_days: int,
        result: dict,
    ) -> None:
        """Collect metrics for a batch of resources for one time window.

        Args:
            client: MonitorManagementClient for the subscription.
            resources: Batch of resource dicts.
            window_days: Lookback window in days.
            result: Output dict to populate (mutated in place).
        """
        end_time = datetime.now(tz=timezone.utc)
        start_time = end_time - _window_to_timedelta(window_days)
        timespan = f"{start_time.isoformat()}/{end_time.isoformat()}"

        for res in resources:
            resource_id: str = res.get("resource_id", "")
            res_type: str = (res.get("type", "") or "").lower()
            metric_names = RESOURCE_METRICS.get(res_type)
            if not metric_names:
                continue

            try:
                self._query_resource_metrics(
                    client=client,
                    resource_id=resource_id,
                    metric_names=metric_names,
                    timespan=timespan,
                    window_days=window_days,
                    result=result,
                )
            except HttpResponseError as exc:
                logger.warning("Metrics query failed for %s (window=%dd): %s", resource_id, window_days, exc)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _query_resource_metrics(
        self,
        client: MonitorManagementClient,
        resource_id: str,
        metric_names: list[str],
        timespan: str,
        window_days: int,
        result: dict,
    ) -> None:
        """Query Azure Monitor for specific metrics on a single resource.

        Args:
            client: MonitorManagementClient.
            resource_id: Full Azure resource ID.
            metric_names: List of metric names to query.
            timespan: ISO 8601 timespan string.
            window_days: Window size (used as key in result dict).
            result: Output dict to populate (mutated in place).
        """
        metrics_str = ",".join(metric_names)
        response = client.metrics.list(
            resource_uri=resource_id,
            timespan=timespan,
            metricnames=metrics_str,
            aggregation=f"{AggregationType.AVERAGE},{AggregationType.MAXIMUM}",
        )

        res_metrics: dict[str, dict[int, float]] = result.setdefault(resource_id, {})

        for metric in response.value:
            metric_name = metric.name.value if metric.name else ""
            values: list[float] = []
            p95_values: list[float] = []

            for ts in metric.timeseries or []:
                for dp in ts.data or []:
                    if dp.average is not None:
                        values.append(dp.average)
                    if dp.maximum is not None:
                        p95_values.append(dp.maximum)

            if values:
                avg_key = f"{metric_name}_avg"
                window_dict = res_metrics.setdefault(avg_key, {})
                window_dict[window_days] = round(sum(values) / len(values), 2)

            if p95_values:
                p95_key = f"{metric_name}_p95"
                p95_sorted = sorted(p95_values)
                idx = max(0, int(len(p95_sorted) * 0.95) - 1)
                window_dict = res_metrics.setdefault(p95_key, {})
                window_dict[window_days] = round(p95_sorted[idx], 2)
