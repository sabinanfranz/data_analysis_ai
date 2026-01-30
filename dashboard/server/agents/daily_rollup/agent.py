from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from ..core.cache_store import build_cache_key, load as load_cache, save_atomic as save_cache
from ..core.canonicalize import compute_llm_input_hash
from ..core.json_guard import ensure_json_object_or_error, parse_json_object
from ..core.prompt_store import PromptStore
from ..core.run_meta import build_meta
from ..target_attainment.agent import _call_openai_chat_completions
from .schema import DailyRollupInput, payload_size_bytes

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_VERSION = "v1"


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


class DailyRollupAgent:
    def __init__(self, *, prompt_dir: Path | None = None, cache_root: Path | None = None, version: str = DEFAULT_PROMPT_VERSION) -> None:
        self.prompt_dir = prompt_dir or Path(__file__).resolve().parent / "prompts"
        self.prompt_store = PromptStore(self.prompt_dir)
        self.cache_root = cache_root or (Path("report_cache") / "llm" / "daily_rollup")
        self.version = version

    def _cache_path(self, cache_key: str, variant: str) -> Path:
        return Path(self.cache_root) / variant / f"{cache_key}.json"

    def run(self, input: DailyRollupInput | dict, *, variant: str, debug: bool, nocache: bool = False) -> Dict[str, Any]:
        try:
            payload = input if isinstance(input, DailyRollupInput) else DailyRollupInput(**input)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        payload_dict = payload.model_dump()
        payload_bytes = payload_size_bytes(payload_dict)
        llm_input_hash = compute_llm_input_hash(payload_dict)
        prompts = self.prompt_store.load_set(variant, self.version)
        prompt_hash = prompts.get("prompt_hash", "")
        settings = _env_llm_settings()
        start_ts = time.monotonic()
        used_cache = False
        used_repair = False
        repair_count = 0

        cache_key = build_cache_key(
            llm_input_hash=llm_input_hash,
            prompt_hash=prompt_hash,
            model=settings.get("model", ""),
            variant=variant,
        )
        cache_path = self._cache_path(cache_key, variant)
        if not nocache:
            cached = load_cache(cache_path)
            if isinstance(cached, dict):
                output = cached.get("output") if "output" in cached else cached
                if isinstance(output, dict):
                    used_cache = True
                    return self._attach_meta(output, debug, llm_input_hash, prompt_hash, payload_bytes, used_cache, used_repair, repair_count, start_ts)

        if settings.get("provider") != "openai" or not settings.get("api_key"):
            result = {"error": "LLM_NOT_CONFIGURED"}
            return self._attach_meta(result, debug, llm_input_hash, prompt_hash, payload_bytes, used_cache, used_repair, repair_count, start_ts)

        parts_json = json.dumps([p.model_dump() for p in payload.parts], ensure_ascii=False, separators=(",", ":"))
        user_prompt = (
            prompts["user"]
            .replace("{date}", payload.date or "")
            .replace("{parts_json}", parts_json)
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_prompt},
        ]

        raw_text = ""
        try:
            raw_text = _call_openai_chat_completions(
                messages,
                model=settings["model"],
                base_url=settings["base_url"],
                api_key=settings["api_key"],
                timeout=settings["timeout"],
                temperature=settings["temperature"],
                max_tokens=settings["max_tokens"],
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
                        timeout=settings["timeout"],
                        temperature=settings["temperature"],
                        max_tokens=settings["max_tokens"],
                    )

                parsed = ensure_json_object_or_error(raw_text, repair_prompt=repair_prompt, llm_call_fn=_repair_call)
                repair_count = 1

            if not isinstance(parsed, dict):
                parsed = {"error": "LLM_OUTPUT_NOT_OBJECT"}

            duration_ms = int((time.monotonic() - start_ts) * 1000)
            if "error" not in parsed and not nocache:
                save_cache(cache_path, {"output": parsed})
            return self._attach_meta(parsed, debug, llm_input_hash, prompt_hash, payload_bytes, used_cache, used_repair, repair_count, start_ts, duration_ms)
        except Exception as exc:  # pragma: no cover - defensive
            parsed = {"error": "DAILY_ROLLUP_LLM_ERROR", "message": str(exc)}
            return self._attach_meta(parsed, debug, llm_input_hash, prompt_hash, payload_bytes, used_cache, used_repair, repair_count, start_ts)

    def _attach_meta(
        self,
        result: Dict[str, Any],
        debug: bool,
        input_hash: str,
        prompt_hash: str,
        payload_bytes: int | None,
        used_cache: bool,
        used_repair: bool,
        repair_count: int,
        start_ts: float,
        duration_ms: int | None = None,
    ) -> Dict[str, Any]:
        if debug:
            duration_ms = duration_ms if duration_ms is not None else int((time.monotonic() - start_ts) * 1000)
            result = {**result}
            result["__meta"] = build_meta(
                input_hash=input_hash,
                prompt_hash=prompt_hash,
                payload_bytes=payload_bytes,
                used_cache=used_cache,
                used_repair=used_repair,
                duration_ms=duration_ms,
                repair_count=repair_count if used_repair else None,
            )
        return result
