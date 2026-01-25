from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

from ..core.cache_store import load as load_cache, save_atomic as save_cache
from ..core.canonicalize import canonical_json, compute_llm_input_hash
from ..core.json_guard import parse_json
from ..core.prompt_store import PromptStore
from ..core.types import AgentContext, LLMConfig
from .fallback import build_fallback_result
from .schema import CounterpartyProgressInputV1, CounterpartyProgressOutputV1

ALLOWED_KEYS = {"progress_status", "confidence", "headline", "evidence_bullets", "recommended_actions"}


def _upper_slug(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:10]


class CounterpartyProgressAgent:
    name = "CounterpartyProgressAgent"
    scope = "report"

    def __init__(self, version: str = "v1") -> None:
        self.version = version
        self.prompt = PromptStore(base_dir=Path(__file__).parent / "prompts")

    def _cache_path(self, ctx: AgentContext, payload: CounterpartyProgressInputV1) -> Path:
        as_of = ctx.as_of_date.isoformat()
        org = payload.counterparty_key.org_id
        upper = payload.counterparty_key.upper_org
        upper_slug = _upper_slug(str(upper or ""))
        return ctx.cache_root / "llm_progress" / as_of / ctx.db_hash / ctx.mode_key / f"{org}__{upper_slug}.json"

    def _load_cache(self, path: Path, llm_input_hash: str) -> Dict[str, Any] | None:
        cached = load_cache(path)
        if not cached:
            return None
        meta = cached.get("llm_meta", {})
        if meta.get("llm_input_hash") != llm_input_hash:
            return None
        if meta.get("prompt_version") != self.version:
            return None
        return cached

    def _llm_disabled(self, llm_cfg: LLMConfig) -> bool:
        return not llm_cfg.is_enabled() or OpenAI is None

    def _llm_call(self, payload_json: str, prompts: Dict[str, str], llm_cfg: LLMConfig):
        if self._llm_disabled(llm_cfg):
            return None, "llm_disabled_or_missing_key"
        client = OpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url or None)
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"].replace("{{PAYLOAD_JSON}}", payload_json)},
        ]
        completion = client.chat.completions.create(
            model=llm_cfg.model,
            messages=messages,
            timeout=llm_cfg.timeout,
            max_tokens=llm_cfg.max_tokens,
            temperature=llm_cfg.temperature,
        )
        text = completion.choices[0].message.content or ""
        return text, None

    def _repair_json(self, prompts: Dict[str, str], llm_cfg: LLMConfig):
        if self._llm_disabled(llm_cfg):
            return None, "llm_disabled_or_missing_key"
        client = OpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url or None)
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["repair"]},
        ]
        completion = client.chat.completions.create(
            model=llm_cfg.model,
            messages=messages,
            timeout=llm_cfg.timeout,
            max_tokens=llm_cfg.max_tokens,
            temperature=llm_cfg.temperature,
        )
        text = completion.choices[0].message.content or ""
        try:
            return json.loads(text), None
        except Exception as exc:
            return None, str(exc)

    def _wrap_output(self, payload: CounterpartyProgressInputV1, body: Dict[str, Any], llm_hash: str, fallback_used: bool, model: str | None) -> Dict[str, Any]:
        filtered = {k: body.get(k) for k in ALLOWED_KEYS}
        validated = CounterpartyProgressOutputV1(
            as_of=payload.as_of,
            report_mode=payload.report_mode,
            counterparty_key=payload.counterparty_key,
            progress_status=filtered.get("progress_status"),
            confidence=filtered.get("confidence") or "MED",
            headline=filtered.get("headline") or "",
            evidence_bullets=filtered.get("evidence_bullets") or [],
            recommended_actions=filtered.get("recommended_actions") or [],
            llm_meta={
                "llm_input_hash": llm_hash,
                "prompt_version": self.version,
                "fallback_used": fallback_used,
                "model": model,
            },
        )
        return validated.model_dump()

    def run(self, conn, ctx: AgentContext, artifacts) -> Dict[Tuple[str, str], Dict[str, Any]]:
        rows: Sequence[Dict[str, Any]] = artifacts.get("base.counterparty_rows", [])
        prompts = self.prompt.load_set(ctx.mode_key, self.version)
        outputs: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in rows:
            payload = CounterpartyProgressInputV1.model_validate(r)
            payload_dict = payload.model_dump()
            payload_json = canonical_json(payload_dict)
            llm_hash = compute_llm_input_hash(payload_dict)
            cache_path = self._cache_path(ctx, payload)
            cached = self._load_cache(cache_path, llm_hash)
            key = (payload.counterparty_key.org_id, payload.counterparty_key.upper_org)
            if cached:
                outputs[key] = {**cached, "used_cache": True}
                continue

            raw_text, err = self._llm_call(payload_json, prompts, ctx.llm)
            body: Dict[str, Any] = {}
            parsed: Dict[str, Any] | None = None
            if err or raw_text is None:
                parsed = None
            else:
                parsed_obj, parse_err = parse_json(raw_text)
                if parse_err:
                    repaired, _ = self._repair_json(prompts, ctx.llm)
                    parsed = repaired if isinstance(repaired, dict) else None
                else:
                    parsed = parsed_obj if isinstance(parsed_obj, dict) else None
            if parsed:
                body = {k: parsed.get(k) for k in ALLOWED_KEYS}

            try:
                wrapped = self._wrap_output(payload, body, llm_hash, fallback_used=False, model=ctx.llm.model)
                # ensure evidence/actions length, else fallback
                if len(wrapped.get("evidence_bullets", [])) != 3 or not (2 <= len(wrapped.get("recommended_actions", [])) <= 3):
                    raise ValueError("invalid lengths")
                save_cache(cache_path, wrapped)
                outputs[key] = wrapped
                continue
            except Exception:
                fb_body = build_fallback_result(payload)
                wrapped = self._wrap_output(payload, fb_body, llm_hash, fallback_used=True, model=ctx.llm.model)
                save_cache(cache_path, wrapped)
                outputs[key] = wrapped
        return outputs
