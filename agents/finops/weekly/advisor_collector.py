"""Azure Advisor Collector — retrieves Azure Advisor recommendations.

Uses azure-mgmt-advisor to collect Cost, OperationalExcellence, Reliability,
and Performance recommendations (and optionally Security) across subscriptions.
"""

from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.advisor import AdvisorManagementClient
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = ["Cost", "OperationalExcellence", "Reliability", "Performance"]


class AdvisorCollector:
    """Collects Azure Advisor recommendations across multiple subscriptions.

    Normalises each Advisor recommendation to a dict compatible with the
    FinOps agent recommendation schema fields.
    """

    def __init__(self, credential: Any | None = None) -> None:
        """Initialise the Advisor Collector.

        Args:
            credential: Azure credential; defaults to DefaultAzureCredential.
        """
        self.credential = credential or DefaultAzureCredential()

    def collect(
        self, subscription_ids: list[str], include_security: bool = False
    ) -> list[dict]:
        """Collect Advisor recommendations for the given subscriptions.

        Args:
            subscription_ids: List of Azure subscription IDs.
            include_security: Whether to include Security category recommendations.

        Returns:
            List of normalised recommendation dicts.
        """
        categories = list(DEFAULT_CATEGORIES)
        if include_security:
            categories.append("Security")

        results: list[dict] = []
        for sub_id in subscription_ids:
            try:
                recs = self._collect_for_subscription(sub_id, categories)
                results.extend(recs)
            except HttpResponseError as exc:
                logger.error("Advisor API failed for subscription %s: %s", sub_id, exc)

        logger.info("Collected %d Advisor recommendations across %d subscriptions", len(results), len(subscription_ids))
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _collect_for_subscription(
        self, subscription_id: str, categories: list[str]
    ) -> list[dict]:
        """Collect Advisor recommendations for a single subscription.

        Args:
            subscription_id: Azure subscription ID.
            categories: List of Advisor categories to retrieve.

        Returns:
            List of normalised recommendation dicts.
        """
        client = AdvisorManagementClient(
            credential=self.credential,
            subscription_id=subscription_id,
        )
        results: list[dict] = []

        try:
            for rec in client.recommendations.list():
                cat = str(rec.category or "").strip()
                if cat not in categories:
                    continue

                resource_id = str(rec.resource_metadata.resource_id if rec.resource_metadata else "")
                impact = str(rec.impact or "").lower()
                short_desc = rec.short_description
                problem = str(short_desc.problem if short_desc else "")
                solution = str(short_desc.solution if short_desc else "")

                results.append({
                    "advisor_id": str(rec.id or ""),
                    "category": cat,
                    "impact": impact,
                    "resource_id": resource_id,
                    "resource_type": str(rec.impacted_field or ""),
                    "resource_name": str(rec.impacted_value or ""),
                    "subscription_id": subscription_id,
                    "problem": problem,
                    "solution": solution,
                    "extended_properties": dict(rec.extended_properties or {}),
                    "potential_benefits": str(rec.potential_benefits or ""),
                    "recommendation_type_id": str(rec.recommendation_type_id or ""),
                    "last_updated": str(rec.last_updated or ""),
                })
        except HttpResponseError as exc:
            logger.error("Failed to list Advisor recs for %s: %s", subscription_id, exc)
            raise

        return results
