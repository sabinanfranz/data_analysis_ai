from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def _clamp(val: any, lo: float, hi: float, default: float) -> float:
    try:
        num = float(val)
    except Exception:
        return default
    return max(lo, min(hi, num))


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str
    timeout: float
    max_tokens: int
    temperature: float
    api_key: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = (os.getenv("LLM_PROVIDER") or "").lower()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        base_url = os.getenv("LLM_BASE_URL", "")
        timeout = _clamp(os.getenv("LLM_TIMEOUT", 15), 5, 60, 15)
        max_tokens = int(_clamp(os.getenv("LLM_MAX_TOKENS", 512), 128, 2048, 512))
        temperature = _clamp(os.getenv("LLM_TEMPERATURE", 0.2), 0.0, 1.0, 0.2)
        api_key = os.getenv("OPENAI_API_KEY", "")
        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=api_key,
        )

    def is_enabled(self) -> bool:
        return self.provider == "openai" and bool(self.api_key)


@dataclass
class AgentContext:
    report_id: str
    mode_key: str
    as_of_date: date
    db_hash: str
    snapshot_db_path: Path
    cache_root: Path
    llm: LLMConfig
