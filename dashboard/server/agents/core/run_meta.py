from __future__ import annotations

from typing import Dict, Any


def build_meta(
    *,
    input_hash: str,
    prompt_hash: str,
    payload_bytes: int | None,
    used_cache: bool,
    used_repair: bool,
    duration_ms: int,
    repair_count: int | None = None,
) -> Dict[str, Any]:
    """
    Build debug meta object. Caller is responsible for attaching only when debug flag is True.
    """
    meta = {
        "input_hash": input_hash,
        "prompt_hash": prompt_hash,
        "payload_bytes": payload_bytes,
        "used_cache": used_cache,
        "used_repair": used_repair,
        "duration_ms": duration_ms,
    }
    if repair_count is not None:
        meta["repair_count"] = repair_count
    return meta
