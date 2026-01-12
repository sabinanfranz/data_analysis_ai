import logging
import threading
from pathlib import Path
from typing import Any, Dict, Tuple

import openpyxl

RESOURCE_PATH = Path(__file__).parent / "resources" / "counterparty_targets_2026.xlsx"

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"mtime": None, "offline": {}, "online": {}}


def _normalize_name(val: Any) -> str:
    text = (val or "").strip()
    if not text:
        return ""
    return text


def _normalize_upper(val: Any) -> str:
    text = (val or "").strip()
    if not text or text in {"-", "–", "—"}:
        return "미입력"
    return text


def _parse_value(val: Any) -> float | None:
    try:
        num = float(val)
        return num * 1e8
    except Exception:
        return None


def _load_sheet(ws, value_col: str) -> Dict[Tuple[str, str], float]:
    rows = ws.iter_rows(min_row=1, max_row=1, values_only=True)
    headers = next(rows, None)
    if not headers:
        logging.warning("[counterparty_targets_2026] sheet=%s empty header", ws.title)
        return {}
    header_idx = {str(h).strip(): idx for idx, h in enumerate(headers) if h is not None and str(h).strip()}
    required = ["기업명", "카운터파티", value_col]
    if not all(col in header_idx for col in required):
        logging.warning("[counterparty_targets_2026] sheet=%s missing columns %s", ws.title, required)
        return {}

    entries: Dict[Tuple[str, str], list] = {}
    for excel_row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        org_raw = row[header_idx["기업명"]] if header_idx["기업명"] < len(row) else None
        upper_raw = row[header_idx["카운터파티"]] if header_idx["카운터파티"] < len(row) else None
        val_raw = row[header_idx[value_col]] if header_idx[value_col] < len(row) else None

        org = _normalize_name(org_raw)
        upper = _normalize_upper(upper_raw)
        key = (org, upper)

        val = _parse_value(val_raw)
        if val is None:
            logging.warning(
                "[counterparty_targets_2026] invalid value sheet=%s row=%d key=(%s|%s) raw=%s",
                ws.title,
                excel_row_idx,
                org,
                upper,
                val_raw,
            )
            continue
        entries.setdefault(key, []).append((excel_row_idx, val_raw, val))

    result: Dict[Tuple[str, str], float] = {}
    for key, items in entries.items():
        if len(items) > 1:
            rows = [it[0] for it in items]
            values = [it[1] for it in items]
            logging.warning(
                "[counterparty_targets_2026] DUPLICATE_KEY sheet=%s key=(%s|%s) rows=%s values=%s",
                ws.title,
                key[0],
                key[1],
                rows,
                values,
            )
            continue
        result[key] = float(items[0][2])
    return result


def load_counterparty_targets_2026() -> Tuple[Dict[Tuple[str, str], float], Dict[Tuple[str, str], float], str]:
    """
    Returns offline_targets, online_targets (won unit) and version string based on xlsx mtime.
    """
    with _CACHE_LOCK:
        try:
            stat = RESOURCE_PATH.stat()
        except FileNotFoundError:
            logging.warning("[counterparty_targets_2026] resource not found: %s", RESOURCE_PATH)
            return {}, {}, "xlsx_mtime:none"
        mtime = int(stat.st_mtime)
        if _CACHE.get("mtime") == mtime:
            return _CACHE["offline"], _CACHE["online"], f"xlsx_mtime:{mtime}"

        wb = openpyxl.load_workbook(RESOURCE_PATH, data_only=True, read_only=True)
        offline_ws = wb["26 출강 타겟"] if "26 출강 타겟" in wb.sheetnames else None
        online_ws = wb["26 온라인 타겟"] if "26 온라인 타겟" in wb.sheetnames else None

        offline = _load_sheet(offline_ws, "26 출강 타겟") if offline_ws else {}
        online = _load_sheet(online_ws, "26 온라인 타겟") if online_ws else {}

        _CACHE.update({"mtime": mtime, "offline": offline, "online": online})
        return offline, online, f"xlsx_mtime:{mtime}"
