from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def norm_str(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = unicodedata.normalize("NFC", s)
    return s


def _round6(x: float) -> float:
    d = Decimal(str(x)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return float(d)


def canonicalize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return _round6(obj)
    if isinstance(obj, str):
        return norm_str(obj)
    if isinstance(obj, list):
        return [canonicalize(v) for v in obj]
    if isinstance(obj, dict):
        items = []
        for k in sorted(obj.keys()):
            kk = norm_str(k) if isinstance(k, str) else str(k)
            items.append((kk, canonicalize(obj[k])))
        return {k: v for k, v in items}
    return norm_str(str(obj))


def canonical_json(payload: dict) -> str:
    canon = canonicalize(payload)
    return json.dumps(canon, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def compute_llm_input_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def slugify(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", text)
    return slug[:200] if slug else "_"


def format_eok(val: float) -> str:
    try:
        num = float(val)
    except Exception:
        return "0.0"
    return f"{num / 1e8:.1f}"

