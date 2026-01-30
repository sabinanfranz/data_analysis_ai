from __future__ import annotations

"""
Thin compatibility layer that forwards to the TargetAttainmentAgent SSOT implementation.
"""

from .agents.target_attainment.agent import (
    TargetAttainmentAgent,
    run_target_attainment,
    _call_openai_chat_completions,
)
from .agents.target_attainment.schema import (
    MAX_TARGET_ATTAINMENT_REQUEST_BYTES,
    TargetAttainmentRequest,
    estimate_request_bytes,
    validate_payload_limits,
)

__all__ = [
    "TargetAttainmentAgent",
    "TargetAttainmentRequest",
    "MAX_TARGET_ATTAINMENT_REQUEST_BYTES",
    "estimate_request_bytes",
    "validate_payload_limits",
    "run_target_attainment",
    "_call_openai_chat_completions",
]


__all__ = [
    "TargetAttainmentRequest",
    "run_target_attainment",
    "validate_payload_limits",
    "estimate_request_bytes",
    "MAX_TARGET_ATTAINMENT_REQUEST_BYTES",
]
