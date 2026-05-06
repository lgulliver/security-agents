"""Report Agent — generates weekly FinOps markdown reports.

Produces a comprehensive weekly report covering executive summary, savings
breakdown, top recommendations, quick wins, high-risk items, and more.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from models.recommendation import Recommendation, RecommendationCollection

logger = logging.getLogger(__name__)


class ReportAgent:
    """Generates a weekly FinOps markdown report from a RecommendationCollection.

    The report includes executive summary, savings by subscription and owner,
    top 10 recommendations, quick wins, high-risk items, and anomaly highlights.
    """

    def generate(
        self,
        recommendations: RecommendationCollection,
        previous_recommendations: list[Recommendation] | None = None,
    ) -> str:
        """Generate the weekly FinOps report.

        Args:
            recommendations: Prioritised RecommendationCollection.
            previous_recommendations: Optional list of last week's recommendations
                for tracking unresolved items and newly introduced anomalies.

        Returns:
            Markdown-formatted report string.
        """
        now = datetime.now(timezone.utc)
        sections: list[str] = []

        sections.append(self._executive_summary(recommendations, now))
        sections.append(self._savings_by_subscription(recommendations))
        sections.append(self._savings_by_owner(recommendations))
        sections.append(self._top_10(recommendations))
        sections.append(self._quick_wins(recommendations))
        sections.append(self._high_risk(recommendations))
        sections.append(self._reservation_section(recommendations))
        sections.append(self._waste_section(recommendations))

        if previous_recommendations:
            sections.append(self._unresolved_previous(recommendations, previous_recommendations))
            sections.append(self._new_anomalies(recommendations, previous_recommendations))

        return "\n\n---\n\n".join(s for s in sections if s)

    # ------------------------------------------------------------------ sections

    def _executive_summary(self, recs: RecommendationCollection, now: datetime) -> str:
        """Generate the executive summary section."""
        open_recs = recs.filter_by_status("open")
        lines = [
            f"# 📊 Azure FinOps Weekly Report — {now.strftime('%d %B %Y')}",
            "",
            "## Executive Summary",
            "",
            f"| Metric | Value |",
            f"| --- | --- |",
            f"| Total recommendations | {len(recs)} |",
            f"| Open recommendations | {len(open_recs)} |",
            f"| **Total estimated monthly saving** | **£{recs.total_saving:,.2f}** |",
            f"| Report generated | {now.strftime('%Y-%m-%d %H:%M UTC')} |",
        ]

        # Breakdown by type
        type_counts: dict[str, tuple[int, float]] = {}
        for rec in recs:
            t = rec.recommendation_type
            count, saving = type_counts.get(t, (0, 0.0))
            type_counts[t] = (count + 1, saving + rec.estimated_monthly_saving)

        if type_counts:
            lines += ["", "### Recommendations by Type", "", "| Type | Count | Saving (£/mo) |", "| --- | --- | --- |"]
            for t, (count, saving) in sorted(type_counts.items(), key=lambda x: -x[1][1]):
                lines.append(f"| {t} | {count} | £{saving:,.2f} |")

        return "\n".join(lines)

    def _savings_by_subscription(self, recs: RecommendationCollection) -> str:
        """Savings breakdown by subscription."""
        sub_savings: dict[str, tuple[str, float]] = {}
        for rec in recs:
            sid = rec.subscription_id
            name = rec.subscription_name or sid
            _, current = sub_savings.get(sid, (name, 0.0))
            sub_savings[sid] = (name, current + rec.estimated_monthly_saving)

        if not sub_savings:
            return ""

        lines = ["## 💳 Savings by Subscription", "", "| Subscription | Estimated Saving (£/mo) |", "| --- | --- |"]
        for sid, (name, saving) in sorted(sub_savings.items(), key=lambda x: -x[1][1]):
            lines.append(f"| {name} (`{sid}`) | £{saving:,.2f} |")
        return "\n".join(lines)

    def _savings_by_owner(self, recs: RecommendationCollection) -> str:
        """Savings breakdown by owner/team."""
        owner_savings: dict[str, float] = {}
        for rec in recs:
            owner = rec.owner or "unknown"
            owner_savings[owner] = owner_savings.get(owner, 0.0) + rec.estimated_monthly_saving

        if not owner_savings:
            return ""

        lines = ["## 👥 Savings by Owner/Team", "", "| Owner/Team | Estimated Saving (£/mo) |", "| --- | --- |"]
        for owner, saving in sorted(owner_savings.items(), key=lambda x: -x[1]):
            lines.append(f"| {owner} | £{saving:,.2f} |")
        return "\n".join(lines)

    def _top_10(self, recs: RecommendationCollection) -> str:
        """Top 10 recommendations by priority score."""
        top = recs.sorted_by_priority().items[:10]
        if not top:
            return ""

        lines = ["## 🏆 Top 10 Recommendations", ""]
        for i, rec in enumerate(top, 1):
            category = rec.action.get("category", "")
            category_badge = f" `[{category}]`" if category else ""
            lines.append(f"### {i}. {rec.action.get('title', rec.id)}{category_badge}")
            lines.append(f"- **Type:** {rec.recommendation_type}")
            lines.append(f"- **Resource:** `{rec.resource_name}` ({rec.resource_type})")
            lines.append(f"- **Subscription:** {rec.subscription_name}")
            lines.append(f"- **Owner:** {rec.owner or '—'}")
            lines.append(f"- **Saving:** £{rec.estimated_monthly_saving:,.2f}/month")
            lines.append(f"- **Confidence:** {rec.confidence} | **Risk:** {rec.risk} | **Effort:** {rec.effort}")
            lines.append(f"- **Priority Score:** {rec.priority_score:.1f}/100")
            lines.append("")

        return "\n".join(lines)

    def _quick_wins(self, recs: RecommendationCollection) -> str:
        """Low-effort, high-saving recommendations."""
        quick = [
            r for r in recs
            if r.effort == "low" and r.estimated_monthly_saving >= 50.0 and r.risk in ("low", "medium")
        ]
        quick.sort(key=lambda r: r.estimated_monthly_saving, reverse=True)

        if not quick:
            return ""

        lines = ["## ⚡ Quick Wins (Low Effort, High Saving)", "",
                 "| Resource | Type | Saving (£/mo) | Risk |", "| --- | --- | --- | --- |"]
        for r in quick[:15]:
            lines.append(f"| `{r.resource_name}` | {r.recommendation_type} | £{r.estimated_monthly_saving:,.2f} | {r.risk} |")
        return "\n".join(lines)

    def _high_risk(self, recs: RecommendationCollection) -> str:
        """High-risk or high-cost recommendations requiring attention."""
        high_risk = [r for r in recs if r.risk == "high" or r.estimated_monthly_saving >= 1000.0]
        if not high_risk:
            return ""

        lines = ["## ⚠️ High-Risk Recommendations", ""]
        for rec in sorted(high_risk, key=lambda r: r.estimated_monthly_saving, reverse=True)[:10]:
            lines.append(f"- **{rec.resource_name}** — {rec.recommendation_type}, £{rec.estimated_monthly_saving:,.2f}/mo, risk={rec.risk}, confidence={rec.confidence}")
        return "\n".join(lines)

    def _reservation_section(self, recs: RecommendationCollection) -> str:
        """Reservation / Savings Plan recommendations."""
        reserve_recs = recs.filter_by_type("reserve")
        if not reserve_recs:
            return ""

        lines = [
            "## 💾 Reservation & Savings Plan Recommendations",
            "",
            f"Total potential saving: **£{reserve_recs.total_saving:,.2f}/month**",
            "",
            "| Resource | Type | Saving (£/mo) | Confidence |",
            "| --- | --- | --- | --- |",
        ]
        for r in sorted(reserve_recs.items, key=lambda x: x.estimated_monthly_saving, reverse=True)[:10]:
            lines.append(f"| `{r.resource_name}` | {r.resource_type} | £{r.estimated_monthly_saving:,.2f} | {r.confidence} |")
        return "\n".join(lines)

    def _waste_section(self, recs: RecommendationCollection) -> str:
        """Waste / orphan candidates."""
        waste_recs = recs.filter_by_type("waste")
        if not waste_recs:
            return ""

        lines = [
            "## 🗑️ Waste & Orphan Candidates",
            "",
            f"Total potential saving: **£{waste_recs.total_saving:,.2f}/month**",
            "",
            "| Resource | Group | Classification | Saving (£/mo) |",
            "| --- | --- | --- | --- |",
        ]
        for r in sorted(waste_recs.items, key=lambda x: x.estimated_monthly_saving, reverse=True)[:15]:
            classification = r.current_state.get("waste_classification", "—")
            lines.append(
                f"| `{r.resource_name}` | {r.resource_group} | {classification} | £{r.estimated_monthly_saving:,.2f} |"
            )
        return "\n".join(lines)

    def _unresolved_previous(
        self,
        current: RecommendationCollection,
        previous: list[Recommendation],
    ) -> str:
        """Report on unresolved recommendations from the previous week."""
        current_ids = {r.id for r in current}
        unresolved = [r for r in previous if r.id not in current_ids and r.status == "open"]
        if not unresolved:
            return ""

        lines = ["## 🔁 Unresolved Previous Recommendations", ""]
        for r in unresolved[:10]:
            lines.append(f"- **{r.id}**: {r.resource_name} — {r.recommendation_type}, £{r.estimated_monthly_saving:,.2f}/mo (created {r.created_at.date()})")
        return "\n".join(lines)

    def _new_anomalies(
        self,
        current: RecommendationCollection,
        previous: list[Recommendation],
    ) -> str:
        """Report newly introduced anomalies vs the previous week."""
        prev_ids = {r.id for r in previous}
        new_anomalies = [
            r for r in current
            if r.recommendation_type == "anomaly" and r.id not in prev_ids
        ]
        if not new_anomalies:
            return ""

        lines = ["## 🆕 Newly Detected Anomalies", ""]
        for r in new_anomalies[:10]:
            lines.append(f"- **{r.action.get('title', r.id)}** — {r.resource_name}, confidence={r.confidence}")
        return "\n".join(lines)
