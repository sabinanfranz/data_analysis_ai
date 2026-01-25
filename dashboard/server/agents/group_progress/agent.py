from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

from ..core.cache_store import load as load_cache, save_atomic as save_cache
from ..core.canonicalize import compute_llm_input_hash, canonical_json
from ..core.prompt_store import PromptStore
from ..core.types import AgentContext
from .fallback import fallback_output
from .schema import GroupProgressInputV1, GroupProgressOutputV1


def _scope_slug(scope_key: str) -> str:
    return hashlib.sha1(scope_key.strip().encode("utf-8")).hexdigest()[:10]


class GroupProgressAgent:
    name = "GroupProgressAgent"
    scope = "report"

    def __init__(self, version: str = "v1") -> None:
        self.version = version
        self.prompt = PromptStore(base_dir=Path(__file__).parent / "prompts")

    def _cache_path(self, ctx: AgentContext, payload: Dict[str, Any]) -> Path:
        as_of = ctx.as_of_date.isoformat()
        scope = payload.get("scope", {}) or {}
        scope_type = scope.get("type", "scope")
        scope_key = scope.get("key", "all")
        slug = _scope_slug(str(scope_key))
        return ctx.cache_root / "llm_group_progress" / as_of / ctx.db_hash / ctx.mode_key / scope_type / f"{slug}.json"

    def run(self, conn, ctx: AgentContext, artifacts) -> Dict[str, Any]:
        payload = artifacts.get("progress.l2_payload")
        if not payload:
            return {}
        payload_json = canonical_json(payload)
        llm_hash = compute_llm_input_hash(payload)
        cache_path = self._cache_path(ctx, payload)
        cached = load_cache(cache_path)
        if cached:
            meta = cached.get("llm_meta", {})
            if meta.get("llm_input_hash") == llm_hash and meta.get("prompt_version") == self.version:
                return {payload.get("scope", {}).get("key"): {**cached, "used_cache": True}}

        fb = fallback_output(GroupProgressInputV1.model_validate(payload)).model_dump()
        fb["llm_meta"]["llm_input_hash"] = llm_hash
        fb["llm_meta"]["prompt_version"] = self.version
        save_cache(cache_path, fb)
        return {payload.get("scope", {}).get("key"): fb}
