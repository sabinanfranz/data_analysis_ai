from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ReportMode = Literal["offline", "online"]


class CounterpartyKeyV1(BaseModel):
    org_id: str = Field(..., description="organization UUID")
    org_name: str
    upper_org: str = Field(..., description="upper org / counterparty (trim-only key)")
    tier: Optional[str] = None


class DealMiniV1(BaseModel):
    id: str
    name: str
    status: Optional[str] = None
    probability: List[str] = Field(default_factory=list)
    amount: Optional[float] = None
    expected_amount: Optional[float] = None
    contract_date: Optional[str] = None
    expected_date: Optional[str] = None
    start_date: Optional[str] = None
    course_format: Optional[str] = None


class MemoMiniV1(BaseModel):
    date: str
    source: Optional[str] = None  # org|deal|people
    text: str = Field(..., max_length=1200)


class ProgressSignalsV1(BaseModel):
    last_activity_date: Optional[str] = None
    open_deals_cnt: int = 0
    won_deals_cnt: int = 0
    dq_flags: List[str] = Field(default_factory=list)


class CounterpartyProgressInputV1(BaseModel):
    schema_version: Literal["counterparty-progress-input/v1"] = "counterparty-progress-input/v1"
    as_of: str = Field(..., description="YYYY-MM-DD")
    report_mode: ReportMode

    counterparty_key: CounterpartyKeyV1

    # SSOT quantitative facts (LLM must not overwrite)
    target_2026: float = 0
    actual_2026: float = 0
    target_is_override: Optional[bool] = None

    # Context (compact)
    viewer_compact: Optional[Dict[str, Any]] = None
    top_deals: List[DealMiniV1] = Field(default_factory=list, description="max 10, sorted desc by amount")
    recent_memos: List[MemoMiniV1] = Field(default_factory=list, description="max 20, last 180d")

    signals: ProgressSignalsV1 = Field(default_factory=ProgressSignalsV1)


ProgressStatus = Literal["NO_PROGRESS", "ONGOING", "GOOD_PROGRESS"]
Confidence = Literal["LOW", "MED", "HIGH"]


class CounterpartyProgressOutputV1(BaseModel):
    schema_version: Literal["counterparty-progress-output/v1"] = "counterparty-progress-output/v1"
    as_of: str
    report_mode: ReportMode
    counterparty_key: CounterpartyKeyV1

    progress_status: ProgressStatus
    confidence: Confidence = "MED"

    headline: str = Field(..., description="Korean, 1 sentence")
    evidence_bullets: List[str] = Field(..., min_length=3, max_length=3)
    recommended_actions: List[str] = Field(..., min_length=2, max_length=3)

    llm_meta: Dict[str, Any] = Field(default_factory=dict)


def export_input_json_schema() -> dict:
    return CounterpartyProgressInputV1.model_json_schema()


def export_output_json_schema() -> dict:
    return CounterpartyProgressOutputV1.model_json_schema()
