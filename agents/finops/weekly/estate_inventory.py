"""Estate Inventory Agent — queries all Azure resources via Resource Graph.

Uses azure-mgmt-resourcegraph to enumerate every resource across the provided
subscriptions, paginating correctly and enriching with SKU, kind, and
provisioning state.
"""

from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000

_INVENTORY_QUERY = """
Resources
| project
    resource_id = id,
    type,
    name,
    location,
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    tags,
    sku,
    kind,
    provisioning_state = properties.provisioningState
| order by type asc, name asc
"""


class EstateInventoryAgent:
    """Collects a full inventory of Azure resources across subscriptions using Resource Graph.

    Paginates properly (1 000 resources per page) and returns a flat list of
    resource metadata dicts.
    """

    def __init__(self, credential: Any | None = None) -> None:
        """Initialise the Estate Inventory agent.

        Args:
            credential: Azure credential; defaults to DefaultAzureCredential.
        """
        self.credential = credential or DefaultAzureCredential()

    def collect(self, subscription_ids: list[str]) -> list[dict]:
        """Collect all resources across the given subscriptions.

        Args:
            subscription_ids: List of Azure subscription IDs to query.

        Returns:
            List of resource metadata dicts.
        """
        if not subscription_ids:
            logger.warning("No subscription IDs provided to EstateInventoryAgent")
            return []

        client = ResourceGraphClient(credential=self.credential)
        resources: list[dict] = []
        skip_token: str | None = None

        while True:
            try:
                batch = self._query_page(client, subscription_ids, skip_token)
            except HttpResponseError as exc:
                logger.error("Resource Graph query failed: %s", exc)
                break

            data = batch.data or []
            resources.extend(data)
            logger.info("Collected %d resources (total so far: %d)", len(data), len(resources))

            skip_token = getattr(batch, "skip_token", None) or getattr(
                getattr(batch, "result_truncated", None), "skip_token", None
            )
            if not skip_token:
                break

        logger.info("Estate inventory complete: %d resources across %d subscriptions", len(resources), len(subscription_ids))
        return resources

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _query_page(
        self,
        client: ResourceGraphClient,
        subscription_ids: list[str],
        skip_token: str | None,
    ):
        """Execute a single paginated Resource Graph query.

        Args:
            client: ResourceGraphClient instance.
            subscription_ids: Subscriptions to query.
            skip_token: Pagination token from the previous response.

        Returns:
            Resource Graph QueryResponse object.
        """
        options = QueryRequestOptions(result_format="objectArray", top=PAGE_SIZE)
        if skip_token:
            options.skip_token = skip_token

        request = QueryRequest(
            subscriptions=subscription_ids,
            query=_INVENTORY_QUERY,
            options=options,
        )
        return client.resources(request)
