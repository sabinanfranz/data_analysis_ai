from __future__ import annotations

import json
from typing import Any, Dict, List

from pydantic import BaseModel


class PartRollupItem(BaseModel):
    part_name: str
    part_report_json: Dict[str, Any]


class DailyRollupInput(BaseModel):
    variant_key: str
    date: str | None = None
    parts: List[PartRollupItem]


def payload_size_bytes(obj: Dict[str, Any]) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0
