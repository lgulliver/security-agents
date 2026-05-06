"""Weekly Analysis entrypoint — CLI for running the full FinOps estate analysis.

Runs the full pipeline: subscription discovery → estate inventory → cost data
collection → Advisor → metrics → rightsizing → reservation → waste → operational
→ anomaly → prioritise → report, and optionally creates GitHub issues.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents.weekly.anomaly_trend import AnomalyTrendAgent
from agents.weekly.advisor_collector import AdvisorCollector
from agents.weekly.cost_data_collector import CostDataCollector
from agents.weekly.estate_inventory import EstateInventoryAgent
from agents.weekly.github_integration import GitHubIntegrationAgent
from agents.weekly.metrics_collector import MetricsCollector
from agents.weekly.operational_finops import OperationalFinOpsAgent
from agents.weekly.recommendation_prioritiser import RecommendationPrioritiser
from agents.weekly.report import ReportAgent
from agents.weekly.reservation import ReservationAgent
from agents.weekly.rightsizing import RightsizingAgent
from agents.weekly.subscription_discovery import SubscriptionDiscoveryAgent
from agents.weekly.waste_orphan import WasteOrphanAgent
from models.recommendation import Recommendation, RecommendationCollection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Azure FinOps Weekly Estate Analysis — run the full FinOps pipeline"
    )
    parser.add_argument(
        "--management-groups",
        nargs="*",
        default=[],
        help="List of Azure Management Group IDs to analyse",
    )
    parser.add_argument(
        "--subscription-ids",
        nargs="*",
        default=[],
        help="Explicit Azure Subscription IDs to analyse",
    )
    parser.add_argument(
        "--output-dir",
        default="./reports",
        help="Directory to write the markdown report to",
    )
    parser.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token (or set GITHUB_TOKEN env var)",
    )
    parser.add_argument("--repo", default="", help="GitHub repository (owner/repo) for creating issues")
    parser.add_argument(
        "--create-issues",
        action="store_true",
        help="Create GitHub issues for top recommendations",
    )
    parser.add_argument(
        "--create-remediation-prs",
        action="store_true",
        help="Attempt to create remediation PRs for auto-fix candidates",
    )
    parser.add_argument(
        "--cost-lookback-days",
        type=int,
        default=30,
        help="Number of days of cost history to collect",
    )
    parser.add_argument(
        "--include-security-advisor",
        action="store_true",
        help="Include Azure Advisor Security recommendations",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute the weekly analysis pipeline.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code: 0 for success.
    """
    logger.info(
        "Starting FinOps weekly analysis: mgs=%s subs=%s",
        args.management_groups,
        args.subscription_ids,
    )

    # ── 1. Subscription discovery ─────────────────────────────────────────
    logger.info("Step 1/10: Subscription discovery")
    try:
        discovery = SubscriptionDiscoveryAgent(
            management_group_ids=args.management_groups,
            subscription_ids=args.subscription_ids,
        )
        subscriptions = discovery.discover()
    except Exception as exc:  # noqa: BLE001
        logger.error("Subscription discovery failed: %s", exc)
        # Fall back to explicit subscription IDs
        subscriptions = [
            {"subscription_id": sid, "name": sid, "tenant_id": "", "management_group_path": "", "tags": {}, "owner": ""}
            for sid in args.subscription_ids
        ]

    subscription_ids = [s["subscription_id"] for s in subscriptions]
    if not subscription_ids:
        logger.error("No subscriptions found. Exiting.")
        return 1
    logger.info("Discovered %d subscriptions", len(subscription_ids))

    # ── 2. Estate inventory ───────────────────────────────────────────────
    logger.info("Step 2/10: Estate inventory")
    try:
        inventory_agent = EstateInventoryAgent()
        resources = inventory_agent.collect(subscription_ids)
    except Exception as exc:  # noqa: BLE001
        logger.error("Estate inventory failed: %s", exc)
        resources = []
    logger.info("Inventory: %d resources", len(resources))

    # ── 3. Cost data collection ───────────────────────────────────────────
    logger.info("Step 3/10: Cost data collection (%d days)", args.cost_lookback_days)
    try:
        cost_collector = CostDataCollector()
        cost_data = cost_collector.collect(subscription_ids, days=args.cost_lookback_days)
    except Exception as exc:  # noqa: BLE001
        logger.error("Cost data collection failed: %s", exc)
        cost_data = []
    logger.info("Cost data: %d entries", len(cost_data))

    # ── 4. Azure Advisor ──────────────────────────────────────────────────
    logger.info("Step 4/10: Azure Advisor collection")
    try:
        advisor_collector = AdvisorCollector()
        advisor_data = advisor_collector.collect(
            subscription_ids, include_security=args.include_security_advisor
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Advisor collection failed: %s", exc)
        advisor_data = []
    logger.info("Advisor: %d recommendations", len(advisor_data))

    # ── 5. Metrics collection ─────────────────────────────────────────────
    logger.info("Step 5/10: Metrics collection")
    try:
        metrics_collector = MetricsCollector()
        metrics = metrics_collector.collect(resources)
    except Exception as exc:  # noqa: BLE001
        logger.error("Metrics collection failed: %s", exc)
        metrics = {}
    logger.info("Metrics: %d resources", len(metrics))

    all_recommendations: list[Recommendation] = []

    # ── 6. Rightsizing ────────────────────────────────────────────────────
    logger.info("Step 6/10: Rightsizing analysis")
    try:
        rightsizing_agent = RightsizingAgent()
        recs = rightsizing_agent.analyse(resources, metrics, advisor_data)
        all_recommendations.extend(recs)
        logger.info("Rightsizing: %d recommendations", len(recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("Rightsizing analysis failed: %s", exc)

    # ── 7. Reservation ────────────────────────────────────────────────────
    logger.info("Step 7/10: Reservation analysis")
    try:
        reservation_agent = ReservationAgent()
        recs = reservation_agent.analyse(resources, cost_data, metrics)
        all_recommendations.extend(recs)
        logger.info("Reservation: %d recommendations", len(recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("Reservation analysis failed: %s", exc)

    # ── 8. Waste/Orphan ───────────────────────────────────────────────────
    logger.info("Step 8/10: Waste/Orphan analysis")
    try:
        waste_agent = WasteOrphanAgent()
        recs = waste_agent.analyse(resources, cost_data)
        all_recommendations.extend(recs)
        logger.info("Waste/Orphan: %d recommendations", len(recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("Waste/Orphan analysis failed: %s", exc)

    # ── 9. Operational FinOps ─────────────────────────────────────────────
    logger.info("Step 9/10: Operational FinOps analysis")
    try:
        operational_agent = OperationalFinOpsAgent()
        recs = operational_agent.analyse(resources, metrics, cost_data)
        all_recommendations.extend(recs)
        logger.info("Operational: %d recommendations", len(recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("Operational FinOps analysis failed: %s", exc)

    # ── 9b. Anomaly/Trend ─────────────────────────────────────────────────
    try:
        anomaly_agent = AnomalyTrendAgent()
        recs = anomaly_agent.analyse(cost_data, subscriptions)
        all_recommendations.extend(recs)
        logger.info("Anomaly/Trend: %d recommendations", len(recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("Anomaly/Trend analysis failed: %s", exc)

    # ── 10. Prioritise ────────────────────────────────────────────────────
    logger.info("Step 10/10: Prioritising recommendations")
    prioritiser = RecommendationPrioritiser()
    collection = prioritiser.prioritise(all_recommendations)
    logger.info(
        "Total: %d recommendations, estimated saving £%.2f/month",
        len(collection),
        collection.total_saving,
    )

    # ── Generate report ───────────────────────────────────────────────────
    report_agent = ReportAgent()
    report_md = report_agent.generate(collection)

    # Write report to disk
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = output_dir / f"finops-report-{date_str}.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("Report written to %s", report_path)

    # Print report summary
    print(f"✅ FinOps analysis complete.")
    print(f"   Subscriptions analysed: {len(subscription_ids)}")
    print(f"   Resources inventoried:  {len(resources)}")
    print(f"   Recommendations:        {len(collection)}")
    print(f"   Estimated saving:       £{collection.total_saving:,.2f}/month")
    print(f"   Report:                 {report_path}")

    # ── GitHub issue creation ─────────────────────────────────────────────
    if args.create_issues and args.github_token and args.repo:
        _create_github_issues(collection, args)

    return 0


def _create_github_issues(collection: RecommendationCollection, args: argparse.Namespace) -> None:
    """Create GitHub issues for top recommendations."""
    try:
        gh_agent = GitHubIntegrationAgent(token=args.github_token)

        # Create issues for top auto_fix and create_pr candidates
        issue_categories = {"auto_fix_candidate", "create_pr", "finance_approval_required"}
        created = 0
        for rec in collection.sorted_by_priority().items[:20]:
            category = rec.action.get("category", "")
            if category not in issue_categories:
                continue

            issue_body = _build_issue_body(rec)
            labels = [
                "finops/open",
                f"finops/{rec.recommendation_type}",
            ]
            try:
                issue_num = gh_agent.create_issue(
                    repo=args.repo,
                    title=f"[FinOps] {rec.action.get('title', rec.id)}",
                    body=issue_body,
                    labels=labels,
                )
                logger.info("Created issue #%d for recommendation %s", issue_num, rec.id)
                created += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to create issue for %s: %s", rec.id, exc)

        logger.info("Created %d GitHub issues", created)
    except Exception as exc:  # noqa: BLE001
        logger.error("GitHub issue creation failed: %s", exc)


def _build_issue_body(rec: Recommendation) -> str:
    """Build a GitHub issue body for a recommendation."""
    import json as _json

    lines = [
        f"## FinOps Recommendation: {rec.recommendation_type}",
        "",
        f"**ID:** `{rec.id}`  ",
        f"**Agent:** {rec.agent}  ",
        f"**Resource:** `{rec.resource_name}` (`{rec.resource_type}`)  ",
        f"**Subscription:** {rec.subscription_name}  ",
        f"**Owner:** {rec.owner or '—'}  ",
        f"**Environment:** {rec.environment or '—'}  ",
        "",
        f"### Summary",
        f"| Field | Value |",
        f"| --- | --- |",
        f"| Estimated saving | £{rec.estimated_monthly_saving:,.2f}/month |",
        f"| Confidence | {rec.confidence} |",
        f"| Risk | {rec.risk} |",
        f"| Effort | {rec.effort} |",
        f"| Reversibility | {rec.reversibility} |",
        f"| Priority score | {rec.priority_score:.1f}/100 |",
        "",
        "### Current State",
        f"```json\n{_json.dumps(rec.current_state, indent=2, default=str)}\n```",
        "",
        "### Recommended State",
        f"```json\n{_json.dumps(rec.recommended_state, indent=2, default=str)}\n```",
        "",
        "### Evidence",
        f"```json\n{_json.dumps(rec.evidence, indent=2, default=str)}\n```",
        "",
        "---",
        f"_Generated by Azure FinOps Agents on {rec.created_at.strftime('%Y-%m-%d %H:%M UTC')}_",
    ]
    return "\n".join(lines)


def main() -> None:
    """Main entrypoint for the weekly analysis CLI."""
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
