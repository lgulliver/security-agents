"""Recommendation Prioritiser — scores and categorises all FinOps recommendations.

Normalises and scores recommendations across all agents, assigning action
categories (auto_fix_candidate, create_pr, create_issue, etc.) and
returning a sorted RecommendationCollection.
"""

from __future__ import annotations

import logging
from datetime import datetime

from models.recommendation import Recommendation, RecommendationCollection

logger = logging.getLogger(__name__)

# Scoring weights (total = 100)
SAVING_MAX_SCORE = 40.0
CONFIDENCE_MAX_SCORE = 20.0
EFFORT_INVERSE_MAX_SCORE = 15.0
RISK_INVERSE_MAX_SCORE = 15.0
REVERSIBILITY_MAX_SCORE = 10.0

# Level to numeric maps
LEVEL_MAP = {"high": 3, "medium": 2, "low": 1}

# Thresholds for action categories
AUTO_FIX_MIN_SAVING = 500.0   # GBP/month
AUTO_FIX_MAX_RISK = "low"
CREATE_PR_MIN_SAVING = 100.0
FINANCE_APPROVAL_MIN_SAVING = 2000.0
NEEDS_REVIEW_CONFIDENCE = "low"

# Saving tiers for score mapping
SAVING_TIERS = [
    (2000.0, 40.0),
    (1000.0, 35.0),
    (500.0, 30.0),
    (200.0, 22.0),
    (100.0, 15.0),
    (50.0, 8.0),
    (0.0, 2.0),
]


def _saving_score(saving: float) -> float:
    """Map a monthly saving (GBP) to a 0-40 score."""
    for threshold, score in SAVING_TIERS:
        if saving >= threshold:
            return score
    return 0.0


def _confidence_score(confidence: str) -> float:
    """Map confidence level to a 0-20 score."""
    return {
        "high": CONFIDENCE_MAX_SCORE,
        "medium": CONFIDENCE_MAX_SCORE * 0.6,
        "low": CONFIDENCE_MAX_SCORE * 0.2,
    }.get(confidence, 0.0)


def _effort_inverse_score(effort: str) -> float:
    """Map effort to an inverse 0-15 score (low effort = high score)."""
    return {
        "low": EFFORT_INVERSE_MAX_SCORE,
        "medium": EFFORT_INVERSE_MAX_SCORE * 0.5,
        "high": EFFORT_INVERSE_MAX_SCORE * 0.1,
    }.get(effort, 0.0)


def _risk_inverse_score(risk: str) -> float:
    """Map risk to an inverse 0-15 score (low risk = high score)."""
    return {
        "low": RISK_INVERSE_MAX_SCORE,
        "medium": RISK_INVERSE_MAX_SCORE * 0.5,
        "high": RISK_INVERSE_MAX_SCORE * 0.1,
    }.get(risk, 0.0)


def _reversibility_score(reversibility: str) -> float:
    """Map reversibility to a 0-10 score (high reversibility = high score)."""
    return {
        "high": REVERSIBILITY_MAX_SCORE,
        "medium": REVERSIBILITY_MAX_SCORE * 0.5,
        "low": REVERSIBILITY_MAX_SCORE * 0.1,
    }.get(reversibility, 0.0)


def _compute_priority_score(rec: Recommendation) -> float:
    """Compute the total priority score for a recommendation (0-100)."""
    return (
        _saving_score(rec.estimated_monthly_saving)
        + _confidence_score(rec.confidence)
        + _effort_inverse_score(rec.effort)
        + _risk_inverse_score(rec.risk)
        + _reversibility_score(rec.reversibility)
    )


def _assign_action_category(rec: Recommendation) -> str:
    """Assign an action category to a recommendation based on its attributes.

    Returns one of: auto_fix_candidate, create_pr, create_issue,
    needs_owner_review, finance_approval_required, suppressed, accepted_waste.
    """
    if rec.status in ("suppressed", "accepted_waste"):
        return rec.status

    saving = rec.estimated_monthly_saving
    risk = rec.risk
    confidence = rec.confidence
    effort = rec.effort

    # Finance approval required for very large savings (implies significant changes)
    if saving >= FINANCE_APPROVAL_MIN_SAVING:
        return "finance_approval_required"

    # Needs owner review for low confidence or high risk — checked early
    if confidence == NEEDS_REVIEW_CONFIDENCE or risk == "high":
        return "needs_owner_review"

    # Auto-fix: high saving, low risk, low/medium effort, high/medium confidence
    if (
        saving >= AUTO_FIX_MIN_SAVING
        and risk == "low"
        and confidence in ("high", "medium")
        and effort in ("low", "medium")
    ):
        return "auto_fix_candidate"

    # Create PR for medium-high savings with manageable risk and medium+ confidence
    if saving >= CREATE_PR_MIN_SAVING and risk in ("low", "medium") and effort in ("low", "medium"):
        return "create_pr"

    # Default: create a GitHub issue for tracking
    return "create_issue"


class RecommendationPrioritiser:
    """Scores, ranks, and categorises recommendations from all agents.

    Applies a weighted scoring model across saving, confidence, effort,
    risk, and reversibility dimensions, then assigns an action category
    to each recommendation.
    """

    def prioritise(self, recommendations: list[Recommendation]) -> RecommendationCollection:
        """Score, categorise, and sort recommendations.

        Args:
            recommendations: Flat list of Recommendation objects from all agents.

        Returns:
            Sorted RecommendationCollection with priority_score populated.
        """
        if not recommendations:
            return RecommendationCollection([])

        scored: list[Recommendation] = []
        for rec in recommendations:
            score = _compute_priority_score(rec)
            category = _assign_action_category(rec)

            # Build updated dict and re-create (Pydantic v2 model)
            updated_data = rec.model_dump()
            updated_data["priority_score"] = round(score, 2)
            # Store action category in the action dict
            updated_data["action"] = {
                **updated_data.get("action", {}),
                "category": category,
            }
            try:
                scored.append(Recommendation(**updated_data))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to update recommendation %s: %s", rec.id, exc)
                scored.append(rec)

        scored.sort(key=lambda r: r.priority_score, reverse=True)
        logger.info(
            "Prioritised %d recommendations; total saving £%.2f",
            len(scored),
            sum(r.estimated_monthly_saving for r in scored),
        )
        return RecommendationCollection(scored)
