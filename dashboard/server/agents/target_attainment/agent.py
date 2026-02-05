from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException

from dashboard.server.markdown_compact import won_groups_compact_to_markdown
from ..core.cache_store import build_cache_key, load as load_cache, save_atomic as save_cache
from ..core.json_guard import ensure_json_object_or_error, parse_json_object
from ..core.prompt_store import PromptStore
from ..core.run_meta import build_meta
from .schema import TargetAttainmentRequest, estimate_request_bytes, hash_payload

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_VERSION = "v1"
DEFAULT_CONTEXT_FORMAT = "md"
ALLOWED_CONTEXT_FORMATS = {"md", "json"}
ALLOWED_PROMPT_VERSIONS = {"v1", "v2"}


def _env_llm_settings() -> Dict[str, Any]:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    timeout_total = float(os.getenv("TARGET_ATTAINMENT_TIMEOUT", os.getenv("LLM_TIMEOUT", "120")))
    retry = int(os.getenv("TARGET_ATTAINMENT_RETRY", "1"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "512"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url.rstrip("/"),
        "timeout_total": timeout_total,
        "retry": retry,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def _get_context_format() -> str:
    val = (os.getenv("TARGET_ATTAINMENT_CONTEXT_FORMAT") or DEFAULT_CONTEXT_FORMAT).strip().lower()
    if val not in ALLOWED_CONTEXT_FORMATS:
        return DEFAULT_CONTEXT_FORMAT
    return val


def _get_prompt_version() -> str:
    val = (os.getenv("TARGET_ATTAINMENT_PROMPT_VERSION") or "v2").strip().lower()
    if val not in ALLOWED_PROMPT_VERSIONS:
        return "v2"
    return val


def _post_openai_once(url: str, headers: Dict[str, str], payload: Dict[str, Any], *, timeout: float) -> Dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _call_openai_chat_completions(
    messages: List[dict],
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout_total: float | None = None,
    temperature: float,
    max_tokens: int,
    retry: int = 0,
    timeout: float | None = None,
    calls_log: List[Dict[str, Any]] | None = None,
    kind: str = "main",
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
    total = timeout_total if timeout_total is not None else (timeout if timeout is not None else 120.0)
    attempts = max(1, 1 + max(0, retry))
    budget = max(total, 0.1)
    attempt_timeout = budget / attempts

    for attempt in range(attempts):
        per_timeout = attempt_timeout if attempt < attempts - 1 else budget
        try:
            if calls_log is not None:
                calls_log.append(
                    {
                        "kind": kind,
                        "attempt": attempt + 1,
                        "attempts": attempts,
                        "url": url,
                        "payload": payload,
                        "timeout_s": per_timeout,
                    }
                )
            data = _post_openai_once(url, headers, payload, timeout=per_timeout)
            try:
                return data["choices"][0]["message"]["content"]
            except Exception as exc:  # pragma: no cover - defensive
                raise RuntimeError(f"Invalid OpenAI response: {exc}")
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            if attempt < attempts - 1:
                logger.warning(
                    "target_attainment.retry",
                    extra={
                        "event": "target_attainment.retry",
                        "attempt": attempt + 1,
                        "attempts": attempts,
                        "timeout_s": per_timeout,
                        "reason": exc.__class__.__name__,
                    },
                )
                budget -= per_timeout
                time.sleep(0.5)
                continue
            logger.warning(
                "target_attainment.timeout",
                extra={"event": "target_attainment.timeout", "attempts": attempts, "timeout_total_s": timeout_total},
            )
            raise
        except httpx.HTTPStatusError:
            # do not retry on HTTP errors
            raise


class TargetAttainmentAgent:
    def __init__(self, *, prompt_dir: Path | None = None, cache_root: Path | None = None, version: str = DEFAULT_PROMPT_VERSION) -> None:
        self.prompt_dir = prompt_dir or Path(__file__).resolve().parent / "prompts"
        self.prompt_store = PromptStore(self.prompt_dir)
        self.cache_root = cache_root or (Path("report_cache") / "llm" / "target_attainment")
        self.version = version

    def _build_numbers(self, req: TargetAttainmentRequest) -> Dict[str, Any]:
        return {
            "target": float(req.target_2026),
            "actual": float(req.actual_2026),
            "gap": float(req.target_2026 - req.actual_2026),
            "attainment_ratio": float(req.actual_2026 / req.target_2026) if req.target_2026 else None,
        }

    def _llm_disabled(self, settings: Dict[str, Any]) -> bool:
        return settings.get("provider") != "openai" or not settings.get("api_key")

    def _cache_path(self, cache_key: str, variant: str) -> Path:
        return Path(self.cache_root) / variant / f"{cache_key}.json"

    def run(
        self,
        request: TargetAttainmentRequest,
        *,
        variant: str,
        debug: bool,
        nocache: bool = False,
        include_input: bool = False,
        context_format: str | None = None,
        prompt_version: str | None = None,
    ) -> Dict[str, Any]:
        if request.target_2026 < 0 or request.actual_2026 < 0:
            raise HTTPException(
                status_code=400,
                detail={"error": "INVALID_NUMBER", "message": "target_2026/actual_2026 must be non-negative"},
            )

        payload_dict = request.model_dump()
        payload_bytes = estimate_request_bytes(payload_dict)
        input_hash = hash_payload(payload_dict)
        numbers = self._build_numbers(request)

        chosen_context_format = (context_format or _get_context_format()).strip().lower()
        if chosen_context_format not in ALLOWED_CONTEXT_FORMATS:
            chosen_context_format = DEFAULT_CONTEXT_FORMAT
        chosen_prompt_version = (prompt_version or _get_prompt_version()).strip().lower()
        if chosen_prompt_version not in ALLOWED_PROMPT_VERSIONS:
            chosen_prompt_version = "v2"

        # SSOT note:
        # - request_md: frontend already fetched server-rendered compact-info-md/v1.1 via /orgs/{id}/won-groups-markdown-compact
        # - derived_md: server-side uses the same SSOT renderer (dashboard.server.markdown_compact.won_groups_compact_to_markdown)
        #   to avoid drift from the JS preview renderer (wonGroupsCompactToMarkdown), which is UI-only.
        md_from_request = None
        if isinstance(getattr(request, "won_group_markdown", None), str):
            md_from_request = request.won_group_markdown.strip()
            if md_from_request == "":
                md_from_request = None

        context_source_for_cache = "request_md" if md_from_request else chosen_context_format

        prompts = self.prompt_store.load_set(variant, chosen_prompt_version)
        prompt_hash = prompts.get("prompt_hash", "")
        settings = _env_llm_settings()
        start_ts = time.monotonic()
        llm_calls: List[Dict[str, Any]] = []

        cache_key = build_cache_key(
            llm_input_hash=input_hash,
            prompt_hash=prompt_hash,
            model=settings.get("model", ""),
            variant=variant,
            extra=f"{chosen_prompt_version}|{chosen_context_format}|{context_source_for_cache}",
        )
        used_cache = False
        used_repair = False

        context_meta: Dict[str, Any] = {
            "context_format": chosen_context_format,
            "context_source": context_source_for_cache,
            "prompt_version": chosen_prompt_version,
            "context_md_chars": None,
            "context_md_truncated": False,
            "context_md_head": None,
            "context_md_hash": None,
            "fallback_reason": None,
        }

        # cache read
        cache_path = self._cache_path(cache_key, variant)
        if not nocache:
            cached = load_cache(cache_path)
            if isinstance(cached, dict):
                result = cached.get("output") if "output" in cached else cached
                if isinstance(result, dict):
                    result = {**result, "numbers": numbers}
                    duration_ms = int((time.monotonic() - start_ts) * 1000)
                    used_cache = True
                    return self._attach_meta_if_needed(
                        result,
                        debug,
                        input_hash,
                        prompt_hash,
                        payload_bytes,
                        used_cache,
                        used_repair,
                        duration_ms,
                        extra_meta=context_meta,
                    )

        if self._llm_disabled(settings):
            result = {"error": "LLM_NOT_CONFIGURED", "numbers": numbers}
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            return self._attach_meta_if_needed(
                result, debug, input_hash, prompt_hash, payload_bytes, used_cache, used_repair, duration_ms
            )

        # Build prompts
        compact_json = json.dumps(request.won_group_json_compact, ensure_ascii=False, separators=(",", ":")) if request.won_group_json_compact is not None else "null"
        context_source = chosen_context_format
        context_payload_for_prompt = compact_json
        md_text: str | None = None

        if md_from_request:
            md_text = md_from_request
            context_meta["context_source"] = "request_md"
            context_meta["context_md_chars"] = len(md_text)
            context_meta["context_md_truncated"] = "(truncated due to size limit)" in md_text
            context_meta["context_md_head"] = md_text[:400]
            context_meta["context_md_hash"] = hashlib.sha256(md_text.encode("utf-8")).hexdigest()
            context_payload_for_prompt = f"```markdown\n{md_text}\n```"
        elif chosen_context_format == "md":
            try:
                md_text = won_groups_compact_to_markdown(
                    request.won_group_json_compact or {},
                    scope_label="UPPER_SELECTED",
                    max_people=60,
                    max_deals=200,
                    deal_memo_limit=10,
                    memo_max_chars=240,
                    redact_phone=True,
                    max_output_chars=200_000,
                )
                if not md_text or md_text.strip() == "" or md_text.strip() == "데이터가 없습니다.":
                    raise ValueError("empty_md_context")
                context_payload_for_prompt = f"```markdown\n{md_text}\n```"
                context_meta["context_source"] = "derived_md"
                context_meta["context_md_chars"] = len(md_text)
                context_meta["context_md_truncated"] = "(truncated due to size limit)" in md_text
                context_meta["context_md_head"] = md_text[:400]
                context_meta["context_md_hash"] = hashlib.sha256(md_text.encode("utf-8")).hexdigest()
            except Exception as exc:
                context_source = "json_fallback"
                context_meta["context_source"] = "json_fallback"
                context_meta["fallback_reason"] = str(exc)[:200]
                context_payload_for_prompt = compact_json
        else:
            context_meta["context_source"] = "json"

        user_prompt = prompts["user"].format(
            target_2026=request.target_2026,
            actual_2026=request.actual_2026,
            won_group_json_compact_json=context_payload_for_prompt,
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_prompt},
        ]

        raw_text = ""
        try:
            logger.info(
                "target_attainment.start",
                extra={
                    "event": "target_attainment.start",
                    "orgId": request.orgId,
                    "upperOrg": request.upperOrg,
                    "bytes": payload_bytes,
                    "input_hash": input_hash,
                    "prompt_hash": prompt_hash,
                },
            )
            raw_text = _call_openai_chat_completions(
                messages,
                model=settings["model"],
                base_url=settings["base_url"],
                api_key=settings["api_key"],
                timeout_total=settings["timeout_total"],
                temperature=settings["temperature"],
                max_tokens=settings["max_tokens"],
                retry=settings.get("retry", 0),
                calls_log=llm_calls,
                kind="main",
            )
            parsed = parse_json_object(raw_text)
            if parsed is None:
                used_repair = True
                repair_prompt = prompts.get("repair", "")

                def _repair_call(prompt_text: str) -> str:
                    return _call_openai_chat_completions(
                        [{"role": "system", "content": prompt_text}],
                        model=settings["model"],
                        base_url=settings["base_url"],
                        api_key=settings["api_key"],
                        timeout_total=settings["timeout_total"],
                        temperature=settings["temperature"],
                        max_tokens=settings["max_tokens"],
                        retry=settings.get("retry", 0),
                        calls_log=llm_calls,
                        kind="repair",
                    )

                parsed = ensure_json_object_or_error(raw_text, repair_prompt=repair_prompt, llm_call_fn=_repair_call)
            if not isinstance(parsed, dict):
                parsed = {"error": "LLM_OUTPUT_NOT_OBJECT", "raw": raw_text}
            parsed["numbers"] = numbers
            duration_ms = int((time.monotonic() - start_ts) * 1000)

            logger.info(
                "target_attainment.done",
                extra={
                    "event": "target_attainment.done",
                    "duration_ms": duration_ms,
                    "used_cache": used_cache,
                    "used_repair": used_repair,
                    "bytes": payload_bytes,
                    "input_hash": input_hash,
                    "prompt_hash": prompt_hash,
                },
            )

            if "error" not in parsed and not nocache:
                store_obj = {k: v for k, v in parsed.items() if k != "__llm_input"}
                save_cache(cache_path, {"output": store_obj})

            if include_input:
                parsed["__llm_input"] = {
                    "calls": llm_calls,
                    "context_format": context_meta.get("context_format"),
                    "context_source": context_meta.get("context_source"),
                    "prompt_version": context_meta.get("prompt_version"),
                    "context_md_chars": context_meta.get("context_md_chars"),
                    "context_md_truncated": context_meta.get("context_md_truncated"),
                    "context_md_head": context_meta.get("context_md_head"),
                    "fallback_reason": context_meta.get("fallback_reason"),
                }

            return self._attach_meta_if_needed(
                parsed,
                debug,
                input_hash,
                prompt_hash,
                payload_bytes,
                used_cache,
                used_repair,
                duration_ms,
                extra_meta=context_meta,
            )
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            timeout_total = settings.get("timeout_total", 120)
            attempts = 1 + max(0, settings.get("retry", 0))
            err_obj = {
                "error": "LLM_CALL_TIMEOUT",
                "message": str(exc),
                "attempts": attempts,
                "timeout_total_s": timeout_total,
                "numbers": numbers,
            }
            if include_input:
                err_obj["__llm_input"] = {
                    "calls": llm_calls,
                    "context_format": context_meta.get("context_format"),
                    "context_source": context_meta.get("context_source"),
                    "prompt_version": context_meta.get("prompt_version"),
                    "context_md_chars": context_meta.get("context_md_chars"),
                    "context_md_truncated": context_meta.get("context_md_truncated"),
                    "context_md_head": context_meta.get("context_md_head"),
                    "fallback_reason": context_meta.get("fallback_reason"),
                }
            return self._attach_meta_if_needed(
                err_obj,
                debug,
                input_hash,
                prompt_hash,
                payload_bytes,
                used_cache,
                used_repair,
                duration_ms,
                extra_meta=context_meta,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "target_attainment.error",
                extra={
                    "event": "target_attainment.error",
                    "orgId": request.orgId,
                    "upperOrg": request.upperOrg,
                    "input_hash": input_hash,
                    "bytes": payload_bytes,
                    "prompt_hash": prompt_hash,
                },
            )
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            parsed = {"error": "TARGET_ATTAINMENT_LLM_ERROR", "message": str(exc), "raw": raw_text, "numbers": numbers}
            if include_input:
                parsed["__llm_input"] = {
                    "calls": llm_calls,
                    "context_format": context_meta.get("context_format"),
                    "context_source": context_meta.get("context_source"),
                    "prompt_version": context_meta.get("prompt_version"),
                    "context_md_chars": context_meta.get("context_md_chars"),
                    "context_md_truncated": context_meta.get("context_md_truncated"),
                    "context_md_head": context_meta.get("context_md_head"),
                    "fallback_reason": context_meta.get("fallback_reason"),
                }
            return self._attach_meta_if_needed(
                parsed,
                debug,
                input_hash,
                prompt_hash,
                payload_bytes,
                used_cache,
                used_repair,
                duration_ms,
                extra_meta=context_meta,
            )

    def _attach_meta_if_needed(
        self,
        result: Dict[str, Any],
        debug: bool,
        input_hash: str,
        prompt_hash: str,
        payload_bytes: int | None,
        used_cache: bool,
        used_repair: bool,
        duration_ms: int,
        extra_meta: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if debug:
            result = {**result}
            meta = build_meta(
                input_hash=input_hash,
                prompt_hash=prompt_hash,
                payload_bytes=payload_bytes,
                used_cache=used_cache,
                used_repair=used_repair,
                duration_ms=duration_ms,
            )
            if extra_meta:
                meta.update(extra_meta)
            result["__meta"] = meta
        return result


def run_target_attainment(
    req: TargetAttainmentRequest,
    *,
    debug: bool = False,
    variant: str | None = None,
    nocache: bool = False,
    payload_bytes: int | None = None,
    include_input: bool = False,
) -> Dict[str, Any]:
    """
    Compatibility wrapper used by the API adapter.
    """
    variant_key = variant or getattr(req, "mode", "offline")
    context_format = _get_context_format()
    prompt_version = _get_prompt_version()
    agent = TargetAttainmentAgent()
    # payload_bytes currently not used inside agent, but kept for signature parity
    return agent.run(
        req,
        variant=variant_key,
        debug=debug,
        nocache=nocache,
        include_input=include_input,
        context_format=context_format,
        prompt_version=prompt_version,
    )
