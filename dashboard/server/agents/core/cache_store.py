from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict


def load(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
    tmp.replace(path)


def build_cache_key(*, llm_input_hash: str, prompt_hash: str, model: str, variant: str | None = None, extra: str | None = None) -> str:
    """
    Build cache key that guarantees prompt_hash inclusion (prompt change => cache miss).
    """
    parts = [llm_input_hash, prompt_hash, model]
    if variant:
        parts.append(variant)
    if extra:
        parts.append(extra)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
