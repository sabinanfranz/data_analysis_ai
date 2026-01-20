from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .database import YEARS_FOR_WON, _date_only, _safe_json_load, _to_number
from .html_to_markdown import html_to_markdown, should_enrich_text, strip_key_deep

SCHEMA_VERSION = "won-groups-json/compact-v1"
ONLINE_COURSE_FORMATS = {"구독제(온라인)", "선택구매(온라인)", "포팅"}
YEAR_ORDER = ["2023", "2024", "2025"]
DEFAULT_FIELDS = {"course_format", "category", "owner", "day1_teams"}


def compact_won_groups_json(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a compact variant of /won-groups-json for LLM input:
    - Remove nested people in deals, keep people_id reference only.
    - Split 고객사 팀(group.team) vs 데이원 팀(deal.day1_teams).
    - Drop null/[] recursively.
    - Pull common deal fields up to group.deal_defaults (mode >=80%, n>=3).
    - Add counterparty/organization won summaries.
    """
    org_meta = raw.get("organization") or {}
    groups_raw = raw.get("groups") or []

    org_summary = _empty_summary_block()
    compact_groups: List[Dict[str, Any]] = []

    for group in groups_raw:
        people_raw = group.get("people") or []
        deals_raw = group.get("deals") or []

        people_list: List[Dict[str, Any]] = []
        people_index: Dict[str, Dict[str, Any]] = {}
        for person in people_raw:
            person_copy = dict(person)
            pid = person_copy.get("id")
            if pid:
                people_index[pid] = person_copy
            people_list.append(person_copy)

        deals_list: List[Dict[str, Any]] = []
        for deal in deals_raw:
            deal_copy = dict(deal)
            person_info = deal_copy.pop("people", None)

            people_id = deal_copy.get("people_id") or deal_copy.get("peopleId")
            if not people_id and isinstance(person_info, dict):
                people_id = person_info.get("id") or person_info.get("peopleId")
            if people_id:
                deal_copy["people_id"] = people_id
                if people_id not in people_index and isinstance(person_info, dict):
                    stub = {
                        k: person_info.get(k)
                        for k in ("id", "name", "upper_org", "team", "title", "edu_area")
                        if person_info.get(k) is not None
                    }
                    people_list.append(stub)
                    people_index[people_id] = stub

            teams_val, teams_raw = _normalize_day1_teams(deal_copy.pop("team", None))
            if teams_val is not None:
                deal_copy["day1_teams"] = teams_val
            if teams_raw is not None:
                deal_copy["day1_teams_raw"] = teams_raw

            probability = deal_copy.get("probability")
            normalized_prob = _normalize_jsonish(probability)
            if normalized_prob is not None:
                deal_copy["probability"] = normalized_prob

            # Normalize date fields to YYYY-MM-DD
            for date_key in ("contract_date", "created_at", "expected_date", "lost_confirmed_at", "start_date", "end_date"):
                if date_key in deal_copy:
                    deal_copy[date_key] = _date_only(deal_copy[date_key]) or None

            deals_list.append(deal_copy)

        group_summary = _build_summary(deals_list)
        _accumulate_summary(org_summary, group_summary)

        defaults = _extract_deal_defaults(deals_list)
        if defaults:
            for deal in deals_list:
                for field, value in defaults.items():
                    if field in deal and _values_equal(deal[field], value):
                        deal.pop(field, None)

        compact_group = {
            "upper_org": group.get("upper_org"),
            "team": group.get("team"),
            "deal_defaults": defaults,
            "counterparty_summary": group_summary,
            "people": people_list,
            "deals": deals_list,
        }
        compact_groups.append(compact_group)

    compact = {
        "schema_version": SCHEMA_VERSION,
        "organization": {**org_meta, "summary": org_summary},
        "groups": compact_groups,
    }
    compact = _strip_memo_html(compact)
    compact = strip_key_deep(compact, "htmlBody")
    return _prune(compact, keep_keys={"schema_version", "organization"})


def _normalize_jsonish(value: Any) -> Any:
    parsed = _safe_json_load(value)
    if isinstance(parsed, (list, dict)):
        return parsed
    return value


def _normalize_day1_teams(raw_value: Any) -> Tuple[List[Dict[str, Any]] | None, Any | None]:
    if raw_value is None:
        return None, None
    parsed = _safe_json_load(raw_value)
    teams_source: Any
    if isinstance(parsed, dict):
        teams_source = [parsed]
    elif isinstance(parsed, list):
        teams_source = parsed
    else:
        return None, raw_value

    normalized: List[Dict[str, Any]] = []
    for item in teams_source:
        if isinstance(item, dict):
            entry: Dict[str, Any] = {}
            if item.get("id") is not None:
                entry["id"] = item.get("id")
            if item.get("name") is not None:
                entry["name"] = item.get("name")
            if entry:
                normalized.append(entry)
        elif item is not None:
            normalized.append({"name": str(item)})
    return normalized, None


def _build_summary(deals: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    summary = _empty_summary_block()
    for deal in deals:
        if deal.get("status") != "Won":
            continue
        year = str(deal.get("contract_date") or "")[:4]
        if year not in YEARS_FOR_WON:
            continue
        amount = _to_number(deal.get("amount")) or 0.0
        summary["won_amount_by_year"][year] += amount
        course_format = deal.get("course_format")
        if course_format in ONLINE_COURSE_FORMATS:
            summary["won_amount_online_by_year"][year] += amount
        else:
            summary["won_amount_offline_by_year"][year] += amount
    return summary


def _empty_summary_block() -> Dict[str, Dict[str, float]]:
    return {
        "won_amount_by_year": {year: 0.0 for year in YEAR_ORDER},
        "won_amount_online_by_year": {year: 0.0 for year in YEAR_ORDER},
        "won_amount_offline_by_year": {year: 0.0 for year in YEAR_ORDER},
    }


def _accumulate_summary(target: Dict[str, Dict[str, float]], source: Dict[str, Dict[str, float]]) -> None:
    for key in target:
        for year in YEAR_ORDER:
            target[key][year] += source.get(key, {}).get(year, 0.0)


def _extract_deal_defaults(deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    if len(deals) < 3:
        return defaults

    for field in DEFAULT_FIELDS:
        values: List[Any] = []
        for deal in deals:
            if field not in deal:
                continue
            val = deal.get(field)
            if val is None or val == []:
                continue
            values.append(val)
        if len(values) < 3:
            continue
        mode_value, mode_count = _mode(values)
        if mode_count / len(deals) >= 0.8:
            defaults[field] = mode_value
    return defaults


def _mode(values: List[Any]) -> Tuple[Any, int]:
    counts: Dict[Any, int] = {}
    first_seen: Dict[Any, Any] = {}
    for val in values:
        key = _hashable(val)
        counts[key] = counts.get(key, 0) + 1
        if key not in first_seen:
            first_seen[key] = val
    mode_key = max(counts, key=counts.get)
    return first_seen[mode_key], counts[mode_key]


def _hashable(val: Any) -> Any:
    if isinstance(val, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in val.items()))
    if isinstance(val, list):
        return tuple(_hashable(v) for v in val)
    return val


def _values_equal(left: Any, right: Any) -> bool:
    return _hashable(left) == _hashable(right)


def _strip_memo_html(value: Any) -> Any:
    """
    Remove htmlBody keys from any memo-like dicts for compact payloads.
    If htmlBody exists and text is missing/blank, fill text with a plain-text
    representation of htmlBody for better readability in compact JSON.
    """
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        html_body = value.get("htmlBody")
        text_val = value.get("text")
        need_fill = (
            html_body is not None
            and should_enrich_text(text_val)
        )
        for k, v in value.items():
            if k == "htmlBody":
                continue
            result[k] = _strip_memo_html(v)
        if need_fill:
            result["text"] = html_to_markdown(str(html_body))
        return result
    if isinstance(value, list):
        return [_strip_memo_html(item) for item in value]
    return value


def _prune(value: Any, keep_keys: set[str]) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, val in value.items():
            pruned = _prune(val, keep_keys)
            if pruned is None:
                continue
            if pruned == [] and key not in keep_keys:
                continue
            if pruned == {} and key not in keep_keys:
                continue
            cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        items: List[Any] = []
        for item in value:
            pruned = _prune(item, keep_keys)
            if pruned is None:
                continue
            if pruned == []:
                continue
            if pruned == {}:
                continue
            items.append(pruned)
        if not items:
            return []
        return items
    if value is None:
        return None
    return value
