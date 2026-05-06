"""Reservation / Savings Plan Agent — identifies reservation and savings plan opportunities.

Analyses resource usage, cost data, and existing reservations to recommend
Azure Reserved Instances, Savings Plans, and reserved capacity purchases.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

# Break-even months for 1yr reserved vs pay-as-you-go (approximate)
RI_BREAKEVEN_MONTHS = 8
# Minimum months of stable usage to recommend a reservation
MIN_STABLE_MONTHS = 2
# Minimum monthly cost to be worth reserving
MIN_MONTHLY_COST_GBP = 50.0

RESERVABLE_TYPES = {
    "microsoft.compute/virtualmachines",
    "microsoft.compute/virtualmachinescalesets",
    "microsoft.sql/servers/databases",
    "microsoft.documentdb/databaseaccounts",
    "microsoft.web/serverfarms",
    "microsoft.cache/redis",
    "microsoft.storage/storageaccounts",
}

SAVINGS_PLAN_ELIGIBLE = {
    "microsoft.compute/virtualmachines",
    "microsoft.compute/virtualmachinescalesets",
    "microsoft.containerservice/managedclusters",
    "microsoft.web/serverfarms",
}

# Estimated savings from 1yr reservation vs PAYG (%)
RI_SAVINGS_PERCENT_1YR = 0.36
SAVINGS_PLAN_PERCENT_1YR = 0.15


class ReservationAgent:
    """Identifies reservation and savings plan opportunities across the estate.

    Considers 7/30/60-day usage stability, existing costs, and workload
    characteristics (prod vs non-prod) to generate reserve recommendations.
    """

    AGENT_NAME = "weekly.reservation"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
        usd_to_gbp: float = 0.79,
        min_monthly_cost: float = MIN_MONTHLY_COST_GBP,
    ) -> None:
        """Initialise the Reservation agent.

        Args:
            subscription_id: Azure subscription ID.
            subscription_name: Azure subscription name.
            currency: Output currency code.
            usd_to_gbp: USD to GBP conversion rate.
            min_monthly_cost: Minimum monthly cost (GBP) to recommend a reservation.
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency
        self.usd_to_gbp = usd_to_gbp
        self.min_monthly_cost = min_monthly_cost

    def analyse(
        self,
        resources: list[dict],
        cost_data: list[dict],
        metrics: dict,
    ) -> list[Recommendation]:
        """Analyse resources for reservation and savings plan opportunities.

        Args:
            resources: List of resource dicts from EstateInventoryAgent.
            cost_data: List of cost entry dicts from CostDataCollector.
            metrics: Dict from MetricsCollector.

        Returns:
            List of Recommendation objects with recommendation_type='reserve'.
        """
        # Build cost index per resource
        resource_costs: dict[str, list[float]] = defaultdict(list)
        for entry in cost_data:
            rid = (entry.get("resource_id") or "").lower()
            cost = float(entry.get("cost", 0) or 0)
            if rid and cost > 0:
                resource_costs[rid].append(cost)

        recommendations: list[Recommendation] = []

        for res in resources:
            resource_id = res.get("resource_id", "")
            res_type = (res.get("type") or "").lower()
            tags: dict = res.get("tags") or {}
            environment = tags.get("environment", "").lower()

            # Skip non-prod for long-term reservations (too unstable)
            if any(kw in environment for kw in ("dev", "test", "sandbox", "preview", "staging")):
                continue

            # Get cost history for this resource
            cost_entries = resource_costs.get(resource_id.lower(), [])
            if not cost_entries:
                continue

            # Aggregate to approximate monthly cost
            daily_avg = sum(cost_entries) / len(cost_entries)
            monthly_cost_gbp = daily_avg * 30 * self.usd_to_gbp

            if monthly_cost_gbp < self.min_monthly_cost:
                continue

            # Check usage stability (coefficient of variation)
            if len(cost_entries) > 1:
                mean = sum(cost_entries) / len(cost_entries)
                variance = sum((x - mean) ** 2 for x in cost_entries) / len(cost_entries)
                cv = (variance ** 0.5) / mean if mean > 0 else 1.0
                # High CV = unstable workload = risky to reserve
                if cv > 0.4:
                    logger.debug("Skipping %s: high cost variance (cv=%.2f)", resource_id, cv)
                    continue

            is_savings_plan_eligible = res_type in SAVINGS_PLAN_ELIGIBLE
            is_reservable = res_type in RESERVABLE_TYPES

            recs = []
            if is_reservable:
                saving_gbp = monthly_cost_gbp * RI_SAVINGS_PERCENT_1YR
                breakeven_months = round(RI_BREAKEVEN_MONTHS * (1 - RI_SAVINGS_PERCENT_1YR))
                recs.append(self._make_rec(
                    res=res,
                    rec_title=f"Reserved Instance opportunity: {res.get('name', resource_id)}",
                    current_state={"billing": "pay_as_you_go", "monthly_cost_gbp": round(monthly_cost_gbp, 2)},
                    recommended_state={
                        "billing": "1yr_reserved",
                        "estimated_monthly_cost_gbp": round(monthly_cost_gbp * (1 - RI_SAVINGS_PERCENT_1YR), 2),
                        "break_even_months": breakeven_months,
                    },
                    estimated_saving=saving_gbp,
                    evidence=[{
                        "source": "cost_data",
                        "daily_avg_cost_gbp": round(daily_avg * self.usd_to_gbp, 4),
                        "monthly_cost_gbp": round(monthly_cost_gbp, 2),
                        "cost_entry_count": len(cost_entries),
                        "ri_discount_pct": f"{RI_SAVINGS_PERCENT_1YR*100:.0f}%",
                    }],
                    tags=tags,
                ))

            if is_savings_plan_eligible and not is_reservable:
                saving_gbp = monthly_cost_gbp * SAVINGS_PLAN_PERCENT_1YR
                recs.append(self._make_rec(
                    res=res,
                    rec_title=f"Azure Savings Plan opportunity: {res.get('name', resource_id)}",
                    current_state={"billing": "pay_as_you_go", "monthly_cost_gbp": round(monthly_cost_gbp, 2)},
                    recommended_state={
                        "billing": "1yr_savings_plan",
                        "estimated_monthly_cost_gbp": round(monthly_cost_gbp * (1 - SAVINGS_PLAN_PERCENT_1YR), 2),
                    },
                    estimated_saving=saving_gbp,
                    evidence=[{
                        "source": "cost_data",
                        "monthly_cost_gbp": round(monthly_cost_gbp, 2),
                        "savings_plan_discount_pct": f"{SAVINGS_PLAN_PERCENT_1YR*100:.0f}%",
                    }],
                    tags=tags,
                ))

            recommendations.extend(recs)

        return recommendations

    def _make_rec(
        self,
        res: dict,
        rec_title: str,
        current_state: dict,
        recommended_state: dict,
        estimated_saving: float,
        evidence: list[dict],
        tags: dict,
    ) -> Recommendation:
        """Build a Recommendation object for a reservation finding."""
        return Recommendation(
            id=f"finops.weekly.reservation.{uuid.uuid4().hex[:8]}",
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
            recommendation_type="reserve",
            current_state=current_state,
            recommended_state=recommended_state,
            estimated_monthly_saving=round(estimated_saving, 2),
            currency=self.currency,
            confidence="medium",
            risk="low",
            effort="low",
            reversibility="medium",
            evidence=evidence,
            action={
                "mode": "advisory",
                "requires_approval": True,
                "rollback": "Allow reservation to expire; switch back to PAYG",
                "title": rec_title,
            },
            created_at=datetime.now(timezone.utc),
            tags=tags,
        )
