"""Anomaly/Trend Agent — detects cost anomalies and spending trends.

Identifies week-over-week cost spikes, new service categories, regional cost
drift, budget burn rate, resource-level anomalies, and forecasted budget breaches.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

WOW_SPIKE_THRESHOLD = 0.20  # 20% week-over-week increase
BUDGET_BURN_WARNING_THRESHOLD = 0.85  # 85% of monthly budget consumed


class AnomalyTrendAgent:
    """Detects cost anomalies and trends across the Azure estate.

    Analyses cost data to surface week-over-week spikes, new service
    categories, regional drift, and budget burn rate concerns.
    """

    AGENT_NAME = "weekly.anomaly_trend"

    def __init__(
        self,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
        wow_spike_threshold: float = WOW_SPIKE_THRESHOLD,
        budget_burn_threshold: float = BUDGET_BURN_WARNING_THRESHOLD,
    ) -> None:
        """Initialise the Anomaly/Trend agent.

        Args:
            subscription_id: Azure subscription ID.
            subscription_name: Azure subscription name.
            currency: Output currency code.
            wow_spike_threshold: Fractional WoW increase to trigger a spike alert.
            budget_burn_threshold: Fractional budget consumption to trigger burn-rate alert.
        """
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency
        self.wow_spike_threshold = wow_spike_threshold
        self.budget_burn_threshold = budget_burn_threshold

    def analyse(
        self,
        cost_data: list[dict],
        subscriptions: list[dict],
    ) -> list[Recommendation]:
        """Analyse cost data for anomalies and trends.

        Args:
            cost_data: List of daily cost entry dicts from CostDataCollector.
            subscriptions: List of subscription dicts from SubscriptionDiscoveryAgent.

        Returns:
            List of Recommendation objects with recommendation_type='anomaly'.
        """
        recommendations: list[Recommendation] = []

        # Group cost entries by date
        daily_totals: dict[str, float] = defaultdict(float)
        service_costs: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        region_costs: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        resource_costs: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        sub_costs: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for entry in cost_data:
            date_str = str(entry.get("date", ""))[:10]
            cost = float(entry.get("cost", 0) or 0)
            service = entry.get("service_name", "unknown")
            sub_id = entry.get("subscription_id", "")
            resource_id = entry.get("resource_id", "")

            daily_totals[date_str] += cost
            service_costs[service][date_str] += cost
            sub_costs[sub_id][date_str] += cost
            if resource_id:
                resource_costs[resource_id][date_str] += cost

        # Sort dates
        sorted_dates = sorted(daily_totals.keys())
        if len(sorted_dates) < 8:
            logger.info("Not enough cost data for WoW analysis (have %d days)", len(sorted_dates))
            return recommendations

        # Week-over-week total spend spike
        wow_recs = self._detect_wow_spike(sorted_dates, daily_totals)
        recommendations.extend(wow_recs)

        # New service categories (appeared in last 7 days, not in prior 7 days)
        new_service_recs = self._detect_new_services(sorted_dates, service_costs)
        recommendations.extend(new_service_recs)

        # Resource-level anomalies
        resource_recs = self._detect_resource_anomalies(sorted_dates, resource_costs)
        recommendations.extend(resource_recs)

        # Subscription budget burn rate
        for sub_info in subscriptions:
            sub_id = sub_info.get("subscription_id", "")
            budget = sub_info.get("tags", {}).get("monthly_budget")
            if budget:
                try:
                    budget_f = float(budget)
                    burn_recs = self._check_budget_burn(sub_id, sub_info, sorted_dates, sub_costs, budget_f)
                    recommendations.extend(burn_recs)
                except (ValueError, TypeError):
                    pass

        return recommendations

    def _detect_wow_spike(
        self, sorted_dates: list[str], daily_totals: dict[str, float]
    ) -> list[Recommendation]:
        """Detect week-over-week total spend spikes."""
        recs = []
        if len(sorted_dates) < 14:
            return recs

        last_7_dates = sorted_dates[-7:]
        prior_7_dates = sorted_dates[-14:-7]

        last_7_total = sum(daily_totals.get(d, 0) for d in last_7_dates)
        prior_7_total = sum(daily_totals.get(d, 0) for d in prior_7_dates)

        if prior_7_total <= 0:
            return recs

        change = (last_7_total - prior_7_total) / prior_7_total
        if change <= self.wow_spike_threshold:
            return recs

        recs.append(self._make_rec(
            resource_id="",
            resource_type="subscription",
            resource_name=f"Total spend across estate",
            resource_group="",
            location="",
            owner="",
            environment="",
            tags={},
            title=f"WoW spend spike: +{change*100:.1f}% vs prior week",
            current_state={
                "last_7d_total_gbp": round(last_7_total, 2),
                "prior_7d_total_gbp": round(prior_7_total, 2),
                "wow_change_pct": round(change * 100, 1),
            },
            recommended_state={"action": "Investigate cost spike root cause"},
            estimated_saving=round((last_7_total - prior_7_total) / 7 * 30, 2),
            confidence="high",
            evidence=[{
                "source": "cost_data",
                "last_7d": last_7_dates,
                "prior_7d": prior_7_dates,
                "change_pct": round(change * 100, 1),
            }],
        ))
        return recs

    def _detect_new_services(
        self, sorted_dates: list[str], service_costs: dict[str, dict[str, float]]
    ) -> list[Recommendation]:
        """Detect new Azure service categories appearing in the last 7 days."""
        recs = []
        if len(sorted_dates) < 8:
            return recs

        recent_dates = set(sorted_dates[-7:])
        older_dates = set(sorted_dates[:-7])

        for service, date_costs in service_costs.items():
            service_dates = set(date_costs.keys())
            appeared_recently = bool(service_dates & recent_dates)
            seen_before = bool(service_dates & older_dates)
            if appeared_recently and not seen_before:
                recent_cost = sum(date_costs.get(d, 0) for d in recent_dates)
                if recent_cost < 1.0:
                    continue
                recs.append(self._make_rec(
                    resource_id="",
                    resource_type="service_category",
                    resource_name=service,
                    resource_group="",
                    location="",
                    owner="",
                    environment="",
                    tags={},
                    title=f"New service category detected: {service} (£{recent_cost:.2f} last 7d)",
                    current_state={"service": service, "last_7d_cost_gbp": round(recent_cost, 2)},
                    recommended_state={"action": "Verify new service usage is expected and authorised"},
                    estimated_saving=0.0,
                    confidence="high",
                    evidence=[{"source": "cost_data", "first_seen_dates": sorted(service_dates & recent_dates)}],
                ))
        return recs

    def _detect_resource_anomalies(
        self, sorted_dates: list[str], resource_costs: dict[str, dict[str, float]]
    ) -> list[Recommendation]:
        """Detect resource-level cost anomalies (WoW spike per resource)."""
        recs = []
        if len(sorted_dates) < 14:
            return recs

        last_7 = set(sorted_dates[-7:])
        prior_7 = set(sorted_dates[-14:-7])

        for rid, date_costs in resource_costs.items():
            last_cost = sum(date_costs.get(d, 0) for d in last_7)
            prior_cost = sum(date_costs.get(d, 0) for d in prior_7)
            if prior_cost <= 0 or last_cost < 5.0:
                continue

            change = (last_cost - prior_cost) / prior_cost
            if change > self.wow_spike_threshold:
                recs.append(self._make_rec(
                    resource_id=rid,
                    resource_type="",
                    resource_name=rid.split("/")[-1],
                    resource_group="",
                    location="",
                    owner="",
                    environment="",
                    tags={},
                    title=f"Resource cost spike: {rid.split('/')[-1]} +{change*100:.1f}% WoW",
                    current_state={
                        "last_7d_gbp": round(last_cost, 2),
                        "prior_7d_gbp": round(prior_cost, 2),
                        "wow_change_pct": round(change * 100, 1),
                        "resource_id": rid,
                    },
                    recommended_state={"action": "Investigate resource cost spike"},
                    estimated_saving=round((last_cost - prior_cost) / 7 * 30, 2),
                    confidence="medium",
                    evidence=[{"source": "cost_data", "resource_id": rid, "change_pct": round(change * 100, 1)}],
                ))

        # Limit to top 20 resource anomalies to avoid noise
        recs.sort(key=lambda r: r.estimated_monthly_saving, reverse=True)
        return recs[:20]

    def _check_budget_burn(
        self,
        sub_id: str,
        sub_info: dict,
        sorted_dates: list[str],
        sub_costs: dict,
        budget: float,
    ) -> list[Recommendation]:
        """Check if a subscription is on track to exceed its monthly budget."""
        recs = []
        sub_date_costs = sub_costs.get(sub_id, {})
        if not sub_date_costs:
            return recs

        # Current month to date
        now_str = sorted_dates[-1][:7]  # YYYY-MM
        mtd_costs = sum(v for k, v in sub_date_costs.items() if k.startswith(now_str))
        days_in_data = sum(1 for k in sub_date_costs if k.startswith(now_str))

        if days_in_data == 0:
            return recs

        # Extrapolate to full month
        daily_avg = mtd_costs / days_in_data
        forecast_monthly = daily_avg * 30

        burn_rate = forecast_monthly / budget if budget > 0 else 0

        if burn_rate > self.budget_burn_threshold:
            recs.append(self._make_rec(
                resource_id=f"/subscriptions/{sub_id}",
                resource_type="subscription",
                resource_name=sub_info.get("name", sub_id),
                resource_group="",
                location="",
                owner=sub_info.get("owner", ""),
                environment="",
                tags=sub_info.get("tags", {}),
                title=f"Budget burn rate {burn_rate*100:.0f}%: forecast £{forecast_monthly:.0f} vs budget £{budget:.0f}",
                current_state={
                    "mtd_cost_gbp": round(mtd_costs, 2),
                    "daily_avg_gbp": round(daily_avg, 2),
                    "forecast_monthly_gbp": round(forecast_monthly, 2),
                    "budget_gbp": budget,
                    "burn_rate_pct": round(burn_rate * 100, 1),
                },
                recommended_state={"action": "Review spend and take corrective action before month end"},
                estimated_saving=round(max(0, forecast_monthly - budget), 2),
                confidence="medium",
                evidence=[{"source": "cost_data", "days_in_data": days_in_data, "burn_rate": round(burn_rate, 3)}],
            ))
        return recs

    def _make_rec(
        self,
        resource_id: str,
        resource_type: str,
        resource_name: str,
        resource_group: str,
        location: str,
        owner: str,
        environment: str,
        tags: dict,
        title: str,
        current_state: dict,
        recommended_state: dict,
        estimated_saving: float,
        confidence: str,
        evidence: list[dict],
    ) -> Recommendation:
        """Build an anomaly Recommendation object."""
        return Recommendation(
            id=f"finops.weekly.anomaly.{uuid.uuid4().hex[:8]}",
            agent=self.AGENT_NAME,
            subscription_id=self.subscription_id,
            subscription_name=self.subscription_name,
            resource_id=resource_id,
            resource_type=resource_type,
            resource_name=resource_name,
            resource_group=resource_group,
            location=location,
            owner=owner,
            environment=environment,
            recommendation_type="anomaly",
            current_state=current_state,
            recommended_state=recommended_state,
            estimated_monthly_saving=round(estimated_saving, 2),
            currency=self.currency,
            confidence=confidence,
            risk="medium",
            effort="low",
            reversibility="high",
            evidence=evidence,
            action={
                "mode": "advisory",
                "requires_approval": False,
                "rollback": "No action — investigation only",
                "title": title,
            },
            created_at=datetime.now(timezone.utc),
            tags=tags,
        )
