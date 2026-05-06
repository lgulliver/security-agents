"""Pydantic v2 data models for FinOps recommendations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_serializer, field_validator


class Recommendation(BaseModel):
    """Represents a single FinOps recommendation produced by any agent.

    Each recommendation captures the current state of a resource, a suggested
    improvement, and supporting evidence/metadata for prioritisation.
    """

    id: str = Field(..., description="Unique recommendation ID, e.g. finops.azure.vm.rightsize.001")
    agent: str = Field(..., description="Name of the agent that created this recommendation")
    subscription_id: str
    subscription_name: str
    resource_id: str
    resource_type: str
    resource_name: str
    resource_group: str
    location: str
    owner: str = Field(default="", description="Owner/team derived from resource tags")
    environment: str = Field(default="", description="Environment derived from resource tags")
    recommendation_type: str = Field(
        ...,
        description="One of: rightsize | reserve | waste | operational | anomaly | tagging | sku | lifecycle",
    )
    current_state: dict = Field(default_factory=dict)
    recommended_state: dict = Field(default_factory=dict)
    estimated_monthly_saving: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="GBP")
    confidence: str = Field(..., description="high | medium | low")
    risk: str = Field(..., description="high | medium | low")
    effort: str = Field(..., description="high | medium | low")
    reversibility: str = Field(..., description="high | medium | low")
    evidence: list[dict] = Field(default_factory=list)
    action: dict = Field(
        default_factory=lambda: {"mode": "advisory", "requires_approval": True, "rollback": ""}
    )
    status: str = Field(default="open", description="open | resolved | suppressed | accepted_waste")
    priority_score: float = Field(default=0.0, ge=0.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(default=None)
    tags: dict = Field(default_factory=dict)

    @field_validator("recommendation_type")
    @classmethod
    def validate_recommendation_type(cls, v: str) -> str:
        """Validate recommendation_type is one of the allowed values."""
        allowed = {"rightsize", "reserve", "waste", "operational", "anomaly", "tagging", "sku", "lifecycle"}
        if v not in allowed:
            raise ValueError(f"recommendation_type must be one of {allowed}, got '{v}'")
        return v

    @field_validator("confidence", "risk", "effort", "reversibility")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """Validate that level fields are one of: high | medium | low."""
        allowed = {"high", "medium", "low"}
        if v not in allowed:
            raise ValueError(f"Value must be one of {allowed}, got '{v}'")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status field."""
        allowed = {"open", "resolved", "suppressed", "accepted_waste"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}, got '{v}'")
        return v

    model_config = {}

    @field_serializer("created_at", "expires_at")
    def serialise_datetime(self, v: datetime | None) -> str | None:
        """Serialise datetime fields to ISO 8601 strings."""
        return v.isoformat() if v is not None else None


class RecommendationCollection:
    """A collection of Recommendation objects with helpers for analysis and reporting."""

    def __init__(self, recommendations: list[Recommendation] | None = None) -> None:
        """Initialise with an optional list of recommendations."""
        self._items: list[Recommendation] = recommendations or []

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"RecommendationCollection(count={len(self._items)}, total_saving={self.total_saving:.2f})"

    def append(self, rec: Recommendation) -> None:
        """Add a recommendation to the collection."""
        self._items.append(rec)

    def extend(self, recs: list[Recommendation]) -> None:
        """Extend collection with a list of recommendations."""
        self._items.extend(recs)

    @property
    def items(self) -> list[Recommendation]:
        """Return the underlying list of recommendations."""
        return list(self._items)

    @property
    def total_saving(self) -> float:
        """Sum of all estimated monthly savings across all recommendations."""
        return sum(r.estimated_monthly_saving for r in self._items)

    def by_agent(self) -> dict[str, list[Recommendation]]:
        """Group recommendations by agent name."""
        result: dict[str, list[Recommendation]] = {}
        for rec in self._items:
            result.setdefault(rec.agent, []).append(rec)
        return result

    def by_owner(self) -> dict[str, list[Recommendation]]:
        """Group recommendations by owner."""
        result: dict[str, list[Recommendation]] = {}
        for rec in self._items:
            key = rec.owner or "unknown"
            result.setdefault(key, []).append(rec)
        return result

    def by_environment(self) -> dict[str, list[Recommendation]]:
        """Group recommendations by environment."""
        result: dict[str, list[Recommendation]] = {}
        for rec in self._items:
            key = rec.environment or "unknown"
            result.setdefault(key, []).append(rec)
        return result

    def filter_by_status(self, status: str) -> "RecommendationCollection":
        """Return a new collection containing only recommendations with the given status."""
        return RecommendationCollection([r for r in self._items if r.status == status])

    def filter_by_type(self, recommendation_type: str) -> "RecommendationCollection":
        """Return a new collection filtered by recommendation_type."""
        return RecommendationCollection([r for r in self._items if r.recommendation_type == recommendation_type])

    def sorted_by_priority(self) -> "RecommendationCollection":
        """Return a new collection sorted by priority_score descending."""
        return RecommendationCollection(sorted(self._items, key=lambda r: r.priority_score, reverse=True))

    def to_markdown_table(self) -> str:
        """Render the collection as a markdown table.

        Returns a markdown-formatted string with key recommendation fields.
        """
        if not self._items:
            return "_No recommendations._\n"

        headers = ["ID", "Type", "Resource", "Owner", "Saving (GBP/mo)", "Confidence", "Risk", "Effort", "Status"]
        rows = []
        for rec in self._items:
            rows.append([
                rec.id,
                rec.recommendation_type,
                rec.resource_name or rec.resource_id,
                rec.owner or "—",
                f"{rec.estimated_monthly_saving:.2f}",
                rec.confidence,
                rec.risk,
                rec.effort,
                rec.status,
            ])

        col_widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]

        def fmt_row(row: list) -> str:
            return "| " + " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)) + " |"

        separator = "| " + " | ".join("-" * w for w in col_widths) + " |"
        lines = [fmt_row(headers), separator] + [fmt_row(row) for row in rows]
        return "\n".join(lines) + "\n"
