from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BLOCKER_LABELS = [
    "PIPELINE_ZERO",
    "BUDGET",
    "DECISION_MAKER",
    "APPROVAL_DELAY",
    "LOW_PRIORITY",
    "COMPETITOR",
    "FIT_UNCLEAR",
    "NO_RESPONSE",
    "PRICE_TERM",
    "SCHEDULE_RESOURCE",
]


class CounterpartyCardPayload(BaseModel):
    report_mode: Literal["offline", "online"]
    as_of_date: date
    counterparty_key: Dict[str, Any]
    tier: str | None = None
    risk_rule: Dict[str, Any]
    signals: Dict[str, Any]
    top_deals_2026: List[Dict[str, Any]] = Field(default_factory=list)
    memos: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality: Dict[str, Any]

    model_config = ConfigDict(extra="allow")


class CounterpartyCardOutput(BaseModel):
    risk_level: Literal["양호", "보통", "심각"]
    top_blockers: List[str]
    evidence_bullets: List[str]
    recommended_actions: List[str]
    fallback_used: bool | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("top_blockers")
    @classmethod
    def validate_blockers(cls, v: List[str]) -> List[str]:
        if not (1 <= len(v) <= 3):
            raise ValueError("top_blockers must have 1~3 items")
        for blk in v:
            if blk not in BLOCKER_LABELS:
                raise ValueError(f"invalid blocker: {blk}")
        return v

    @field_validator("evidence_bullets")
    @classmethod
    def validate_evidence(cls, v: List[str]) -> List[str]:
        if len(v) != 3:
            raise ValueError("evidence_bullets must have exactly 3 items")
        return v

    @field_validator("recommended_actions")
    @classmethod
    def validate_actions(cls, v: List[str]) -> List[str]:
        if not (2 <= len(v) <= 3):
            raise ValueError("recommended_actions must have 2~3 items")
        return v

