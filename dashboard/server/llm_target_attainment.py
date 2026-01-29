from __future__ import annotations

import json
import os
import time
import hashlib
import logging
from typing import Any, Dict, Literal, Tuple

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from .prompt_loader import load_prompt

logger = logging.getLogger(__name__)

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


def _hash_payload(payload_dict: Dict[str, Any]) -> str:
    try:
        data = json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception:
        data = ""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _env_llm_settings() -> Dict[str, Any]:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    timeout = float(os.getenv("LLM_TIMEOUT", "30"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "512"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url.rstrip("/"),
        "timeout": timeout,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t[3:]
        if t.lower().startswith("json"):
            t = t[4:].lstrip()
        if "```" in t:
            t = t.split("```", 1)[0]
        return t.strip()
    return t


def _try_parse_json(text: str) -> Tuple[bool, Any | None, str | None]:
    try:
        obj = json.loads(text)
        return True, obj, None
    except Exception as exc:  # pragma: no cover - error path
        return False, None, str(exc)


def _call_openai_chat_completions(
    messages: list[dict],
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float,
    temperature: float,
    max_tokens: int,
) -> str:
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Invalid OpenAI response: {exc}")


def run_target_attainment(req: TargetAttainmentRequest, *, debug: bool = False, payload_bytes: int | None = None) -> dict:
    if req.target_2026 < 0 or req.actual_2026 < 0:
        raise HTTPException(status_code=400, detail={"error": "INVALID_NUMBER", "message": "target_2026/actual_2026 must be non-negative"})

    payload_dict = req.model_dump()
    bytes_est = payload_bytes if payload_bytes is not None else estimate_request_bytes(payload_dict)
    input_hash = _hash_payload(payload_dict)

    numbers = {
        "target": float(req.target_2026),
        "actual": float(req.actual_2026),
        "gap": float(req.target_2026 - req.actual_2026),
        "attainment_ratio": float(req.actual_2026 / req.target_2026) if req.target_2026 else None,
    }

    system_default = (
        '너는 B2B 세일즈/딜 파이프라인 데이터를 보고 2026 타겟 달성 가능성을 평가하는 분석가다.\n'
        '- 반드시 "유효한 JSON 오브젝트"만 출력한다. (마크다운/코드펜스/설명문 금지)\n'
        "- 숫자는 가능하면 number로 출력한다.\n"
        "- 아래 스키마를 최대한 지켜라.\n\n"
        '출력 JSON 스키마:\n{\n  "likelihood": "HIGH" | "MEDIUM" | "LOW",\n  "one_line": string,\n  "reasons": string[],\n'
        '  "risks": string[],\n  "next_actions": string[],\n  "numbers": { "target": number, "actual": number, "gap": number, "attainment_ratio": number | null }\n}'
    )
    user_default = (
        "아래 입력을 보고 2026 target 달성 가능성을 평가해줘.\n"
        "- won_group_json_compact에는 선택된 상위 조직 단위의 people/deal/memo 요약 정보가 들어있다.\n"
        "- target_2026, actual_2026 숫자를 함께 고려한다.\n"
        '- 판단 기준은 "현재 실적(actual) + 남은 파이프라인/딜 신호(있다면)"로 타겟 달성 가능성을 추정하는 것이다.\n'
        "- 출력은 시스템 규칙대로 JSON 오브젝트만.\n\n[INPUT]\n"
        "target_2026: {target_2026}\nactual_2026: {actual_2026}\n\nwon_group_json_compact (json):\n{won_group_json_compact_json}"
    )
    repair_default = (
        '너는 JSON 수리기다.\n아래 텍스트를 "유효한 JSON 오브젝트"로만 변환해 출력하라.\n'
        "- 마크다운/코드펜스/추가 설명 금지\n- 오직 JSON만 출력\n\n[TEXT]\n{raw_text}"
    )

    system_prompt = load_prompt("target_attainment_system", default_text=system_default)
    user_prompt_tpl = load_prompt("target_attainment_user", default_text=user_default)
    repair_prompt_tpl = load_prompt("target_attainment_repair", default_text=repair_default)

    compact_json = json.dumps(req.won_group_json_compact, ensure_ascii=False, separators=(",", ":"))
    user_prompt = user_prompt_tpl.format(
        target_2026=req.target_2026,
        actual_2026=req.actual_2026,
        won_group_json_compact_json=compact_json,
    )

    settings = _env_llm_settings()
    start_ts = time.monotonic()
    used_repair = False
    used_cache = False

    if settings.get("provider") != "openai" or not settings.get("api_key"):
        result = {
            "error": "LLM_NOT_CONFIGURED",
            "numbers": numbers,
        }
        if debug:
            result["__meta"] = {
                "input_hash": input_hash,
                "payload_bytes": bytes_est,
                "used_cache": False,
                "used_repair": False,
                "duration_ms": int((time.monotonic() - start_ts) * 1000),
            }
        return result

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    raw_text = ""
    try:
        logger.info(
          "target_attainment.start",
          extra={"event": "target_attainment.start", "orgId": req.orgId, "upperOrg": req.upperOrg, "bytes": bytes_est, "input_hash": input_hash},
        )
        raw_text = _call_openai_chat_completions(
            messages,
            model=settings["model"],
            base_url=settings["base_url"],
            api_key=settings["api_key"],
            timeout=settings["timeout"],
            temperature=settings["temperature"],
            max_tokens=settings["max_tokens"],
        )
        stripped = _strip_code_fences(raw_text)
        ok, parsed, _err = _try_parse_json(stripped)
        if not ok:
            used_repair = True
            repair_prompt = repair_prompt_tpl.format(raw_text=raw_text)
            repair_messages = [{"role": "system", "content": repair_prompt}]
            repaired = _call_openai_chat_completions(
                repair_messages,
                model=settings["model"],
                base_url=settings["base_url"],
                api_key=settings["api_key"],
                timeout=settings["timeout"],
                temperature=settings["temperature"],
                max_tokens=settings["max_tokens"],
            )
            repaired_stripped = _strip_code_fences(repaired)
            ok, parsed, _err = _try_parse_json(repaired_stripped)
            if not ok:
                return {"error": "LLM_OUTPUT_NOT_JSON", "raw": repaired, "numbers": numbers}
        if not isinstance(parsed, dict):
            return {"error": "LLM_OUTPUT_NOT_OBJECT", "raw": raw_text, "numbers": numbers}
        parsed["numbers"] = numbers
        duration_ms = int((time.monotonic() - start_ts) * 1000)
        logger.info(
            "target_attainment.done",
            extra={
                "event": "target_attainment.done",
                "duration_ms": duration_ms,
                "used_cache": used_cache,
                "used_repair": used_repair,
                "bytes": bytes_est,
                "input_hash": input_hash,
            },
        )
        if debug:
            parsed["__meta"] = {
                "input_hash": input_hash,
                "payload_bytes": bytes_est,
                "used_cache": used_cache,
                "used_repair": used_repair,
                "duration_ms": duration_ms,
            }
        return parsed
    except Exception as exc:  # pragma: no cover - exercised via tests indirectly
        logger.exception(
            "target_attainment.error",
            extra={"event": "target_attainment.error", "orgId": req.orgId, "upperOrg": req.upperOrg, "input_hash": input_hash, "bytes": bytes_est},
        )
        return {"error": "TARGET_ATTAINMENT_LLM_ERROR", "message": str(exc), "raw": raw_text, "numbers": numbers}


__all__ = [
    "TargetAttainmentRequest",
    "run_target_attainment",
    "validate_payload_limits",
    "estimate_request_bytes",
    "MAX_TARGET_ATTAINMENT_REQUEST_BYTES",
]
