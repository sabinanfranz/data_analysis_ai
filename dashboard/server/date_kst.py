"""
KST date/time normalization SSOT.

정책:
- 이 모듈만 날짜→KST date-only 변환을 담당한다.
- 이 모듈 밖에서는 split("T"), [:10], [:7] 같은 문자열 슬라이싱으로 날짜를 만들지 말 것.
- 최종 목표는 백엔드가 KST 기준 YYYY-MM-DD를 확정해 내려주고, 프런트는 그 값을 그대로 표시하는 것이다.
(PR1에서는 도입만 하고 기존 코드에 적용하지 않는다.)
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone, timedelta
from typing import Optional, Any

KST_TZ = timezone(timedelta(hours=9))


def _parse_iso_datetime(text: str) -> Optional[datetime]:
    """Safely parse ISO datetime strings (handles trailing Z)."""
    candidate = text
    if " " in candidate and "T" not in candidate:
        # tolerate single space separator
        parts = candidate.split(" ")
        if len(parts) == 2:
            candidate = "T".join(parts)
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _parse_date_flexible(text: str) -> Optional[date]:
    """Parse date-only strings with -, /, . or none."""
    m = re.match(r"^(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})$", text)
    if not m:
        return None
    y, mth, d = map(int, m.groups())
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def kst_date_only(raw: Any) -> str:
    """
    Normalize to KST date-only (YYYY-MM-DD). Return "" on failure/empty.
    Supported inputs: None, "", date, datetime, and strings:
      - YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / YYYYMMDD
      - ISO datetime with Z or offset (e.g., 2025-12-31T15:00:00.000Z)
    """
    if raw is None:
        return ""
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo:
            dt = dt.astimezone(KST_TZ)
        return dt.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()

    text = str(raw).strip()
    if not text:
        return ""

    # ISO datetime handling
    if "T" in text or re.search(r"[+-]\d{2}:?\d{2}$", text) or text.endswith("Z"):
        dt = _parse_iso_datetime(text)
        if dt:
            if dt.tzinfo:
                dt = dt.astimezone(KST_TZ)
            return dt.date().isoformat()

    # Date-only patterns
    d = _parse_date_flexible(text)
    if d:
        return d.isoformat()

    return ""


def kst_year(raw: Any) -> Optional[str]:
    val = kst_date_only(raw)
    return val[:4] if val else None


def kst_ym(raw: Any) -> Optional[str]:
    val = kst_date_only(raw)
    return val[:7] if val else None


def kst_yymm(raw: Any) -> Optional[str]:
    ym = kst_ym(raw)
    if not ym:
        return None
    year, month = ym.split("-")
    return f"{year[2:]}{month}"
