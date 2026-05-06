"""Subscription Discovery Agent — discovers Azure subscriptions from management groups.

Uses the azure-mgmt-managementgroups and azure-mgmt-subscription SDKs to
enumerate subscriptions the caller has access to, enriched with management
group path and owner metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.managementgroups import ManagementGroupsAPI
from azure.mgmt.subscription import SubscriptionClient
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def _make_credential() -> DefaultAzureCredential:
    """Return a DefaultAzureCredential instance."""
    return DefaultAzureCredential()


class SubscriptionDiscoveryAgent:
    """Discovers Azure subscriptions from management groups and/or an explicit list.

    For each subscription it collects: id, name, tenant_id, management_group_path,
    tags, and owner metadata derived from tags.
    """

    def __init__(
        self,
        management_group_ids: list[str] | None = None,
        subscription_ids: list[str] | None = None,
        credential: Any | None = None,
    ) -> None:
        """Initialise the Subscription Discovery agent.

        Args:
            management_group_ids: List of management group IDs to enumerate.
            subscription_ids: Explicit list of subscription IDs to include.
            credential: Azure credential object; defaults to DefaultAzureCredential.
        """
        self.management_group_ids = management_group_ids or []
        self.subscription_ids = subscription_ids or []
        self.credential = credential or _make_credential()

    def discover(self) -> list[dict]:
        """Discover all accessible subscriptions.

        Combines subscriptions found via management group enumeration and any
        explicitly provided subscription IDs.

        Returns:
            List of subscription metadata dicts.
        """
        found: dict[str, dict] = {}

        # Enumerate from management groups
        for mg_id in self.management_group_ids:
            try:
                subs = self._subscriptions_from_mg(mg_id, path=[mg_id])
                for sub in subs:
                    found[sub["subscription_id"]] = sub
            except HttpResponseError as exc:
                logger.error("Failed to enumerate management group %s: %s", mg_id, exc)

        # Add explicit subscription IDs
        for sub_id in self.subscription_ids:
            if sub_id not in found:
                try:
                    sub_detail = self._get_subscription_detail(sub_id)
                    found[sub_id] = sub_detail
                except HttpResponseError as exc:
                    logger.error("Failed to get subscription detail for %s: %s", sub_id, exc)

        return list(found.values())

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _subscriptions_from_mg(self, mg_id: str, path: list[str]) -> list[dict]:
        """Recursively enumerate subscriptions under a management group.

        Args:
            mg_id: Management group ID.
            path: Current path from the root management group.

        Returns:
            List of subscription metadata dicts.
        """
        client = ManagementGroupsAPI(credential=self.credential)
        sub_client = SubscriptionClient(credential=self.credential)
        result: list[dict] = []

        try:
            mg = client.management_groups.get(
                group_id=mg_id,
                expand="children",
                recurse=False,
            )
            children = mg.children or []
        except HttpResponseError as exc:
            logger.warning("Could not expand management group %s: %s", mg_id, exc)
            return result

        for child in children:
            child_type = (child.type or "").lower()
            if "subscription" in child_type:
                sub_id = (child.name or "").strip("/")
                try:
                    sub = sub_client.subscriptions.get(sub_id)
                    tags: dict = sub.tags or {}
                    result.append({
                        "subscription_id": sub.subscription_id,
                        "name": sub.display_name,
                        "tenant_id": sub.tenant_id,
                        "management_group_path": "/".join(path),
                        "state": str(sub.state),
                        "tags": tags,
                        "owner": tags.get("owner", tags.get("Owner", "")),
                    })
                except HttpResponseError as exc:
                    logger.warning("Could not get details for subscription %s: %s", sub_id, exc)
            elif "managementgroup" in child_type:
                child_mg_id = child.name or ""
                result.extend(self._subscriptions_from_mg(child_mg_id, path + [child_mg_id]))

        return result

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _get_subscription_detail(self, subscription_id: str) -> dict:
        """Fetch metadata for a single subscription.

        Args:
            subscription_id: Azure subscription ID.

        Returns:
            Subscription metadata dict.
        """
        client = SubscriptionClient(credential=self.credential)
        try:
            sub = client.subscriptions.get(subscription_id)
            tags: dict = sub.tags or {}
            return {
                "subscription_id": sub.subscription_id,
                "name": sub.display_name,
                "tenant_id": sub.tenant_id,
                "management_group_path": "",
                "state": str(sub.state),
                "tags": tags,
                "owner": tags.get("owner", tags.get("Owner", "")),
            }
        except HttpResponseError as exc:
            logger.error("HttpResponseError fetching subscription %s: %s", subscription_id, exc)
            raise
