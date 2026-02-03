import calendar
import itertools
import json
import logging
import os
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import statepath_engine as sp
from .counterparty_targets_2026 import load_counterparty_targets_2026
from . import date_kst

DB_PATH_ENV = os.getenv("DB_PATH", "salesmap_latest.db")
print(f"[db] Using DB_PATH={DB_PATH_ENV}")
DB_PATH = Path(DB_PATH_ENV)
DATE_KST_MODE = os.getenv("DATE_KST_MODE", "legacy").lower()
if DATE_KST_MODE not in {"legacy", "shadow", "strict"}:
    logging.warning("Invalid DATE_KST_MODE=%s. Falling back to legacy.", DATE_KST_MODE)
    DATE_KST_MODE = "legacy"
try:
    DATE_KST_SHADOW_MAX_EXAMPLES = int(os.getenv("DATE_KST_SHADOW_MAX_EXAMPLES", "20"))
except Exception:
    DATE_KST_SHADOW_MAX_EXAMPLES = 20


def _date_kst_mode() -> str:
    return DATE_KST_MODE


def _is_strict_mode() -> bool:
    return _date_kst_mode() == "strict"


def _is_shadow_mode() -> bool:
    return _date_kst_mode() == "shadow"


def _effective_date_mode(mode: Optional[str] = None) -> str:
    m = (mode or _date_kst_mode() or "legacy").lower()
    return "strict" if m == "strict" else "legacy"


def sql_year_clause(col_expr: str, year: str, mode: Optional[str] = None) -> Tuple[str, List[Any]]:
    eff = _effective_date_mode(mode)
    if eff == "strict":
        return f"kst_year({col_expr}) = ?", [str(year)]
    return f'{col_expr} LIKE ?', [f"{year}%"]


def sql_years_clause(col_expr: str, years: Sequence[str], mode: Optional[str] = None) -> Tuple[str, List[Any]]:
    eff = _effective_date_mode(mode)
    years = list(years)
    if eff == "strict":
        placeholders = ",".join(["?"] * len(years))
        return f"kst_year({col_expr}) IN ({placeholders})", [str(y) for y in years]
    clauses = []
    params: List[Any] = []
    for y in years:
        clauses.append(f"{col_expr} LIKE ?")
        params.append(f"{y}%")
    return "(" + " OR ".join(clauses) + ")", params


def sql_year_expr(col_expr: str, mode: Optional[str] = None) -> str:
    eff = _effective_date_mode(mode)
    if eff == "strict":
        return f"kst_year({col_expr})"
    return f"SUBSTR({col_expr}, 1, 4)"


def sql_ym_clause(col_expr: str, ym: str, mode: Optional[str] = None) -> Tuple[str, List[Any]]:
    eff = _effective_date_mode(mode)
    if eff == "strict":
        return f"kst_ym({col_expr}) = ?", [ym]
    return f"{col_expr} LIKE ?", [f"{ym}%"]


class ShadowDiffCollector:
    """
    Collects legacy vs strict date normalization diffs when DATE_KST_MODE=shadow.
    Only keeps up to max_examples to avoid log spam.
    """

    def __init__(self, enabled: bool, max_examples: int = DATE_KST_SHADOW_MAX_EXAMPLES):
        self.enabled = enabled
        self.max_examples = max_examples
        self.diff_count = 0
        self.examples: List[Dict[str, Any]] = []

    def _should_check(self, raw: Any) -> bool:
        if raw is None:
            return False
        text = str(raw)
        if "T" not in text:
            return False
        return any(tok in text for tok in ("Z", "+", "-"))

    def add(
        self,
        field: str,
        raw: Any,
        legacy: Any,
        strict: Any,
        deal_id: Any | None = None,
        extra: Dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        if not self._should_check(raw):
            return
        if legacy == strict:
            return
        self.diff_count += 1
        if len(self.examples) >= self.max_examples:
            return
        example = {"field": field, "raw": raw, "legacy": legacy, "strict": strict}
        if deal_id is not None:
            example["dealId"] = deal_id
        if extra:
            example.update(extra)
        self.examples.append(example)

    def emit(self, logger: logging.Logger, context: Dict[str, Any]) -> None:
        if not self.enabled or self.diff_count == 0:
            return
        payload = {
            "tag": "DATE_KST_SHADOW_DIFF",
            **context,
            "diff_count": self.diff_count,
            "examples": self.examples,
        }
        logger.warning("DATE_KST_SHADOW_DIFF %s", payload)


_OWNER_LOOKUP_CACHE: Dict[Path, Dict[str, str]] = {}
_TABLE_COLUMNS_CACHE: Dict[Tuple[Path, str], Tuple[Optional[float], Set[str]]] = {}
YEARS_FOR_WON = {"2023", "2024", "2025"}
ONLINE_COURSE_FORMATS = {"구독제(온라인)", "선택구매(온라인)", "포팅"}
ONLINE_PNL_FORMATS = {
    "구독제(온라인)",
    "구독제 (온라인)",
    "선택구매(온라인)",
    "선택구매 (온라인)",
    "포팅",
}
SIZE_GROUPS = ["대기업", "중견기업", "중소기업", "공공기관", "대학교", "기타/미입력"]
INQ_ALL = "__ALL__"
PUBLIC_KEYWORDS = ["공단", "공사", "진흥원", "재단", "협회", "청", "시청", "도청", "구청", "교육청", "원"]
ACCOUNTING_AUDIT_START_KEY = "2025-01"
ACCOUNTING_DATA_ENV = "ACCOUNTING_DATA_PATH"
_KST_TZ = timezone(timedelta(hours=9))
_COUNTERPARTY_DRI_CACHE: Dict[Tuple[Path, float, str, int, str], Dict[str, Any]] = {}
_COUNTERPARTY_DRI_SUMMARY_CACHE: Dict[Tuple[Path, float, str, str], Dict[str, Any]] = {}
_COUNTERPARTY_TARGET_WARNED: Set[Tuple[float, str]] = set()
_RANK_2025_SUMMARY_CACHE: Dict[Tuple[Path, float, str, Tuple[int, ...]], Dict[str, Any]] = {}
_PERF_MONTHLY_DATA_CACHE: Dict[Tuple[Path, float], Dict[str, Any]] = {}
_PERF_MONTHLY_SUMMARY_CACHE: Dict[Tuple[Path, float, str, str], Dict[str, Any]] = {}
_PERF_MONTHLY_INQUIRIES_CACHE: Dict[Tuple[Path, float], Dict[str, Any]] = {}
_PERF_MONTHLY_INQUIRIES_SUMMARY_CACHE: Dict[Tuple[Path, float, str, str, str], Dict[str, Any]] = {}
# 2026 체결률(근황) 전용 캐시
CLOSE_RATE_ONLINE_COURSE_FORMATS = ["구독제(온라인)", "선택구매(온라인)", "포팅"]
CLOSE_RATE_OFFLINE_FORMATS = {"출강", "복합(출강+온라인)", "교육체계 수립", "비대면 실시간"}
CLOSE_RATE_COURSE_GROUPS = ["구독제(온라인)", "선택구매(온라인)", "포팅", "오프라인"]
CLOSE_RATE_METRICS = ["total", "confirmed", "high", "low", "lost", "close_rate"]
_PERF_MONTHLY_CLOSE_RATE_CACHE: Dict[Tuple[Path, float], Dict[str, Any]] = {}
_PERF_MONTHLY_CLOSE_RATE_SUMMARY_CACHE: Dict[Tuple[Path, float, str, str, str, str], Dict[str, Any]] = {}
_PL_PROGRESS_PAYLOAD_CACHE: Dict[Tuple[Path, float, int], Dict[str, Any]] = {}
_PL_PROGRESS_SUMMARY_CACHE: Dict[Tuple[Path, float, int], Dict[str, Any]] = {}
_QC_MONTHLY_REVENUE_CACHE: Dict[Tuple[Path, float, str, int, int, Optional[str], Optional[float]], Dict[str, Any]] = {}
_ACCOUNTING_COURSE_ID_CACHE: Dict[Tuple[Path, Optional[float]], Set[str]] = {}

INQUIRY_SIZE_GROUPS = ["대기업", "중견기업", "중소기업", "공공기관", "대학교", "기타", "미기재"]
INQUIRY_COURSE_FORMATS = [
    "구독제(온라인)",
    "선택구매(온라인)",
    "포팅",
    "출강",
    "복합(출강+온라인)",
    "교육체계 수립",
    "스킬컨설팅",
    "스킬진단인증",
    "컨텐츠 개발제작",
    "비대면 실시간",
    "바이트디그리",
    "기타",
    "미기재",
]
INQUIRY_CATEGORY_GROUPS = ["온라인", "생성형AI", "DT", "직무별교육", "스킬", "기타", "미기재"]

PL_2026_TARGET_DEFAULT: Dict[str, Dict[str, float]] = {
    "2601": {"online": 3.7, "offline": 2.1},
    "2602": {"online": 4.0, "offline": 2.1},
    "2603": {"online": 4.3, "offline": 8.6},
    "2604": {"online": 4.6, "offline": 9.1},
    "2605": {"online": 4.9, "offline": 12.4},
    "2606": {"online": 5.3, "offline": 15.1},
    "2607": {"online": 5.5, "offline": 18.0},
    "2608": {"online": 5.5, "offline": 21.6},
    "2609": {"online": 5.5, "offline": 18.0},
    "2610": {"online": 5.6, "offline": 14.7},
    "2611": {"online": 5.6, "offline": 14.6},
    "2612": {"online": 5.6, "offline": 13.6},
}

# Full target table hardcoded from resources/2026 PnL target.txt (T values only)
PL_2026_TARGET_FULL: Dict[str, Dict[str, Dict[str, float]]] = {
    "REV_TOTAL": {
        "2026": {"T": 210.0},
        "2601": {"T": 5.8},
        "2602": {"T": 6.1},
        "2603": {"T": 12.9},
        "2604": {"T": 13.7},
        "2605": {"T": 17.3},
        "2606": {"T": 20.4},
        "2607": {"T": 23.5},
        "2608": {"T": 27.1},
        "2609": {"T": 23.5},
        "2610": {"T": 20.3},
        "2611": {"T": 20.2},
        "2612": {"T": 19.2},
    },
    "REV_ONLINE": {
        "2026": {"T": 60.1},
        "2601": {"T": 3.7},
        "2602": {"T": 4.0},
        "2603": {"T": 4.3},
        "2604": {"T": 4.6},
        "2605": {"T": 4.9},
        "2606": {"T": 5.3},
        "2607": {"T": 5.5},
        "2608": {"T": 5.5},
        "2609": {"T": 5.5},
        "2610": {"T": 5.6},
        "2611": {"T": 5.6},
        "2612": {"T": 5.6},
    },
    "REV_OFFLINE": {
        "2026": {"T": 149.9},
        "2601": {"T": 2.1},
        "2602": {"T": 2.1},
        "2603": {"T": 8.6},
        "2604": {"T": 9.1},
        "2605": {"T": 12.4},
        "2606": {"T": 15.1},
        "2607": {"T": 18.0},
        "2608": {"T": 21.6},
        "2609": {"T": 18.0},
        "2610": {"T": 14.7},
        "2611": {"T": 14.6},
        "2612": {"T": 13.6},
    },
    "COST_CONTRIB_TOTAL": {
        "2026": {"T": 76.4},
        "2601": {"T": 1.5},
        "2602": {"T": 1.5},
        "2603": {"T": 4.5},
        "2604": {"T": 4.8},
        "2605": {"T": 6.3},
        "2606": {"T": 7.6},
        "2607": {"T": 8.9},
        "2608": {"T": 10.5},
        "2609": {"T": 8.9},
        "2610": {"T": 7.5},
        "2611": {"T": 7.4},
        "2612": {"T": 7.0},
    },
    "COST_CONTRIB_ONLINE": {
        "2026": {"T": 8.8},
        "2601": {"T": 0.6},
        "2602": {"T": 0.6},
        "2603": {"T": 0.6},
        "2604": {"T": 0.7},
        "2605": {"T": 0.7},
        "2606": {"T": 0.8},
        "2607": {"T": 0.8},
        "2608": {"T": 0.8},
        "2609": {"T": 0.8},
        "2610": {"T": 0.8},
        "2611": {"T": 0.8},
        "2612": {"T": 0.8},
    },
    "COST_CONTRIB_OFFLINE": {
        "2026": {"T": 67.4},
        "2601": {"T": 0.9},
        "2602": {"T": 0.9},
        "2603": {"T": 3.9},
        "2604": {"T": 4.1},
        "2605": {"T": 5.6},
        "2606": {"T": 6.8},
        "2607": {"T": 8.1},
        "2608": {"T": 9.7},
        "2609": {"T": 8.1},
        "2610": {"T": 6.6},
        "2611": {"T": 6.6},
        "2612": {"T": 6.1},
    },
    "PROFIT_CONTRIB_TOTAL": {
        "2026": {"T": 133.6},
        "2601": {"T": 4.3},
        "2602": {"T": 4.6},
        "2603": {"T": 8.4},
        "2604": {"T": 8.9},
        "2605": {"T": 11.0},
        "2606": {"T": 12.8},
        "2607": {"T": 14.6},
        "2608": {"T": 16.6},
        "2609": {"T": 14.6},
        "2610": {"T": 12.8},
        "2611": {"T": 12.8},
        "2612": {"T": 12.2},
    },
    "PROFIT_CONTRIB_ONLINE": {
        "2026": {"T": 51.3},
        "2601": {"T": 3.1},
        "2602": {"T": 3.4},
        "2603": {"T": 3.7},
        "2604": {"T": 3.9},
        "2605": {"T": 4.2},
        "2606": {"T": 4.5},
        "2607": {"T": 4.7},
        "2608": {"T": 4.7},
        "2609": {"T": 4.7},
        "2610": {"T": 4.8},
        "2611": {"T": 4.8},
        "2612": {"T": 4.8},
    },
    "PROFIT_CONTRIB_OFFLINE": {
        "2026": {"T": 82.5},
        "2601": {"T": 1.2},
        "2602": {"T": 1.2},
        "2603": {"T": 4.7},
        "2604": {"T": 5.0},
        "2605": {"T": 6.8},
        "2606": {"T": 8.3},
        "2607": {"T": 9.9},
        "2608": {"T": 11.9},
        "2609": {"T": 9.9},
        "2610": {"T": 8.1},
        "2611": {"T": 8.0},
        "2612": {"T": 7.5},
    },
    "COST_FIXED_TOTAL": {
        "2026": {"T": 112.7},
        "2601": {"T": 8.8},
        "2602": {"T": 8.8},
        "2603": {"T": 9.3},
        "2604": {"T": 9.2},
        "2605": {"T": 9.3},
        "2606": {"T": 9.7},
        "2607": {"T": 9.6},
        "2608": {"T": 9.8},
        "2609": {"T": 9.8},
        "2610": {"T": 9.4},
        "2611": {"T": 9.4},
        "2612": {"T": 9.6},
    },
    "COST_FIXED_PROD": {
        "2026": {"T": 2.4},
        "2601": {"T": 0.2},
        "2602": {"T": 0.2},
        "2603": {"T": 0.2},
        "2604": {"T": 0.2},
        "2605": {"T": 0.2},
        "2606": {"T": 0.2},
        "2607": {"T": 0.2},
        "2608": {"T": 0.2},
        "2609": {"T": 0.2},
        "2610": {"T": 0.2},
        "2611": {"T": 0.2},
        "2612": {"T": 0.2},
    },
    "COST_FIXED_MKT": {
        "2026": {"T": 3.6},
        "2601": {"T": 0.3},
        "2602": {"T": 0.3},
        "2603": {"T": 0.3},
        "2604": {"T": 0.3},
        "2605": {"T": 0.3},
        "2606": {"T": 0.3},
        "2607": {"T": 0.3},
        "2608": {"T": 0.3},
        "2609": {"T": 0.3},
        "2610": {"T": 0.3},
        "2611": {"T": 0.3},
        "2612": {"T": 0.3},
    },
    "COST_FIXED_LABOR": {
        "2026": {"T": 76.0},
        "2601": {"T": 6.3},
        "2602": {"T": 6.3},
        "2603": {"T": 6.4},
        "2604": {"T": 6.3},
        "2605": {"T": 6.3},
        "2606": {"T": 6.4},
        "2607": {"T": 6.3},
        "2608": {"T": 6.3},
        "2609": {"T": 6.4},
        "2610": {"T": 6.3},
        "2611": {"T": 6.3},
        "2612": {"T": 6.4},
    },
    "COST_FIXED_RENT": {
        "2026": {"T": 11.2},
        "2601": {"T": 0.9},
        "2602": {"T": 0.9},
        "2603": {"T": 1.0},
        "2604": {"T": 0.9},
        "2605": {"T": 0.9},
        "2606": {"T": 1.0},
        "2607": {"T": 0.9},
        "2608": {"T": 0.9},
        "2609": {"T": 1.0},
        "2610": {"T": 0.9},
        "2611": {"T": 0.9},
        "2612": {"T": 1.0},
    },
    "COST_FIXED_OTHER": {
        "2026": {"T": 19.5},
        "2601": {"T": 1.1},
        "2602": {"T": 1.1},
        "2603": {"T": 1.4},
        "2604": {"T": 1.5},
        "2605": {"T": 1.6},
        "2606": {"T": 1.8},
        "2607": {"T": 1.9},
        "2608": {"T": 2.1},
        "2609": {"T": 1.9},
        "2610": {"T": 1.7},
        "2611": {"T": 1.7},
        "2612": {"T": 1.7},
    },
    "OP": {
        "2026": {"T": 20.9},
        "2601": {"T": -4.5},
        "2602": {"T": -4.2},
        "2603": {"T": -0.9},
        "2604": {"T": -0.3},
        "2605": {"T": 1.7},
        "2606": {"T": 3.1},
        "2607": {"T": 5.0},
        "2608": {"T": 6.8},
        "2609": {"T": 4.8},
        "2610": {"T": 3.4},
        "2611": {"T": 3.4},
        "2612": {"T": 2.6},
    },
}



def _date_only_legacy(val: Any) -> str:
    """
    Normalize a datetime-ish value to YYYY-MM-DD (KST). Returns "" when empty/None.
    Legacy implementation (string split).
    """
    if val is None:
        return ""
    text_raw = str(val).strip()
    if not text_raw:
        return ""

    # Try ISO8601 with timezone first to avoid off-by-one when source is UTC/Z.
    if "T" in text_raw:
        iso_text = text_raw
        if iso_text.endswith("Z"):
            iso_text = iso_text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(iso_text)
            if dt.tzinfo is not None:
                return dt.astimezone(_KST_TZ).date().isoformat()
            return dt.date().isoformat()
        except Exception:
            pass

    text = text_raw
    if " " in text:
        text = text.split(" ")[0]
    if "T" in text:
        text = text.split("T")[0]
    # Fallback: allow dots/compact digits via date_kst parser
    kst = date_kst.kst_date_only(text)
    if kst:
        return kst
    return text


def _date_only(val: Any) -> str:
    if _is_strict_mode():
        return date_kst.kst_date_only(val)
    return _date_only_legacy(val)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.create_function("kst_date", 1, date_kst.kst_date_only)
        conn.create_function("kst_year", 1, date_kst.kst_year)
        conn.create_function("kst_ym", 1, date_kst.kst_ym)
        conn.create_function("kst_yymm", 1, date_kst.kst_yymm)
    except Exception:
        logging.exception("Failed to register KST date UDFs")
    return conn


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    """
    Check if the given table has a column. Uses PRAGMA table_info for presence detection.
    """
    db_path: Optional[Path] = None
    mtime: Optional[float] = None
    try:
        db_info = conn.execute("PRAGMA database_list").fetchone()
        if db_info and db_info["file"]:
            db_path = Path(db_info["file"])
            try:
                mtime = db_path.stat().st_mtime
            except Exception:
                mtime = None
    except Exception:
        db_path = None

    cache_key = (db_path, table_name) if db_path else None
    if cache_key and cache_key in _TABLE_COLUMNS_CACHE:
        cached_mtime, cached_cols = _TABLE_COLUMNS_CACHE[cache_key]
        if cached_mtime is None or cached_mtime == mtime:
            return column_name in cached_cols

    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    cols = set()
    for row in rows:
        try:
            cols.add(row["name"])
        except Exception:
            try:
                cols.add(row[1])
            except Exception:
                continue

    if cache_key:
        _TABLE_COLUMNS_CACHE[cache_key] = (mtime, cols)
    return column_name in cols


def _normalize_course_id(val: Any) -> str:
    text = (val or "").strip()
    if not text or text == "-":
        return ""
    # drop commas/spaces and keep digits only
    text = text.replace(",", "").replace(" ", "")
    text = re.sub(r"[^0-9]", "", text)
    return text


def _load_accounting_course_ids(path: Path) -> Tuple[Set[str], Optional[float], str]:
    """
    Load accounting course IDs from TSV file (column '코스ID' or '코스 ID').
    Returns (set, mtime, status).
    status: "OK" | "MISSING" | "INVALID_HEADER"
    """
    if not path.exists():
        return set(), None, "MISSING"

    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = None

    cache_key = (path, mtime)
    if cache_key in _ACCOUNTING_COURSE_ID_CACHE:
        return _ACCOUNTING_COURSE_ID_CACHE[cache_key], mtime, "OK"

    course_ids: Set[str] = set()
    status = "OK"
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if not lines:
            _ACCOUNTING_COURSE_ID_CACHE[cache_key] = course_ids
            return course_ids, mtime, status
        header = lines[0].split("\t")
        header_norm = [h.replace(" ", "") for h in header]
        try:
            col_idx = header_norm.index("코스ID")
        except ValueError:
            status = "INVALID_HEADER"
            _ACCOUNTING_COURSE_ID_CACHE[cache_key] = course_ids
            return course_ids, mtime, status
        for line in lines[1:]:
            parts = line.split("\t")
            if col_idx >= len(parts):
                continue
            raw = parts[col_idx]
            norm = _normalize_course_id(raw)
            if norm:
                course_ids.add(norm)
    except Exception:
        status = "INVALID_HEADER"

    _ACCOUNTING_COURSE_ID_CACHE[cache_key] = course_ids
    return course_ids, mtime, status


def _pick_column(conn: sqlite3.Connection, table: str, candidates: Sequence[str]) -> Optional[str]:
    """
    Return the first existing column name among candidates for the given table.
    """
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    cols = {row["name"] for row in rows}
    for cand in candidates:
        if cand in cols:
            return cand
    return None


def _q(col: str) -> str:
    return f'"{col}"'


def _q_or_null(col: Optional[str]) -> str:
    return _q(col) if col else "NULL"


def _dq(col: Optional[str]) -> str:
    """Deal table column reference with quoting."""
    return f"d.{_q(col)}" if col else "NULL"


def _fetch_all(conn: sqlite3.Connection, query: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
    cur = conn.execute(query, params)
    return cur.fetchall()


def _rows_to_dicts(rows: Sequence[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def _safe_json_load(value: Any) -> Any:
    """
    Parse JSON fields stored as TEXT. If parsing fails, return the original value.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        import json

        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _parse_owner_names(raw: Any) -> List[str]:
    names: List[str] = []
    data = _safe_json_load(raw)
    if isinstance(data, dict):
        name = data.get("name") or data.get("id")
        if name:
            names.append(str(name).strip())
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                name = item.get("name") or item.get("id")
                if name:
                    names.append(str(name).strip())
            elif isinstance(item, str) and item.strip():
                names.append(item.strip())
    elif isinstance(data, str) and data.strip():
        names.append(data.strip())
    seen: Set[str] = set()
    deduped: List[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def _parse_owner_names_normalized(raw: Any) -> List[str]:
    return [normalize_owner_name(name) for name in _parse_owner_names(raw) if name]


def _dealcheck_members(team_key: str) -> Set[str]:
    if team_key in _DEALCHECK_MEMBER_CACHE:
        return _DEALCHECK_MEMBER_CACHE[team_key]
    cfg = TEAM_CONFIG.get(team_key)
    if not cfg:
        raise ValueError(f"Unknown teamKey: {team_key}")
    team_name = cfg.get("part_team_key")
    team = PART_STRUCTURE.get(team_name, {})
    names: List[str] = []
    for part_names in team.values():
        names.extend(part_names or [])
    members = {normalize_owner_name(n) for n in names if n}
    _DEALCHECK_MEMBER_CACHE[team_key] = members
    return members


def _dealcheck_team_members(team_key: Optional[str]) -> Optional[Set[str]]:
    if team_key is None:
        return None
    if team_key not in {"edu1", "edu2"}:
        raise ValueError(f"Unknown teamKey: {team_key}")
    return _dealcheck_members(team_key)


def _parse_owner_names_preferred(deal_owner_json: Any, people_owner_json: Any) -> List[str]:
    """
    Prefer deal.owner_json if present, else fallback to people.owner_json. Returns deduped string list.
    """
    owners = _parse_owner_names(deal_owner_json)
    if not owners:
        owners = _parse_owner_names(people_owner_json)
    return owners


def _qc_members(team_key: str) -> Set[str]:
    """
    QC 전용 팀 구성원 반환. team_key가 'all'이면 모든 팀 합집합.
    """
    if team_key == "all":
        members: Set[str] = set()
        for tk in ("edu1", "edu2", "public"):
            members.update(_qc_members(tk))
        return members
    if team_key == "public":
        # 공공교육팀은 part 구조가 단일이므로 바로 normalize
        raw = PART_STRUCTURE.get("공공교육팀", {})
        names: List[str] = []
        for arr in raw.values():
            names.extend(arr or [])
        return {normalize_owner_name(n) for n in names if n}
    return _dealcheck_members(team_key)


def _status_norm(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "other"
    if "sql" in text:
        return "sql"
    if "convert" in text:
        return "convert"
    if "won" in text or "확정" in text:
        return "won"
    if "lost" in text or "lose" in text or "패배" in text:
        return "lost"
    return "other"


def _prob_norm(raw: Any, status_normed: str) -> str:
    tokens = _prob_tokens(raw)
    if status_normed == "lost":
        return "LOST"
    if "확정" in tokens:
        return "확정"
    if "높음" in tokens:
        return "높음"
    if not tokens:
        return "미기재"
    return next(iter(tokens))


def _missing_str(val: Any) -> bool:
    if val is None:
        return True
    text = str(val).strip().lower()
    return text == "" or text in {"nan", "null", "nat", "<na>", "none"}


def _missing_num(val: Any) -> bool:
    return val is None


_re_month = re.compile(r"(?:1[0-2]|[1-9])월")


def _prob_is_high(val: Any) -> bool:
    """
    Return True if probability includes '확정' or '높음'.
    Supports string, list, or JSON string.
    """
    if val is None:
        return False
    loaded = val
    if isinstance(val, str):
        loaded = _safe_json_load(val)
    if isinstance(loaded, list):
        return any(_prob_is_high(item) for item in loaded)
    text = str(loaded).strip()
    return text in {"확정", "높음"}


def _prob_tokens(val: Any) -> Set[str]:
    """
    Normalize probability field into a set of string tokens.
    Supports string, list, dict values, or JSON string of those shapes.
    """
    if val is None:
        return set()
    loaded: Any = val
    if isinstance(val, str):
        loaded = _safe_json_load(val)
    if isinstance(loaded, list):
        tokens: Set[str] = set()
        for item in loaded:
            tokens.update(_prob_tokens(item))
        return tokens
    if isinstance(loaded, dict):
        tokens = set()
        for v in loaded.values():
            tokens.update(_prob_tokens(v))
        return tokens
    return {str(loaded).strip()} if str(loaded).strip() else set()


def _prob_is_confirmed(val: Any) -> bool:
    tokens = _prob_tokens(val)
    return "확정" in tokens


def _prob_is_high_only(val: Any) -> bool:
    tokens = _prob_tokens(val)
    return "높음" in tokens and "확정" not in tokens


def _prob_equals(val: Any, target: str) -> bool:
    tokens = _prob_tokens(val)
    return target in tokens


def _parse_date(val: Any) -> Optional[date]:
    """
    Parse a date or datetime-ish value.
    - If ISO8601 with timezone (Z or +HH:MM), convert to KST and take the date to avoid day rollover.
    - Otherwise, normalize to YYYY-MM-DD and parse as naive date.
    """
    if val is None:
        return None
    text_raw = str(val).strip()
    if not text_raw:
        return None

    # First, delegate to the canonical KST parser to support dots/compact digits/UTC offsets.
    kst = date_kst.kst_date_only(text_raw)
    if kst:
        try:
            return datetime.strptime(kst, "%Y-%m-%d").date()
        except Exception:
            return None

    # Fallback: legacy ISO parsing
    if "T" in text_raw:
        iso_text = text_raw
        if iso_text.endswith("Z"):
            iso_text = iso_text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(iso_text)
            if dt.tzinfo is not None:
                return dt.astimezone(_KST_TZ).date()
        except Exception:
            pass

    text = _date_only(text_raw)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def _today_kst_date() -> date:
    return datetime.now(timezone.utc).astimezone(_KST_TZ).date()


def _sub_business_days(d: date, n: int) -> date:
    """Return the date that is n business days (Mon-Fri) before d."""
    if n <= 0:
        return d
    cur = d
    counted = 0
    while counted < n:
        cur = cur - timedelta(days=1)
        if cur.weekday() < 5:  # 0=Mon, 6=Sun
            counted += 1
    return cur


def _within_last_n_business_days(event_date: Optional[date], today: date, n: int) -> bool:
    if event_date is None:
        return False
    if event_date > today:
        return False
    window_start = _sub_business_days(today, n)
    return window_start <= event_date <= today


def _parse_kst_date_best_effort(raw: Any) -> Optional[date]:
    """Parse a date string to date (KST-adjusted when tz info exists)."""
    if raw is None:
        return None
    text_raw = str(raw).strip()
    if not text_raw:
        return None

    kst = date_kst.kst_date_only(text_raw)
    if kst:
        try:
            return datetime.strptime(kst, "%Y-%m-%d").date()
        except Exception:
            pass

    text = text_raw
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    text = text.replace(".", "-").replace("/", "-")
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def _date_str(parsed: Optional[date], raw: Any) -> str:
    """
    Return YYYY-MM-DD string preferring parsed date (KST adjusted).
    """
    if parsed:
        return parsed.isoformat()
    return _date_only(raw)


def _normalize_course_format(val: Any) -> str:
    text = (val or "").strip()
    # Remove spaces before parentheses to match 온라인 포맷 변형
    text = re.sub(r"\s+\(", "(", text)
    return text


_INQUIRY_CATEGORY_MAP: Dict[str, Set[str]] = {
    "온라인": {"법정의무교육", "온라인", "자유입과(온라인)"},
    "생성형AI": {"생성형AI"},
    "DT": {"데이터분석/CDS", "DX Essential", "빅데이터/AI"},
    "직무별교육": {
        "재무회계",
        "PM/PO",
        "마케팅",
        "개발/CD",
        "OA/업무자동화",
        "비즈니스/문제해결력",
        "HR",
        "디자인",
        "UI/UX",
    },
    "스킬": {"Skill-based HRD", "Skill Match"},
}


def _normalize_inquiry_size(org_name: str | None, size_raw: str | None) -> str:
    """
    Inquiry 전용 규모 정규화: 실제 값(pass-through) 우선, 7개 버킷 고정.
    """
    s = (size_raw or "").strip()
    if not s:
        return "미기재"

    if s in {"대기업", "중견기업", "중소기업", "공공기관", "대학교", "기타"}:
        return s

    if s == "기타/미입력":
        return "기타"

    return "기타"


def _normalize_inquiry_course_format(val: Any) -> str:
    text = _normalize_course_format(val)
    if not text:
        return "미기재"
    if text in INQUIRY_COURSE_FORMATS:
        return text
    return "기타"


def _map_inquiry_category_group(val: Any) -> str:
    text = (val or "").strip()
    if not text:
        return "미기재"
    for grp, keywords in _INQUIRY_CATEGORY_MAP.items():
        if text in keywords:
            return grp
    return "기타"


def _is_false_like(val: Any) -> bool:
    if val is False:
        return True
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return float(val) == 0.0
    text = str(val).strip().lower()
    return text in {"false", "0", "no", "n", "x"}


def _is_online_for_pnl(val: Any) -> bool:
    fmt = _normalize_course_format(val)
    return fmt in ONLINE_PNL_FORMATS


def _month_keys_for_year(year: int) -> List[str]:
    yy = f"{year % 100:02d}"
    return [f"{yy}{m:02d}" for m in range(1, 13)]


def _month_boundaries(year: int) -> Dict[str, Tuple[date, date]]:
    boundaries: Dict[str, Tuple[date, date]] = {}
    for m in range(1, 13):
        month_key = f"{year % 100:02d}{m:02d}"
        last_day = calendar.monthrange(year, m)[1]
        boundaries[month_key] = (date(year, m, 1), date(year, m, last_day))
    return boundaries


def infer_size_group(org_name: str | None, size_raw: str | None) -> str:
    name = (org_name or "").strip()
    size_val = (size_raw or "").strip()
    if "대기업" in size_val:
        return "대기업"
    if "중견" in size_val:
        return "중견기업"
    if "중소" in size_val:
        return "중소기업"
    upper_name = name.upper()
    if any(keyword in name for keyword in ["대학교", "대학"]) or "UNIVERSITY" in upper_name:
        return "대학교"
    for kw in PUBLIC_KEYWORDS:
        if kw in name:
            return "공공기관"
    return "기타/미입력"


def normalize_owner_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return ""
    if re.search(r"[A-Za-z]$", text):
        return text[:-1].strip()
    return text


def is_large_or_mid(size_group: str) -> bool:
    """Return True for 대기업 or 중견기업 (including 변형에 '중견' 포함)."""
    if not size_group:
        return False
    sg = str(size_group).strip()
    return sg in {"대기업", "중견기업"} or ("중견" in sg)


def is_missing_person_meta(upper_org: Any, team_signature: Any, title_signature: Any, edu_area: Any) -> bool:
    return any(_missing_str(val) for val in (upper_org, team_signature, title_signature, edu_area))


def is_month_exception(owner_name_norm: str, deal_name: str) -> bool:
    norm = normalize_owner_name(owner_name_norm)
    if norm not in {"김정은", "이은서"}:
        return False
    return bool(_re_month.search(deal_name or ""))


PART_STRUCTURE = {
    "기업교육 1팀": {
        "1파트": [
            "김솔이",
            "황초롱",
            "김정은",
            "김동찬",
            "정태윤",
            "서정연",
            "오진선",
            "공새봄",
            "김별",  # 팀장 포함
        ],
        "2파트": ["강지선", "정하영", "박범규", "하승민", "이은서", "김세연", "이주연"],
    },
    "기업교육 2팀": {
        "1파트": [
            "권노을",
            "이윤지",
            "이현진",
            "김민선",
            "강연정",
            "방신우",
            "홍제환",
            "정선희",  # 팀장 포함
        ],
        "2파트": ["정다혜", "임재우", "송승희", "손승완", "김윤지", "손지훈", "홍예진"],
        "온라인셀": ["강진우", "강다현", "이수빈"],
    },
    "공공교육팀": {
        "전체": ["이준석", "김미송", "오정민", "조경원", "김다인", "서민정", "김지원", "김진호"],
    },
}

TEAM_CONFIG = {
    "edu1": {
        "label": "교육 1팀 딜체크",
        "part_team_key": "기업교육 1팀",
    },
    "edu2": {
        "label": "교육 2팀 딜체크",
        "part_team_key": "기업교육 2팀",
    },
    "public": {
        "label": "공공교육팀",
        "part_team_key": "공공교육팀",
    },
}

_DEALCHECK_MEMBER_CACHE: Dict[str, Set[str]] = {}
QC_RULES: List[Tuple[str, str]] = [
    ("R1", "상태=won & 계약 체결일 없음"),
    ("R2", "상태=won & 금액 결측"),
    ("R3", "상태=won & 수강시작/종료일 결측"),
    ("R4", "상태=won & 코스 ID 결측"),
    ("R5", "상태=won & 성사 확정 아님"),
    ("R6", "상태=lost & 성사 값 불일치"),
    ("R7", "계약일>수강시작 & 연월 불일치"),
    ("R8", "생성 7일 경과 & 카테고리 결측"),
    ("R9", "생성 7일 경과 & 과정포맷 결측"),
    ("R10", "성사=높음 & 수주 예정일 결측"),
    ("R11", "상태=convert"),
    ("R12", "성사=확정/높음 & 금액/예상액 모두 결측"),
    ("R13", "고객사 담당자 정보 결측"),
    ("R14", "상태=won & 온라인 과정포맷 입과정보 결측"),
    ("R15", "상태=won & 강사 정보 결측"),
    ("R16", "생성형AI(대기업·오프라인) 제안서 미작성/미업로드"),
]
QC_SINCE_DATE = date(2024, 10, 1)
QC_TEAM_LABELS = {"edu1": "기업교육 1팀", "edu2": "기업교육 2팀", "public": "공공교육팀", "all": "전체"}
QC_HIDDEN_RULE_CODES: Set[str] = {"R17"}
QC_EXCLUDE_FROM_TOTAL_ISSUES: Set[str] = {"R17"}


def _clean_form_memo(text: str) -> Optional[Dict[str, str]]:
    """
    Extract a minimal set of fields from form-style memos for LLM use.
    Drops: phone/company_size/industry/channel/consent_*/utm_*
    Keeps everything else (including question-like keys) after merging wrapped lines.
    """
    if not text:
        return None

    # Pre-trim: collapse double newlines and remove smiley ":)"
    normalized_text = text.replace("\r\n", "\n").replace("\n\n", "\n").replace(":)", "")

    # If special disclaimer exists, force empty cleanText
    if "단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청" in normalized_text:
        return ""

    # Only proceed when utm_source or 고객 마케팅 수신 동의가 있을 때
    if "utm_source" not in normalized_text and "고객 마케팅 수신 동의" not in normalized_text:
        return None

    lines_raw = normalized_text.split("\n")
    merged_lines: List[str] = []
    current = ""
    for raw in lines_raw:
        ln = raw.strip()
        if not ln:
            continue
        if ":" in ln:
            if current:
                merged_lines.append(current)
            current = ln
        else:
            # continuation line for previous value
            if current:
                current = f"{current} {ln}"
            else:
                current = ln
    if current:
        merged_lines.append(current)

    drop_key_norms = {
        "고객전화",
        "회사기업규모",
        "회사업종",
        "방문경로",
        "개인정보수집동의",
        "고객마케팅수신동의",
        "SkyHive'sPrivacyPolicy",
        "ATD'sPrivacyNotice",
        "개인정보제3자제공동의",
        "고객utm_source",
        "고객utm_medium",
        "고객utm_campaign",
        "고객utm_content",
    }

    result: Dict[str, str] = {}
    for ln in merged_lines:
        match = re.match(r"^[-•]?\s*([^:]+):\s*(.*)$", ln)
        if not match:
            continue
        raw_key, raw_val = match.group(1).strip(), match.group(2).strip().strip(".")
        if raw_val in ("", "(공백)", "-"):
            continue
        key_norm = raw_key.replace(" ", "")
        if key_norm in drop_key_norms:
            continue
        key = None
        # question detection
        if "궁금" in raw_key or "고민" in raw_key:
            key = "question"
        if not key:
            # keep normalized key as-is (without spaces) to preserve info
            key = key_norm
        if key not in result:
            result[key] = raw_val

    if not result:
        return None

    minimal_set = {"고객이름", "고객이메일", "회사이름", "고객담당업무", "고객직급/직책"}
    if set(result.keys()) == minimal_set:
        return ""

    return result


def _get_owner_lookup(db_path: Path) -> Dict[str, str]:
    """
    Build a best-effort id->name map from 담당자 JSON fields across tables.
    Memo ownerId values will be mapped using this.
    """
    cached = _OWNER_LOOKUP_CACHE.get(db_path)
    if cached is not None:
        return cached

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    lookup: Dict[str, str] = {}
    targets = [
        ("organization", '"담당자"'),
        ("people", '"담당자"'),
        ("deal", '"담당자"'),
    ]
    with _connect(db_path) as conn:
        for table, column in targets:
            rows = _fetch_all(
                conn,
                f"SELECT DISTINCT {column} AS owner FROM {table} "
                f"WHERE {column} IS NOT NULL AND TRIM({column}) <> ''",
            )
            for row in rows:
                data = _safe_json_load(row["owner"])
                if isinstance(data, dict):
                    oid = data.get("id")
                    name = data.get("name")
                    if oid and name and oid not in lookup:
                        lookup[oid] = name

    _OWNER_LOOKUP_CACHE[db_path] = lookup
    return lookup


def list_sizes(db_path: Path = DB_PATH) -> List[str]:
    """
    Return distinct organization sizes ordered alphabetically.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT DISTINCT "기업 규모" AS size FROM organization '
            'WHERE "기업 규모" IS NOT NULL AND TRIM("기업 규모") <> "" '
            "ORDER BY size",
        )
    return [row["size"] for row in rows if row["size"]]


def list_organizations(
    size: str = "전체",
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    eff_mode = _effective_date_mode()
    won_clause, won_params = sql_year_clause(' "계약 체결일"', "2025", eff_mode)

    limit = max(1, min(limit, 500))  # guardrail
    offset = max(0, offset)

    query = (
        'SELECT o.id, COALESCE(o."이름", o.id) AS name, o."기업 규모" AS size, '
        'o."팀" AS team_json, o."담당자" AS owner_json, '
        "COALESCE(w.won2025, 0) AS won2025 "
        "FROM organization o "
        "LEFT JOIN (SELECT organizationId, COUNT(*) AS people_count FROM people WHERE organizationId IS NOT NULL GROUP BY organizationId) pc "
        "  ON pc.organizationId = o.id "
        "LEFT JOIN (SELECT organizationId, COUNT(*) AS deal_count FROM deal WHERE organizationId IS NOT NULL GROUP BY organizationId) dc "
        "  ON dc.organizationId = o.id "
        "LEFT JOIN ("
        '  SELECT organizationId, SUM(CAST("금액" AS REAL)) AS won2025 '
        f"  FROM deal WHERE \"상태\" = 'Won' AND {won_clause} AND organizationId IS NOT NULL "
        "  GROUP BY organizationId"
        ") w ON w.organizationId = o.id "
        "WHERE 1=1 "
    )
    params: List[Any] = []
    params.extend(won_params)

    if size and size != "전체":
        query += 'AND "기업 규모" = ? '
        params.append(size)
    if search:
        query += 'AND ("이름" LIKE ? OR id LIKE ?) '
        like = f"%{search}%"
        params.extend([like, like])

    query += "AND (COALESCE(pc.people_count, 0) > 0 OR COALESCE(dc.deal_count, 0) > 0) "
    query += "ORDER BY won2025 DESC, name LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with _connect(db_path) as conn:
        rows = _fetch_all(conn, query, params)

    orgs: List[Dict[str, Any]] = []
    for row in rows:
        orgs.append(
            {
                "id": row["id"],
                "name": row["name"],
                "size": row["size"],
                "team": _safe_json_load(row["team_json"]) or [],
                "owner": _safe_json_load(row["owner_json"]) or None,
            }
        )
    return orgs


# ----------------------- StatePath Portfolio Helpers -----------------------
def _statepath_rows(db_path: Path) -> List[sqlite3.Row]:
    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  d.organizationId AS orgId, '
            '  COALESCE(o."이름", d.organizationId) AS orgName, '
            '  o."기업 규모" AS sizeRaw, '
            '  p."소속 상위 조직" AS upper_org, '
            '  d."과정포맷" AS course_format, '
            '  d."금액" AS amount, '
            '  d."예상 체결액" AS expected_amount, '
            '  d."계약 체결일" AS contract_date, '
            '  d."생성 날짜" AS created_at '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            "LEFT JOIN people p ON p.id = d.peopleId "
            'WHERE d."상태" = \'Won\' AND d.organizationId IS NOT NULL',
        )
    return rows


def _build_statepath_cells(rows: List[sqlite3.Row]) -> Dict[str, Dict[str, Dict[str, float]]]:
    data: Dict[str, Dict[str, Dict[str, float]]] = {}
    for row in rows:
        year = _parse_year_from_text(row["contract_date"]) or _parse_year_from_text(row["created_at"])
        if year not in ("2024", "2025"):
            continue
        amount = _amount_fallback(row["amount"], row["expected_amount"])
        if amount <= 0:
            continue
        lane = sp.infer_lane(row["upper_org"])
        rail = sp.infer_rail_from_deal({"course_format": row["course_format"]})
        org_id = row["orgId"]
        cell = f"{lane}_{rail}"
        org_entry = data.setdefault(org_id, {y: {"HRD_ONLINE": 0.0, "HRD_OFFLINE": 0.0, "BU_ONLINE": 0.0, "BU_OFFLINE": 0.0} for y in ("2024", "2025")})
        org_entry[year][cell] += amount / 1e8
    return data


def _build_state_from_cells(cells: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    return sp.build_state(cells, "2024"), sp.build_state(cells, "2025")


def _build_path_from_states(state_2024: Dict[str, Any], state_2025: Dict[str, Any]) -> Dict[str, Any]:
    return sp.build_path(state_2024, state_2025)


def _bucket_dir(prev: str, curr: str) -> str:
    if prev == curr:
        return "flat"
    if sp.BUCKET_ORDER.index(curr) > sp.BUCKET_ORDER.index(prev):
        return "up"
    return "down"


def get_statepath_portfolio(
    size_group: str = "전체",
    search: str | None = None,
    filters: Optional[Dict[str, Any]] = None,
    sort: str = "won2025_desc",
    limit: int = 500,
    offset: int = 0,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")
    limit = max(1, min(limit, 2000))
    offset = max(0, offset)
    rows = _statepath_rows(db_path)
    cells_by_org = _build_statepath_cells(rows)
    meta_map: Dict[str, sqlite3.Row] = {}
    for row in rows:
        if row["orgId"] not in meta_map:
            meta_map[row["orgId"]] = row

    items_raw: List[Dict[str, Any]] = []
    for org_id, org_cells in cells_by_org.items():
        row_meta = meta_map.get(org_id)
        if not row_meta:
            continue
        state24, state25 = _build_state_from_cells(org_cells)
        path = _build_path_from_states(state24, state25)
        seed = path["seed"]
        org_name = row_meta["orgName"]
        sg = infer_size_group(org_name, row_meta["sizeRaw"])
        if size_group != "전체" and sg != size_group:
            continue
        if search and search not in org_name:
            continue
        bucket_dir = _bucket_dir(state24["bucket"], state25["bucket"])
        rail_dir_online = _bucket_dir(state24["bucket_online"], state25["bucket_online"])
        rail_dir_offline = _bucket_dir(state24["bucket_offline"], state25["bucket_offline"])
        events = path["events"]
        has_open = any(ev["type"] in ("OPEN", "OPEN_CELL") for ev in events)
        has_scale_up = any(ev["type"] in ("SCALE_UP", "SCALE_UP_CELL") for ev in events)
        risk = any(ev["type"] in ("CLOSE", "CLOSE_CELL", "SCALE_DOWN", "SCALE_DOWN_CELL") for ev in events)
        item = {
            "orgId": org_id,
            "orgName": org_name,
            "sizeRaw": row_meta["sizeRaw"],
            "sizeGroup": sg,
            "companyTotalEok2024": state24["total_eok"],
            "companyBucket2024": state24["bucket"],
            "companyTotalEok2025": state25["total_eok"],
            "companyBucket2025": state25["bucket"],
            "deltaEok": state25["total_eok"] - state24["total_eok"],
            "companyBucketTransition": f"{state24['bucket']}→{state25['bucket']}",
            "seed": seed,
            "risk": risk,
            "eventCounts": {
                "openCell": sum(1 for ev in events if ev["type"] in ("OPEN", "OPEN_CELL")),
                "closeCell": sum(1 for ev in events if ev["type"] in ("CLOSE", "CLOSE_CELL")),
                "scaleUpCell": sum(1 for ev in events if ev["type"] in ("SCALE_UP", "SCALE_UP_CELL")),
                "scaleDownCell": sum(1 for ev in events if ev["type"] in ("SCALE_DOWN", "SCALE_DOWN_CELL")),
                "companyChange": 1 if state24["bucket"] != state25["bucket"] else 0,
                "railChange": sum(1 for ev in events if ev["type"] == "RAIL_SCALE_CHANGE"),
            },
            "openedCells": [ev.get("cell") for ev in events if ev["type"] in ("OPEN", "OPEN_CELL")],
            "closedCells": [ev.get("cell") for ev in events if ev["type"] in ("CLOSE", "CLOSE_CELL")],
            "scaledUpCells": [ev.get("cell") for ev in events if ev["type"] in ("SCALE_UP", "SCALE_UP_CELL")],
            "scaledDownCells": [ev.get("cell") for ev in events if ev["type"] in ("SCALE_DOWN", "SCALE_DOWN_CELL")],
            "railChange": {
                "ONLINE": rail_dir_online,
                "OFFLINE": rail_dir_offline,
            },
            "qaFlagCount": len(path.get("qa_flags", [])),
            "states": {"2024": state24, "2025": state25},
            "path": path,
            "_events": events,
            "_bucket_dir": bucket_dir,
            "_has_open": has_open,
            "_has_scale_up": has_scale_up,
        }
        items_raw.append(item)

    filters = filters or {}
    filtered = []
    for item in items_raw:
        if filters.get("riskOnly") and not item["risk"]:
            continue
        if filters.get("hasOpen") and not item["_has_open"]:
            continue
        if filters.get("hasScaleUp") and not item["_has_scale_up"]:
            continue
        company_dir = filters.get("companyDir", "all")
        if company_dir != "all" and item["_bucket_dir"] != company_dir:
            continue
        seed = filters.get("seed", "all")
        if seed != "all" and item["seed"] != seed:
            continue
        rail = filters.get("rail", "all")
        rail_dir = filters.get("railDir", "all")
        if rail != "all":
            if rail_dir != "all" and item["railChange"].get(rail) != rail_dir:
                continue
        company_from = filters.get("companyFrom", "all")
        company_to = filters.get("companyTo", "all")
        if company_from != "all" and item["companyBucket2024"] != company_from:
            continue
        if company_to != "all" and item["companyBucket2025"] != company_to:
            continue
        cell = filters.get("cell", "all")
        cell_event = filters.get("cellEvent", "all")
        if cell != "all" or cell_event != "all":
            matched = False
            for ev in item["_events"]:
                if cell != "all" and ev.get("cell") != cell:
                    continue
                if cell_event != "all":
                    if cell_event == "OPEN" and ev["type"] not in ("OPEN", "OPEN_CELL"):
                        continue
                    if cell_event == "CLOSE" and ev["type"] not in ("CLOSE", "CLOSE_CELL"):
                        continue
                    if cell_event == "UP" and ev["type"] not in ("SCALE_UP", "SCALE_UP_CELL"):
                        continue
                    if cell_event == "DOWN" and ev["type"] not in ("SCALE_DOWN", "SCALE_DOWN_CELL"):
                        continue
                matched = True
                break
            if not matched:
                continue
        filtered.append(item)

    def sort_key(it: Dict[str, Any]):
        if sort == "delta_desc":
            return -(it["deltaEok"])
        if sort == "bucket_up_desc":
            return -sp.BUCKET_ORDER.index(it["companyBucket2025"]) + sp.BUCKET_ORDER.index(it["companyBucket2024"])
        if sort == "risk_first":
            return (0 if it["risk"] else 1, -it["companyTotalEok2025"])
        if sort == "name_asc":
            return (it["orgName"] or "")
        return -it["companyTotalEok2025"]

    filtered.sort(key=sort_key)
    total_count = len(filtered)
    sliced = filtered[offset : offset + limit]

    summary = _build_portfolio_summary(filtered, size_group, search, filters)
    def _project(item: Dict[str, Any]) -> Dict[str, Any]:
        # Minimal contract fields (underscore) + backward-compatible camelCase keys for FE
        s24 = item.get("states", {}).get("2024", {})
        s25 = item.get("states", {}).get("2025", {})
        cells24 = s24.get("cells", {}) if isinstance(s24.get("cells"), dict) else {}
        cells25 = s25.get("cells", {}) if isinstance(s25.get("cells"), dict) else {}
        projected = {
            "org_id": item["orgId"],
            "org_name": item["orgName"],
            "size_raw": item["sizeRaw"],
            "segment": item["sizeGroup"],
            "company_total_eok_2024": item["companyTotalEok2024"],
            "company_bucket_2024": item["companyBucket2024"],
            "company_total_eok_2025": item["companyTotalEok2025"],
            "company_bucket_2025": item["companyBucket2025"],
            "delta_eok": item["deltaEok"],
            "company_online_bucket_2024": s24.get("bucket_online"),
            "company_offline_bucket_2024": s24.get("bucket_offline"),
            "company_online_bucket_2025": s25.get("bucket_online"),
            "company_offline_bucket_2025": s25.get("bucket_offline"),
            "cells_2024": cells24,
            "cells_2025": cells25,
            "seed": item.get("seed"),
        }
        projected.update(
            {
                "orgId": item["orgId"],
                "orgName": item["orgName"],
                "sizeRaw": item["sizeRaw"],
                "sizeGroup": item["sizeGroup"],
                "companyTotalEok2024": item["companyTotalEok2024"],
                "companyBucket2024": item["companyBucket2024"],
                "companyTotalEok2025": item["companyTotalEok2025"],
                "companyBucket2025": item["companyBucket2025"],
                "deltaEok": item["deltaEok"],
                "companyOnlineBucket2024": s24.get("bucket_online"),
                "companyOfflineBucket2024": s24.get("bucket_offline"),
                "companyOnlineBucket2025": s25.get("bucket_online"),
                "companyOfflineBucket2025": s25.get("bucket_offline"),
                "cells2024": cells24,
                "cells2025": cells25,
                "seed": item.get("seed"),
            }
        )
        return projected

    items = [_project(item) for item in sliced]
    return {
        "summary": summary,
        "items": items,
        "meta": {
            "segment": size_group,
            "sizeGroup": size_group,  # backward compatibility
            "search": search or "",
            "sort": sort,
            "limit": limit,
            "offset": offset,
            "totalCount": total_count,
        },
    }


def _build_portfolio_summary(items: List[Dict[str, Any]], size_group: str, search: str | None, filters: Dict[str, Any]) -> Dict[str, Any]:
    if not items:
        buckets = sp.BUCKET_ORDER
        return {
            "accountCount": 0,
            "sum2024Eok": 0.0,
            "sum2025Eok": 0.0,
            "companyBucketChangeCounts": {"up": 0, "flat": 0, "down": 0},
            "openAccountCount": 0,
            "closeAccountCount": 0,
            "riskAccountCount": 0,
            "seedCounts": {s: 0 for s in ["H→B", "B→H", "SIMUL", "NONE"]},
            "companyTransitionMatrix": {"buckets": buckets, "counts": [[0 for _ in buckets] for _ in buckets]},
            "cellEventMatrix": {cell: {"OPEN": 0, "CLOSE": 0, "UP": 0, "DOWN": 0} for cell in ["HRD_ONLINE", "HRD_OFFLINE", "BU_ONLINE", "BU_OFFLINE"]},
            "railChangeSummary": {"ONLINE": {"up": 0, "flat": 0, "down": 0}, "OFFLINE": {"up": 0, "flat": 0, "down": 0}},
            "topPatterns": {},
            "segmentComparison": [],
        }
    buckets = sp.BUCKET_ORDER
    matrix = [[0 for _ in buckets] for _ in buckets]
    cell_matrix = {cell: {"OPEN": 0, "CLOSE": 0, "UP": 0, "DOWN": 0} for cell in ["HRD_ONLINE", "HRD_OFFLINE", "BU_ONLINE", "BU_OFFLINE"]}
    rail_change = {"ONLINE": {"up": 0, "flat": 0, "down": 0}, "OFFLINE": {"up": 0, "flat": 0, "down": 0}}
    seed_counts = {s: 0 for s in ["H→B", "B→H", "SIMUL", "NONE"]}
    open_count = 0
    close_count = 0
    risk_count = 0
    sum2024 = 0.0
    sum2025 = 0.0
    for it in items:
        sum2024 += it["companyTotalEok2024"]
        sum2025 += it["companyTotalEok2025"]
        dir_company = _bucket_dir(it["companyBucket2024"], it["companyBucket2025"])
        i = buckets.index(it["companyBucket2024"])
        j = buckets.index(it["companyBucket2025"])
        matrix[i][j] += 1
        if dir_company == "up":
            open_count += 1
        if dir_company == "down":
            close_count += 1
        if it["risk"]:
            risk_count += 1
        seed_counts[it["seed"]] = seed_counts.get(it["seed"], 0) + 1
        for ev in it["_events"]:
            c = ev.get("cell")
            if c in cell_matrix:
                if ev["type"] in ("OPEN", "OPEN_CELL"):
                    cell_matrix[c]["OPEN"] += 1
                elif ev["type"] in ("CLOSE", "CLOSE_CELL"):
                    cell_matrix[c]["CLOSE"] += 1
                elif ev["type"] in ("SCALE_UP", "SCALE_UP_CELL"):
                    cell_matrix[c]["UP"] += 1
                elif ev["type"] in ("SCALE_DOWN", "SCALE_DOWN_CELL"):
                    cell_matrix[c]["DOWN"] += 1
        for rail in ("ONLINE", "OFFLINE"):
            rail_change[rail][it["railChange"][rail]] += 1

    top_patterns = {
        "topOpenCell": _top_cell_event(cell_matrix, "OPEN"),
        "topCloseCell": _top_cell_event(cell_matrix, "CLOSE"),
        "topUpCell": _top_cell_event(cell_matrix, "UP"),
        "topDownCell": _top_cell_event(cell_matrix, "DOWN"),
        "topSeed": _top_seed(seed_counts),
    }
    segment_comparison: List[Dict[str, Any]] = []
    if (
        size_group == "전체"
        and not search
        and all(v in (False, "all", None) for v in filters.values())
    ):
        group_map: Dict[str, Dict[str, Any]] = {}
        for it in items:
            sg = it["sizeGroup"]
            entry = group_map.setdefault(
                sg,
                {
                    "sizeGroup": sg,
                    "accountCount": 0,
                    "sum2025Eok": 0.0,
                    "companyUp": 0,
                    "open": 0,
                    "risk": 0,
                    "seedH2B": 0,
                },
            )
            entry["accountCount"] += 1
            entry["sum2025Eok"] += it["companyTotalEok2025"]
            if _bucket_dir(it["companyBucket2024"], it["companyBucket2025"]) == "up":
                entry["companyUp"] += 1
            if it["openedCells"]:
                entry["open"] += 1
            if it["risk"]:
                entry["risk"] += 1
            if it["seed"] == "H→B":
                entry["seedH2B"] += 1
        for sg, entry in group_map.items():
            total = entry["accountCount"]
            segment_comparison.append(
                {
                    "sizeGroup": sg,
                    "accountCount": total,
                    "sum2025Eok": entry["sum2025Eok"],
                    "companyUpRate": entry["companyUp"] / total if total else 0,
                    "openRate": entry["open"] / total if total else 0,
                    "riskRate": entry["risk"] / total if total else 0,
                    "seedH2BRate": entry["seedH2B"] / total if total else 0,
                }
            )

    return {
        "accountCount": len(items),
        "sum2024Eok": sum2024,
        "sum2025Eok": sum2025,
        "companyBucketChangeCounts": {
            "up": sum(1 for it in items if _bucket_dir(it["companyBucket2024"], it["companyBucket2025"]) == "up"),
            "flat": sum(1 for it in items if _bucket_dir(it["companyBucket2024"], it["companyBucket2025"]) == "flat"),
            "down": sum(1 for it in items if _bucket_dir(it["companyBucket2024"], it["companyBucket2025"]) == "down"),
        },
        "openAccountCount": open_count,
        "closeAccountCount": close_count,
        "riskAccountCount": risk_count,
        "seedCounts": seed_counts,
        "companyTransitionMatrix": {"buckets": buckets, "counts": matrix},
        "cellEventMatrix": cell_matrix,
        "railChangeSummary": rail_change,
        "topPatterns": top_patterns,
        "segmentComparison": segment_comparison,
    }


def _top_cell_event(cell_matrix: Dict[str, Dict[str, int]], key: str) -> Dict[str, Any]:
    best_cell = None
    best_val = -1
    for cell, counts in cell_matrix.items():
        if counts[key] > best_val:
            best_cell = cell
            best_val = counts[key]
    return {"cell": best_cell, "count": best_val}


def _top_seed(seed_counts: Dict[str, int]) -> Dict[str, Any]:
    best_seed = None
    best_val = -1
    for seed, cnt in seed_counts.items():
        if cnt > best_val:
            best_seed = seed
            best_val = cnt
    return {"seed": best_seed, "count": best_val}


def get_statepath_detail(org_id: str, db_path: Path = DB_PATH) -> Dict[str, Any] | None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")
    rows = [r for r in _statepath_rows(db_path) if r["orgId"] == org_id]
    if not rows:
        return None
    cells_by_org = _build_statepath_cells(rows)
    cells = cells_by_org.get(org_id)
    if not cells:
        return None
    state24, state25 = _build_state_from_cells(cells)
    path = _build_path_from_states(state24, state25)
    org_name = rows[0]["orgName"]
    size_raw = rows[0]["sizeRaw"]
    size_group_val = infer_size_group(org_name, size_raw)
    return {
        "org": {"id": org_id, "name": org_name, "sizeRaw": size_raw, "sizeGroup": size_group_val},
        "year_states": {"2024": state24, "2025": state25},
        "path_2024_to_2025": path,
        "qa": {"flags": [], "checks": {"y2024_ok": True, "y2025_ok": True}},
    }
def get_org_by_id(org_id: str, db_path: Path = DB_PATH) -> Dict[str, Any] | None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")
    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT id, COALESCE("이름", id) AS name, "기업 규모" AS size, '
            '"팀" AS team_json, "담당자" AS owner_json '
            "FROM organization WHERE id = ? LIMIT 1",
            (org_id,),
        )
    if not rows:
        return None
    row = rows[0]
    return {
        "id": row["id"],
        "name": row["name"],
        "size": row["size"],
        "team": _safe_json_load(row["team_json"]) or [],
        "owner": _safe_json_load(row["owner_json"]) or None,
    }


def get_org_memos(org_id: str, limit: int = 100, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    limit = max(1, min(limit, 500))
    owner_lookup = _get_owner_lookup(db_path)
    with _connect(db_path) as conn:
        has_html = _has_column(conn, "memo", "htmlBody")
        select_cols = "id, text, ownerId, createdAt, updatedAt"
        if has_html:
            select_cols = "id, text, htmlBody, ownerId, createdAt, updatedAt"
        rows = _fetch_all(
            conn,
            f"SELECT {select_cols} "
            "FROM memo "
            "WHERE organizationId = ? AND peopleId IS NULL AND dealId IS NULL "
            "ORDER BY createdAt DESC "
            "LIMIT ?",
            (org_id, limit),
        )
    result: List[Dict[str, Any]] = []
    for row in rows:
        owner_id = row["ownerId"]
        html_body = row["htmlBody"] if "htmlBody" in row.keys() else None
        result.append(
            {
                **dict(row),
                "htmlBody": html_body,
                "ownerName": owner_lookup.get(owner_id, owner_id),
            }
        )
    return result


def get_people_for_org(
    org_id: str, has_deal: bool | None = None, db_path: Path = DB_PATH
) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT p.id, p.organizationId, COALESCE(p."이름", p.id) AS name, '
            'p."소속 상위 조직" AS upper_org, p."팀(명함/메일서명)" AS team_signature, '
            'p."직급(명함/메일서명)" AS title_signature, p."담당 교육 영역" AS edu_area, '
            'p."이메일" AS email, p."전화" AS phone, '
            "COALESCE(dc.deal_count, 0) AS deal_count "
            "FROM people p "
            "LEFT JOIN ("
            "  SELECT peopleId, COUNT(*) AS deal_count "
            "  FROM deal "
            "  WHERE peopleId IS NOT NULL "
            "  GROUP BY peopleId"
            ") dc ON dc.peopleId = p.id "
            "WHERE p.organizationId = ? "
            "ORDER BY name",
            (org_id,),
        )

    people = _rows_to_dicts(rows)
    if has_deal is None:
        return people
    if has_deal:
        return [p for p in people if (p.get("deal_count") or 0) > 0]
    return [p for p in people if (p.get("deal_count") or 0) == 0]


def _to_number(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_year_from_text_legacy(val: Any) -> str | None:
    if val is None:
        return None
    text = str(val)
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return None


def _parse_year_from_text(val: Any) -> str | None:
    if _is_strict_mode():
        year = date_kst.kst_year(val)
        return year if year else None
    return _parse_year_from_text_legacy(val)


def _year_from_dates(contract_date: Any, expected_date: Any) -> str | None:
    year = _parse_year_from_text(contract_date)
    if year:
        return year
    return _parse_year_from_text(expected_date)


def _month_key_from_text_legacy(val: Any) -> str | None:
    """
    Extract YYMM from strings like YYYY-MM or YYYY-MM-DD (also tolerates YYYY/MM).
    Legacy implementation (string split).
    """
    if val is None:
        return None
    text_raw = str(val).strip()
    if not text_raw:
        return None

    # Prefer the canonical KST parser for broad format coverage (., digits-only, UTC offsets).
    kst_yymm = date_kst.kst_yymm(text_raw)
    if kst_yymm:
        return kst_yymm

    # If ISO datetime, first normalize to KST date then extract.
    if "T" in text_raw:
        kst_date = _date_only_legacy(text_raw)
        match_kst = re.match(r"^(\d{4})-(\d{2})", kst_date)
        if match_kst:
            yyyy, mm = match_kst.group(1), match_kst.group(2)
            return f"{yyyy[-2:]}{mm}"

    match = re.match(r"^(\d{4})[-/.]?(\d{1,2})", text_raw)
    if not match:
        return None
    year, month = match.group(1), match.group(2)
    return f"{year[-2:]}{int(month):02d}"


def _month_key_from_text(val: Any) -> str | None:
    if _is_strict_mode():
        return date_kst.kst_yymm(val)
    return _month_key_from_text_legacy(val)


def _month_key_from_dates(contract_date: Any, expected_date: Any) -> str | None:
    return _month_key_from_text(contract_date) or _month_key_from_text(expected_date)


def _month_range_keys(from_ym: str, to_ym: str) -> List[str]:
    """
    Build YYMM list inclusive between two YYYY-MM strings.
    """
    def _parse_pair(text: str) -> Tuple[int, int]:
        parts = re.split(r"[-/]", text.strip())
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
        raise ValueError(f"Invalid year-month: {text}")

    y1, m1 = _parse_pair(from_ym)
    y2, m2 = _parse_pair(to_ym)
    start = (y1, m1)
    end = (y2, m2)
    if (y1, m1) > (y2, m2):
        start, end = end, start
    year, month = start
    keys: List[str] = []
    while (year, month) <= end:
        keys.append(f"{year % 100:02d}{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return keys


def _owners_match_team(owners: Any, allowed: Optional[Set[str]]) -> bool:
    if not allowed:
        return True
    owner_list = _parse_owner_names(owners)
    if not owner_list:
        return False
    for name in owner_list:
        norm = normalize_owner_name(name)
        if norm and norm in allowed:
            return True
    return False


def _perf_close_rate_scope_members(scope: str) -> Optional[Set[str]]:
    """
    scope -> allowed member set (normalized). None means no filtering.
    corp_group = edu1+edu2 전체.
    """
    def part_members(team_key: str, part_key: str) -> Set[str]:
        team = PART_STRUCTURE.get(team_key, {})
        raw = team.get(part_key, [])
        return {normalize_owner_name(n) for n in raw if n}

    if scope == "all":
        return None
    if scope == "corp_group":
        return _dealcheck_members("edu1") | _dealcheck_members("edu2")
    if scope == "edu1":
        return _dealcheck_members("edu1")
    if scope == "edu2":
        return _dealcheck_members("edu2")
    if scope == "edu1_p1":
        return part_members("기업교육 1팀", "1파트")
    if scope == "edu1_p2":
        return part_members("기업교육 1팀", "2파트")
    if scope == "edu2_p1":
        return part_members("기업교육 2팀", "1파트")
    if scope == "edu2_p2":
        return part_members("기업교육 2팀", "2파트")
    if scope == "edu2_online":
        return part_members("기업교육 2팀", "온라인셀")
    raise ValueError(f"Unknown scope: {scope}")


def _amount_fallback(amount: Any, expected: Any) -> float:
    num = _to_number(amount)
    if num is not None and num > 0:
        return num
    num_exp = _to_number(expected)
    if num_exp is not None and num_exp > 0:
        return num_exp
    return 0.0


def _tier_multiplier(tier: str | None) -> float:
    t = (tier or "").upper()
    if t == "S0":
        return 1.5
    if t in {"P0", "P1"}:
        return 1.7
    if t == "P2":
        return 1.5
    if t in {"P3", "P4", "P5"}:
        return 1.0
    return 1.0


def _norm_min(val: Any) -> str:
    if val is None:
        return ""
    return str(val).replace("\u00A0", " ").strip()


def _normalize_counterparty_upper(val: Any) -> str:
    text = _norm_min(val)
    if not text or text in {"-", "–", "—"}:
        return "미입력"
    return text


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        if hasattr(row, "keys"):
            return row[key] if key in row.keys() else default
        return row.get(key, default)
    except Exception:
        return default


def _norm_text(val: Any) -> str:
    text = _norm_min(val)
    return text if text else "미입력"


def _compute_grade(total_amount: float) -> str:
    """
    Grade bands based on 2025 총액 (억 기준, 이상~미만):
    S0: >=10, P0: >=2, P1: >=1, P2: >=0.5, P3: >=0.25, P4: >=0.1, P5: <0.1
    """
    amount_eok = (total_amount or 0.0) / 1e8
    if amount_eok >= 10.0:
        return "S0"
    if amount_eok >= 2.0:
        return "P0"
    if amount_eok >= 1.0:
        return "P1"
    if amount_eok >= 0.5:
        return "P2"
    if amount_eok >= 0.25:
        return "P3"
    if amount_eok >= 0.1:
        return "P4"
    return "P5"


def get_deals_for_person(person_id: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT id, peopleId, organizationId, COALESCE("이름", id) AS name, '
            '"상태" AS status, "금액" AS amount, "예상 체결액" AS expected_amount, '
            '"계약 체결일" AS contract_date, "담당자" AS owner_json, "생성 날짜" AS created_at '
            "FROM deal "
            "WHERE peopleId = ? "
            'ORDER BY "계약 체결일" IS NULL, "계약 체결일" DESC, "생성 날짜" DESC',
            (person_id,),
        )

    deals: List[Dict[str, Any]] = []
    for row in rows:
        owner = _safe_json_load(row["owner_json"])
        deals.append(
            {
                "id": row["id"],
                "peopleId": row["peopleId"],
                "organizationId": row["organizationId"],
                "name": row["name"],
                "status": row["status"],
                "amount": _to_number(row["amount"]),
                "expected_amount": _to_number(row["expected_amount"]),
                "contract_date": row["contract_date"],
                "ownerName": owner.get("name") if isinstance(owner, dict) else None,
                "created_at": row["created_at"],
            }
        )
    return deals


def get_memos_for_person(
    person_id: str, limit: int = 200, db_path: Path = DB_PATH
) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    limit = max(1, min(limit, 500))
    owner_lookup = _get_owner_lookup(db_path)
    with _connect(db_path) as conn:
        has_html = _has_column(conn, "memo", "htmlBody")
        select_cols = "id, text, ownerId, createdAt, updatedAt"
        if has_html:
            select_cols = "id, text, htmlBody, ownerId, createdAt, updatedAt"
        rows = _fetch_all(
            conn,
            f"SELECT {select_cols} "
            "FROM memo "
            "WHERE peopleId = ? AND (dealId IS NULL OR TRIM(dealId) = '') "
            "ORDER BY createdAt DESC "
            "LIMIT ?",
            (person_id, limit),
        )
    result: List[Dict[str, Any]] = []
    for row in rows:
        owner_id = row["ownerId"]
        html_body = row["htmlBody"] if "htmlBody" in row.keys() else None
        result.append(
            {
                **dict(row),
                "htmlBody": html_body,
                "ownerName": owner_lookup.get(owner_id, owner_id),
            }
        )
    return result


def get_memos_for_deal(deal_id: str, limit: int = 200, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    limit = max(1, min(limit, 500))
    owner_lookup = _get_owner_lookup(db_path)
    with _connect(db_path) as conn:
        has_html = _has_column(conn, "memo", "htmlBody")
        select_cols = "id, text, ownerId, createdAt, updatedAt"
        if has_html:
            select_cols = "id, text, htmlBody, ownerId, createdAt, updatedAt"
        rows = _fetch_all(
            conn,
            f"SELECT {select_cols} "
            "FROM memo "
            "WHERE dealId = ? "
            "ORDER BY createdAt DESC "
            "LIMIT ?",
            (deal_id, limit),
        )
    result: List[Dict[str, Any]] = []
    for row in rows:
        owner_id = row["ownerId"]
        html_body = row["htmlBody"] if "htmlBody" in row.keys() else None
        result.append(
            {
                **dict(row),
                "htmlBody": html_body,
                "ownerName": owner_lookup.get(owner_id, owner_id),
            }
        )
    return result


def get_won_summary_by_upper_org(org_id: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    Group Won deals by people upper_org and aggregate amounts per contract year (2023/2024/2025).
    Includes customer contacts (team/name/title/edu_area) and deal owners (데이원 담당자) lists.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  d."금액" AS amount, '
            '  d."계약 체결일" AS contract_date, '
            '  d."담당자" AS owner_json, '
            '  p."소속 상위 조직" AS upper_org, '
            '  COALESCE(p."이름", p.id) AS person_name, '
            '  p."팀(명함/메일서명)" AS team_signature, '
            '  p."직급(명함/메일서명)" AS title_signature, '
            '  p."담당 교육 영역" AS edu_area '
            "FROM deal d "
            "LEFT JOIN people p ON p.id = d.peopleId "
            "WHERE d.organizationId = ? AND d.\"상태\" = 'Won'",
            (org_id,),
        )

    grouped: Dict[str, Dict[str, Any]] = {}

    def _normalize_upper(val: Any) -> str:
        cleaned = (val or "").strip()
        return cleaned if cleaned else "미입력"

    def _format_contact(row: sqlite3.Row) -> str:
        team = (row["team_signature"] or "미입력").strip() or "미입력"
        name = (row["person_name"] or "미입력").strip() or "미입력"
        title = (row["title_signature"] or "미입력").strip() or "미입력"
        edu = (row["edu_area"] or "미입력").strip() or "미입력"
        return f"{team} / {name} / {title} / {edu}"

    for row in rows:
        upper = _normalize_upper(row["upper_org"])
        entry = grouped.setdefault(
            upper,
            {
                "upper_org": upper,
                "won2023": 0.0,
                "won2024": 0.0,
                "won2025": 0.0,
                "contacts": set(),
                "owners": set(),
                "owners2025": set(),
                "dealCount": 0,
            },
        )
        amount_val = _to_number(row["amount"])
        amount = amount_val or 0.0
        contract_date = row["contract_date"] or ""
        year = str(contract_date)[:4]
        contributes_to_won = False
        if year in YEARS_FOR_WON:
            entry[f"won{year}"] += amount
            contributes_to_won = True
        entry["dealCount"] += 1

        # For upper_org = "미입력", include contacts only when the deal contributes to Won sum.
        if upper == "미입력":
            if contributes_to_won and amount_val is not None:
                entry["contacts"].add(_format_contact(row))
        else:
            entry["contacts"].add(_format_contact(row))

        owner = _safe_json_load(row["owner_json"])
        owner_name = None
        if isinstance(owner, dict):
            owner_name = owner.get("name") or owner.get("id")
        elif isinstance(owner, str):
            owner_name = owner
        if owner_name:
            entry["owners"].add(str(owner_name))
        else:
            entry["owners"].add("미입력")
        if year == "2025":
            if owner_name:
                entry["owners2025"].add(str(owner_name))
            else:
                entry["owners2025"].add("미입력")

    # Convert sets to sorted lists and amounts to numbers (kept as float for formatting on frontend)
    result: List[Dict[str, Any]] = []
    for entry in grouped.values():
        result.append(
            {
                "upper_org": entry["upper_org"],
                "won2023": entry["won2023"],
                "won2024": entry["won2024"],
                "won2025": entry["won2025"],
                "contacts": sorted(entry["contacts"]),
                "owners": sorted(entry["owners"]),
                "owners2025": sorted(entry["owners2025"]),
                "dealCount": entry["dealCount"],
            }
        )

    # Sort by total amount desc (sum of years)
    result.sort(key=lambda x: (x["won2023"] + x["won2024"] + x["won2025"]), reverse=True)
    return result


def get_rank_2025_deals(size: str = "전체", db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    Aggregate 2024/2025 'Won' deals by organization.
    - 2025: total + online/offline split + grade
    - 2024: total + grade
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    eff_mode = _effective_date_mode()
    y2025_clause, y2025_params = sql_year_clause('d."계약 체결일"', "2025", eff_mode)
    conditions = [y2025_clause]
    params: List[Any] = list(y2025_params)
    if size and size != "전체":
        conditions.append('o."기업 규모" = ?')
        params.append(size)

    with _connect(db_path) as conn:
        rows_2025 = _fetch_all(
            conn,
            'SELECT '
            '  d.organizationId AS orgId, '
            '  COALESCE(o."이름", d.organizationId) AS orgName, '
            '  d."과정포맷" AS courseFormat, '
            '  SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            f"WHERE {' AND '.join(conditions)} "
            'GROUP BY d.organizationId, orgName, d."과정포맷"',
            params,
        )

        y2024_clause, y2024_params = sql_year_clause('d."계약 체결일"', "2024", eff_mode)
        conditions_2024 = ['d."상태" = ?', y2024_clause]
        params_2024: List[Any] = ["Won", *y2024_params]
        if size and size != "전체":
            conditions_2024.append('o."기업 규모" = ?')
            params_2024.append(size)
        rows_2024 = _fetch_all(
            conn,
            'SELECT '
            '  d.organizationId AS orgId, '
            '  COALESCE(o."이름", d.organizationId) AS orgName, '
            '  SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            f"WHERE {' AND '.join(conditions_2024)} "
            'GROUP BY d.organizationId, orgName',
            params_2024,
        )

    # Accumulate per org with online/offline split (2025) and 2024 total
    orgs: Dict[str, Dict[str, Any]] = {}
    for row in rows_2025:
        org_id = row["orgId"]
        org_name = row["orgName"]
        course = row["courseFormat"]
        amount = _to_number(row["totalAmount"]) or 0.0
        org_entry = orgs.setdefault(
            org_id,
            {
                "orgId": org_id,
                "orgName": org_name,
                "totalAmount": 0.0,
                "onlineAmount": 0.0,
                "offlineAmount": 0.0,
                "totalAmount2024": 0.0,
            },
        )
        if not org_entry.get("orgName") and org_name:
            org_entry["orgName"] = org_name
        org_entry["totalAmount"] += amount
        if course in ONLINE_COURSE_FORMATS:
            org_entry["onlineAmount"] += amount
        else:
            org_entry["offlineAmount"] += amount

    for row in rows_2024:
        org_id = row["orgId"]
        org_entry = orgs.setdefault(
            org_id,
            {
                "orgId": org_id,
                "orgName": row["orgName"],
                "totalAmount": 0.0,
                "onlineAmount": 0.0,
                "offlineAmount": 0.0,
                "totalAmount2024": 0.0,
            },
        )
        amount = _to_number(row["totalAmount"]) or 0.0
        org_entry["totalAmount2024"] += amount

    for entry in orgs.values():
        entry["grade"] = _compute_grade(entry["totalAmount"])
        entry["grade2024"] = _compute_grade(entry["totalAmount2024"])
        entry["totalAmount2024"] = entry.get("totalAmount2024", 0.0)

    ranked = sorted(orgs.values(), key=lambda x: x["totalAmount"] or 0, reverse=True)
    return ranked


def get_mismatched_deals(size: str = "대기업", db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    Return deals where the deal organization differs from the person's organization.
    Filters by organization size (deal organization) when provided.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    conditions = [
        "d.organizationId IS NOT NULL",
        "p.organizationId IS NOT NULL",
        "d.organizationId <> p.organizationId",
    ]
    params: List[Any] = []
    if size and size != "전체":
        conditions.append('o_deal."기업 규모" = ?')
        params.append(size)

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  d.id AS dealId, '
            '  COALESCE(d."이름", d.id) AS dealName, '
            '  d.organizationId AS dealOrgId, '
            '  COALESCE(o_deal."이름", d.organizationId) AS dealOrgName, '
            '  p.id AS personId, '
            '  COALESCE(p."이름", p.id) AS personName, '
            '  p.organizationId AS personOrgId, '
            '  COALESCE(o_person."이름", p.organizationId) AS personOrgName, '
            '  d."계약 체결일" AS contract_date, '
            '  d."금액" AS amount '
            "FROM deal d "
            "JOIN people p ON p.id = d.peopleId "
            "LEFT JOIN organization o_deal ON o_deal.id = d.organizationId "
            "LEFT JOIN organization o_person ON o_person.id = p.organizationId "
            f"WHERE {' AND '.join(conditions)} "
            'ORDER BY d."계약 체결일" IS NULL, d."계약 체결일" DESC, d.id',
            params,
        )

    result: List[Dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "dealId": row["dealId"],
                "dealName": row["dealName"],
                "dealOrgId": row["dealOrgId"],
                "dealOrgName": row["dealOrgName"],
                "personId": row["personId"],
                "personName": row["personName"],
                "personOrgId": row["personOrgId"],
                "personOrgName": row["personOrgName"],
                "contract_date": row["contract_date"],
                "amount": _to_number(row["amount"]),
            }
        )
    return result


def get_won_industry_summary(
    size: str = "전체",
    years: Sequence[str] = ("2023", "2024", "2025"),
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """
    Aggregate Won deals by industry_major per year and count organizations.
    Returns list sorted by 2025 amount desc.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    years_set: Set[str] = set(str(y) for y in years)
    eff_mode = _effective_date_mode()
    year_expr = sql_year_expr('d."계약 체결일"', eff_mode)
    years_clause, years_params = sql_years_clause('d."계약 체결일"', years_set, eff_mode)
    conditions = ['d."상태" = ?']
    params: List[Any] = ["Won"]
    if size and size != "전체":
        conditions.append('o."기업 규모" = ?')
        params.append(size)
    conditions.append(years_clause)
    params.extend(years_params)
    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  COALESCE(o."업종 구분(대)", "미입력") AS industry_major, '
            '  COALESCE(o.id, d.organizationId) AS org_id, '
            f"  {year_expr} AS year, "
            '  SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            f"WHERE {' AND '.join(conditions)} "
            '  AND d."계약 체결일" IS NOT NULL '
            "GROUP BY industry_major, org_id, year",
            params,
        )

    industry_map: Dict[str, Dict[str, Any]] = {}
    org_seen: Dict[str, Set[str]] = {}

    for row in rows:
        year = str(row["year"])
        if year not in years_set:
            continue
        industry = (row["industry_major"] or "미입력").strip() or "미입력"
        amount = _to_number(row["totalAmount"]) or 0.0
        entry = industry_map.setdefault(
            industry,
            {
                "industry": industry,
                "won2023": 0.0,
                "won2024": 0.0,
                "won2025": 0.0,
                "orgCount": 0,
            },
        )
        entry[f"won{year}"] += amount

        # count unique orgs per industry
        org_id = row["org_id"]
        if org_id:
            seen = org_seen.setdefault(industry, set())
            if org_id not in seen:
                seen.add(org_id)
                entry["orgCount"] += 1

    result = list(industry_map.values())
    # sort by 2025 amount desc
    result.sort(key=lambda x: x["won2025"], reverse=True)
    return result


def get_rank_2025_counterparty_detail(
    org_id: str, upper_org: str, db_path: Path = DB_PATH
) -> Dict[str, Any]:
    """
    Detail for a specific org + upper_org:
    - people filtered by upper_org
    - team breakdown (2025 Won online/offline, deal counts, deals list)
    - offline deal sources for 25/26 (to mirror counterparty DRI aggregates)
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")
    upper_norm = (upper_org or "").strip() or "미입력"
    online_set = sp.ONLINE_COURSE_FORMATS

    def _norm_upper(val: Any) -> str:
        text = (val or "").strip()
        return text if text else "미입력"

    def _parse_owner_names(raw: Any) -> List[str]:
        names: List[str] = []
        data = _safe_json_load(raw)
        if isinstance(data, dict):
            name = data.get("name") or data.get("id")
            if name:
                names.append(str(name))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("id")
                    if name:
                        names.append(str(name))
                elif isinstance(item, str) and item.strip():
                    names.append(item.strip())
        elif isinstance(data, str) and data.strip():
            names.append(data.strip())
        return names

    with _connect(db_path) as conn:
        people_rows = _fetch_all(
            conn,
            'SELECT id, COALESCE("이름", id) AS name, '
            '"소속 상위 조직" AS upper_org, '
            '"팀(명함/메일서명)" AS team_signature, '
            '"직급(명함/메일서명)" AS title_signature, '
            '"담당 교육 영역" AS edu_area '
            "FROM people "
            "WHERE organizationId = ?",
            (org_id,),
        )

        deal_rows = _fetch_all(
            conn,
            'SELECT '
            '  d.id, '
            '  COALESCE(d."이름", d.id) AS name, '
            '  d.peopleId AS people_id, '
            '  COALESCE(p."이름", p.id) AS people_name, '
            '  d."상태" AS status, '
            '  d."성사 가능성" AS probability, '
            '  d."금액" AS amount, '
            '  d."예상 체결액" AS expected_amount, '
            '  d."계약 체결일" AS contract_date, '
            '  d."수주 예정일" AS expected_date, '
            '  d."수강시작일" AS start_date, '
            '  d."수강종료일" AS end_date, '
            '  d."생성 날짜" AS created_at, '
            '  d."과정포맷" AS course_format, '
            '  d."담당자" AS owner_json, '
            '  p."소속 상위 조직" AS upper_org, '
            '  p."팀(명함/메일서명)" AS team_signature '
            "FROM deal d "
            "LEFT JOIN people p ON p.id = d.peopleId "
            "WHERE d.organizationId = ?",
            (org_id,),
        )

    def _start_year(val: Any) -> str | None:
        return _parse_year_from_text(val)

    def _is_offline(fmt: Any) -> bool:
        return (fmt or "").strip() not in online_set

    def _is_high(prob: Any, status: Any) -> bool:
        if _prob_is_high(prob):
            return True
        return (status or "").strip() == "Won"

    people = []
    for p in people_rows:
        if _norm_upper(p["upper_org"]) != upper_norm:
            continue
        people.append(
            {
                "id": p["id"],
                "name": p["name"],
                "upper_org": _norm_upper(p["upper_org"]),
                "team_signature": (p["team_signature"] or "").strip() or "미입력",
                "title_signature": (p["title_signature"] or "").strip() or "미입력",
                "edu_area": (p["edu_area"] or "").strip() or "미입력",
            }
        )

    team_map: Dict[str, Dict[str, Any]] = {}
    offline25_deals: List[Dict[str, Any]] = []
    offline26_deals: List[Dict[str, Any]] = []
    online26_deals: List[Dict[str, Any]] = []
    for d in deal_rows:
        if _norm_upper(d["upper_org"]) != upper_norm:
            continue
        team = (d["team_signature"] or "미입력").strip() or "미입력"
        entry = team_map.setdefault(team, {"team": team, "online": 0.0, "offline": 0.0, "deals": []})
        amt = _amount_fallback(d["amount"], d["expected_amount"])
        fmt = d["course_format"] or ""
        year = _year_from_dates(d["contract_date"], d["expected_date"])
        start_year = _start_year(d["start_date"])
        if year == "2025":
            if fmt in online_set:
                entry["online"] += amt
            else:
                entry["offline"] += amt
        owner_names = _parse_owner_names(d["owner_json"])
        entry["deals"].append(
            {
                "id": d["id"],
                "name": d["name"],
                "people_id": d["people_id"],
                "people_name": d["people_name"],
                "status": d["status"],
                "probability": d["probability"],
                "amount": amt,
                "expected_amount": _to_number(d["expected_amount"]) or 0.0,
                "contract_date": d["contract_date"],
                "expected_date": d["expected_date"],
                "start_date": d["start_date"],
                "end_date": d["end_date"],
                "created_at": d["created_at"],
                "course_format": d["course_format"],
                "owner": ", ".join(owner_names) if owner_names else "",
                "team": team,
                "upper_org": _norm_upper(d["upper_org"]),
            }
        )
        # offline sources
        if amt > 0:
            is_high = _is_high(d["probability"], d["status"])
            if _is_offline(fmt):
                if is_high and year == "2025" and start_year != "2026":
                    offline25_deals.append(entry["deals"][-1])
                if (is_high and year == "2026") or (is_high and year == "2025" and start_year == "2026"):
                    offline26_deals.append(entry["deals"][-1])
            else:
                if is_high and year == "2025" and start_year == "2026":
                    online26_deals.append(entry["deals"][-1])
                if is_high and year == "2026":
                    online26_deals.append(entry["deals"][-1])

    # sort deals by contract_date desc then created_at desc for readability
    for entry in team_map.values():
        entry["deals"].sort(
            key=lambda x: (
                (_parse_year_from_text(x.get("contract_date")) or ""),
                x.get("contract_date") or "",
                x.get("created_at") or "",
            ),
            reverse=True,
        )
    offline25_deals.sort(key=lambda x: (x.get("contract_date") or "", x.get("created_at") or ""), reverse=True)
    offline26_deals.sort(key=lambda x: (x.get("contract_date") or "", x.get("created_at") or ""), reverse=True)
    online26_deals.sort(key=lambda x: (x.get("contract_date") or "", x.get("created_at") or ""), reverse=True)

    summary = {
        "online": sum(t["online"] for t in team_map.values()),
        "offline": sum(t["offline"] for t in team_map.values()),
        "dealCount": sum(len(t["deals"]) for t in team_map.values()),
    }

    # flatten deals for frontend filtering
    all_deals: List[Dict[str, Any]] = []
    for entry in team_map.values():
        all_deals.extend(entry["deals"])

    return {
        "people": people,
        "teams": list(team_map.values()),
        "summary": summary,
        "deals": all_deals,
        "offline25_deals": offline25_deals,
        "offline26_deals": offline26_deals,
        "online26_deals": online26_deals,
    }


def get_rank_2025_deals_people(size: str = "대기업", db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    For organizations (by size) that have Won deals in 2025, return people with all their deals (any status).
    Grouped by person to support People-centric rendering.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    # 단계 A: 2025 Won 보유 조직 집합
    eff_mode = _effective_date_mode()
    y2025_clause, y2025_params = sql_year_clause('d."계약 체결일"', "2025", eff_mode)
    org_conditions = ['d."상태" = ?', y2025_clause]
    org_params: List[Any] = ["Won", *y2025_params]
    if size and size != "전체":
        org_conditions.append('o."기업 규모" = ?')
        org_params.append(size)

    with _connect(db_path) as conn:
        org_rows = _fetch_all(
            conn,
            'SELECT d.organizationId AS orgId, COALESCE(o."이름", d.organizationId) AS orgName, '
            'SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            f"WHERE {' AND '.join(org_conditions)} "
            "GROUP BY d.organizationId, orgName",
            org_params,
        )
        if not org_rows:
            return []

        org_map = {row["orgId"]: row["orgName"] for row in org_rows}
        org_totals = {row["orgId"]: _to_number(row["totalAmount"]) or 0.0 for row in org_rows}
        org_ids = list(org_map.keys())

        def placeholders(seq: Sequence[Any]) -> str:
            return ",".join("?" for _ in seq)

        # 단계 B: 대상 조직의 모든 딜(상태 무관) + 연결 People 조회
        deal_rows = _fetch_all(
            conn,
            'SELECT '
            '  d.organizationId AS orgId, '
            '  d.id AS dealId, '
            '  COALESCE(d."이름", d.id) AS dealName, '
            '  d."상태" AS status, '
            '  d."금액" AS amount, '
            '  d."계약 체결일" AS contract_date, '
            '  d."생성 날짜" AS created_at, '
            '  d."과정포맷" AS course_format, '
            '  d.peopleId AS personId, '
            '  COALESCE(p."이름", p.id) AS personName, '
            '  p."소속 상위 조직" AS upper_org, '
            '  p."팀(명함/메일서명)" AS team_signature, '
            '  p."직급(명함/메일서명)" AS title_signature, '
            '  p."담당 교육 영역" AS edu_area '
            "FROM deal d "
            "LEFT JOIN people p ON p.id = d.peopleId "
            f'WHERE d.organizationId IN ({placeholders(org_ids)}) '
            "ORDER BY orgId, personName, d.\"생성 날짜\" IS NULL, d.\"생성 날짜\" DESC",
            tuple(org_ids),
        )

    # 그룹핑: (orgId, personId) 단위
    grouped: Dict[tuple[str | None, str | None], Dict[str, Any]] = {}
    for row in deal_rows:
        key = (row["orgId"], row["personId"])
        entry = grouped.get(key)
        if not entry:
            entry = {
                "orgId": row["orgId"],
                "orgName": org_map.get(row["orgId"], row["orgId"]),
                "orgTotal2025": org_totals.get(row["orgId"], 0.0),
                "personId": row["personId"],
                "personName": row["personName"],
                "upper_org": row["upper_org"],
                "team_signature": row["team_signature"],
                "title_signature": row["title_signature"],
                "edu_area": row["edu_area"],
                "deals": [],
            }
            grouped[key] = entry
        entry["deals"].append(
            {
                "dealId": row["dealId"],
                "dealName": row["dealName"],
                "status": row["status"],
                "amount": _to_number(row["amount"]),
                "contract_date": row["contract_date"],
                "created_at": row["created_at"],
                "course_format": row["course_format"],
            }
        )

    # 정렬: 회사명, 사람 이름
    result = list(grouped.values())
    result.sort(
        key=lambda x: (
            -(x.get("orgTotal2025") or 0),
            (x.get("upper_org") or ""),
            (x.get("team_signature") or ""),
            (x.get("personName") or ""),
        )
    )
    return result


def get_won_groups_json(org_id: str, db_path: Path = DB_PATH) -> Dict[str, Any]:
    """
    Build grouped JSON by upper_org -> team for organizations that have Won deals in 2023/2024/2025.
    Each group includes all deals (any status) for people in that upper_org/team, attached people info,
    deal memos, people memos, and submitted webform names. Organization meta and memos are included.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    def _normalize_upper(val: Any) -> str:
        cleaned = (val or "").strip()
        return cleaned if cleaned else "미입력"

    def _normalize_team(val: Any) -> str:
        cleaned = (val or "").strip()
        return cleaned if cleaned else "미입력"

    def _parse_webforms(raw: Any) -> List[Dict[str, Any]]:
        data = _safe_json_load(raw)
        items: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            return items
        for entry in data:
            if isinstance(entry, dict):
                wf_id = entry.get("id") or entry.get("webFormId") or entry.get("webformId")
                name = entry.get("name") or entry.get("title")
                if name or wf_id:
                    items.append({"id": wf_id, "name": name or ""})
            elif isinstance(entry, str) and entry.strip():
                items.append({"id": None, "name": entry.strip()})
        return items
    def _build_history_index(conn: sqlite3.Connection, people_ids: List[str]) -> Dict[tuple[str, str], List[str]]:
        if not people_ids:
            return {}
        placeholders = ",".join("?" for _ in people_ids)
        try:
            rows = _fetch_all(
                conn,
                f"SELECT peopleId, webFormId, createdAt FROM webform_history WHERE peopleId IN ({placeholders})",
                tuple(people_ids),
            )
        except sqlite3.OperationalError as exc:
            # Older DB without webform_history table
            if "no such table" in str(exc):
                return {}
            raise
        history: Dict[tuple[str, str], List[str]] = {}
        for row in rows:
            pid = str(row["peopleId"] or "").strip()
            wf_id = str(row["webFormId"] or "").strip()
            if not pid or not wf_id:
                continue
            date = _date_only(row["createdAt"])
            if not date:
                continue
            key = (pid, wf_id)
            dates = history.setdefault(key, [])
            if date not in dates:
                dates.append(date)
        return history

    with _connect(db_path) as conn:
        org_rows = _fetch_all(
            conn,
            'SELECT id, COALESCE("이름", id) AS name, "기업 규모" AS size, "업종" AS industry, '
            '  "업종 구분(대)" AS industry_major, "업종 구분(중)" AS industry_mid '
            "FROM organization WHERE id = ? LIMIT 1",
            (org_id,),
        )
        if not org_rows:
            return {"organization": None, "groups": []}
        org_row = org_rows[0]
        has_memo_html = _has_column(conn, "memo", "htmlBody")
        org_meta = {
            "id": org_row["id"],
            "name": org_row["name"],
            "size": org_row["size"],
            "industry": org_row["industry"],
            "industry_major": org_row["industry_major"],
            "industry_mid": org_row["industry_mid"],
        }

        people_rows = _fetch_all(
            conn,
            'SELECT id, COALESCE("이름", id) AS name, "소속 상위 조직" AS upper_org, '
            '"팀(명함/메일서명)" AS team_signature, "직급(명함/메일서명)" AS title_signature, '
            '"담당 교육 영역" AS edu_area, "제출된 웹폼 목록" AS webforms '
            "FROM people WHERE organizationId = ?",
            (org_id,),
        )
        people_ids = [row["id"] for row in people_rows if row["id"]]
        webform_history_index = _build_history_index(conn, people_ids)
        people_map: Dict[str, Dict[str, Any]] = {}
        for row in people_rows:
            pid = row["id"]
            upper = _normalize_upper(row["upper_org"])
            team_sig = _normalize_team(row["team_signature"])
            webform_entries = _parse_webforms(row["webforms"])

            def _attach_date(entry: Dict[str, Any]) -> Dict[str, Any]:
                wf_id = entry.get("id")
                dates = webform_history_index.get((pid, wf_id)) if wf_id else None
                if not dates:
                    date_value: str | list[str] = "날짜 확인 불가"
                else:
                    unique_dates = sorted(set(dates))
                    if len(unique_dates) == 1:
                        date_value = unique_dates[0]
                    else:
                        date_value = unique_dates
                cleaned = {"name": entry.get("name", "")}
                cleaned["date"] = date_value
                return cleaned

            people_map[pid] = {
                "id": pid,
                "name": row["name"],
                "upper_org": upper,
                "team": team_sig,
                "team_signature": row["team_signature"],
                "title_signature": row["title_signature"],
                "edu_area": row["edu_area"],
                "webforms": [_attach_date(entry) for entry in webform_entries],
            }

        deal_rows = _fetch_all(
            conn,
            'SELECT '
            '  id, peopleId, organizationId, COALESCE("이름", id) AS name, '
            '  "팀" AS team, "담당자" AS owner_json, "상태" AS status, '
            '  "성사 가능성" AS probability, "수주 예정일" AS expected_date, '
            '  "예상 체결액" AS expected_amount, "LOST 확정일" AS lost_confirmed_at, '
            '  "이탈 사유" AS lost_reason, "과정포맷" AS course_format, '
            '  "카테고리" AS category, "계약 체결일" AS contract_date, '
            '  "금액" AS amount, "수강시작일" AS start_date, "수강종료일" AS end_date, '
            '  "Net(%)" AS net_percent, "생성 날짜" AS created_at '
            "FROM deal WHERE organizationId = ?",
            (org_id,),
        )

        # Memo preloading (single pass)
        memo_select = (
            "SELECT id, dealId, peopleId, organizationId, text, createdAt"
            + (", htmlBody" if has_memo_html else "")
            + " FROM memo WHERE organizationId = ?"
        )
        memo_rows = _fetch_all(conn, memo_select, (org_id,))

    # Build memo lookup maps outside connection
    person_memos: Dict[str, List[Dict[str, Any]]] = {}
    deal_memos: Dict[str, List[Dict[str, Any]]] = {}
    org_memos: List[Dict[str, Any]] = []
    for memo in memo_rows:
        date_only = _date_only(memo["createdAt"])
        cleaned = _clean_form_memo(memo["text"])
        html_body = memo["htmlBody"] if "htmlBody" in memo.keys() else None
        if cleaned == "":
            # Skip low-value form memos
            continue
        if cleaned is None:
            entry = {"date": date_only, "text": memo["text"], "htmlBody": html_body}
        else:
            # Replace text with structured cleanText
            entry = {"date": date_only, "cleanText": cleaned, "htmlBody": html_body}
        deal_id = memo["dealId"]
        person_id = memo["peopleId"]
        org_only = memo["organizationId"]
        if deal_id:
            deal_memos.setdefault(deal_id, []).append(entry)
        elif person_id:
            person_memos.setdefault(person_id, []).append(entry)
        elif org_only:
            org_memos.append(entry)

    # Determine target upper_org set (Won in 2023/2024/2025)
    target_uppers: set[str] = set()
    for row in deal_rows:
        status = row["status"]
        if status != "Won":
            continue
        year = str(row["contract_date"] or "")[:4]
        if year not in YEARS_FOR_WON:
            continue
        pid = row["peopleId"]
        person = people_map.get(pid)
        upper = person["upper_org"] if person else "미입력"
        target_uppers.add(upper)

    if not target_uppers:
        return {"organization": {**org_meta, "memos": org_memos}, "groups": []}

    groups: Dict[tuple[str, str], Dict[str, Any]] = {}

    def _ensure_group(upper: str, team: str) -> Dict[str, Any]:
        key = (upper, team)
        if key not in groups:
            groups[key] = {"upper_org": upper, "team": team, "deals": [], "people": []}
        return groups[key]

    # Populate people per group (only those belonging to target uppers)
    for person in people_map.values():
        if person["upper_org"] not in target_uppers:
            continue
        group = _ensure_group(person["upper_org"], person["team"])
        group["people"].append(
            {
                "id": person["id"],
                "name": person["name"],
                "upper_org": person["upper_org"],
                "team": person["team_signature"],
                "title": person["title_signature"],
                "edu_area": person["edu_area"],
                "webforms": person["webforms"],
                "memos": person_memos.get(person["id"], []),
            }
        )

    # Populate deals per group (all statuses for target uppers)
    for row in deal_rows:
        pid = row["peopleId"]
        person = people_map.get(pid)
        if not person or person["upper_org"] not in target_uppers:
            continue
        group = _ensure_group(person["upper_org"], person["team"])
        owner = _safe_json_load(row["owner_json"])
        if isinstance(owner, dict):
            owner_name = owner.get("name") or owner.get("id")
        else:
            owner_name = owner
        group["deals"].append(
            {
                "id": row["id"],
            "created_at": _date_only(row["created_at"]),
            "name": row["name"],
            "team": row["team"],
            "owner": owner_name,
            "status": row["status"],
            "probability": row["probability"],
            "expected_date": _date_only(row["expected_date"]),
            "expected_amount": _to_number(row["expected_amount"]),
            "lost_confirmed_at": _date_only(row["lost_confirmed_at"]),
            "lost_reason": row["lost_reason"],
            "course_format": row["course_format"],
            "category": row["category"],
            "contract_date": _date_only(row["contract_date"]),
            "amount": _to_number(row["amount"]),
            "start_date": _date_only(row["start_date"]),
            "end_date": _date_only(row["end_date"]),
            "net_percent": row["net_percent"],
                "people": {
                    "id": person["id"],
                    "name": person["name"],
                    "upper_org": person["upper_org"],
                    "team": person["team_signature"],
                    "title": person["title_signature"],
                    "edu_area": person["edu_area"],
                },
                "memos": deal_memos.get(row["id"], []),
            }
        )

    groups_list = list(groups.values())
    groups_list.sort(key=lambda g: (g["upper_org"], g["team"]))

    return {
        "organization": {**org_meta, "memos": org_memos},
        "groups": groups_list,
    }


def get_deal_check(team_key: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")
    allowed_members = _dealcheck_members(team_key)

    retention_org_ids: Set[str] = set()
    org_won_2025_total: Dict[str, float] = {}

    with _connect(db_path) as conn:
        planning_col = _pick_column(conn, "deal", ["기획시트 링크"])
        planning_col_expr = f"{_dq(planning_col)} AS planning_sheet_link" if planning_col else "NULL AS planning_sheet_link"
        lost_col = _pick_column(conn, "deal", ["LOST 확정일", "Lost 확정일", "lost_confirmed_at"])
        lost_col_expr = f"d.{_q(lost_col)} AS lost_confirmed_date_raw" if lost_col else "NULL AS lost_confirmed_date_raw"
        won_rows = _fetch_all(
            conn,
            'SELECT organizationId AS org_id, "금액" AS amount '
            "FROM deal "
            "WHERE \"상태\" = 'Won' "
            "AND \"계약 체결일\" LIKE '2025%' "
            "AND organizationId IS NOT NULL",
        )

        for row in won_rows:
            org_id = row["org_id"]
            if not org_id:
                continue
            amount = _to_number(row["amount"])
            if amount is None or amount < 0:
                continue
            retention_org_ids.add(org_id)
            org_won_2025_total[org_id] = org_won_2025_total.get(org_id, 0.0) + amount

        rows = _fetch_all(
            conn,
            "SELECT "
            "  d.id AS deal_id, "
            "  d.peopleId AS people_id, "
            "  d.organizationId AS deal_org_id, "
            "  d.\"생성 날짜\" AS created_at, "
            "  d.\"이름\" AS deal_name, "
            "  d.\"과정포맷\" AS course_format, "
            "  d.\"담당자\" AS owner_json, "
            "  d.\"성사 가능성\" AS probability, "
            "  d.\"수주 예정일\" AS expected_close_date, "
            "  d.\"예상 체결액\" AS expected_amount, "
            f"  {planning_col_expr}, "
            "  d.\"상태\" AS status_raw, "
            "  d.\"계약 체결일\" AS contract_date_raw, "
            f"  {lost_col_expr}, "
            "  p.\"소속 상위 조직\" AS upper_org, "
            "  p.\"팀(명함/메일서명)\" AS team_signature, "
            "  p.id AS person_id, "
            "  p.\"이름\" AS person_name, "
            "  COALESCE(d.organizationId, p.organizationId) AS org_id, "
            "  o.\"이름\" AS org_name, "
            "  mc.memoCount AS memo_count "
            "FROM deal d "
            "LEFT JOIN people p ON p.id = d.peopleId "
            "LEFT JOIN organization o ON o.id = COALESCE(d.organizationId, p.organizationId) "
            "LEFT JOIN ("
            "  SELECT dealId, COUNT(*) AS memoCount "
            "  FROM memo "
            "  WHERE dealId IS NOT NULL AND TRIM(dealId) <> '' "
            "  GROUP BY dealId"
            ") mc ON mc.dealId = d.id "
            "WHERE d.\"상태\" IN ('SQL', 'Won', 'Lost', 'LOST')",
        )

    items: List[Dict[str, Any]] = []
    today_kst = _today_kst_date()
    WINDOW_BDAYS = 10

    for row in rows:
        owner_names_raw = _parse_owner_names(row["owner_json"])
        if not owner_names_raw:
            continue
        normalized_owners = _parse_owner_names_normalized(row["owner_json"])
        if not any(name in allowed_members for name in normalized_owners):
            continue

        status_raw = row["status_raw"]
        status_norm = _status_norm(status_raw)

        # Visibility filter by status
        show = False
        if status_norm == "other" or status_norm == "convert":
            continue
        if status_norm == "won":
            contract_dt = _parse_kst_date_best_effort(row["contract_date_raw"])
            if contract_dt and _within_last_n_business_days(contract_dt, today_kst, WINDOW_BDAYS):
                show = True
            else:
                if contract_dt is not None:
                    show = False
                else:
                    expected_dt = _parse_kst_date_best_effort(row["expected_close_date"])
                    show = _within_last_n_business_days(expected_dt, today_kst, WINDOW_BDAYS)
        elif status_norm == "lost":
            lost_dt = _parse_kst_date_best_effort(row["lost_confirmed_date_raw"])
            show = _within_last_n_business_days(lost_dt, today_kst, WINDOW_BDAYS)
        else:
            # status_norm == "won" handled above, convert handled at top, so remaining is SQL
            show = True

        if not show:
            continue

        org_id = row["org_id"]
        org_name = row["org_name"] or org_id or "-"
        raw_planning = row["planning_sheet_link"]
        planning_link = None
        if raw_planning is not None:
            trimmed = str(raw_planning).strip()
            planning_link = trimmed if trimmed else None
        items.append(
            {
                "dealId": row["deal_id"],
                "orgId": org_id,
                "orgName": org_name,
                "upperOrg": row["upper_org"],
                "teamSignature": row["team_signature"],
                "personId": row["person_id"],
                "personName": row["person_name"],
                "createdAt": row["created_at"],
                "dealName": row["deal_name"],
                "courseFormat": row["course_format"],
                "owners": owner_names_raw,
                "probability": row["probability"],
                "expectedCloseDate": row["expected_close_date"],
                "expectedAmount": _to_number(row["expected_amount"]),
                "planningSheetLink": planning_link,
                "memoCount": int(row["memo_count"] or 0),
                "isRetention": bool(org_id and org_id in retention_org_ids),
                "orgWon2025Total": org_won_2025_total.get(org_id, 0.0) if org_id else 0.0,
                "status": status_norm,
            }
        )

    items.sort(
        key=lambda x: (
            -(x.get("orgWon2025Total") or 0.0),
            x.get("createdAt") or "",
            x.get("dealId") or "",
        )
    )
    return items


def get_edu1_deal_check_sql_deals(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    return get_deal_check("edu1", db_path=db_path)


def get_edu2_deal_check_sql_deals(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    return get_deal_check("edu2", db_path=db_path)


def get_ops_2026_online_retention(db_path: Path = DB_PATH) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        start_col = _pick_column(conn, "deal", ["수강시작일", "수강 시작일"])
        end_col = _pick_column(conn, "deal", ["수강종료일", "수강 종료일"])
        course_id_col = _pick_column(conn, "deal", ["코스 ID", "코스ID", "courseId", "course_id"])
        online_cycle_col = _pick_column(conn, "deal", ["(온라인)입과 주기", "온라인 입과 주기", "온라인입과주기"])
        online_first_col = _pick_column(conn, "deal", ["(온라인)최초 입과 여부", "온라인 최초 입과 여부", "온라인 최초입과 여부"])

        conditions: List[str] = ['d."상태" = \'Won\'', 'd."생성 날짜" >= \'2024-01-01\'']
        params: List[Any] = []
        conditions.append('d."과정포맷" IN (?, ?, ?)')
        params.extend(list(ONLINE_COURSE_FORMATS))
        if start_col:
            conditions.append(f'{_dq(start_col)} IS NOT NULL AND TRIM({_dq(start_col)}) <> \'\'')
        if end_col:
            conditions.append(f'{_dq(end_col)} IS NOT NULL AND TRIM({_dq(end_col)}) <> \'\'')
            conditions.append(f'{_dq(end_col)} >= ? AND {_dq(end_col)} <= ?')
            params.extend(["2024-10-01", "2027-12-31"])
        if course_id_col:
            conditions.append(f'{_dq(course_id_col)} IS NOT NULL AND TRIM({_dq(course_id_col)}) <> \'\'')

        memo_subquery = """
          SELECT dealId, COUNT(*) AS memoCount
          FROM memo
          WHERE dealId IS NOT NULL AND TRIM(dealId) <> ''
          GROUP BY dealId
        """
        query = f"""
          SELECT
            d.id AS deal_id,
            d.organizationId AS org_id,
            COALESCE(o."이름", d.organizationId) AS org_name,
            p."소속 상위 조직" AS upper_org,
            p."팀(명함/메일서명)" AS team_signature,
            p.id AS person_id,
            p."이름" AS person_name,
            d."생성 날짜" AS created_at,
            d."이름" AS deal_name,
            d."과정포맷" AS course_format,
            d."상태" AS status,
            d."금액" AS amount,
            {_dq(online_cycle_col)} AS online_cycle,
            {_dq(online_first_col)} AS online_first,
            {_dq(start_col)} AS start_date,
            {_dq(end_col)} AS end_date,
            d."담당자" AS deal_owner_json,
            p."담당자" AS people_owner_json,
            mc.memoCount AS memo_count
          FROM deal d
          LEFT JOIN people p ON p.id = d.peopleId
          LEFT JOIN organization o ON o.id = COALESCE(d.organizationId, p.organizationId)
          LEFT JOIN ({memo_subquery}) mc ON mc.dealId = d.id
          WHERE {' AND '.join(conditions)}
          ORDER BY {_dq(end_col) if end_col else 'd."생성 날짜"'}, org_name, d.id
        """
        rows = _fetch_all(conn, query, params)

    items: List[Dict[str, Any]] = []
    for row in rows:
        amount = _to_number(row["amount"])
        if amount is None:
            continue
        start_date = _date_only(row["start_date"]) if "start_date" in row.keys() else ""
        end_date = _date_only(row["end_date"]) if "end_date" in row.keys() else ""
        if not start_date or not end_date:
            continue
        owners = _parse_owner_names_preferred(row["deal_owner_json"], row["people_owner_json"])
        items.append(
            {
                "dealId": row["deal_id"],
                "orgId": row["org_id"],
                "orgName": row["org_name"],
                "upperOrg": row["upper_org"],
                "teamSignature": row["team_signature"],
                "personId": row["person_id"],
                "personName": row["person_name"],
                "createdAt": row["created_at"],
                "dealName": row["deal_name"],
                "courseFormat": row["course_format"],
                "owners": owners,
                "status": row["status"],
                "amount": amount,
                "onlineCycle": row["online_cycle"],
                "onlineFirst": row["online_first"],
                "startDate": start_date,
                "endDate": end_date,
                "memoCount": int(row["memo_count"] or 0),
            }
        )

    items.sort(key=lambda r: (r.get("endDate") or "", r.get("orgName") or "", r.get("dealId") or ""))
    db_version = None
    try:
        stat = db_path.stat()
        db_version = f"db_mtime:{int(stat.st_mtime)}"
    except Exception:
        db_version = None
    return {"items": items, "meta": {"db_version": db_version, "rowCount": len(items)}}


def _qc_rule_labels() -> Dict[str, str]:
    return {code: label for code, label in QC_RULES}


def _qc_pick_columns(conn: sqlite3.Connection) -> Tuple[Dict[str, Optional[str]], List[str]]:
    schema_missing: List[str] = []
    def pick(cands: Sequence[str], name: str) -> Optional[str]:
        col = _pick_column(conn, "deal", cands)
        if col is None:
            schema_missing.append(name)
        return col

    cols = {
        "expected_close": pick(["수주 예정일", "수주 예정일(종합)"], "expected_close_date"),
        "expected_amount": pick(["예상 체결액", "수주 예정액(종합)"], "expected_amount"),
        "contract_signed": pick(["계약 체결일", "계약체결일"], "contract_signed_date"),
        "start_date": pick(["수강시작일", "courseStartDate"], "course_start_date"),
        "end_date": pick(["수강종료일", "courseEndDate"], "course_end_date"),
        "course_format": pick(["과정포맷", "category1"], "course_format"),
        "course_category": pick(["과정 카테고리", "카테고리"], "course_category"),
        "course_id": pick(["코스 ID", "코스ID"], "course_id"),
        "online_cycle": pick(["(온라인)입과 주기", "온라인 입과 주기"], "online_cycle"),
        "online_first": pick(["(온라인)입과 첫 회차", "온라인 입과 첫 회차"], "online_first"),
        "instructor_name1": pick(["강사 이름1", "강사1 이름"], "instructor_name1"),
        "instructor_fee1": pick(["강사비1", "강사비"], "instructor_fee1"),
        "proposal_written": pick(["제안서 작성 여부"], "proposal_written"),
        "proposal_upload": pick(["업로드 제안서명"], "proposal_upload"),
        "probability": pick(["성사 가능성"], "probability"),
        "created_at": pick(["생성 날짜", "생성일", "createdAt", "created_at", "created_at_utc"], "created_at"),
        "status": pick(["상태"], "status"),
        "amount": pick(["금액"], "amount"),
        "owner": pick(["담당자"], "owner"),
        "deal_name": pick(["이름", "name"], "deal_name"),
    }
    return cols, schema_missing


def _qc_team_for_owner(owner: str) -> Optional[str]:
    norm = normalize_owner_name(owner)
    for tk in ("edu1", "edu2", "public"):
        if norm in _qc_members(tk):
            return tk
    return None


def _qc_compute(team: str, db_path: Path = DB_PATH, include_hidden: bool = False) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")
    if team not in {"all", "edu1", "edu2", "public"}:
        raise ValueError(f"Unsupported team: {team}")

    with _connect(db_path) as conn:
        cols, schema_missing = _qc_pick_columns(conn)
        select_fields = [
            "d.id AS deal_id",
            f"COALESCE({_dq(cols['deal_name'])}, d.id) AS deal_name",
            f"{_dq(cols['owner'])} AS owner_json",
            f"{_dq(cols['status'])} AS status_raw",
            f"{_dq(cols['probability'])} AS probability_raw",
            f"{_dq(cols['amount'])} AS amount_raw",
            f"{_dq(cols['expected_amount'])} AS expected_amount_raw",
            f"{_dq(cols['expected_close'])} AS expected_close_date",
            f"{_dq(cols['contract_signed'])} AS contract_signed_date",
            f"{_dq(cols['start_date'])} AS course_start_date",
            f"{_dq(cols['end_date'])} AS course_end_date",
            f"{_dq(cols['course_format'])} AS course_format",
            f"{_dq(cols['course_category'])} AS course_category",
            f"{_dq(cols['course_id'])} AS course_id",
            f"{_dq(cols['online_cycle'])} AS online_cycle",
            f"{_dq(cols['online_first'])} AS online_first",
            f"{_dq(cols['instructor_name1'])} AS instructor_name1",
            f"{_dq(cols['instructor_fee1'])} AS instructor_fee1",
            f"{_dq(cols['proposal_written'])} AS proposal_written",
            f"{_dq(cols['proposal_upload'])} AS proposal_upload",
            f"{_dq(cols['created_at'])} AS created_at",
            "d.organizationId AS org_id",
            'COALESCE(o."이름", d.organizationId) AS org_name',
            'o."기업 규모" AS org_size_raw',
            "d.peopleId AS people_id",
            'COALESCE(p."이름", p.id) AS people_name',
            'p."소속 상위 조직" AS upper_org',
            'p."팀(명함/메일서명)" AS team_signature',
            'p."직급(명함/메일서명)" AS title_signature',
            'p."담당 교육 영역" AS edu_area',
        ]
        query = (
            "SELECT "
            + ", ".join(select_fields)
            + " FROM deal d "
              "LEFT JOIN people p ON p.id = d.peopleId "
              "LEFT JOIN organization o ON o.id = COALESCE(d.organizationId, p.organizationId) "
        )
        rows = _fetch_all(conn, query)

    allowed_members = _qc_members(team)
    meta_dq = {
        "excluded_not_in_team": 0,
        "excluded_name_contains_nonrevenue": 0,
        "excluded_before_since": 0,
        "excluded_owner_empty": 0,
    }
    rules_map = _qc_rule_labels()
    people_summary: Dict[str, Dict[str, Any]] = {}
    details_by_owner: Dict[str, List[Dict[str, Any]]] = {}

    for row in rows:
        owner_list = _parse_owner_names(row["owner_json"])
        owner_norms = _parse_owner_names_normalized(row["owner_json"])
        owner_display = owner_list[0] if owner_list else ""
        owner_norm = owner_norms[0] if owner_norms else ""
        if not owner_norm:
            meta_dq["excluded_owner_empty"] += 1
            continue
        owner_team = _qc_team_for_owner(owner_norm)
        if not owner_team:
            meta_dq["excluded_not_in_team"] += 1
            continue
        if team != "all" and owner_team != team:
            meta_dq["excluded_not_in_team"] += 1
            continue

        deal_name = str(row["deal_name"] or "").strip()
        if "비매출입과" in deal_name:
            meta_dq["excluded_name_contains_nonrevenue"] += 1
            continue

        created_at = _parse_date(row["created_at"])
        if created_at and created_at < QC_SINCE_DATE:
            meta_dq["excluded_before_since"] += 1
            continue

        # 딜/담당자 예외 제거
        if owner_display == "김민선" and deal_name in {"신세계백화점_직급별 생성형 AI", "우리은행_WLT II DT 평가과정"}:
            continue
        if owner_display == "김윤지" and deal_name.startswith("현대씨앤알_콘텐츠 임차_"):
            continue

        status_n = _status_norm(row["status_raw"])
        prob_n = _prob_norm(row["probability_raw"], status_n)
        amount_val = _to_number(row["amount_raw"])
        expected_amount_val = _to_number(row["expected_amount_raw"])
        contract_date = _parse_date(row["contract_signed_date"])
        expected_close = _parse_date(row["expected_close_date"])
        start_date = _parse_date(row["course_start_date"])
        end_date = _parse_date(row["course_end_date"])
        course_fmt = (row["course_format"] or "").strip()
        course_category = (row["course_category"] or "").strip()
        course_id = (row["course_id"] or "").strip()
        online_cycle = (row["online_cycle"] or "").strip()
        online_first = (row["online_first"] or "").strip()
        instructor_name1 = (row["instructor_name1"] or "").strip()
        instructor_fee1 = _to_number(row["instructor_fee1"])
        org_size_group = infer_size_group(row["org_name"], row["org_size_raw"])

        issues: List[str] = []

        if status_n == "won" and _missing_str(contract_date):
            issues.append("R1")
        if status_n == "won" and _missing_num(amount_val):
            issues.append("R2")
        if status_n == "won" and (_missing_str(start_date) or _missing_str(end_date)):
            issues.append("R3")
        if status_n == "won" and _missing_str(course_id):
            issues.append("R4")
        if status_n == "won" and prob_n != "확정":
            issues.append("R5")
        if status_n == "lost" and prob_n != "LOST":
            issues.append("R6")
        if contract_date and start_date and contract_date > start_date:
            if (contract_date.year, contract_date.month) != (start_date.year, start_date.month):
                exempt_r7 = False
                if course_fmt in ONLINE_COURSE_FORMATS:
                    exempt_r7 = True
                if owner_display == "강진우" and (row["org_name"] or "") in {"홈앤서비스", "엔씨소프트", "엘지전자"}:
                    exempt_r7 = True
                if not exempt_r7:
                    issues.append("R7")
        if created_at and (date.today() - created_at).days >= 7 and _missing_str(course_category):
            if cols["course_category"]:
                issues.append("R8")
        if created_at and (date.today() - created_at).days >= 7 and _missing_str(course_fmt):
            if cols["course_format"]:
                issues.append("R9")
        if prob_n == "높음" and _missing_str(expected_close):
            issues.append("R10")
        if status_n == "convert":
            issues.append("R11")
        if prob_n in {"확정", "높음"} and _missing_num(amount_val) and _missing_num(expected_amount_val):
            issues.append("R12")
        size_group = infer_size_group(row["org_name"], row["org_size_raw"])
        person_meta_missing = is_missing_person_meta(
            row["upper_org"], row["team_signature"], row["title_signature"], row["edu_area"]
        )
        month_exception = is_month_exception(owner_norm, deal_name)

        if is_large_or_mid(size_group) and status_n in {"won", "sql"} and person_meta_missing and not month_exception:
            issues.append("R13")
        if status_n == "won" and course_fmt in ONLINE_COURSE_FORMATS and _missing_str(online_cycle):
            if cols["online_cycle"]:
                issues.append("R14")
        if status_n == "won" and course_fmt and course_fmt not in ONLINE_COURSE_FORMATS:
            r15_exempt = False
            if owner_display in {"김정은", "이은서"} and _re_month.search(deal_name):
                r15_exempt = True
            if cols["instructor_name1"] and _missing_str(instructor_name1) and not r15_exempt:
                issues.append("R15")
        if is_large_or_mid(size_group) and status_n == "lost" and person_meta_missing and not month_exception:
            issues.append("R17")
        # R16: 2025-01-01 이후, 비온라인, 카테고리=생성형AI, 조직 규모=대기업, Won 상태
        if status_n == "won":
            created_at_dt = _parse_date(row["created_at"])
            is_target_date = created_at_dt is not None and created_at_dt >= date(2025, 1, 1)
            is_offline = course_fmt not in ONLINE_COURSE_FORMATS
            is_genai = course_category == "생성형AI"
            is_major = org_size_group == "대기업"
            if is_target_date and is_offline and is_genai and is_major:
                proposal_written = str(row["proposal_written"] or "").strip()
                proposal_upload = str(row["proposal_upload"] or "").strip()
                if _missing_str(proposal_written):
                    issues.append("R16")
                elif proposal_written != "X" and _missing_str(proposal_upload):
                    issues.append("R16")

        issue_count = len(issues)
        if issue_count == 0:
            continue

        person_key = owner_norm
        summary = people_summary.setdefault(
            person_key,
            {
                "ownerName": owner_display or owner_norm,
                "teamKey": owner_team,
                "teamLabel": QC_TEAM_LABELS.get(owner_team, owner_team),
                "totalIssues": 0,
                "dealCount": 0,
                "byRule": {code: 0 for code, _ in QC_RULES},
            },
        )
        summary["totalIssues"] += issue_count
        summary["dealCount"] += 1
        for code in issues:
            summary["byRule"][code] = summary["byRule"].get(code, 0) + 1

        detail = {
            "dealId": row["deal_id"],
            "dealName": deal_name or row["deal_id"],
            "organizationId": row["org_id"],
            "organizationName": row["org_name"],
            "peopleId": row["people_id"],
            "peopleName": row["people_name"],
            "createdAt": _date_only(row["created_at"]),
            "status": row["status_raw"],
            "probability": row["probability_raw"],
            "expectedCloseDate": _date_only(row["expected_close_date"]),
            "contractSignedDate": _date_only(row["contract_signed_date"]),
            "courseStartDate": _date_only(row["course_start_date"]),
            "courseEndDate": _date_only(row["course_end_date"]),
            "expectedAmount": expected_amount_val,
            "amount": amount_val,
            "category": course_category,
            "courseFormat": course_fmt,
            "courseId": course_id,
            "upperOrg": row["upper_org"],
            "teamSignature": row["team_signature"],
            "titleSignature": row["title_signature"],
                "eduArea": row["edu_area"],
                "onlineCycle": online_cycle,
                "onlineFirst": online_first,
                "instructorName1": instructor_name1,
                "instructorFee1": instructor_fee1,
                "proposalWritten": row["proposal_written"],
                "proposalUpload": row["proposal_upload"],
            "issueCodes": issues,
            "issueCount": issue_count,
            "issueDescriptions": [f"{code}: {rules_map.get(code, '')}" for code in issues],
        }
        details_by_owner.setdefault(person_key, []).append(detail)

    if not include_hidden:
        # Apply hidden-rule filtering to details before computing totals exposed to API.
        def _filter_codes(codes: List[str]) -> List[str]:
            return [c for c in codes if c not in QC_HIDDEN_RULE_CODES]

        # Filter per-item codes and recompute issueCount; also strip hidden rule descriptions.
        for owner_key, items in details_by_owner.items():
            for item in items:
                visible_codes = _filter_codes(item.get("issueCodes", []))
                item["issueCodes"] = visible_codes
                item["issueDescriptions"] = [
                    desc for desc in item.get("issueDescriptions", []) if desc.split(":", 1)[0] in visible_codes
                ]
                item["issueCount"] = len(visible_codes)

        # Filter rule list for exposure.
        exposed_rules = [(code, label) for code, label in QC_RULES if code not in QC_HIDDEN_RULE_CODES]

        # Recompute people totals excluding hidden codes.
        filtered_people_rows: List[Dict[str, Any]] = []
        for person in people_summary.values():
            filtered_by_rule = {
                code: cnt for code, cnt in person["byRule"].items() if code not in QC_HIDDEN_RULE_CODES
            }
            total_issues = sum(cnt for code, cnt in filtered_by_rule.items() if code not in QC_EXCLUDE_FROM_TOTAL_ISSUES)
            filtered_people_rows.append(
                {
                    **person,
                    "byRule": filtered_by_rule,
                    "totalIssues": total_issues,
                }
            )

        filtered_people_rows.sort(key=lambda r: (-r["totalIssues"], -r["dealCount"], r["ownerName"]))

        return {
            "meta": {
                "as_of": date.today().isoformat(),
                "since": QC_SINCE_DATE.isoformat(),
                "db_mtime": db_path.stat().st_mtime,
                "team": team,
                "schema_missing": schema_missing,
                "dq": meta_dq,
            },
            "rules": [{"code": code, "label": label} for code, label in exposed_rules],
            "people": filtered_people_rows,
            "details_by_owner": details_by_owner,
        }

    # include_hidden=True: return raw (no filtering)
    people_rows = list(people_summary.values())
    people_rows.sort(key=lambda r: (-r["totalIssues"], -r["dealCount"], r["ownerName"]))
    return {
        "meta": {
            "as_of": date.today().isoformat(),
            "since": QC_SINCE_DATE.isoformat(),
            "db_mtime": db_path.stat().st_mtime,
            "team": team,
            "schema_missing": schema_missing,
            "dq": meta_dq,
        },
        "rules": [{"code": code, "label": label} for code, label in QC_RULES],
        "people": people_rows,
        "details_by_owner": details_by_owner,
    }


def get_qc_deal_errors_summary(team: str = "all", db_path: Path = DB_PATH) -> Dict[str, Any]:
    result = _qc_compute(team, db_path=db_path, include_hidden=False)
    # drop details for summary payload
    result.pop("details_by_owner", None)
    return result


def get_qc_deal_errors_for_owner(team: str, owner: str, db_path: Path = DB_PATH) -> Dict[str, Any]:
    result = _qc_compute(team, db_path=db_path, include_hidden=False)
    owner_norm = normalize_owner_name(owner)
    details = result.pop("details_by_owner", {})
    return {
        "meta": result["meta"],
        "rules": result["rules"],
        "owner": {
            "ownerName": owner,
            "teamLabel": QC_TEAM_LABELS.get(team, team),
        },
        "items": details.get(owner_norm, []),
    }


def _qc_monthly_team_members(team: str) -> Set[str]:
    """
    Return normalized owner names for the given QC team (edu1|edu2|public).
    """
    members = _qc_members(team)
    return {m for m in members if m}


def _parse_owner_names_display(raw: Any) -> List[str]:
    """
    Parse owner names for display while keeping normalization consistent with roster matching.
    """
    owners_raw = _parse_owner_names(raw)
    seen: Set[str] = set()
    result: List[str] = []
    for name in owners_raw:
        norm = normalize_owner_name(name) or name.strip()
        if not norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        result.append(norm)
    return result


def _matches_team(owners: Any, team_members: Set[str]) -> bool:
    owner_list = _parse_owner_names(owners)
    if not owner_list:
        return False
    for name in owner_list:
        norm = normalize_owner_name(name)
        if norm and norm in team_members:
            return True
    return False


def get_qc_monthly_revenue_report(
    team: str, year: int, month: int, history_from: str | None = None, db_path: Path = DB_PATH
) -> Dict[str, Any]:
    """
    Build monthly revenue report/review lists for QC.
    - team: edu1|edu2|public
    - year: YYYY
    - month: 1~12
    - history_from: optional 'YYYY-MM' to include review history for past months (inclusive).
    """
    if team not in {"edu1", "edu2", "public"}:
        raise ValueError("team must be one of edu1|edu2|public")
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    if year < 2000 or year > 2100:
        raise ValueError("year must be between 2000 and 2100")
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    accounting_path = Path(os.getenv(ACCOUNTING_DATA_ENV, Path(__file__).parent / "resources" / "accounting data.txt"))
    accounting_ids, accounting_mtime, accounting_status = _load_accounting_course_ids(accounting_path)

    selected_key = f"{year:04d}-{month:02d}"

    history_start_key: str | None = None
    if history_from:
        match = re.match(r"^(\d{4})-(\d{2})$", history_from.strip())
        if not match:
            raise ValueError("history_from must be in YYYY-MM format")
        h_year, h_month = int(match.group(1)), int(match.group(2))
        if h_month < 1 or h_month > 12:
            raise ValueError("history_from month must be between 1 and 12")
        history_start_key = f"{h_year:04d}-{h_month:02d}"
        if history_start_key > selected_key:
            raise ValueError("history_from cannot be later than the selected year/month")

    def _month_iter(start_key: str, end_key: str) -> List[Tuple[int, int, str]]:
        sy, sm = int(start_key[:4]), int(start_key[5:])
        ey, em = int(end_key[:4]), int(end_key[5:])
        cur_y, cur_m = sy, sm
        items: List[Tuple[int, int, str]] = []
        while (cur_y, cur_m) <= (ey, em):
            items.append((cur_y, cur_m, f"{cur_y:04d}-{cur_m:02d}"))
            if cur_m == 12:
                cur_y += 1
                cur_m = 1
            else:
                cur_m += 1
        return items

    months_list = _month_iter(history_start_key or selected_key, selected_key)
    months_set = {key for _, _, key in months_list}

    mtime = db_path.stat().st_mtime
    cache_key = (db_path, mtime, team, year, month, history_start_key, accounting_mtime)
    cached = _QC_MONTHLY_REVENUE_CACHE.get(cache_key)
    if cached:
        return cached

    team_members = _qc_monthly_team_members(team)

    def _parse_date_flexible(val: Any) -> Optional[date]:
        if val is None:
            return None
        text = str(val).strip()
        if not text:
            return None
        # ISO datetime은 그대로 파싱(밀리초 '.' 보존)
        if "T" in text:
            return _parse_date(text)
        # date-only만 구분자 normalize
        standardized = text.replace(".", "-").replace("/", "-")
        return _parse_date(standardized)

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  id, '
            '  "코스 ID" AS course_id, '
            '  "이름" AS deal_name, '
            '  "담당자" AS owner_json, '
            '  "상태" AS status_raw, '
            '  "성사 가능성" AS probability_raw, '
            '  "계약 체결일" AS contract_date_raw, '
            '  "수주 예정일" AS expected_close_date_raw, '
            '  "금액" AS amount_raw, '
            '  "예상 체결액" AS expected_amount_raw, '
            '  "수강시작일" AS start_date_raw, '
            '  "수강종료일" AS end_date_raw '
            "FROM deal",
        )

    collector = ShadowDiffCollector(enabled=_is_shadow_mode())

    report_by_month: Dict[str, List[Dict[str, Any]]] = {}
    review_by_month: Dict[str, List[Dict[str, Any]]] = {}
    missing_accounting: List[Dict[str, Any]] = []
    seen_missing_ids: Set[str] = set()

    for row in rows:
        owners_display = _parse_owner_names_display(row["owner_json"])
        if not owners_display:
            continue
        if not _matches_team(row["owner_json"], team_members):
            continue

        course_id = (row["course_id"] or "").strip()
        deal_name = (row["deal_name"] or "").strip()
        status_norm = _status_norm(row["status_raw"])
        prob_is_high = _prob_is_high(row["probability_raw"]) or _prob_is_high(row["status_raw"])
        contract_date = _parse_date_flexible(row["contract_date_raw"])
        expected_close_date = _parse_date_flexible(row["expected_close_date_raw"])
        amount_val = _to_number(row["amount_raw"])
        expected_amount_val = _to_number(row["expected_amount_raw"])
        start_date = _parse_date_flexible(row["start_date_raw"])
        end_date = _parse_date_flexible(row["end_date_raw"])
        start_date_text = _date_str(start_date, row["start_date_raw"])
        end_date_text = _date_str(end_date, row["end_date_raw"])
        contract_date_text = _date_str(contract_date, row["contract_date_raw"])
        expected_close_text = _date_str(expected_close_date, row["expected_close_date_raw"])
        if collector.enabled:
            for field, raw, legacy_date in [
                ("contractDate", row["contract_date_raw"], _date_only_legacy(row["contract_date_raw"])),
                ("expectedCloseDate", row["expected_close_date_raw"], _date_only_legacy(row["expected_close_date_raw"])),
                ("startDate", row["start_date_raw"], _date_only_legacy(row["start_date_raw"])),
                ("endDate", row["end_date_raw"], _date_only_legacy(row["end_date_raw"])),
            ]:
                strict_date = date_kst.kst_date_only(raw)
                collector.add(field, raw, legacy_date, strict_date, deal_id=row.get("id"))
                if legacy_date and strict_date and len(legacy_date) == 10 and len(strict_date) == 10:
                    collector.add(f"{field}.ym", raw, legacy_date[:7], strict_date[:7], deal_id=row.get("id"))
        report_base_ok = (
            course_id
            and deal_name
            and status_norm == "won"
            and contract_date
            and amount_val is not None
            and not _missing_str(row["start_date_raw"])
            and not _missing_str(row["end_date_raw"])
        )

        # --- Report list (Won, fully populated) ---
        report_month_key = None
        if contract_date:
            report_month_key = f"{contract_date.year:04d}-{contract_date.month:02d}"
        report_condition = (
            report_base_ok
            and report_month_key in months_set
        )
        if report_condition and report_month_key:
            report_by_month.setdefault(report_month_key, []).append(
                {
                    "dealId": row["id"],
                    "courseId": course_id,
                    "dealName": deal_name,
                    "owners": owners_display,
                    "status": row["status_raw"],
                    "contractDate": contract_date_text,
                    "amount": amount_val,
                    "startDate": start_date_text,
                    "endDate": end_date_text,
                }
            )

        # --- Missing accounting audit (prior months, independent of review conditions) ---
        if (
            report_month_key
            and report_base_ok
            and ACCOUNTING_AUDIT_START_KEY <= report_month_key < selected_key
        ):
            norm_course = _normalize_course_id(course_id)
            if norm_course and norm_course not in accounting_ids:
                if row["id"] not in seen_missing_ids:
                    seen_missing_ids.add(row["id"])
                    missing_accounting.append(
                        {
                            "reportMonthKey": report_month_key,
                            "dealId": row["id"],
                            "courseId": course_id,
                            "dealName": deal_name,
                            "owners": owners_display,
                            "status": row["status_raw"],
                            "contractDate": contract_date_text,
                            "amount": amount_val,
                            "startDate": start_date_text,
                            "endDate": end_date_text,
                        }
                    )

        # --- Review list (확정/높음, not already in report) ---
        # Date rule: prefer contract_date if present else expected_close_date.
        date_for_match = contract_date or expected_close_date
        if not date_for_match:
            continue
        month_key_for_review = f"{date_for_match.year:04d}-{date_for_match.month:02d}"
        if month_key_for_review not in months_set:
            continue
        if not prob_is_high:
            continue
        if "[비매출입과]" in deal_name:
            continue
        if report_condition and report_month_key == month_key_for_review:
            continue

        review_by_month.setdefault(month_key_for_review, []).append(
            {
                "dealId": row["id"],
                "courseId": course_id,
                "dealName": deal_name,
                "owners": owners_display,
                "status": row["status_raw"],
                "probability": row["probability_raw"],
                "expectedCloseDate": expected_close_text,
                "contractDate": contract_date_text,
                "expectedAmount": expected_amount_val,
                "amount": amount_val,
                "startDate": start_date_text,
                "endDate": end_date_text,
            }
        )

    for deals in report_by_month.values():
        deals.sort(key=lambda d: (d["contractDate"] or "", d["dealName"], d["dealId"]))
    for deals in review_by_month.values():
        deals.sort(
            key=lambda d: (
                d["contractDate"] or d["expectedCloseDate"] or "",
                d["dealName"] or "",
                d["dealId"] or "",
            )
        )

    if missing_accounting:
        missing_accounting.sort(
            key=lambda d: (
                d["reportMonthKey"],
                d["contractDate"] or "",
                d["dealName"] or "",
                d["dealId"] or "",
            ),
            reverse=True,
        )

    payload = {
        "team": team,
        "year": year,
        "month": month,
        "reportDeals": report_by_month.get(selected_key, []),
        "reviewDeals": review_by_month.get(selected_key, []),
        "counts": {
            "report": len(report_by_month.get(selected_key, [])),
            "review": len(review_by_month.get(selected_key, [])),
            "missingAccounting": len(missing_accounting),
        },
        "meta": {"db_version": mtime, "accounting_status": accounting_status},
        "missingAccountingDeals": missing_accounting,
    }

    if history_start_key:
        history_sections: List[Dict[str, Any]] = []
        for y, m, key in reversed(months_list):
            deals = review_by_month.get(key, [])
            if not deals:
                continue
            history_sections.append(
                {
                    "year": y,
                    "month": m,
                    "monthKey": key,
                    "count": len(deals),
                    "deals": deals,
                }
            )
        payload["reviewHistory"] = history_sections

    collector.emit(
        logging.getLogger(__name__),
        {
            "endpoint": "qc/monthly-revenue-report",
            "team": team,
            "year": year,
            "month": month,
            "historyFrom": history_start_key,
        },
    )
    _QC_MONTHLY_REVENUE_CACHE[cache_key] = payload
    return payload


def get_initial_dashboard_data(db_path: Path = DB_PATH) -> Dict[str, Any]:
    """
    Read the SQLite snapshot and return a JSON-serializable structure for the dashboard.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        has_memo_html = _has_column(conn, "memo", "htmlBody")
        org_rows = _fetch_all(
            conn,
            'SELECT id, COALESCE("이름", id) AS name, "업종" AS industry, "팀" AS team, '
            '"담당자" AS owner, "전화" AS phone, "기업 규모" AS size '
            "FROM organization ORDER BY name",
        )
        people_rows = _fetch_all(
            conn,
            'SELECT id, organizationId, COALESCE("이름", id) AS name, '
            '"직급/직책" AS title, "이메일" AS email, "전화" AS phone, "고객 상태" AS status '
            "FROM people ORDER BY organizationId, name",
        )
        deal_rows = _fetch_all(
            conn,
            'SELECT id, peopleId, organizationId, COALESCE("이름", id) AS name, "상태" AS status, '
            '"금액" AS amount, "예상 체결액" AS expected_amount, "마감일" AS deadline, "수주 예정일" AS expected_date '
            "FROM deal ORDER BY organizationId, peopleId",
        )
        memo_select = (
            "SELECT id, dealId, peopleId, organizationId, text, createdAt, updatedAt, ownerId"
            + (", htmlBody" if has_memo_html else "")
            + " FROM memo"
        )
        memo_rows = _fetch_all(
            conn,
            memo_select,
        )

    organizations = _rows_to_dicts(org_rows)
    people = _rows_to_dicts(people_rows)
    deals = _rows_to_dicts(deal_rows)
    memos = _rows_to_dicts(memo_rows)
    if memos:
        for memo in memos:
            if "htmlBody" not in memo:
                memo["htmlBody"] = None

    deals_by_person: Dict[str, List[Dict[str, Any]]] = {}
    for deal in deals:
        pid = deal.get("peopleId")
        if not pid:
            continue
        deals_by_person.setdefault(pid, []).append(deal)

    people_with_deals: List[Dict[str, Any]] = []
    people_without_deals: List[Dict[str, Any]] = []
    people_by_org: Dict[str, List[Dict[str, Any]]] = {}
    for person in people:
        pid = person.get("id")
        org_id = person.get("organizationId")
        person_deals = deals_by_person.get(pid, [])
        enriched = {**person, "dealCount": len(person_deals)}
        if person_deals:
            people_with_deals.append(enriched)
        else:
            people_without_deals.append(enriched)
        if org_id:
            people_by_org.setdefault(org_id, []).append(enriched)

    deal_memos_by_id: Dict[str, List[Dict[str, Any]]] = {}
    people_memos_by_id: Dict[str, List[Dict[str, Any]]] = {}
    company_memos: Dict[str, List[Dict[str, Any]]] = {}

    for memo in memos:
        deal_id = memo.get("dealId")
        person_id = memo.get("peopleId")
        org_id = memo.get("organizationId")

        if deal_id:
            deal_memos_by_id.setdefault(deal_id, []).append(memo)
            continue
        if person_id:
            people_memos_by_id.setdefault(person_id, []).append(memo)
            continue
        if org_id:
            company_memos.setdefault(org_id, []).append(memo)

    # Filter out organizations without people and without deals (matching original behavior)
    filtered_organizations: List[Dict[str, Any]] = []
    for org in organizations:
        org_id = org.get("id")
        org_people = people_by_org.get(org_id, [])
        has_people = bool(org_people)
        has_deals = any(deals_by_person.get(p.get("id")) for p in org_people)
        if has_people or has_deals:
            filtered_organizations.append(org)

    return {
        "organizations": filtered_organizations,
        "companyMemos": company_memos,
        "peopleWithDeals": people_with_deals,
        "peopleWithoutDeals": people_without_deals,
        "dealsByPersonId": deals_by_person,
        "peopleMemosById": people_memos_by_id,
        "dealMemosById": deal_memos_by_id,
    }


def get_won_totals_by_size(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    Aggregate Won deals by organization size and contract year (2023/2024/2025).
    Missing years default to 0 for simpler rendering.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  COALESCE(o."기업 규모", "미입력") AS size, '
            '  SUBSTR(d."계약 체결일", 1, 4) AS year, '
            '  SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            'WHERE d."상태" = \'Won\' '
            '  AND d."계약 체결일" IS NOT NULL '
            '  AND SUBSTR(d."계약 체결일", 1, 4) IN ("2023", "2024", "2025") '
            "GROUP BY size, year",
        )

    by_size: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        size = (row["size"] or "미입력").strip() or "미입력"
        year = str(row["year"])
        total = _to_number(row["totalAmount"]) or 0.0
        entry = by_size.setdefault(
            size,
            {
                "size": size,
                "won2023": 0.0,
                "won2024": 0.0,
                "won2025": 0.0,
            },
        )
        if year in YEARS_FOR_WON:
            entry[f"won{year}"] += total

    result = list(by_size.values())
    result.sort(key=lambda x: (x["won2023"] + x["won2024"] + x["won2025"]), reverse=True)
    return result


def get_rank_2025_summary_by_size(
    exclude_org_name: str = "삼성전자",
    years: Optional[Sequence[int]] = None,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    """
    Aggregate Won amount by organization size for given years (default 2025/2026), excluding a specific org name.
    Returns cached result per DB mtime + exclude key.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    years_list = [int(y) for y in (years or [2025, 2026]) if y is not None]
    if not years_list:
        years_list = [2025, 2026]
    years_str = [str(y) for y in years_list]
    eff_mode = _effective_date_mode()
    stat = db_path.stat()
    snapshot_version = f"db_mtime:{int(stat.st_mtime)}"

    cache_mode = "strict" if eff_mode == "strict" else "legacy"
    cache_key = (db_path, stat.st_mtime, exclude_org_name or "", tuple(years_list), cache_mode)
    cached = _RANK_2025_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    year_expr = sql_year_expr('d."계약 체결일"', eff_mode)
    years_clause, years_params = sql_years_clause('d."계약 체결일"', years_str, eff_mode)
    params: List[Any] = list(years_params)
    exclude_condition = ""
    if exclude_org_name:
        exclude_condition = ' AND COALESCE(o."이름", d.organizationId) <> ?'
        params.append(exclude_org_name)

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            f'''
            SELECT
              COALESCE(NULLIF(o."기업 규모", ''), '미입력') AS size,
              {year_expr} AS year,
              SUM(CAST(d."금액" AS REAL)) AS totalAmount
            FROM deal d
            LEFT JOIN organization o ON o.id = d.organizationId
            WHERE d."상태" = 'Won'
              AND d."계약 체결일" IS NOT NULL
              AND {years_clause}
              {exclude_condition}
            GROUP BY size, year
            ''',
            params,
        )

    by_size: Dict[str, Dict[str, float]] = {}
    totals = {"sum_2025": 0.0, "sum_2026": 0.0}
    for row in rows:
        size = (row["size"] or "미입력").strip() or "미입력"
        year = str(row["year"])
        amount = _to_number(row["totalAmount"]) or 0.0
        entry = by_size.setdefault(size, {"sum_2025": 0.0, "sum_2026": 0.0})
        if year == "2025":
            entry["sum_2025"] += amount
            totals["sum_2025"] += amount
        elif year == "2026":
            entry["sum_2026"] += amount
            totals["sum_2026"] += amount

    # ensure sizes exist even when missing
    default_sizes = ["대기업", "중견기업", "중소기업", "공공기관", "대학교", "미입력"]
    for size in default_sizes:
        by_size.setdefault(size, {"sum_2025": 0.0, "sum_2026": 0.0})

    result = {
        "snapshot_version": snapshot_version,
        "excluded_org_names": [exclude_org_name] if exclude_org_name else [],
        "years": years_list,
        "by_size": by_size,
        "totals": totals,
    }
    _RANK_2025_SUMMARY_CACHE[cache_key] = result
    return result


def _detect_course_id_column(conn: sqlite3.Connection) -> Optional[str]:
    """
    Find an existing course id column from known candidates.
    Returns the first match or None if nothing is found.
    """
    info_rows = _fetch_all(conn, "PRAGMA table_info('deal')")
    candidates = ["코스 ID", "코스ID", "course_id", "courseId", "Course ID"]
    for row in info_rows:
        name = row["name"]
        if name in candidates:
            return name
    return None


def _compute_existing_org_ids_for_2025(db_path: Path) -> Set[str]:
    """
    Identify orgs with 2025 Won deals that have course_id + start/end date + amount + contract_date in 2025.
    Org id is COALESCE(deal.organizationId, people.organizationId).
    """
    if not db_path.exists():
        return set()
    with _connect(db_path) as conn:
        course_id_col = _detect_course_id_column(conn)
        if not course_id_col:
            return set()
        start_col = _pick_column(conn, "deal", ["수강시작일", "수강 시작일", "start_date", "startDate"])
        end_col = _pick_column(conn, "deal", ["수강종료일", "수강 종료일", "end_date", "endDate"])
        contract_col = _pick_column(conn, "deal", ["계약 체결일", "contract_date", "contractDate"])
        amount_col = _pick_column(conn, "deal", ["금액", "amount"])
        if not start_col or not end_col or not contract_col or not amount_col:
            return set()
        rows = _fetch_all(
            conn,
            f"""
            SELECT
              d."상태" AS status_raw,
              d."{course_id_col}" AS course_id,
              d."{start_col}" AS start_date,
              d."{end_col}" AS end_date,
              d."{contract_col}" AS contract_date,
              d."{amount_col}" AS amount,
              COALESCE(NULLIF(TRIM(d.organizationId), ''), NULLIF(TRIM(p.organizationId), '')) AS org_id
            FROM deal d
            LEFT JOIN people p ON p.id = d.peopleId
            WHERE d."상태" = 'Won'
            """,
        )
    rows = _rows_to_dicts(rows)
    existing: Set[str] = set()
    for row in rows:
        status_norm = _status_norm(row.get("status_raw"))
        if status_norm != "won":
            continue
        org_id = (row.get("org_id") or "").strip()
        if not org_id:
            continue
        course_id = (row.get("course_id") or "").strip()
        if not course_id:
            continue
        amt = _to_number(row.get("amount"))
        if amt is None or amt <= 0:
            continue
        start_dt = _parse_kst_date_best_effort(row.get("start_date"))
        end_dt = _parse_kst_date_best_effort(row.get("end_date"))
        contract_dt = _parse_kst_date_best_effort(row.get("contract_date"))
        if not (start_dt and end_dt and contract_dt):
            continue
        if contract_dt.year != 2025:
            continue
        existing.add(org_id)
    return existing

def _load_perf_monthly_data(db_path: Path) -> Dict[str, Any]:
    """
    Load deals with fields required for monthly performance aggregation.
    Caches per DB mtime to keep summary/drilldown in sync.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime)
    cached = _PERF_MONTHLY_DATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    def has_value(val: Any) -> bool:
        return val is not None and str(val).strip() != ""

    try_query_error = None
    with _connect(db_path) as conn:
        course_id_col = _detect_course_id_column(conn)
        course_id_select = f'd."{course_id_col}" AS course_id' if course_id_col else "NULL AS course_id"
        category_col = _pick_column(conn, "deal", ["카테고리", "category", "Category"])
        category_select = f'd."{category_col}" AS category' if category_col else "NULL AS category"
        base_query = f'''
            SELECT
              d.id AS deal_id,
              d."이름" AS deal_name,
              d.organizationId AS org_id,
              COALESCE(o."이름", d.organizationId) AS org_name,
              o."기업 규모" AS size_raw,
              p."소속 상위 조직" AS upper_org,
              p."이름" AS person_name,
              d."과정포맷" AS course_format,
              d."담당자" AS owner_json,
              d."상태" AS status,
              d."성사 가능성" AS probability,
              d."금액" AS amount,
              d."예상 체결액" AS expected_amount,
              d."계약 체결일" AS contract_date,
              d."수주 예정일" AS expected_close_date,
              d."수강시작일" AS start_date,
              d."수강종료일" AS end_date,
              {course_id_select},
              {category_select}
            FROM deal d
            LEFT JOIN organization o ON o.id = d.organizationId
            LEFT JOIN people p ON p.id = d.peopleId
            WHERE
              (
                d."계약 체결일" LIKE '2025%' OR d."계약 체결일" LIKE '2026%' OR
                d."수주 예정일" LIKE '2025%' OR d."수주 예정일" LIKE '2026%'
              )
        '''
        try:
            rows = _fetch_all(conn, base_query)
        except sqlite3.OperationalError as exc:
            try_query_error = exc
            course_id_col = None
            fallback_query = base_query.replace(course_id_select, "NULL AS course_id")
            rows = _fetch_all(conn, fallback_query)

    major_sizes = {"대기업", "중견기업", "중소기업"}
    collector = ShadowDiffCollector(enabled=_is_shadow_mode())
    data_rows: List[Dict[str, Any]] = []
    for row in rows:
        month_key = _month_key_from_dates(row["contract_date"], row["expected_close_date"])
        if not month_key:
            continue
        if collector.enabled:
            strict_key = date_kst.kst_yymm(row["contract_date"]) or date_kst.kst_yymm(row["expected_close_date"])
            collector.add(
                "month_key",
                row["contract_date"] or row["expected_close_date"],
                month_key,
                strict_key,
                deal_id=row["deal_id"],
            )
        org_name = row["org_name"] or (row["org_id"] or "-")
        size_group = infer_size_group(org_name, row["size_raw"])
        is_major = size_group in major_sizes
        is_online = (row["course_format"] or "").strip() in ONLINE_COURSE_FORMATS
        amount_num = _to_number(row["amount"])
        expected_amount_num = _to_number(row["expected_amount"])
        start_ok = has_value(row["start_date"])
        end_ok = has_value(row["end_date"])
        course_id_ok = True if course_id_col is None else has_value(row["course_id"])

        bucket: Optional[str] = None
        amount_used: float = 0.0

        if (
            (row["status"] or "").strip() == "Won"
            and start_ok
            and end_ok
            and course_id_ok
            and amount_num is not None
        ):
            bucket = "CONTRACT"
            amount_used = amount_num
        elif _prob_equals(row["probability"], "확정"):
            bucket = "CONFIRMED"
            amount_used = _amount_fallback(amount_num, expected_amount_num)
        elif _prob_equals(row["probability"], "높음"):
            bucket = "HIGH"
            amount_used = _amount_fallback(amount_num, expected_amount_num)

        if not bucket:
            continue

        data_rows.append(
            {
                "month": month_key,
                "bucket": bucket,
                "amount_used": float(amount_used or 0.0),
                "amount": amount_num,
                "expected_amount": expected_amount_num,
                "org_name": org_name,
                "upper_org": row["upper_org"] or "미입력",
                "customer_person_name": row["person_name"] or "미입력",
                "deal_id": row["deal_id"],
                "deal_name": row["deal_name"] or row["deal_id"],
                "course_format": row["course_format"],
                "category": row["category"] if "category" in row.keys() else None,
                "day1_owner_names": _parse_owner_names(row["owner_json"]),
                "status": row["status"],
                "probability": row["probability"],
                "expected_close_date": row["expected_close_date"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "course_id": row["course_id"] if course_id_col else None,
                "contract_date": row["contract_date"],
                "is_online": is_online,
                "is_major_size": is_major,
                "org_is_samsung": org_name == "삼성전자",
                "course_id_available": course_id_col is not None,
            }
        )

    payload = {
        "rows": data_rows,
        "snapshot_version": f"db_mtime:{int(stat.st_mtime)}",
        "course_id_available": any(r.get("course_id") is not None for r in data_rows) or course_id_col is not None,
        "try_query_error": str(try_query_error) if try_query_error else None,
    }
    collector.emit(
        logging.getLogger(__name__),
        {"endpoint": "perf/monthly-amounts(load)", "from_month": "2025-01", "to_month": "2026-12"},
    )
    _PERF_MONTHLY_DATA_CACHE[cache_key] = payload
    return payload



def _load_perf_monthly_inquiries_data(db_path: Path, debug: bool = False) -> Dict[str, Any]:
    """
    Load deals for monthly inquiry (deal creation) counts.
    Uses deal."생성 날짜" as month key and filters out Convert / onlineFirst==FALSE.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime)
    cached = _PERF_MONTHLY_INQUIRIES_CACHE.get(cache_key)
    if not debug and cached is not None:
        return cached

    collector = ShadowDiffCollector(enabled=_is_shadow_mode())
    excluded = {"status_convert": 0, "online_first_false": 0, "online_first_missing": 0, "missing_created_at": 0}
    join_source = {"deal_org_used": 0, "people_org_used": 0, "missing_both": 0}
    value_counts_size: Dict[str, int] = {}
    size_raw_counts: Dict[str, int] = {}
    size_group_counts: Dict[str, int] = {}
    join_diag = {
        "deal_org_null": 0,
        "deal_org_blank": 0,
        "people_org_null": 0,
        "people_org_blank": 0,
        "coalesce_org_blank": 0,
        "org_join_miss": 0,
        "org_size_raw_missing": 0,
    }
    sample_join_miss: List[Dict[str, Any]] = []
    sample_size_missing_univ_public: List[Dict[str, Any]] = []
    missing_course_raw = 0
    missing_category_raw = 0
    raw_sizes: Set[str] = set()
    raw_formats: Set[str] = set()
    raw_categories: Set[str] = set()

    with _connect(db_path) as conn:
        created_col = _pick_column(conn, "deal", ["생성 날짜", "생성일", "createdAt", "created_at", "created_at_utc"])
        if not created_col:
            raise ValueError("deal 생성 날짜 컬럼을 찾을 수 없습니다.")
        course_id_col = _detect_course_id_column(conn)
        online_first_col = _pick_column(
            conn,
            "deal",
            [
                "(온라인)최초 입과 여부",
                "온라인최초 입과 여부",
                "온라인 최초 입과 여부",
                "online_first",
                "online_first_enrollment",
                "online_first_enroll",
            ],
        )

        course_id_select = f'd."{course_id_col}" AS course_id' if course_id_col else "NULL AS course_id"
        online_first_select = f'd."{online_first_col}" AS online_first' if online_first_col else "NULL AS online_first"

        year_clause, year_params = sql_years_clause(f'd."{created_col}"', ["2025", "2026"], mode="strict")

        rows = _fetch_all(
            conn,
            f"""
            SELECT
              d.id AS deal_id,
              d."이름" AS deal_name,
              NULLIF(TRIM(d.organizationId), '') AS deal_org_id,
              NULLIF(TRIM(p.organizationId), '') AS people_org_id,
              COALESCE(NULLIF(TRIM(d.organizationId), ''), NULLIF(TRIM(p.organizationId), '')) AS org_id,
              COALESCE(o."이름", COALESCE(NULLIF(TRIM(d.organizationId), ''), NULLIF(TRIM(p.organizationId), ''))) AS org_name,
              o."기업 규모" AS size_raw,
              d."과정포맷" AS course_format_raw,
              d."카테고리" AS category_raw,
              d."상태" AS status,
              d."성사 가능성" AS probability,
              d."예상 체결액" AS expected_amount,
              d."금액" AS amount,
              d."수주 예정일" AS expected_close_date,
              d."계약 체결일" AS contract_date,
              d."수강시작일" AS start_date,
              d."수강종료일" AS end_date,
              d."담당자" AS owner_json,
              p."소속 상위 조직" AS upper_org,
              p."이름" AS person_name,
              d."{created_col}" AS created_at,
              {online_first_select},
              {course_id_select}
            FROM deal d
            LEFT JOIN people p ON p.id = d.peopleId
            LEFT JOIN organization o ON o.id = COALESCE(NULLIF(TRIM(d.organizationId), ''), NULLIF(TRIM(p.organizationId), ''))
            WHERE {year_clause}
            """,
            year_params,
        )
        rows = [dict(r) for r in rows]

    data_rows: List[Dict[str, Any]] = []
    for row in rows:
        month_key = _month_key_from_text(row["created_at"])
        if not month_key:
            excluded["missing_created_at"] += 1
            continue
        if collector.enabled:
            strict_key = date_kst.kst_yymm(row["created_at"])
            collector.add("month_key", row["created_at"], month_key, strict_key, deal_id=row.get("deal_id"))
        status_norm = _status_norm(row["status"])
        if status_norm == "convert":
            excluded["status_convert"] += 1
            continue

        raw_sizes.add((row["size_raw"] or "").strip())
        raw_formats.add((row["course_format_raw"] or "").strip())
        raw_categories.add((row["category_raw"] or "").strip())

        deal_org_id_raw = row.get("deal_org_id_raw")
        people_org_id_raw = row.get("people_org_id_raw")
        if deal_org_id_raw is None:
            join_diag["deal_org_null"] += 1
        elif str(deal_org_id_raw).strip() == "":
            join_diag["deal_org_blank"] += 1
        if people_org_id_raw is None:
            join_diag["people_org_null"] += 1
        elif str(people_org_id_raw).strip() == "":
            join_diag["people_org_blank"] += 1

        deal_org_id = (row.get("deal_org_id") or "").strip()
        people_org_id = (row.get("people_org_id") or "").strip()
        if deal_org_id:
            join_source["deal_org_used"] += 1
        elif people_org_id:
            join_source["people_org_used"] += 1
        else:
            join_source["missing_both"] += 1

        size_raw_key = (row["size_raw"] or "").strip() or "<NULL_OR_EMPTY>"
        size_raw_counts[size_raw_key] = size_raw_counts.get(size_raw_key, 0) + 1
        if not (row.get("org_id") or "").strip():
            join_diag["coalesce_org_blank"] += 1

        org_join_failed = row.get("org_id") and row.get("org_name") is None and row.get("size_raw") is None
        if org_join_failed:
            join_diag["org_join_miss"] += 1
            if len(sample_join_miss) < 20:
                sample_join_miss.append(
                    {
                        "deal_id": row.get("deal_id"),
                        "deal_name": row.get("deal_name"),
                        "deal_org_id": deal_org_id,
                        "people_org_id": people_org_id,
                        "org_id": row.get("org_id"),
                        "org_name": row.get("org_name"),
                        "size_raw": row.get("size_raw"),
                    }
                )

        org_size_raw_missing = size_raw_key == "<NULL_OR_EMPTY>"
        if org_size_raw_missing:
            join_diag["org_size_raw_missing"] += 1
            org_name = (row.get("org_name") or "").strip()
            if (
                len(sample_size_missing_univ_public) < 20
                and (("대학" in org_name) or any(kw in org_name for kw in PUBLIC_KEYWORDS))
            ):
                sample_size_missing_univ_public.append(
                    {
                        "deal_id": row.get("deal_id"),
                        "deal_name": row.get("deal_name"),
                        "org_name": org_name,
                        "org_id": row.get("org_id"),
                        "size_raw": row.get("size_raw"),
                    }
                )

        course_format_norm = _normalize_course_format(row["course_format_raw"])
        is_online_fmt = course_format_norm in ONLINE_COURSE_FORMATS

        if online_first_col and is_online_fmt and _is_false_like(row["online_first"]):
            excluded["online_first_false"] += 1
            continue
        if online_first_col and is_online_fmt and _missing_str(row["online_first"]):
            excluded["online_first_missing"] += 1

        size_group = _normalize_inquiry_size(row["org_name"], row["size_raw"])
        value_counts_size[size_group] = value_counts_size.get(size_group, 0) + 1
        size_group_counts[size_group] = size_group_counts.get(size_group, 0) + 1

        course_format = _normalize_inquiry_course_format(row["course_format_raw"])
        if not (row["course_format_raw"] or "").strip():
            missing_course_raw += 1

        category_group = _map_inquiry_category_group(row["category_raw"])
        if not (row["category_raw"] or "").strip():
            missing_category_raw += 1
        owner_names = _parse_owner_names(row["owner_json"])

        data_rows.append(
            {
                "deal_id": row["deal_id"],
                "deal_name": row["deal_name"],
            "org_id": row["org_id"],
            "org_name": row["org_name"],
                "size_group": size_group,
                "course_format": course_format,
                "category_group": category_group,
                "category": row["category_raw"],
                "month": month_key,
                "owner_names": owner_names,
                "upper_org": row["upper_org"],
                "person_name": row["person_name"],
                "status": row["status"],
                "probability": row["probability"],
                "expected_close_date": row["expected_close_date"],
                "expected_amount": _to_number(row["expected_amount"]),
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "course_id": row["course_id"],
                "contract_date": row["contract_date"],
                "amount": _to_number(row["amount"]),
            }
        )

    payload = {
        "rows": data_rows,
        "snapshot_version": f"db_mtime:{int(stat.st_mtime)}",
        "meta_debug": {
            "impl_tag": "inq_v1_people_nullif_trim",
            "excluded": excluded,
            "value_counts": {
                "sizeGroup": value_counts_size,
                "courseFormat_missing_raw": missing_course_raw,
                "category_missing_raw": missing_category_raw,
                "size_raw_counts": size_raw_counts,
                "size_group_counts": size_group_counts,
            },
            "join_source": join_source,
            "join_diag": {
                **join_diag,
                "sample_join_miss": sample_join_miss,
                "sample_size_missing_univ_public": sample_size_missing_univ_public,
            },
            "raw_samples": {
                "size_raw_unique_top": list(itertools.islice(raw_sizes, 20)),
                "course_format_raw_unique_top": list(itertools.islice(raw_formats, 20)),
                "category_raw_unique_top": list(itertools.islice(raw_categories, 20)),
            },
        },
    }
    if not debug:
        _PERF_MONTHLY_INQUIRIES_CACHE[cache_key] = payload
    collector.emit(logging.getLogger(__name__), {"endpoint": "perf/monthly-inquiries(load)", "created_col": created_col})
    return payload

 
 
def _load_perf_monthly_close_rate_data(db_path: Path = DB_PATH) -> Dict[str, Any]:
    """
    Load deals for close-rate aggregation (확정/높음/낮음/LOST) per month/size/course group.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime)
    cached = _PERF_MONTHLY_CLOSE_RATE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    collector = ShadowDiffCollector(enabled=_is_shadow_mode())
    excluded = {
        "status_convert": 0,
        "missing_created_at": 0,
        "created_at_parse_fail": 0,
        "online_not_first": 0,
        "other_course_format": 0,
        "offline_not_genai": 0,
    }

    with _connect(db_path) as conn:
        created_col = _pick_column(conn, "deal", ["생성 날짜", "생성일", "createdAt", "created_at", "created_at_utc"])
        if not created_col:
            raise ValueError("deal 생성 날짜 컬럼을 찾을 수 없습니다.")
        category_col = _pick_column(conn, "deal", ["과정 대분류", "category1"])
        course_id_col = _detect_course_id_column(conn)
        online_first_col = _pick_column(
            conn,
            "deal",
            [
                "(온라인)최초 입과 여부",
                "온라인최초 입과 여부",
                "온라인 최초 입과 여부",
                "online_first",
                "online_first_enrollment",
                "online_first_enroll",
            ],
        )

        course_id_select = f'd."{course_id_col}" AS course_id' if course_id_col else "NULL AS course_id"
        online_first_select = f'd."{online_first_col}" AS online_first' if online_first_col else "NULL AS online_first"
        category_select = f'd."{category_col}" AS category_raw' if category_col else "NULL AS category_raw"

        year_clause, year_params = sql_years_clause(f'd."{created_col}"', ["2025", "2026"], mode="strict")

        rows = _fetch_all(
            conn,
            f"""
            SELECT
              d.id AS deal_id,
              d."이름" AS deal_name,
              NULLIF(TRIM(d.organizationId), '') AS deal_org_id,
              NULLIF(TRIM(p.organizationId), '') AS people_org_id,
              COALESCE(NULLIF(TRIM(d.organizationId), ''), NULLIF(TRIM(p.organizationId), '')) AS org_id,
              COALESCE(o."이름", COALESCE(NULLIF(TRIM(d.organizationId), ''), NULLIF(TRIM(p.organizationId), ''))) AS org_name,
              o."기업 규모" AS size_raw,
              d."과정포맷" AS course_format_raw,
              {category_select},
              d."상태" AS status,
              d."성사 가능성" AS probability,
              d."예상 체결액" AS expected_amount,
              d."금액" AS amount,
              d."수주 예정일" AS expected_close_date,
              d."계약 체결일" AS contract_date,
              d."수강시작일" AS start_date,
              d."수강종료일" AS end_date,
              d."담당자" AS owner_json,
              p."소속 상위 조직" AS upper_org,
              p."팀(명함/메일서명)" AS team_signature,
              p."이름" AS person_name,
              d."{created_col}" AS created_at,
              {online_first_select},
              {course_id_select}
            FROM deal d
            LEFT JOIN people p ON p.id = d.peopleId
            LEFT JOIN organization o ON o.id = COALESCE(NULLIF(TRIM(d.organizationId), ''), NULLIF(TRIM(p.organizationId), ''))
            WHERE {year_clause}
            """,
            year_params,
        )
        rows = [dict(r) for r in rows]

    data_rows: List[Dict[str, Any]] = []
    raw_formats: Set[str] = set()
    raw_categories: Set[str] = set()

    for row in rows:
        month_key = _month_key_from_text(row.get("created_at"))
        if not month_key:
            excluded["missing_created_at"] += 1
            continue
        if collector.enabled:
            strict_key = date_kst.kst_yymm(row["created_at"])
            collector.add("month_key", row["created_at"], month_key, strict_key, deal_id=row.get("deal_id"))
        status_norm = _status_norm(row.get("status"))
        if status_norm == "convert":
            excluded["status_convert"] += 1
            continue

        course_format_norm = _normalize_course_format(row.get("course_format_raw"))
        raw_formats.add((row.get("course_format_raw") or "").strip())
        raw_categories.add((row.get("category_raw") or "").strip())
        if course_format_norm in CLOSE_RATE_ONLINE_COURSE_FORMATS:
            course_group = course_format_norm
        elif course_format_norm in CLOSE_RATE_OFFLINE_FORMATS:
            course_group = "오프라인"
        else:
            excluded["other_course_format"] += 1
            continue

        category_group = _map_inquiry_category_group(row.get("category_raw"))
        if course_group == "오프라인" and category_group != "생성형AI":
            excluded["offline_not_genai"] += 1
            continue

        is_online_fmt = course_format_norm in CLOSE_RATE_ONLINE_COURSE_FORMATS
        if is_online_fmt and online_first_col and _is_false_like(row.get("online_first")):
            excluded["online_not_first"] += 1
            continue

        size_group = _normalize_inquiry_size(row.get("org_name"), row.get("size_raw")) or "미기재"

        prob_bucket = "low"
        if status_norm == "lost":
            prob_bucket = "lost"
        elif _prob_equals(row.get("probability"), "확정"):
            prob_bucket = "confirmed"
        elif _prob_equals(row.get("probability"), "높음"):
            prob_bucket = "high"
        elif _prob_equals(row.get("probability"), "LOST"):
            prob_bucket = "lost"

        data_rows.append(
            {
                "deal_id": row.get("deal_id"),
                "deal_name": row.get("deal_name"),
                "org_id": row.get("org_id"),
                "org_name": row.get("org_name"),
                "size_group": size_group,
                "course_group": course_group,
                "category_group": category_group,
                "month": month_key,
                "prob_bucket": prob_bucket,
                "owner_names": _parse_owner_names(row.get("owner_json")),
                "course_format": course_format_norm,
                "probability": row.get("probability"),
                "status": row.get("status"),
                "expected_close_date": row.get("expected_close_date"),
                "expected_amount": _to_number(row.get("expected_amount")),
                "start_date": row.get("start_date"),
                "end_date": row.get("end_date"),
                "course_id": row.get("course_id"),
                "contract_date": row.get("contract_date"),
                "amount": _to_number(row.get("amount")),
                "upper_org": row.get("upper_org"),
                "team_signature": row.get("team_signature"),
                "person_name": row.get("person_name"),
            }
        )

    payload = {
        "rows": data_rows,
        "existing_org_ids": _compute_existing_org_ids_for_2025(db_path),
        "snapshot_version": f"db_mtime:{int(stat.st_mtime)}",
        "meta_debug": {
            "total_loaded": len(rows),
            "excluded_convert": excluded["status_convert"],
            "excluded_missing_created_at": excluded["missing_created_at"],
            "excluded_created_at_parse_fail": excluded["created_at_parse_fail"],
            "excluded_online_not_first": excluded["online_not_first"],
            "excluded_other_course_format": excluded["other_course_format"],
            "excluded_offline_not_genai": excluded["offline_not_genai"],
            "raw_formats_sample": list(itertools.islice(raw_formats, 20)),
            "raw_categories_sample": list(itertools.islice(raw_categories, 20)),
        },
    }
    _PERF_MONTHLY_CLOSE_RATE_CACHE[cache_key] = payload
    return payload


def get_perf_monthly_close_rate_summary(
    from_month: str = "2025-01",
    to_month: str = "2026-12",
    cust: str = "all",
    scope: str = "all",
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    if cust not in {"all", "new", "existing"}:
        raise ValueError(f"Unknown cust: {cust}")
    # scope 검증은 helper 내부에서 ValueError 발생
    allowed_members = _perf_close_rate_scope_members(scope)

    months = _month_range_keys(from_month, to_month)
    if not months:
        raise ValueError("from/to month range is empty")
    month_set = set(months)

    payload = _load_perf_monthly_close_rate_data(db_path)
    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime, from_month, to_month, cust, scope)
    cached = _PERF_MONTHLY_CLOSE_RATE_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    existing_org_ids = payload.get("existing_org_ids") or set()

    def zero_map():
        return {m: 0 for m in months}

    total_counts: Dict[Tuple[str, str], Dict[str, int]] = {}
    metric_counts: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    for size in INQUIRY_SIZE_GROUPS:
        for course in CLOSE_RATE_COURSE_GROUPS:
            total_counts[(size, course)] = zero_map()
            for metric in CLOSE_RATE_METRICS:
                metric_counts[(size, course, metric)] = zero_map()

    summary_debug = {
        "excluded_out_of_range": 0,
        "excluded_scope_mismatch": 0,
        "excluded_customer_type_mismatch": 0,
    }
    included = 0

    for row in payload["rows"]:
        month_key = row.get("month")
        if month_key not in month_set:
            summary_debug["excluded_out_of_range"] += 1
            continue
        size = row.get("size_group")
        course_group = row.get("course_group")
        if size not in INQUIRY_SIZE_GROUPS or course_group not in CLOSE_RATE_COURSE_GROUPS:
            continue
        if allowed_members is not None and not _owners_match_team(row.get("owner_names"), allowed_members):
            summary_debug["excluded_scope_mismatch"] += 1
            continue

        org_id = (row.get("org_id") or "").strip()
        if cust == "existing" and org_id not in existing_org_ids:
            summary_debug["excluded_customer_type_mismatch"] += 1
            continue
        if cust == "new" and org_id in existing_org_ids:
            summary_debug["excluded_customer_type_mismatch"] += 1
            continue

        included += 1
        total_counts[(size, course_group)][month_key] += 1
        bucket = row.get("prob_bucket")
        if bucket in {"confirmed", "high", "low", "lost"}:
            metric_counts[(size, course_group, bucket)][month_key] += 1
        # total is mirrored from total_counts later (SSOT)
        metric_counts[(size, course_group, "total")][month_key] += 1

    # mirror total into metric_counts for row generation
    for size in INQUIRY_SIZE_GROUPS:
        for course in CLOSE_RATE_COURSE_GROUPS:
            metric_counts[(size, course, "total")] = total_counts[(size, course)]

    # close_rate per month
    for size in INQUIRY_SIZE_GROUPS:
        for course in CLOSE_RATE_COURSE_GROUPS:
            totals = total_counts[(size, course)]
            conf = metric_counts[(size, course, "confirmed")]
            high = metric_counts[(size, course, "high")]
            rate_map = metric_counts[(size, course, "close_rate")]
            for m in months:
                denom = totals[m]
                numer = conf[m] + high[m]
                rate_map[m] = round((numer / denom) * 100, 1) if denom > 0 else 0.0

    label_map = {
        "total": "전체",
        "confirmed": "확정",
        "high": "높음",
        "low": "낮음",
        "lost": "LOST",
        "close_rate": "체결률(%)",
    }

    rows_list: List[Dict[str, Any]] = []
    for size in INQUIRY_SIZE_GROUPS:
        for course in CLOSE_RATE_COURSE_GROUPS:
            rows_list.append(
                {
                    "level": 1,
                    "segment": size,
                    "rowKey": course,
                    "label": course,
                    "countsByMonth": total_counts[(size, course)],
                }
            )
            for metric in CLOSE_RATE_METRICS:
                rows_list.append(
                    {
                        "level": 2,
                        "segment": size,
                        "parentKey": course,
                        "rowKey": f"{course}||{metric}",
                        "label": label_map.get(metric, metric),
                        "countsByMonth": metric_counts[(size, course, metric)],
                    }
                )

    meta_debug = {
        **(payload.get("meta_debug") or {}),
        **summary_debug,
        "after_filters": included,
    }

    result = {
        "months": months,
        "rows": rows_list,
        "meta": {
            "snapshot_version": payload.get("snapshot_version"),
            "from": from_month,
            "to": to_month,
            "cust": cust,
            "scope": scope,
            "meta_debug": meta_debug,
        },
    }
    _PERF_MONTHLY_CLOSE_RATE_SUMMARY_CACHE[cache_key] = result
    return result


def get_perf_monthly_close_rate_deals(
    segment: str,
    row: str,
    month: str,
    cust: str = "all",
    scope: str = "all",
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    if cust not in {"all", "new", "existing"}:
        raise ValueError(f"Unknown cust: {cust}")
    allowed_members = _perf_close_rate_scope_members(scope)
    if segment not in INQUIRY_SIZE_GROUPS:
        raise ValueError(f"Unknown segment(size group): {segment}")
    if not month or len(month.strip()) != 4:
        raise ValueError("month must be YYMM format, e.g., 2501")
    if "||" not in row:
        raise ValueError("row must be course_group||metric")
    course_group, metric = row.split("||", 1)
    if course_group not in CLOSE_RATE_COURSE_GROUPS:
        raise ValueError(f"Unknown course_group: {course_group}")
    if metric not in CLOSE_RATE_METRICS:
        raise ValueError(f"Unknown metric: {metric}")

    payload = _load_perf_monthly_close_rate_data(db_path)
    month_key = month.strip()
    existing_org_ids = payload.get("existing_org_ids") or set()

    items: List[Dict[str, Any]] = []
    numerator = 0
    denominator = 0

    for row_data in payload["rows"]:
        if row_data.get("month") != month_key:
            continue
        if row_data.get("size_group") != segment:
            continue
        if row_data.get("course_group") != course_group:
            continue
        if allowed_members is not None and not _owners_match_team(row_data.get("owner_names"), allowed_members):
            continue
        org_id = (row_data.get("org_id") or "").strip()
        if cust == "existing" and org_id not in existing_org_ids:
            continue
        if cust == "new" and org_id in existing_org_ids:
            continue

        denominator += 1
        if row_data.get("prob_bucket") in {"confirmed", "high"}:
            numerator += 1

        if metric != "close_rate" and row_data.get("prob_bucket") != metric:
            continue

        items.append(
            {
                "orgName": row_data.get("org_name"),
                "upperOrg": row_data.get("upper_org"),
                "teamSignature": row_data.get("team_signature"),
                "customerPersonName": row_data.get("person_name"),
                "dealId": row_data.get("deal_id"),
                "dealName": row_data.get("deal_name"),
                "courseFormat": row_data.get("course_format"),
                "categoryGroup": row_data.get("category_group"),
                "day1OwnerNames": row_data.get("owner_names"),
                "status": row_data.get("status"),
                "probability": row_data.get("probability"),
                "expectedCloseDate": row_data.get("expected_close_date"),
                "expectedAmount": row_data.get("expected_amount"),
                "startDate": row_data.get("start_date"),
                "endDate": row_data.get("end_date"),
                "courseId": row_data.get("course_id"),
                "contractDate": row_data.get("contract_date"),
                "amount": row_data.get("amount"),
            }
        )

    meta = {
        "snapshot_version": payload.get("snapshot_version"),
        "cust": cust,
        "scope": scope,
    }
    if metric == "close_rate":
        meta.update(
            {
                "numeratorCount": numerator,
                "denominatorCount": denominator,
                "totalCount": denominator,
                "close_rate": round((numerator / denominator) * 100, 1) if denominator > 0 else 0.0,
            }
        )

    return {
        "segment": {"key": segment, "label": segment},
        "row": {"key": row, "label": row},
        "month": month_key,
        "dealCount": len(items),
        "items": items,
        "meta": {
            **meta,
            "filters": {
                "segment": segment,
                "course_group": course_group,
                "metric": metric,
                "month": month_key,
                "cust": cust,
                "scope": scope,
            },
            "dedupedDealsCount": len(items),
        },
    }


def _perf_segments() -> List[Dict[str, Any]]:
    big_label = {
        "ALL": "전체",
        "SAMSUNG": "삼성전자",
        "SAMSUNG_ONLINE": "삼성전자 / 온라인",
        "SAMSUNG_OFFLINE": "삼성전자 / 비온라인",
        "NON_SAMSUNG_MAJOR_SIZE": "기업 고객(삼성 제외)",
        "NON_MAJOR_SIZE": "공공 고객",
        "NON_SAMSUNG_ONLINE": "온라인(삼성 제외)",
        "NON_SAMSUNG_ONLINE_MAJOR_SIZE": "온라인(기업 고객(삼전 제외))",
        "ONLINE_NON_MAJOR_SIZE": "온라인(공공 고객)",
        "NON_SAMSUNG_OFFLINE": "비온라인(삼성 제외)",
        "NON_SAMSUNG_OFFLINE_MAJOR_SIZE": "비온라인(기업 고객(삼전 제외))",
        "OFFLINE_NON_MAJOR_SIZE": "비온라인(공공 고객)",
    }
    defs = [
        ("ALL", lambda d: True),
        ("SAMSUNG", lambda d: d["org_is_samsung"]),
        ("SAMSUNG_ONLINE", lambda d: d["org_is_samsung"] and d["is_online"]),
        ("SAMSUNG_OFFLINE", lambda d: d["org_is_samsung"] and not d["is_online"]),
        ("NON_SAMSUNG_MAJOR_SIZE", lambda d: not d["org_is_samsung"] and d["is_major_size"]),
        ("NON_MAJOR_SIZE", lambda d: not d["is_major_size"]),
        ("NON_SAMSUNG_ONLINE", lambda d: not d["org_is_samsung"] and d["is_online"]),
        ("NON_SAMSUNG_ONLINE_MAJOR_SIZE", lambda d: not d["org_is_samsung"] and d["is_online"] and d["is_major_size"]),
        ("ONLINE_NON_MAJOR_SIZE", lambda d: d["is_online"] and not d["is_major_size"]),
        ("NON_SAMSUNG_OFFLINE", lambda d: not d["org_is_samsung"] and not d["is_online"]),
        ("NON_SAMSUNG_OFFLINE_MAJOR_SIZE", lambda d: not d["org_is_samsung"] and not d["is_online"] and d["is_major_size"]),
        ("OFFLINE_NON_MAJOR_SIZE", lambda d: not d["is_online"] and not d["is_major_size"]),
    ]
    return [{"key": key, "label": big_label.get(key, key), "predicate": pred} for key, pred in defs]


_PERF_ROW_ORDER = ["TOTAL", "CONTRACT", "CONFIRMED", "HIGH"]
_PERF_ROW_LABEL = {
    "TOTAL": "합산",
    "CONTRACT": "계약 체결",
    "CONFIRMED": "성사 확정",
    "HIGH": "성사 높음",
}

_PL_PROGRESS_ROWS = [
    ("REV_TOTAL", "총매출", 0, "eok"),
    ("REV_ONLINE", "└ 온라인 매출", 1, "eok"),
    ("REV_OFFLINE", "└ 출강 매출", 1, "eok"),
    ("COST_CONTRIB_TOTAL", "공헌비용 합계", 0, "eok"),
    ("COST_CONTRIB_ONLINE", "└ 온라인 공헌비용", 1, "eok"),
    ("COST_CONTRIB_OFFLINE", "└ 출강 공헌비용", 1, "eok"),
    ("PROFIT_CONTRIB_TOTAL", "공헌이익 합계", 0, "eok"),
    ("PROFIT_CONTRIB_ONLINE", "└ 온라인 공헌이익", 1, "eok"),
    ("PROFIT_CONTRIB_OFFLINE", "└ 출강 공헌이익", 1, "eok"),
    ("COST_FIXED_TOTAL", "고정비 합계", 0, "eok"),
    ("COST_FIXED_PROD", "└ 제작비", 1, "eok"),
    ("COST_FIXED_MKT", "└ 마케팅비", 1, "eok"),
    ("COST_FIXED_LABOR", "└ 인건비", 1, "eok"),
    ("COST_FIXED_RENT", "└ 임대료", 1, "eok"),
    ("COST_FIXED_OTHER", "└ 기타비용", 1, "eok"),
    ("OP", "OP", 0, "eok"),
    ("OP_MARGIN", "영업이익률(%)", 0, "percent"),
]


def get_perf_monthly_amounts_summary(
    from_month: str = "2025-01",
    to_month: str = "2026-12",
    team: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    """
    Summary table for monthly amounts by segment and row (계약/확정/높음).
    Amounts are raw 원 단위; months are YYMM keys.
    """
    months = _month_range_keys(from_month, to_month)
    month_set = set(months)
    if not months:
        raise ValueError("from/to month range is empty")

    payload = _load_perf_monthly_data(db_path)
    team_members = _dealcheck_team_members(team)
    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime, from_month, to_month, team or "all")
    cached = _PERF_MONTHLY_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows_data = [row for row in payload["rows"] if row["month"] in month_set]
    if team_members is not None:
        rows_data = [row for row in rows_data if _owners_match_team(row.get("day1_owner_names"), team_members)]
    segments_result: List[Dict[str, Any]] = []
    for seg in _perf_segments():
        bucket_data: Dict[str, Dict[str, Any]] = {}
        for bucket_key in _PERF_ROW_ORDER:
            bucket_data[bucket_key] = {
                "byMonth": {m: 0.0 for m in months},
                "dealCountByMonth": {m: 0 for m in months},
            }
        for deal in rows_data:
            bucket = deal["bucket"]
            if bucket not in bucket_data:
                continue
            if not seg["predicate"](deal):
                continue
            month = deal["month"]
            bucket_data[bucket]["byMonth"][month] += deal["amount_used"]
            bucket_data[bucket]["dealCountByMonth"][month] += 1
            bucket_data["TOTAL"]["byMonth"][month] += deal["amount_used"]
            bucket_data["TOTAL"]["dealCountByMonth"][month] += 1

        seg_rows: List[Dict[str, Any]] = []
        for row_key in _PERF_ROW_ORDER:
            seg_rows.append(
                {
                    "key": row_key,
                    "label": _PERF_ROW_LABEL.get(row_key, row_key),
                    "byMonth": bucket_data[row_key]["byMonth"],
                    "dealCountByMonth": bucket_data[row_key]["dealCountByMonth"],
                }
            )
        segments_result.append({"key": seg["key"], "label": seg["label"], "rows": seg_rows})

    result = {
        "months": months,
        "segments": segments_result,
        "meta": {"snapshot_version": payload.get("snapshot_version"), "team": team},
    }
    _PERF_MONTHLY_SUMMARY_CACHE[cache_key] = result
    return result


def get_perf_monthly_amounts_deals(
    segment: str,
    row: str,
    month: str,
    team: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    """
    Drilldown list of deals for a given segment/row/month (YYMM).
    """
    month_key = month.strip()
    if not month_key or len(month_key) != 4:
        raise ValueError("month must be YYMM format, e.g., 2501")

    seg_defs = {seg["key"]: seg for seg in _perf_segments()}
    if segment not in seg_defs:
        raise ValueError(f"Unknown segment: {segment}")
    row_defs = {k: _PERF_ROW_LABEL[k] for k in _PERF_ROW_ORDER}
    if row not in row_defs:
        raise ValueError(f"Unknown row: {row}")

    payload = _load_perf_monthly_data(db_path)
    team_members = _dealcheck_team_members(team)
    seg_def = seg_defs[segment]
    items: List[Dict[str, Any]] = []
    buckets_for_row: Set[str] = {"CONTRACT", "CONFIRMED", "HIGH"} if row == "TOTAL" else {row}
    seen: Set[str] = set()
    for deal in payload["rows"]:
        if deal["month"] != month_key:
            continue
        if deal["bucket"] not in buckets_for_row:
            continue
        if team_members is not None and not _owners_match_team(deal.get("day1_owner_names"), team_members):
            continue
        if not seg_def["predicate"](deal):
            continue
        deal_id = deal["deal_id"]
        if deal_id in seen:
            continue
        seen.add(deal_id)
        items.append(
            {
                "orgName": deal["org_name"],
                "upperOrg": deal["upper_org"],
                "customerPersonName": deal["customer_person_name"],
                "dealId": deal["deal_id"],
                "dealName": deal["deal_name"],
                "courseFormat": deal["course_format"],
                "category": deal.get("category"),
                "day1OwnerNames": deal["day1_owner_names"],
                "status": deal["status"],
                "probability": deal["probability"],
                "expectedCloseDate": deal["expected_close_date"],
                "expectedAmount": deal["expected_amount"],
                "startDate": deal["start_date"],
                "endDate": deal["end_date"],
                "courseId": deal["course_id"],
                "contractDate": deal["contract_date"],
                "amount": deal["amount"],
                "amountUsed": deal["amount_used"],
            }
        )

    total_amount = sum(d.get("amountUsed") or 0.0 for d in items)
    return {
        "segment": {"key": segment, "label": seg_def["label"]},
        "row": {"key": row, "label": row_defs[row]},
        "month": month_key,
        "totalAmount": total_amount,
        "dealCount": len(items),
        "items": items,
        "note": "성사 확정/높음은 금액이 없으면 예상 체결액을 합산합니다.",
        "meta": {"snapshot_version": payload.get("snapshot_version"), "team": team},
    }


def get_perf_monthly_inquiries_summary(
    from_month: str = "2025-01",
    to_month: str = "2026-12",
    team: Optional[str] = None,
    db_path: Path = DB_PATH,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Summary counts of deal creations by (size_group, course_format, category_group) × month.
    """
    months = _month_range_keys(from_month, to_month)
    month_set = set(months)
    if not months:
        raise ValueError("from/to month range is empty")

    payload = _load_perf_monthly_inquiries_data(db_path, debug=debug)
    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime, from_month, to_month, team or "all")
    if not debug:
        cached = _PERF_MONTHLY_INQUIRIES_SUMMARY_CACHE.get(cache_key)
        if cached is not None:
            return cached

    team_members = _dealcheck_team_members(team)
    detail_counts: Dict[Tuple[str, str, str], Dict[str, int]] = {}
    fmt_rollup: Dict[Tuple[str, str], Dict[str, int]] = {}

    def _init_counts_for_detail(size: str, course: str, category: str) -> Dict[str, int]:
        return detail_counts.setdefault((size, course, category), {m: 0 for m in months})

    for size in INQUIRY_SIZE_GROUPS:
        for course in INQUIRY_COURSE_FORMATS:
            fmt_rollup[(size, course)] = {m: 0 for m in months}
            for category in INQUIRY_CATEGORY_GROUPS:
                _init_counts_for_detail(size, course, category)

    rows_total_in_range = 0
    excluded_by_team = 0
    excluded_by_team_by_size: Dict[str, int] = {}
    excluded_owner_counter: Counter[str] = Counter()

    for row in payload["rows"]:
        if row["month"] not in month_set:
            continue
        rows_total_in_range += 1
        if team_members is not None and not _owners_match_team(row.get("owner_names"), team_members):
            excluded_by_team += 1
            size = row["size_group"]
            excluded_by_team_by_size[size] = excluded_by_team_by_size.get(size, 0) + 1
            for name in row.get("owner_names") or []:
                excluded_owner_counter[name] += 1
            continue
        size = row["size_group"]
        course = row["course_format"]
        category = row["category_group"]
        month = row["month"]
        detail_counts[(size, course, category)][month] += 1
        fmt_rollup[(size, course)][month] += 1

    rows_list: List[Dict[str, Any]] = []
    for size in INQUIRY_SIZE_GROUPS:
        for course in INQUIRY_COURSE_FORMATS:
            # level 1: format rollup
            rows_list.append(
                {
                    "level": 1,
                    "sizeGroup": size,
                    "courseFormat": course,
                    "categoryGroup": None,
                    "segmentKey": size,
                    "rowKey": f"{course}||{INQ_ALL}",
                    "key": f"{course}||{INQ_ALL}",
                    "label": course,
                    "countByMonth": fmt_rollup[(size, course)],
                }
            )
            for category in INQUIRY_CATEGORY_GROUPS:
                # level 2: detail
                rows_list.append(
                    {
                        "level": 2,
                        "sizeGroup": size,
                        "courseFormat": course,
                        "categoryGroup": category,
                        "segmentKey": size,
                        "rowKey": f"{course}||{category}",
                        "key": f"{course}||{category}",
                        "label": category,
                        "countByMonth": detail_counts[(size, course, category)],
                    }
                )

    team_filter_debug = None
    if debug and team is not None:
        team_filter_debug = {
            "team_param": team,
            "allowed_member_count": len(team_members or []),
            "rows_total_in_range": rows_total_in_range,
            "rows_after_team_filter": rows_total_in_range - excluded_by_team,
            "excluded_by_team": excluded_by_team,
            "excluded_by_team_by_size": excluded_by_team_by_size,
            "excluded_owner_names_top": excluded_owner_counter.most_common(20),
        }

    result = {
        "months": months,
        "rows": rows_list,
        "meta": {
            "snapshot_version": payload.get("snapshot_version"),
            "team": team,
            "debug": payload.get("meta_debug"),
        },
    }
    if team_filter_debug is not None:
        result["meta"]["debug"] = result["meta"].get("debug") or {}
        result["meta"]["debug"]["team_filter"] = team_filter_debug
    if not debug:
        _PERF_MONTHLY_INQUIRIES_SUMMARY_CACHE[cache_key] = result
    return result


def get_perf_monthly_inquiries_deals(
    segment: str,
    row: str,
    month: str,
    team: Optional[str] = None,
    db_path: Path = DB_PATH,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Drilldown deals for monthly inquiries grid (segment=size group, row=course||category).
    """
    if not month or len(month.strip()) != 4:
        raise ValueError("month must be YYMM format, e.g., 2501")
    month_key = month.strip()
    if segment not in INQUIRY_SIZE_GROUPS:
        raise ValueError(f"Unknown segment(size group): {segment}")
    if "||" not in row:
        course_fmt, category_grp = INQ_ALL, INQ_ALL
    else:
        course_fmt, category_grp = row.split("||", 1)
    if course_fmt != INQ_ALL and course_fmt not in INQUIRY_COURSE_FORMATS:
        raise ValueError(f"Unknown courseFormat: {course_fmt}")
    if category_grp != INQ_ALL and category_grp not in INQUIRY_CATEGORY_GROUPS:
        raise ValueError(f"Unknown categoryGroup: {category_grp}")

    payload = _load_perf_monthly_inquiries_data(db_path, debug=debug)
    team_members = _dealcheck_team_members(team)
    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    excluded_samples: List[Dict[str, Any]] = []

    for row_data in payload["rows"]:
        if row_data["month"] != month_key:
            continue
        if row_data["size_group"] != segment:
            continue
        if course_fmt != INQ_ALL and row_data["course_format"] != course_fmt:
            continue
        if category_grp != INQ_ALL and row_data["category_group"] != category_grp:
            continue
        if team_members is not None and not _owners_match_team(row_data.get("owner_names"), team_members):
            if debug and len(excluded_samples) < 50:
                excluded_samples.append(
                    {
                        "dealId": row_data["deal_id"],
                        "dealName": row_data["deal_name"],
                        "ownerNames": row_data.get("owner_names"),
                        "orgName": row_data["org_name"],
                        "sizeRaw": row_data.get("size_raw"),
                        "sizeGroup": row_data.get("size_group"),
                    }
                )
            continue
        deal_id = row_data["deal_id"]
        if deal_id in seen:
            continue
        seen.add(deal_id)
        items.append(
            {
                "orgName": row_data["org_name"],
                "upperOrg": row_data["upper_org"],
                "customerPersonName": row_data["person_name"],
                "dealId": deal_id,
                "dealName": row_data["deal_name"],
                "courseFormat": row_data["course_format"],
                "day1OwnerNames": row_data.get("owner_names"),
                "status": row_data["status"],
                "probability": row_data["probability"],
                "expectedCloseDate": row_data["expected_close_date"],
                "expectedAmount": row_data["expected_amount"],
                "startDate": row_data["start_date"],
                "endDate": row_data["end_date"],
                "courseId": row_data["course_id"],
                "contractDate": row_data["contract_date"],
                "amount": row_data["amount"],
                "category": row_data.get("category"),
            }
        )

    if course_fmt == INQ_ALL and category_grp == INQ_ALL:
        row_label = "전체"
    elif category_grp == INQ_ALL:
        row_label = f"{course_fmt} (합계)"
    else:
        row_label = f"{course_fmt} · {category_grp}"

    result = {
        "segment": {"key": segment, "label": segment},
        "row": {"key": row, "label": row_label},
        "month": month_key,
        "dealCount": len(items),
        "items": items,
        "meta": {"snapshot_version": payload.get("snapshot_version"), "team": team},
    }
    if debug and excluded_samples:
        result["meta"]["debug"] = {"excluded_samples": excluded_samples}
    return result


def _pl_target_for_year(year: int) -> Dict[str, Dict[str, float]]:
    if year != 2026:
        return {}

    # For T variant we fully override with hardcoded table (억 단위)
    months = _month_keys_for_year(year)
    result: Dict[str, Dict[str, float]] = {m: {"online": 0.0, "offline": 0.0} for m in months}
    for month in months:
        online = PL_2026_TARGET_FULL.get("REV_ONLINE", {}).get(month, {}).get("T")
        offline = PL_2026_TARGET_FULL.get("REV_OFFLINE", {}).get(month, {}).get("T")
        if online is not None:
            result[month]["online"] = float(online)
        if offline is not None:
            result[month]["offline"] = float(offline)
    return result


def _round2(val: Optional[float]) -> Optional[float]:
    if val is None:
        return None
    return round(float(val), 4)


def _load_pl_progress_payload(year: int = 2026, db_path: Path = DB_PATH) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime, year)
    cached = _PL_PROGRESS_PAYLOAD_CACHE.get(cache_key)
    if cached is not None:
        return cached

    month_keys = _month_keys_for_year(year)
    month_windows = _month_boundaries(year)
    excluded = {"missing_dates": 0, "missing_amount": 0, "invalid_date_range": 0}

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            """
            SELECT
              d.id AS deal_id,
              d."이름" AS deal_name,
              d.organizationId AS org_id,
              COALESCE(o."이름", d.organizationId) AS org_name,
              p."소속 상위 조직" AS upper_org,
              p."이름" AS person_name,
              d."과정포맷" AS course_format,
              d."담당자" AS owner_json,
              d."상태" AS status,
              d."성사 가능성" AS probability,
              d."금액" AS amount,
              d."예상 체결액" AS expected_amount,
              d."계약 체결일" AS contract_date,
              d."수주 예정일" AS expected_close_date,
              d."수강시작일" AS start_date,
              d."수강종료일" AS end_date
            FROM deal d
            LEFT JOIN organization o ON o.id = d.organizationId
            LEFT JOIN people p ON p.id = d.peopleId
            WHERE d."수강시작일" IS NOT NULL OR d."수강종료일" IS NOT NULL
            """,
        )

    deals: List[Dict[str, Any]] = []
    for row in rows:
        tokens = _prob_tokens(row["probability"])
        status = (row["status"] or "").strip()
        is_expected = "확정" in tokens or "높음" in tokens or (not tokens and status == "Won")
        if not is_expected:
            continue

        start = _parse_date(row["start_date"])
        end = _parse_date(row["end_date"])
        if not start or not end:
            excluded["missing_dates"] += 1
            continue
        if end < start:
            excluded["invalid_date_range"] += 1
            continue

        amount_num = _to_number(row["amount"])
        expected_num = _to_number(row["expected_amount"])
        amount_used = amount_num if amount_num and amount_num > 0 else expected_num if expected_num and expected_num > 0 else None
        if amount_used is None:
            excluded["missing_amount"] += 1
            continue

        total_days = (end - start).days + 1
        if total_days <= 0:
            excluded["invalid_date_range"] += 1
            continue

        is_online = _is_online_for_pnl(row["course_format"])
        recognized_by_month: Dict[str, float] = {}
        overlap_by_month: Dict[str, Dict[str, int]] = {}
        for month_key, (m_start, m_end) in month_windows.items():
            if end < m_start or start > m_end:
                continue
            overlap_start = max(start, m_start)
            overlap_end = min(end, m_end)
            overlap_days = (overlap_end - overlap_start).days + 1
            if overlap_days <= 0:
                continue
            recognized_eok = (float(amount_used) * overlap_days / total_days) / 1e8
            if recognized_eok <= 0:
                continue
            recognized_by_month[month_key] = recognized_eok
            overlap_by_month[month_key] = {"overlap_days": overlap_days, "total_days": total_days}

        if not recognized_by_month:
            continue

        deals.append(
            {
                "deal_id": row["deal_id"],
                "deal_name": row["deal_name"] or row["deal_id"],
                "org_id": row["org_id"],
                "org_name": row["org_name"] or (row["org_id"] or "-"),
                "upper_org": row["upper_org"] or "미입력",
                "customer_person_name": row["person_name"] or "미입력",
                "course_format": row["course_format"],
                "owner_names": _parse_owner_names(row["owner_json"]),
                "status": row["status"],
                "probability": row["probability"],
                "expected_close_date": row["expected_close_date"],
                "expected_amount": expected_num,
                "contract_date": row["contract_date"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "amount": amount_num,
                "amount_used": float(amount_used),
                "recognized_by_month": recognized_by_month,
                "overlap_by_month": overlap_by_month,
                "is_online": is_online,
            }
        )

    payload = {
        "deals": deals,
        "month_keys": month_keys,
        "snapshot_version": f"db_mtime:{int(stat.st_mtime)}",
        "excluded": excluded,
    }
    _PL_PROGRESS_PAYLOAD_CACHE[cache_key] = payload
    return payload


def get_pl_progress_summary(year: int = 2026, db_path: Path = DB_PATH) -> Dict[str, Any]:
    months = _month_keys_for_year(year)
    targets = _pl_target_for_year(year)
    if not months:
        raise ValueError("No months available for given year")

    payload = _load_pl_progress_payload(year=year, db_path=db_path)
    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime, year)
    cached = _PL_PROGRESS_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    data_variant: Dict[str, Dict[str, Dict[str, float]]] = {
        "T": {m: {"online": 0.0, "offline": 0.0} for m in months},
        "E": {m: {"online": 0.0, "offline": 0.0} for m in months},
    }
    for month, tgt in targets.items():
        if month in data_variant["T"]:
            data_variant["T"][month]["online"] = float(tgt.get("online", 0.0))
            data_variant["T"][month]["offline"] = float(tgt.get("offline", 0.0))

    for deal in payload["deals"]:
        variant = "E"
        for month, amt in deal["recognized_by_month"].items():
            if month not in data_variant[variant]:
                continue
            key = "online" if deal["is_online"] else "offline"
            data_variant[variant][month][key] += float(amt)

    def compute_rows_for_variant(variant: str) -> Dict[str, Dict[str, float]]:
        # For T: directly use PL_2026_TARGET_FULL values (억 단위) when available
        if variant == "T" and year == 2026:
            rows: Dict[str, Dict[str, float]] = {key: {} for key, _, _, _ in _PL_PROGRESS_ROWS}
            for key, _, _, fmt in _PL_PROGRESS_ROWS:
                table = PL_2026_TARGET_FULL.get(key, {})
                for month in months:
                    val = table.get(month, {}).get("T")
                    rows[key][month] = _round2(val) if val is not None else 0.0
            return rows

        # E (and any non-T) uses computed values from deals
        rows: Dict[str, Dict[str, float]] = {key: {} for key, _, _, _ in _PL_PROGRESS_ROWS}
        for month in months:
            online_rev = data_variant[variant][month]["online"]
            offline_rev = data_variant[variant][month]["offline"]
            total_rev = online_rev + offline_rev
            contrib_cost_online = online_rev * 0.15
            contrib_cost_offline = offline_rev * 0.45
            contrib_cost_total = contrib_cost_online + contrib_cost_offline
            profit_online = online_rev - contrib_cost_online
            profit_offline = offline_rev - contrib_cost_offline
            profit_total = profit_online + profit_offline
            fixed_prod = 0.2
            fixed_mkt = 0.3
            fixed_labor = 6.0
            fixed_rent = fixed_labor * 0.15
            fixed_other = 1.0 + (offline_rev * 0.05)
            fixed_total = fixed_prod + fixed_mkt + fixed_labor + fixed_rent + fixed_other
            op = profit_total - fixed_total
            margin = (op / total_rev * 100.0) if total_rev > 0 else None

            rows["REV_TOTAL"][month] = _round2(total_rev)
            rows["REV_ONLINE"][month] = _round2(online_rev)
            rows["REV_OFFLINE"][month] = _round2(offline_rev)
            rows["COST_CONTRIB_TOTAL"][month] = _round2(contrib_cost_total)
            rows["COST_CONTRIB_ONLINE"][month] = _round2(contrib_cost_online)
            rows["COST_CONTRIB_OFFLINE"][month] = _round2(contrib_cost_offline)
            rows["PROFIT_CONTRIB_TOTAL"][month] = _round2(profit_total)
            rows["PROFIT_CONTRIB_ONLINE"][month] = _round2(profit_online)
            rows["PROFIT_CONTRIB_OFFLINE"][month] = _round2(profit_offline)
            rows["COST_FIXED_TOTAL"][month] = _round2(fixed_total)
            rows["COST_FIXED_PROD"][month] = _round2(fixed_prod)
            rows["COST_FIXED_MKT"][month] = _round2(fixed_mkt)
            rows["COST_FIXED_LABOR"][month] = _round2(fixed_labor)
            rows["COST_FIXED_RENT"][month] = _round2(fixed_rent)
            rows["COST_FIXED_OTHER"][month] = _round2(fixed_other)
            rows["OP"][month] = _round2(op)
            rows["OP_MARGIN"][month] = _round2(margin) if margin is not None else None
        return rows

    computed: Dict[str, Dict[str, Dict[str, float]]] = {}
    for variant in ["T", "E"]:
        computed[variant] = compute_rows_for_variant(variant)

    year_key_t = f"Y{year}_T"
    year_key_e = f"Y{year}_E"

    columns: List[Dict[str, Any]] = [
        {"key": year_key_t, "label": f"{year}(T)", "month": None, "variant": "T", "kind": "YEAR"},
        {"key": year_key_e, "label": f"{year}(E)", "month": None, "variant": "E", "kind": "YEAR"},
    ]
    for m in months:
        columns.append({"key": f"{m}_T", "label": f"{m}(T)", "month": m, "variant": "T", "kind": "MONTH"})
        columns.append({"key": f"{m}_E", "label": f"{m}(E)", "month": m, "variant": "E", "kind": "MONTH"})

    totals_by_variant: Dict[str, Dict[str, Optional[float]]] = {v: {} for v in ["T", "E"]}
    for variant in ["T", "E"]:
        for key, label, level, fmt in _PL_PROGRESS_ROWS:
            if fmt == "percent":
                continue
            total_val = sum((computed[variant][key].get(m) or 0.0) for m in months)
            totals_by_variant[variant][key] = _round2(total_val)

    rows_out: List[Dict[str, Any]] = []
    for key, label, level, fmt in _PL_PROGRESS_ROWS:
        values: Dict[str, Optional[float]] = {}
        # monthly values
        for m in months:
            values[f"{m}_T"] = computed["T"][key][m]
            values[f"{m}_E"] = computed["E"][key][m]
        # yearly values
        if fmt == "percent":
            rev_t = totals_by_variant["T"].get("REV_TOTAL") or 0.0
            rev_e = totals_by_variant["E"].get("REV_TOTAL") or 0.0
            op_t = totals_by_variant["T"].get("OP") or 0.0
            op_e = totals_by_variant["E"].get("OP") or 0.0
            values[year_key_t] = _round2(op_t / rev_t * 100.0) if rev_t > 0 else None
            values[year_key_e] = _round2(op_e / rev_e * 100.0) if rev_e > 0 else None
        else:
            if key in PL_2026_TARGET_FULL and year == 2026:
                values[year_key_t] = PL_2026_TARGET_FULL[key].get(str(year), {}).get("T", totals_by_variant["T"].get(key, 0.0))
            else:
                values[year_key_t] = totals_by_variant["T"].get(key, 0.0)
            values[year_key_e] = totals_by_variant["E"].get(key, 0.0)

        rows_out.append({"key": key, "label": label, "level": level, "format": fmt, "values": values})

    result = {
        "year": year,
        "months": months,
        "columns": columns,
        "rows": rows_out,
        "meta": {
            "unit": "억",
            "snapshot_version": payload.get("snapshot_version"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "excluded": payload.get("excluded", {}),
        },
    }
    _PL_PROGRESS_SUMMARY_CACHE[cache_key] = result
    return result


def get_pl_progress_deals(
    year: int,
    month: str,
    rail: str,
    variant: str = "E",
    limit: int = 500,
    offset: int = 0,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    month_key = month.strip()
    if not month_key or len(month_key) != 4:
        raise ValueError("month must be YYMM format (e.g., 2601)")
    rail_norm = rail.upper()
    if rail_norm not in {"TOTAL", "ONLINE", "OFFLINE"}:
        raise ValueError("rail must be TOTAL|ONLINE|OFFLINE")
    variant_norm = (variant or "E").upper()
    if variant_norm not in {"E", "T"}:
        raise ValueError("variant must be E or T")
    if variant_norm == "T":
        return {
            "year": year,
            "month": month_key,
            "rail": rail_norm,
            "variant": variant_norm,
            "items": [],
            "meta": {"snapshot_version": None, "total": 0},
        }

    limit = max(1, min(limit or 500, 2000))
    offset = max(0, offset or 0)

    payload = _load_pl_progress_payload(year=year, db_path=db_path)
    items: List[Dict[str, Any]] = []
    for deal in payload["deals"]:
        if month_key not in deal["recognized_by_month"]:
            continue
        if rail_norm == "ONLINE" and not deal["is_online"]:
            continue
        if rail_norm == "OFFLINE" and deal["is_online"]:
            continue
        recognized_amt = deal["recognized_by_month"].get(month_key, 0.0)
        overlap_info = deal["overlap_by_month"].get(month_key, {})
        items.append(
            {
                "dealId": deal["deal_id"],
                "dealName": deal["deal_name"],
                "orgId": deal["org_id"],
                "orgName": deal["org_name"],
                "upperOrg": deal["upper_org"],
                "customerPersonId": None,
                "customerPersonName": deal["customer_person_name"],
                "day1OwnerNames": deal["owner_names"],
                "courseFormat": deal["course_format"],
                "status": deal["status"],
                "probability": deal["probability"],
                "expectedCloseDate": deal["expected_close_date"],
                "expectedAmount": deal["expected_amount"],
                "contractDate": deal["contract_date"],
                "startDate": deal["start_date"],
                "endDate": deal["end_date"],
                "amount": deal["amount"],
                "amountUsed": deal["amount_used"],
                "recognizedAmount": _round2(recognized_amt),
                "totalDays": overlap_info.get("total_days"),
                "overlapDays": overlap_info.get("overlap_days"),
            }
        )

    def sort_key(item: Dict[str, Any]) -> Tuple[float, float, str]:
        rec = float(item.get("recognizedAmount") or 0.0)
        amt = float(item.get("amountUsed") or 0.0)
        return (rec, amt, item.get("dealName") or "")

    items.sort(key=lambda it: sort_key(it), reverse=True)
    total = len(items)
    sliced = items[offset : offset + limit]

    return {
        "year": year,
        "month": month_key,
        "rail": rail_norm,
        "variant": variant_norm,
        "items": sliced,
        "meta": {"snapshot_version": payload.get("snapshot_version"), "total": total},
    }


def _compute_counterparty_dri_rows(
    size: str,
    org_limit: int | None,
    org_offset: int,
    db_path: Path,
    offline_targets: Dict[Tuple[str, str], float],
    online_targets: Dict[Tuple[str, str], float],
    targets_version: str,
    targets_meta: Dict[Tuple[str, str], Dict[str, Any]],
    debug: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], int]:
    online_set = sp.ONLINE_COURSE_FORMATS
    db_stat = db_path.stat()
    snapshot_version = f"db_mtime:{int(db_stat.st_mtime)}"
    override_keys: Set[Tuple[str, str]] = set(offline_targets.keys()) | set(online_targets.keys())
    override_diagnostics: List[Dict[str, Any]] = []
    targets_meta = targets_meta or {}

    with _connect(db_path) as conn:
        has_expected_close = _has_column(conn, "deal", "수주 예정일")
        has_start_date = _has_column(conn, "deal", "수강시작일")
        has_probability = _has_column(conn, "deal", "성사 가능성")
        conditions: List[str] = []
        params: List[Any] = []
        # 상태가 Lost/Convert인 딜은 상단 조직/카운터파티 계산에서 제외
        conditions.append('d."상태" NOT IN (\'Lost\',\'Convert\')')
        if has_expected_close:
            conditions.append(
                '('
                ' (d."계약 체결일" LIKE ? OR d."수주 예정일" LIKE ?)'
                ' OR (d."계약 체결일" LIKE ? OR d."수주 예정일" LIKE ?)'
                ')'
            )
            params.extend(["2025%", "2025%", "2026%", "2026%"])
        else:
            conditions.append('(d."계약 체결일" LIKE ? OR d."계약 체결일" LIKE ?)')
            params.extend(["2025%", "2026%"])

        if size and size != "전체":
            conditions.append('o."기업 규모" = ?')
            params.append(size)

        expected_date_select = 'd."수주 예정일"' if has_expected_close else "NULL"
        start_date_select = 'd."수강시작일"' if has_start_date else "NULL"
        probability_select = 'd."성사 가능성"' if has_probability else "'확정'"

        limit_clause = "LIMIT ? OFFSET ?" if org_limit is not None else ""
        top_orgs = _fetch_all(
            conn,
            'WITH org_sum AS ('
            '  SELECT d.organizationId AS orgId, COALESCE(o."이름", d.organizationId) AS orgName, '
            '         o."기업 규모" AS sizeRaw, SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "  FROM deal d "
            "  LEFT JOIN organization o ON o.id = d.organizationId "
            f"  WHERE {' AND '.join(conditions)} "
            "  GROUP BY d.organizationId, orgName, sizeRaw "
            '), ranked AS ('
            f"  SELECT * FROM org_sum ORDER BY totalAmount DESC {limit_clause}"
            ") SELECT * FROM ranked",
            params + ([org_limit, org_offset] if org_limit is not None else []),
        )

        top_ids = {row["orgId"] for row in top_orgs}
        if not top_ids:
            meta = {"orgCount": 0, "rowCount": 0, "offset": org_offset, "limit": org_limit, "snapshot_version": snapshot_version}
            return [], meta, 0

        placeholders = ",".join(["?"] * len(top_ids))
        counterparty_rows = _fetch_all(
            conn,
            f'SELECT '
            '  d.organizationId AS orgId, '
            '  COALESCE(o."이름", d.organizationId) AS orgName, '
            '  o."기업 규모" AS sizeRaw, '
            '  p."소속 상위 조직" AS upper_org, '
            '  d."과정포맷" AS course_format, '
            '  d."금액" AS amount, '
            '  d."예상 체결액" AS expected_amount, '
            '  d."계약 체결일" AS contract_date, '
            f"  {expected_date_select} AS expected_date, "
            f"  {start_date_select} AS start_date, "
            f"  {probability_select} AS probability "
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            "LEFT JOIN people p ON p.id = d.peopleId "
            f"WHERE {' AND '.join(conditions)} AND d.organizationId IN ({placeholders}) ",
            params + list(top_ids),
        )

    org_lookup = {
        row["orgId"]: {
            "orgId": row["orgId"],
            "orgName": _norm_text(row["orgName"]),
            "sizeRaw": row["sizeRaw"],
            "total": _to_number(row["totalAmount"]) or 0.0,
        }
        for row in top_orgs
    }

    cp_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in counterparty_rows:
        org_id = row["orgId"]
        upper = _normalize_counterparty_upper(row["upper_org"])
        key = (org_id, upper)
        entry = cp_map.setdefault(
            key,
            {
                "orgId": org_id,
                "upperOrg": upper,
                "cpOnline2025": 0.0,
                "cpOffline2025": 0.0,
                "cpOnline2026": 0.0,
                "cpTotal2025": 0.0,
                "cpOffline2026": 0.0,
                "owners2025": set(),
                "dealCount2025": 0,
                "orgName": org_lookup.get(org_id, {}).get("orgName", org_id),
                "sizeRaw": org_lookup.get(org_id, {}).get("sizeRaw"),
            },
        )
        amount = _amount_fallback(row["amount"], row["expected_amount"])
        if not amount:
            continue
        prob_high = _prob_is_high(row["probability"])
        fmt = row["course_format"]
        year = _year_from_dates(row["contract_date"], row["expected_date"])
        start_year = _parse_year_from_text(row["start_date"])
        is_offline = fmt not in online_set

        if prob_high and year == "2025":
            if is_offline and start_year != "2026":
                entry["cpOffline2025"] += amount
                entry["cpTotal2025"] += amount
                entry["dealCount2025"] += 1
            elif not is_offline and start_year != "2026":
                entry["cpOnline2025"] += amount
                entry["cpTotal2025"] += amount
                entry["dealCount2025"] += 1
            # 2025 + start 2026 오프라인/온라인 → 26 가산
            if is_offline and start_year == "2026":
                entry["cpOffline2026"] += amount
            if not is_offline and start_year == "2026":
                entry["cpOnline2026"] += amount
        if prob_high and year == "2026":
            if is_offline:
                entry["cpOffline2026"] += amount
            else:
                entry["cpOnline2026"] += amount

    deal_row_keys: Set[Tuple[str, str]] = set()
    deal_row_lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (org_id, upper), cp in cp_map.items():
        org_entry = org_lookup.get(org_id, {})
        org_name = (org_entry.get("orgName") or "").strip()
        upper_norm = _normalize_counterparty_upper(upper)
        if org_name:
            key = (org_name, upper_norm)
            deal_row_keys.add(key)
            deal_row_lookup[key] = cp

    # owners: fetch minimal rows for top orgs only
    owner_rows: List[sqlite3.Row] = []
    with _connect(db_path) as conn:
        has_people_owner = _has_column(conn, "people", "담당자")
        people_owner_select = 'p."담당자"' if has_people_owner else "NULL"
        owner_rows = _fetch_all(
            conn,
            f'SELECT d.organizationId AS orgId, COALESCE(p."소속 상위 조직","미입력") AS upper_org, '
            f'{people_owner_select} AS people_owner_json, d."담당자" AS deal_owner_json '
            "FROM deal d "
            "LEFT JOIN people p ON p.id = d.peopleId "
            f"WHERE d.\"상태\" = 'Won' AND d.\"계약 체결일\" LIKE '2025%' AND d.organizationId IN ({placeholders})",
            list(top_ids),
        )

    def _parse_owner_names(raw: Any) -> List[str]:
        names: List[str] = []
        data = _safe_json_load(raw)
        if isinstance(data, dict):
            name = data.get("name") or data.get("id")
            if name:
                names.append(str(name))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("id")
                    if name:
                        names.append(str(name))
                elif isinstance(item, str) and item.strip():
                    names.append(item.strip())
        elif isinstance(data, str) and data.strip():
            names.append(data.strip())
        return names

    def _extract_preferred_owner_names(row: sqlite3.Row) -> List[str]:
        people_names = _parse_owner_names(row["people_owner_json"])
        if people_names:
            return people_names
        deal_names = _parse_owner_names(row["deal_owner_json"])
        if deal_names:
            return deal_names
        return ["미입력"]

    for row in owner_rows:
        org_id = row["orgId"]
        upper = _normalize_counterparty_upper(row["upper_org"])
        key = (org_id, upper)
        if key not in cp_map:
            continue
        entry = cp_map[key]
        owner_names = _extract_preferred_owner_names(row)
        for name in owner_names:
            entry["owners2025"].add(name)

    rows: List[Dict[str, Any]] = []
    used_offline_overrides: Set[Tuple[str, str]] = set()
    used_online_overrides: Set[Tuple[str, str]] = set()

    # Collect org/upper universe for unused override diagnostics
    all_org_names: Set[str] = set()
    all_org_upper_pairs: Set[Tuple[str, str]] = set()
    people_upper_by_org_all: Dict[str, Set[str]] = {}
    with _connect(db_path) as conn:
        org_rows = _fetch_all(conn, 'SELECT id, COALESCE("이름", id) AS name FROM organization')
        org_name_lookup = {row["id"]: _norm_text(row["name"]) for row in org_rows}
        all_org_names.update(org_name_lookup.values())
        has_people_upper = _has_column(conn, "people", "소속 상위 조직")
        if has_people_upper:
            people_rows = _fetch_all(
                conn,
                'SELECT organizationId, "소속 상위 조직" AS upper_org FROM people WHERE organizationId IS NOT NULL',
            )
            for prow in people_rows:
                org_name = org_name_lookup.get(prow["organizationId"], "").strip()
                if not org_name:
                    continue
                upper_norm = _normalize_counterparty_upper(prow["upper_org"])
                all_org_upper_pairs.add((org_name, upper_norm))
                people_upper_by_org_all.setdefault(prow["organizationId"], set()).add(upper_norm)
        # Fallback: if people table absent, at least ensure org names set is populated.
    # Add cp_map will also add pairs below, but we want full-universe upper pairs when possible.
    for (org_id, upper), cp in cp_map.items():
        org_entry = org_lookup.get(org_id, {})
        org_tier = _compute_grade(org_entry.get("total", 0.0))
        org_name = (cp.get("orgName") or "").strip()
        upper_norm = _normalize_counterparty_upper(upper)
        target_key = (org_name, upper_norm)
        offline_override = target_key in offline_targets
        online_override = target_key in online_targets
        target_offline = offline_targets.get(target_key, cp["cpOffline2025"] * _tier_multiplier(org_tier))
        target_online = online_targets.get(target_key, cp["cpOnline2025"])
        if offline_override:
            used_offline_overrides.add(target_key)
        if online_override:
            used_online_overrides.add(target_key)

        rows.append(
            {
                "orgId": org_id,
                "orgName": org_name or org_id,
                "orgTier": org_tier,
                "orgWon2025": org_entry.get("total", 0.0),
                "orgOnline2025": org_entry.get("online", 0.0),
                "orgOffline2025": org_entry.get("offline", 0.0),
                "upperOrg": upper_norm,
                "cpOnline2025": cp["cpOnline2025"],
                "cpOffline2025": cp["cpOffline2025"],
                "cpTotal2025": cp["cpTotal2025"],
                "cpOnline2026": cp.get("cpOnline2026", 0.0),
                "cpOffline2026": cp.get("cpOffline2026", 0.0),
                "owners2025": sorted(cp["owners2025"]) if cp.get("owners2025") else [],
                "dealCount2025": cp["dealCount2025"],
                "target26Offline": target_offline,
                "target26Online": target_online,
                "target26OfflineIsOverride": offline_override,
                "target26OnlineIsOverride": online_override,
            }
        )

    existing_keys: Set[Tuple[str, str]] = set()
    for r in rows:
        org_name_norm = _norm_min(r.get("orgName"))
        upper_norm = _normalize_counterparty_upper(r.get("upperOrg"))
        if org_name_norm:
            existing_keys.add((org_name_norm, upper_norm))

    candidate_keys: Set[Tuple[str, str]] = set()
    candidate_keys.update({(_norm_min(org), _normalize_counterparty_upper(upper)) for org, upper in offline_targets.keys()})
    candidate_keys.update({(_norm_min(org), _normalize_counterparty_upper(upper)) for org, upper in online_targets.keys()})

    if candidate_keys:
        with _connect(db_path) as conn:
            org_rows_all = _fetch_all(
                conn,
                'SELECT id, COALESCE("이름", id) AS name, "기업 규모" AS sizeRaw FROM organization',
            )
            org_by_name: Dict[str, Dict[str, Any]] = {}
            org_name_dupes: Set[str] = set()
            for row in org_rows_all:
                name_norm = _norm_min(row["name"])
                if not name_norm:
                    continue
                if name_norm in org_by_name:
                    org_name_dupes.add(name_norm)
                org_by_name.setdefault(name_norm, row)

            org_total_lookup: Dict[str, float] = {row["orgId"]: row.get("total", 0.0) for row in org_lookup.values()}
            candidate_org_ids: Set[str] = set()
            for org_name_norm, _ in candidate_keys:
                if org_name_norm in org_name_dupes:
                    continue
                entry = org_by_name.get(org_name_norm)
                if entry:
                    candidate_org_ids.add(entry["id"])

            people_upper_by_org: Dict[str, Set[str]] = {}
            if candidate_org_ids:
                placeholders = ",".join("?" * len(candidate_org_ids))
                people_rows = _fetch_all(
                    conn,
                    f'SELECT organizationId, "소속 상위 조직" AS upper_org FROM people WHERE organizationId IN ({placeholders})',
                    list(candidate_org_ids),
                )
                for prow in people_rows:
                    org_id = prow["organizationId"]
                    upper_norm = _normalize_counterparty_upper(prow["upper_org"])
                    people_upper_by_org.setdefault(org_id, set()).add(upper_norm)

            missing_totals: Set[str] = set(candidate_org_ids) - set(org_total_lookup.keys())
            if missing_totals:
                cond_sql = " AND ".join(conditions)
                placeholders = ",".join("?" * len(missing_totals))
                total_rows = _fetch_all(
                    conn,
                    f'SELECT d.organizationId AS orgId, SUM(CAST(d."금액" AS REAL)) AS totalAmount '
                    "FROM deal d "
                    "LEFT JOIN organization o ON o.id = d.organizationId "
                    f"WHERE {cond_sql} AND d.organizationId IN ({placeholders}) "
                    "GROUP BY d.organizationId",
                    params + list(missing_totals),
                )
                for trow in total_rows:
                    org_total_lookup[trow["orgId"]] = _to_number(trow["totalAmount"]) or 0.0

            owners_by_org: Dict[str, Set[str]] = {}
            for r in rows:
                org_id = r.get("orgId")
                if not org_id:
                    continue
                owners_by_org.setdefault(org_id, set()).update(r.get("owners2025") or [])

            owners_needed = [org_id for org_id in candidate_org_ids if not owners_by_org.get(org_id)]
            if owners_needed:
                has_people_owner = _has_column(conn, "people", "담당자")
                people_owner_select = 'p."담당자"' if has_people_owner else "NULL"
                placeholders = ",".join("?" * len(owners_needed))
                owner_rows_extra = _fetch_all(
                    conn,
                    f'SELECT d.organizationId AS orgId, COALESCE(p."소속 상위 조직","미입력") AS upper_org, '
                    f'{people_owner_select} AS people_owner_json, d."담당자" AS deal_owner_json '
                    "FROM deal d "
                    "LEFT JOIN people p ON p.id = d.peopleId "
                    "WHERE d.\"상태\" = \'Won\' AND d.\"계약 체결일\" LIKE \'2025%\' AND d.organizationId IN ("
                    f"{placeholders})",
                    list(owners_needed),
                )
                for orow in owner_rows_extra:
                    owners_by_org.setdefault(orow["orgId"], set()).update(_extract_preferred_owner_names(orow))

        org_meta_by_id: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            org_id = row.get("orgId")
            if not org_id or org_id in org_meta_by_id:
                continue
            org_meta_by_id[org_id] = {
                "orgWon2025": row.get("orgWon2025") or 0.0,
                "sizeRaw": row.get("sizeRaw"),
            }

        for org_name_norm, upper_norm in sorted(candidate_keys):
            if not org_name_norm:
                continue
            if org_name_norm in org_name_dupes:
                if debug:
                    meta_entry = targets_meta.get((org_name_norm, upper_norm), {})
                    override_diagnostics.append(
                        {
                            "orgName": meta_entry.get("orgRaw") or org_name_norm,
                            "upperOrg": meta_entry.get("upperRaw") or upper_norm,
                            "org_match_count": 2,
                            "matched_org_id": None,
                            "matched_org_size": None,
                            "size_mismatch": False,
                            "upper_org_exists_in_people": False,
                            "has_deal_row_already": False,
                            "has_override": True,
                            "cpTotal2025": 0.0,
                            "would_be_dropped_by_zero_total_filter": True,
                        }
                    )
                continue

            org_entry = org_by_name.get(org_name_norm)
            if not org_entry:
                if debug:
                    meta_entry = targets_meta.get((org_name_norm, upper_norm), {})
                    override_diagnostics.append(
                        {
                            "orgName": meta_entry.get("orgRaw") or org_name_norm,
                            "upperOrg": meta_entry.get("upperRaw") or upper_norm,
                            "org_match_count": 0,
                            "matched_org_id": None,
                            "matched_org_size": None,
                            "size_mismatch": False,
                            "upper_org_exists_in_people": False,
                            "has_deal_row_already": False,
                            "has_override": True,
                            "cpTotal2025": 0.0,
                            "would_be_dropped_by_zero_total_filter": True,
                        }
                    )
                continue
            org_size = _row_get(org_entry, "sizeRaw")
            if size and size != "전체" and org_size != size:
                if debug:
                    meta_entry = targets_meta.get((org_name_norm, upper_norm), {})
                    override_diagnostics.append(
                        {
                            "orgName": meta_entry.get("orgRaw") or org_name_norm,
                            "upperOrg": meta_entry.get("upperRaw") or upper_norm,
                            "org_match_count": 1,
                            "matched_org_id": org_entry["id"],
                            "matched_org_size": org_size,
                            "size_mismatch": True,
                            "upper_org_exists_in_people": False,
                            "has_deal_row_already": False,
                            "has_override": True,
                            "cpTotal2025": 0.0,
                            "would_be_dropped_by_zero_total_filter": True,
                        }
                    )
                continue

            org_id = org_entry["id"]
            upper_set = people_upper_by_org.get(org_id, set())
            upper_exists = upper_norm in upper_set

            matched_org_name = _norm_min(org_entry["name"])
            key_norm = (matched_org_name, upper_norm) if matched_org_name else None
            has_deal_row = bool(key_norm and key_norm in existing_keys)
            cp_total_2025 = 0.0
            if key_norm and key_norm in deal_row_lookup:
                cp_total_2025 = deal_row_lookup[key_norm].get("cpTotal2025", 0.0)

            has_override = (org_name_norm, upper_norm) in override_keys
            org_total = org_total_lookup.get(org_id, 0.0)
            org_tier_guess = _compute_grade(org_total)
            would_drop_zero = (cp_total_2025 == 0) and (org_tier_guess != "N") and (not has_override)

            if debug:
                meta_entry = targets_meta.get((org_name_norm, upper_norm), {})
                override_diagnostics.append(
                    {
                        "orgName": meta_entry.get("orgRaw") or org_name_norm,
                        "upperOrg": meta_entry.get("upperRaw") or upper_norm,
                        "org_match_count": 1,
                        "matched_org_id": org_id,
                        "matched_org_size": org_size,
                        "size_mismatch": False,
                        "upper_org_exists_in_people": upper_exists,
                        "has_deal_row_already": has_deal_row,
                        "has_override": has_override,
                        "cpTotal2025": cp_total_2025,
                        "would_be_dropped_by_zero_total_filter": would_drop_zero,
                    }
                )

            if (matched_org_name, upper_norm) in existing_keys:
                continue
            if not upper_exists:
                continue

            org_won = org_meta_by_id.get(org_id, {}).get("orgWon2025")
            if org_won is None:
                org_won = org_total_lookup.get(org_id, 0.0)
            owners_list = sorted(owners_by_org.get(org_id, set()))

            offline_override = offline_targets.get((org_name_norm, upper_norm))
            online_override = online_targets.get((org_name_norm, upper_norm))
            if offline_override is not None:
                used_offline_overrides.add((org_name_norm, upper_norm))
            if online_override is not None:
                used_online_overrides.add((org_name_norm, upper_norm))

            rows.append(
                {
                    "orgId": org_id,
                    "orgName": matched_org_name or org_id,
                    "orgTier": "N",
                    "orgWon2025": org_won or 0.0,
                    "orgOnline2025": 0.0,
                    "orgOffline2025": 0.0,
                    "upperOrg": upper_norm,
                    "cpOnline2025": 0.0,
                    "cpOffline2025": 0.0,
                    "cpTotal2025": 0.0,
                    "cpOnline2026": 0.0,
                    "cpOffline2026": 0.0,
                    "owners2025": owners_list,
                    "dealCount2025": 0,
                    "target26Offline": offline_override if offline_override is not None else 0.0,
                    "target26Online": online_override if online_override is not None else 0.0,
                    "target26OfflineIsOverride": offline_override is not None,
                    "target26OnlineIsOverride": online_override is not None,
                }
            )
            existing_keys.add((matched_org_name, upper_norm))

    def _row_has_override(r: Dict[str, Any]) -> bool:
        key = (_norm_min(r.get("orgName")), _normalize_counterparty_upper(r.get("upperOrg")))
        return bool(r.get("target26OfflineIsOverride")) or bool(r.get("target26OnlineIsOverride")) or key in override_keys

    rows = [
        r
        for r in rows
        if (r.get("cpTotal2025") or 0) > 0 or ((r.get("orgTier") or "").upper() == "N") or _row_has_override(r)
    ]
    rows.sort(key=lambda r: (-r["orgWon2025"], -r["cpTotal2025"]))

    unused_offline = set(offline_targets.keys()) - used_offline_overrides
    unused_online = set(online_targets.keys()) - used_online_overrides

    def _raw_key(key: Tuple[str, str]) -> Tuple[str, str]:
        meta_entry = targets_meta.get(key, {})
        return (
            (meta_entry.get("orgRaw") if meta_entry.get("orgRaw") is not None else key[0]),
            (meta_entry.get("upperRaw") if meta_entry.get("upperRaw") is not None else key[1]),
        )

    # classify unused: org missing vs upper missing (org exists)
    def _classify(unused_keys: Set[Tuple[str, str]]) -> Tuple[Set[Tuple[str, str]], Set[Tuple[str, str]]]:
        org_missing = set()
        upper_missing = set()
        for org_name, upper in unused_keys:
            raw_org, raw_upper = _raw_key((org_name, upper))
            if org_name not in all_org_names:
                org_missing.add((raw_org, raw_upper))
            elif (org_name, upper) not in all_org_upper_pairs:
                upper_missing.add((raw_org, raw_upper))
        return org_missing, upper_missing

    offline_org_missing, offline_upper_missing = _classify(unused_offline)
    online_org_missing, online_upper_missing = _classify(unused_online)

    warn_key = (db_stat.st_mtime, targets_version)
    if warn_key not in _COUNTERPARTY_TARGET_WARNED:
        _COUNTERPARTY_TARGET_WARNED.add(warn_key)

        def _log_unused(label: str, keys: Set[Tuple[str, str]]) -> None:
            if not keys:
                return
            lines = "\n  - " + "\n  - ".join(f"{org} | {upper}" for org, upper in sorted(keys))
            logging.warning(
                "[counterparty_targets_2026] %s: count=%d%s",
                label,
                len(keys),
                lines,
            )

        _log_unused("unused offline overrides (org missing in DB)", offline_org_missing)
        _log_unused("unused offline overrides (org present but upper missing)", offline_upper_missing)
        _log_unused("unused online overrides (org missing in DB)", online_org_missing)
        _log_unused("unused online overrides (org present but upper missing)", online_upper_missing)

    meta = {
        "orgCount": len(top_orgs),
        "rowCount": len(rows),
        "offset": org_offset,
        "limit": org_limit,
        "snapshot_version": snapshot_version,
    }
    if debug:
        meta["overrideDiagnostics"] = override_diagnostics
    return rows, meta, len(top_orgs)


def get_rank_2025_top100_counterparty_dri(
    size: str = "대기업",
    limit: int | None = None,
    offset: int = 0,
    db_path: Path = DB_PATH,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Top organizations by 2025 Won (size-filtered) with counterparty(upper_org) breakdown and owners list.
    - Online formats: 구독제(온라인)/선택구매(온라인)/포팅 (exact match)
    - Offline: others
    - Sorting: orgWon2025 desc, then cpTotal2025 desc
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    max_limit = 200_000
    if limit is not None:
        limit = max(1, min(limit or 1, max_limit))
        offset = max(0, offset or 0)
    else:
        offset = 0

    offline_targets, online_targets, targets_meta, targets_version = load_counterparty_targets_2026()
    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime, size or "대기업", limit or "all", offset, targets_version, debug)
    cached = None if debug else _COUNTERPARTY_DRI_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows, meta, org_count = _compute_counterparty_dri_rows(
        size=size,
        org_limit=limit,
        org_offset=offset,
        db_path=db_path,
        offline_targets=offline_targets,
        online_targets=online_targets,
        targets_version=targets_version,
        targets_meta=targets_meta,
        debug=debug,
    )

    result = {
        "size": size or "대기업",
        "limit": limit,
        "offset": offset,
        "rows": rows,
        "meta": {**meta, "targetsVersion": targets_version},
    }
    if not debug:
        _COUNTERPARTY_DRI_CACHE[cache_key] = result
    return result


def get_rank_2025_counterparty_dri_targets_summary(size: str = "대기업", db_path: Path = DB_PATH) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    offline_targets, online_targets, targets_meta, targets_version = load_counterparty_targets_2026()
    stat = db_path.stat()
    cache_key = (db_path, stat.st_mtime, size or "대기업", targets_version)
    cached = _COUNTERPARTY_DRI_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows, meta, _ = _compute_counterparty_dri_rows(
        size=size,
        org_limit=200000,
        org_offset=0,
        db_path=db_path,
        offline_targets=offline_targets,
        online_targets=online_targets,
        targets_version=targets_version,
        targets_meta=targets_meta,
        debug=False,
    )

    totals = {
        "cpOffline2025": 0.0,
        "target26Offline": 0.0,
        "cpOffline2026": 0.0,
        "cpOnline2025": 0.0,
        "target26Online": 0.0,
        "cpOnline2026": 0.0,
        "overrideAppliedOffline": 0,
        "overrideAppliedOnline": 0,
    }
    for row in rows:
        totals["cpOffline2025"] += row.get("cpOffline2025") or 0.0
        totals["target26Offline"] += row.get("target26Offline") or 0.0
        totals["cpOffline2026"] += row.get("cpOffline2026") or 0.0
        totals["cpOnline2025"] += row.get("cpOnline2025") or 0.0
        totals["target26Online"] += row.get("target26Online") or 0.0
        totals["cpOnline2026"] += row.get("cpOnline2026") or 0.0
        if row.get("target26OfflineIsOverride"):
            totals["overrideAppliedOffline"] += 1
        if row.get("target26OnlineIsOverride"):
            totals["overrideAppliedOnline"] += 1

    result = {
        "meta": {
            "size": size or "대기업",
            "rowCount": len(rows),
            "snapshot_version": meta.get("snapshot_version"),
            "targets_version": targets_version,
        },
        "totals": totals,
    }
    _COUNTERPARTY_DRI_SUMMARY_CACHE[cache_key] = result
    return result
