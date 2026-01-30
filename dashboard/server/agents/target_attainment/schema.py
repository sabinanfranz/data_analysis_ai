from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Literal

from pydantic import BaseModel

MAX_TARGET_ATTAINMENT_REQUEST_BYTES = 512_000


class TargetAttainmentRequest(BaseModel):
    orgId: str
    orgName: str | None = None
    upperOrg: str
    mode: Literal["offline", "online"] = "offline"
    target_2026: float
    actual_2026: float
    won_group_json_compact: Dict[str, Any]


def estimate_request_bytes(payload_dict: Dict[str, Any]) -> int:
    try:
        encoded = json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except Exception:
        encoded = b""
    return len(encoded)


def validate_payload_limits(payload_dict: Dict[str, Any]) -> int:
    size = estimate_request_bytes(payload_dict)
    if size > MAX_TARGET_ATTAINMENT_REQUEST_BYTES:
        raise ValueError("PAYLOAD_TOO_LARGE")
    return size


def hash_payload(payload_dict: Dict[str, Any]) -> str:
    try:
        data = json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception:
        data = ""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
