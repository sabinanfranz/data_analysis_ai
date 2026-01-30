from __future__ import annotations

import json
from typing import Any, Callable, Tuple


def parse_json(text: str) -> Tuple[Any | None, str | None]:
    try:
        return json.loads(text), None
    except Exception as exc:
        return None, str(exc)


def validate_output(obj: Any, validator: Callable[[Any], None] | None = None) -> Tuple[bool, str | None]:
    try:
        if validator:
            validator(obj)
        return True, None
    except Exception as exc:
        return False, str(exc)


def repair_once(repair_fn: Callable[[str], str], bad_text: str) -> Tuple[Any | None, str | None]:
    try:
        fixed = repair_fn(bad_text)
        return json.loads(fixed), None
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Lenient JSON-only guard (PR-A)
# ---------------------------------------------------------------------------

MAX_REPAIR_ATTEMPTS = 2
MAX_RAW_LEN = 4096


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t[3:]
        if t.lower().startswith("json"):
            t = t[4:].lstrip()
        if "```" in t:
            t = t.split("```", 1)[0]
    return t.strip()


def _slice_braces(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_json_object(text: str) -> dict | None:
    """
    Best-effort JSON object parser.
    - Removes code fences.
    - Keeps only the segment between the first '{' and the last '}'.
    - Returns dict on success, None otherwise.
    """
    if not isinstance(text, str):
        return None
    candidate = _strip_code_fence(text)
    candidate = _slice_braces(candidate)
    try:
        obj = json.loads(candidate)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def repair_to_json_object(bad_text: str, repair_prompt: str, llm_call_fn: Optional[Callable[[str], str]] = None) -> dict | None:
    """
    Attempt to repair non-JSON text into a JSON object using an LLM callback.
    llm_call_fn: callable that takes prompt text and returns string output.
    """
    if llm_call_fn is None:
        return None
    attempt_input = bad_text
    for _ in range(MAX_REPAIR_ATTEMPTS):
        prompt_text = repair_prompt
        try:
            prompt_text = repair_prompt.format(raw_text=attempt_input)
        except Exception:
            # If formatting fails, fall back to raw prompt as-is
            prompt_text = repair_prompt
        repaired = llm_call_fn(prompt_text)
        parsed = parse_json_object(repaired)
        if parsed is not None:
            return parsed
        attempt_input = repaired
    return None


def ensure_json_object_or_error(text: str, *, repair_prompt: str | None = None, llm_call_fn=None) -> dict:
    """
    Ensure JSON object output with optional repair.
    Returns JSON object; on failure returns {"error": "...", "raw": "<trimmed>"}.
    """
    parsed = parse_json_object(text)
    if parsed is not None:
        return parsed
    if repair_prompt and llm_call_fn:
        repaired = repair_to_json_object(text, repair_prompt, llm_call_fn=llm_call_fn)
        if repaired is not None:
            return repaired
    raw = text if isinstance(text, str) else str(text)
    if len(raw) > MAX_RAW_LEN:
        raw = raw[:MAX_RAW_LEN] + "...(truncated)"
    return {"error": "Non-JSON response", "raw": raw}
