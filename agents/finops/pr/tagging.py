"""PR Tagging Agent — enforces resource tagging standards in Terraform plans.

Checks Terraform plan JSON for required and conditional tags on all managed
resources, returning recommendations and a compliance summary.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from models.recommendation import Recommendation

logger = logging.getLogger(__name__)

REQUIRED_TAGS = ["owner", "service", "product", "environment", "cost_center", "criticality", "managed_by"]

EPHEMERAL_ENVIRONMENTS = {
    "non-prod", "sandbox", "preview", "temporary", "ephemeral", "test",
    "dev", "development", "staging",
}

# Resource types that are typically inline/implicit and don't need tags
SKIP_RESOURCE_TYPES = {
    "azurerm_role_assignment",
    "azurerm_role_definition",
    "azurerm_policy_assignment",
    "azurerm_management_lock",
    "azurerm_resource_group_policy_assignment",
    "azurerm_subnet",
    "azurerm_network_security_rule",
    "azurerm_route",
}


class PRTaggingAgent:
    """Analyses a Terraform plan JSON for tagging compliance.

    Checks each managed resource for required tags and conditional tags
    (e.g. expiry_date for ephemeral environments).
    """

    AGENT_NAME = "pr.tagging"

    def __init__(
        self,
        mode: str = "advisory",
        required_tags: list[str] | None = None,
        ephemeral_environments: set[str] | None = None,
        subscription_id: str = "",
        subscription_name: str = "",
        currency: str = "GBP",
    ) -> None:
        """Initialise the Tagging Agent.

        Args:
            mode: 'advisory' (warnings only) or 'blocking' (fail the pipeline).
            required_tags: Override the default required tag list.
            ephemeral_environments: Override the default ephemeral environment names.
            subscription_id: Azure subscription ID.
            subscription_name: Azure subscription name.
            currency: Output currency code.
        """
        self.mode = mode
        self.required_tags = required_tags or REQUIRED_TAGS
        self.ephemeral_environments = ephemeral_environments or EPHEMERAL_ENVIRONMENTS
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.currency = currency

    def analyse(self, plan_json_path: str) -> tuple[list[Recommendation], dict]:
        """Analyse a Terraform plan for tagging compliance.

        Args:
            plan_json_path: Path to the Terraform plan JSON file.

        Returns:
            Tuple of (list of Recommendation objects, summary dict with keys
            'missing', 'conditional_missing', 'compliant').
        """
        with open(plan_json_path, "r", encoding="utf-8") as fh:
            plan = json.load(fh)

        workspace = plan.get("workspace", "default")
        resource_changes: list[dict] = plan.get("resource_changes", [])
        recommendations: list[Recommendation] = []
        summary: dict[str, list[str]] = {"missing": [], "conditional_missing": [], "compliant": []}

        for change in resource_changes:
            actions = change.get("change", {}).get("actions", [])
            if not actions or actions == ["no-op"]:
                continue

            res_type = change.get("type", "")
            if res_type in SKIP_RESOURCE_TYPES:
                continue

            # Only check resources that support tags (most azurerm_ resources do)
            if not res_type.startswith("azurerm_"):
                continue

            res_name = change.get("name", "")
            res_address = change.get("address", f"{res_type}.{res_name}")
            after: dict = change.get("change", {}).get("after") or {}

            # Some resources don't have a tags attribute at all
            if "tags" not in after and change.get("change", {}).get("after_unknown", {}).get("tags") is True:
                # Tags computed at apply time – skip
                continue

            tags: dict = after.get("tags") or {}
            location = after.get("location", "uksouth")
            resource_group = after.get("resource_group_name", "")
            environment = tags.get("environment", workspace).lower()
            owner = tags.get("owner", "")

            missing_required = [t for t in self.required_tags if t not in tags]
            missing_conditional: list[str] = []

            if environment in self.ephemeral_environments and "expiry_date" not in tags:
                missing_conditional.append("expiry_date")

            if missing_required or missing_conditional:
                if missing_required:
                    summary["missing"].append(res_address)
                if missing_conditional:
                    summary["conditional_missing"].append(res_address)

                rec = Recommendation(
                    id=f"finops.pr.tagging.{uuid.uuid4().hex[:8]}",
                    agent=self.AGENT_NAME,
                    subscription_id=self.subscription_id,
                    subscription_name=self.subscription_name,
                    resource_id=res_address,
                    resource_type=res_type,
                    resource_name=res_name,
                    resource_group=resource_group,
                    location=location,
                    owner=owner,
                    environment=environment,
                    recommendation_type="tagging",
                    current_state={"tags": tags, "missing_required": missing_required, "missing_conditional": missing_conditional},
                    recommended_state={
                        "tags": {
                            **tags,
                            **{t: "<required>" for t in missing_required},
                            **{t: "<required_for_env>" for t in missing_conditional},
                        }
                    },
                    estimated_monthly_saving=0.0,
                    currency=self.currency,
                    confidence="high",
                    risk="low",
                    effort="low",
                    reversibility="high",
                    evidence=[
                        {
                            "missing_required_tags": missing_required,
                            "missing_conditional_tags": missing_conditional,
                            "current_tags": list(tags.keys()),
                            "environment": environment,
                            "mode": self.mode,
                        }
                    ],
                    action={
                        "mode": self.mode,
                        "requires_approval": self.mode == "blocking",
                        "rollback": f"Add missing tags to {res_address}",
                    },
                    created_at=datetime.now(timezone.utc),
                    tags=tags,
                )
                recommendations.append(rec)
                logger.info(
                    "Tagging issue on %s: missing=%s conditional=%s",
                    res_address,
                    missing_required,
                    missing_conditional,
                )
            else:
                summary["compliant"].append(res_address)
                logger.debug("Resource %s is tag-compliant", res_address)

        return recommendations, summary
