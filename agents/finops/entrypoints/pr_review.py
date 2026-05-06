"""PR Review entrypoint — CLI for running FinOps checks on a Terraform plan.

Runs CostDiffAgent, SKUSanityAgent, TaggingAgent, and LifecycleWasteAgent
against a Terraform plan JSON, aggregates results, and optionally posts a
PR comment via GitHub.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from agents.pr.cost_diff import PRCostDiffAgent
from agents.pr.lifecycle_waste import PRLifecycleWasteAgent
from agents.pr.sku_sanity import PRSKUSanityAgent
from agents.pr.tagging import PRTaggingAgent
from agents.weekly.github_integration import GitHubIntegrationAgent
from agents.weekly.recommendation_prioritiser import RecommendationPrioritiser
from models.recommendation import RecommendationCollection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Azure FinOps PR Review — analyse a Terraform plan for cost/tagging/lifecycle issues"
    )
    parser.add_argument("--plan-json", required=True, help="Path to Terraform plan JSON file")
    parser.add_argument(
        "--mode",
        choices=["advisory", "blocking"],
        default="advisory",
        help="Run in advisory (warnings only) or blocking (exit 1 on findings) mode",
    )
    parser.add_argument(
        "--output-format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format for findings",
    )
    parser.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token for posting PR comments (or set GITHUB_TOKEN env var)",
    )
    parser.add_argument("--repo", default="", help="GitHub repository (owner/repo) for PR comments")
    parser.add_argument("--pr-number", type=int, default=0, help="Pull request number for comments")
    parser.add_argument(
        "--subscription-id", default="", help="Azure subscription ID (metadata only)"
    )
    parser.add_argument("--subscription-name", default="", help="Azure subscription name (metadata only)")
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute the PR review pipeline.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code: 0 for success, 1 for blocking failures.
    """
    plan_path = args.plan_json
    mode = args.mode

    logger.info("Starting FinOps PR review: plan=%s mode=%s", plan_path, mode)

    all_recommendations = []

    # 1. Cost Diff
    try:
        cost_agent = PRCostDiffAgent(
            subscription_id=args.subscription_id,
            subscription_name=args.subscription_name,
        )
        cost_recs, cost_summary = cost_agent.analyse(plan_path)
        all_recommendations.extend(cost_recs)
        logger.info("CostDiffAgent: %d recommendations", len(cost_recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("CostDiffAgent failed: %s", exc)
        cost_summary = ""

    # 2. SKU Sanity
    try:
        sku_agent = PRSKUSanityAgent(
            subscription_id=args.subscription_id,
            subscription_name=args.subscription_name,
        )
        sku_recs = sku_agent.analyse(plan_path)
        all_recommendations.extend(sku_recs)
        logger.info("SKUSanityAgent: %d recommendations", len(sku_recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("SKUSanityAgent failed: %s", exc)
        sku_recs = []

    # 3. Tagging
    try:
        tagging_agent = PRTaggingAgent(
            mode=mode,
            subscription_id=args.subscription_id,
            subscription_name=args.subscription_name,
        )
        tagging_recs, tagging_summary = tagging_agent.analyse(plan_path)
        all_recommendations.extend(tagging_recs)
        logger.info("TaggingAgent: %d recommendations", len(tagging_recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("TaggingAgent failed: %s", exc)
        tagging_recs = []
        tagging_summary = {}

    # 4. Lifecycle/Waste
    try:
        lifecycle_agent = PRLifecycleWasteAgent(
            subscription_id=args.subscription_id,
            subscription_name=args.subscription_name,
        )
        lifecycle_recs = lifecycle_agent.analyse(plan_path)
        all_recommendations.extend(lifecycle_recs)
        logger.info("LifecycleWasteAgent: %d recommendations", len(lifecycle_recs))
    except Exception as exc:  # noqa: BLE001
        logger.error("LifecycleWasteAgent failed: %s", exc)
        lifecycle_recs = []

    # 5. Prioritise
    prioritiser = RecommendationPrioritiser()
    collection = prioritiser.prioritise(all_recommendations)

    # 6. Build output
    if args.output_format == "json":
        output = json.dumps([r.model_dump(mode="json") for r in collection], indent=2, default=str)
    else:
        output = _build_pr_markdown(collection, cost_summary, tagging_summary, mode)

    print(output)

    # 7. Post GitHub PR comment
    if args.github_token and args.repo and args.pr_number:
        try:
            gh_agent = GitHubIntegrationAgent(token=args.github_token)
            gh_agent.post_pr_comment(args.repo, args.pr_number, output[:65000])
            logger.info("Posted PR comment on %s#%d", args.repo, args.pr_number)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to post PR comment: %s", exc)

    # 8. Determine exit code
    if mode == "blocking":
        blocking_recs = [
            r for r in collection
            if r.action.get("mode") == "blocking" and r.status == "open"
        ]
        if blocking_recs:
            logger.error(
                "Blocking mode: %d blocking findings. Failing the PR check.", len(blocking_recs)
            )
            return 1

    return 0


def _build_pr_markdown(
    collection: RecommendationCollection,
    cost_summary: str,
    tagging_summary: dict,
    mode: str,
) -> str:
    """Build the markdown PR comment body."""
    lines = [
        "## 🔍 Azure FinOps PR Review",
        "",
        f"> Mode: **{mode}** | Total recommendations: **{len(collection)}** | "
        f"Estimated savings: **£{collection.total_saving:,.2f}/month**",
        "",
    ]

    if cost_summary:
        lines.append(cost_summary)

    if tagging_summary:
        missing_count = len(tagging_summary.get("missing", []))
        cond_count = len(tagging_summary.get("conditional_missing", []))
        compliant_count = len(tagging_summary.get("compliant", []))
        lines += [
            "### 🏷️ Tagging Summary",
            "",
            f"| Status | Count |",
            f"| --- | --- |",
            f"| ✅ Compliant | {compliant_count} |",
            f"| ❌ Missing required tags | {missing_count} |",
            f"| ⚠️ Missing conditional tags | {cond_count} |",
            "",
        ]

    # Top findings table
    if collection.items:
        lines += ["### Top Findings", "", collection.to_markdown_table()]

    return "\n".join(lines)


def main() -> None:
    """Main entrypoint for the PR review CLI."""
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
