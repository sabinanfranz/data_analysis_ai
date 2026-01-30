from __future__ import annotations

import json
from typing import Any, Dict, List

from pydantic import BaseModel


class PartReportRow(BaseModel):
    orgId: str | int
    upperOrg: str | None = None
    tier: str | None = None
    target: float | int | None = None
    actual: float | int | None = None
    row_agent_output_json: Dict[str, Any]


class PartReportInput(BaseModel):
    variant_key: str
    part_name: str
    rows: List[PartReportRow]


def payload_size_bytes(obj: Dict[str, Any]) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0
