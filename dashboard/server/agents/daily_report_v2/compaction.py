from __future__ import annotations

from typing import Any, Dict, List

MAX_STR_LEN = 500
MAX_LIST_LEN = 10

ALLOWLIST_KEYS = {"rowKey", "error", "likelihood", "one_line", "numbers", "top_reasons", "flags"}


def _trim_str(val: str, limit: int = MAX_STR_LEN) -> str:
    if len(val) <= limit:
        return val
    return val[:limit] + "...(truncated)"


def _trim_list(values: List[Any], *, debug: bool) -> List[Any]:
    trimmed: List[Any] = []
    for v in values[:MAX_LIST_LEN]:
        if isinstance(v, str):
            trimmed.append(_trim_str(v))
        elif isinstance(v, list):
            trimmed.append(_trim_list(v, debug=debug))
        elif isinstance(v, dict):
            # shallow keep; deeper trimming not to overcomplicate
            trimmed.append(v)
        else:
            trimmed.append(v)
    return trimmed


class RowOutputCompactor:
    @staticmethod
    def compact(row_output: Dict[str, Any] | None, *, debug: bool = False) -> Dict[str, Any]:
        if not isinstance(row_output, dict):
            return {"error": "INVALID_ROW_OUTPUT"}

        out: Dict[str, Any] = {}
        for key, value in row_output.items():
            if key not in ALLOWLIST_KEYS:
                continue
            if key == "one_line" and isinstance(value, str):
                out[key] = _trim_str(value)
            elif key in {"top_reasons", "flags"} and isinstance(value, list):
                out[key] = _trim_list(value, debug=debug)
            elif key == "numbers" and isinstance(value, dict):
                out[key] = value
            elif key == "error" and isinstance(value, str):
                out[key] = _trim_str(value, limit=300)
            else:
                out[key] = value

        if debug:
            if "__meta" in row_output and isinstance(row_output["__meta"], dict):
                out["__meta"] = row_output["__meta"]
        return out


def build_part_inputs(rows: List[Dict[str, Any]], compacted_row_outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build part-level inputs with minimal fields; groups by upperOrg (or fallback).
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for idx, row in enumerate(rows):
        upper = row.get("upperOrg") or row.get("upper_org") or "__unknown__"
        rk = row.get("rowKey") or row.get("key") or row.get("id") or f"idx:{idx}"
        compacted = compacted_row_outputs[idx] if idx < len(compacted_row_outputs) else {"error": "missing_output"}
        entry = {
            "rowKey": rk,
            "orgId": row.get("orgId") or row.get("org_id") or "",
            "upperOrg": upper,
            "tier": row.get("tier"),
            "target": row.get("target") if row.get("target") is not None else row.get("target_2026") or 0,
            "actual": row.get("actual") if row.get("actual") is not None else row.get("actual_2026") or 0,
            "row_agent_output_json": compacted,
        }
        groups.setdefault(upper, []).append(entry)

    part_inputs: List[Dict[str, Any]] = []
    for upper, items in groups.items():
        part_inputs.append({"part_name": upper, "rows": items})
    # deterministic order
    part_inputs.sort(key=lambda x: str(x["part_name"]))
    return part_inputs
