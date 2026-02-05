from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, model_validator

MAX_TARGET_ATTAINMENT_REQUEST_BYTES = 512_000
MAX_MARKDOWN_CHARS = 250_000


class TargetAttainmentRequest(BaseModel):
    orgId: str
    orgName: str | None = None
    upperOrg: str
    mode: Literal["offline", "online"] = "offline"
    target_2026: float
    actual_2026: float
    won_group_json_compact: Optional[Dict[str, Any]] = None
    won_group_markdown: Optional[str] = None

    @model_validator(mode="after")
    def _ensure_input_present(self) -> "TargetAttainmentRequest":
        md = self.won_group_markdown
        if isinstance(md, str):
            md = md.strip()
        self.won_group_markdown = md or None
        if self.won_group_markdown and len(self.won_group_markdown) > MAX_MARKDOWN_CHARS:
            raise ValueError("won_group_markdown too large")

        if not self.won_group_markdown and self.won_group_json_compact is None:
            raise ValueError("Either won_group_markdown or won_group_json_compact must be provided")
        return self


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
