from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ReportMode = Literal["offline", "online"]
ScopeType = Literal["business", "team", "part"]


class ScopeKeyV1(BaseModel):
    type: ScopeType
    key: str


class RollupMetricsV1(BaseModel):
    target_sum_2026: float = 0
    actual_sum_2026: float = 0
    progress_ratio: Optional[float] = None
    no_progress_cnt: int = 0
    ongoing_cnt: int = 0
    good_progress_cnt: int = 0


class L1ItemMiniV1(BaseModel):
    org_id: str
    org_name: str
    upper_org: str
    tier: Optional[str] = None
    target_2026: float = 0
    actual_2026: float = 0
    progress_status: Literal["NO_PROGRESS", "ONGOING", "GOOD_PROGRESS"]
    headline: str


class GroupProgressInputV1(BaseModel):
    schema_version: Literal["group-progress-input/v1"] = "group-progress-input/v1"
    as_of: str
    report_mode: ReportMode
    scope: ScopeKeyV1
    rollup: RollupMetricsV1
    items: List[L1ItemMiniV1] = Field(default_factory=list)


class GroupProgressOutputV1(BaseModel):
    schema_version: Literal["group-progress-output/v1"] = "group-progress-output/v1"
    as_of: str
    report_mode: ReportMode
    scope: ScopeKeyV1

    executive_summary: List[str] = Field(..., min_length=2, max_length=4)
    problem_diagnosis: List[str] = Field(..., min_length=2, max_length=8)
    today_priorities: List[str] = Field(..., min_length=3, max_length=8)

    rollup: RollupMetricsV1
    llm_meta: Dict[str, Any] = Field(default_factory=dict)


def export_input_json_schema() -> dict:
    return GroupProgressInputV1.model_json_schema()


def export_output_json_schema() -> dict:
    return GroupProgressOutputV1.model_json_schema()
