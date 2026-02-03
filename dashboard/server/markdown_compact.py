from __future__ import annotations

from typing import Any, Dict, List, Sequence

import re

from .json_compact import YEAR_ORDER

PHONE_REGEX = re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b")


def md_escape_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def fmt_won(n: Any) -> str:
    try:
        num = float(n)
    except (TypeError, ValueError):
        return ""
    if num.is_integer():
        return f"{int(num):,}"
    return f"{num:,.1f}"


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[: max_chars]
    return text[: max_chars - 3] + "..."


def _redact_phone(text: str) -> str:
    return PHONE_REGEX.sub("[phone]", text)


def render_summary_table(summary: Dict[str, Any] | None, years: Sequence[str] = ("2023", "2024", "2025")) -> str:
    if not summary:
        return ""
    lines: List[str] = []
    years = list(years)
    lines.append(f"| 항목 | {' | '.join(years)} |")
    lines.append(f"| --- | {' | '.join('---' for _ in years)} |")
    rows = [
        ("Won 합계", summary.get("won_amount_by_year") or {}),
        ("Won 온라인", summary.get("won_amount_online_by_year") or {}),
        ("Won 오프라인", summary.get("won_amount_offline_by_year") or {}),
    ]
    for label, obj in rows:
        cells = [fmt_won(obj.get(y)) for y in years]
        lines.append(f"| {md_escape_cell(label)} | {' | '.join(md_escape_cell(c) for c in cells)} |")
    return "\n".join(lines)


def sum_summary_blocks(blocks: Sequence[Dict[str, Any]] | None) -> Dict[str, Dict[str, float]]:
    years = YEAR_ORDER if YEAR_ORDER else ["2023", "2024", "2025"]
    result = {
        "won_amount_by_year": {y: 0.0 for y in years},
        "won_amount_online_by_year": {y: 0.0 for y in years},
        "won_amount_offline_by_year": {y: 0.0 for y in years},
    }
    if not blocks:
        return result
    for block in blocks:
        if not block:
            continue
        for key in ("won_amount_by_year", "won_amount_online_by_year", "won_amount_offline_by_year"):
            src = block.get(key) or {}
            for y in years:
                try:
                    result[key][y] += float(src.get(y) or 0)
                except (TypeError, ValueError):
                    continue
    return result


def pick_clean_text(clean_text: Dict[str, Any] | None) -> str:
    if not clean_text or not isinstance(clean_text, dict):
        return ""
    preferred_keys = [
        "question",
        "summary",
        "short",
        "brief",
        "상담문의내용",
        "내용",
        "text",
        "body",
        "value",
        "content",
        "message",
    ]
    for key in preferred_keys:
        val = clean_text.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    for val in clean_text.values():
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def normalize_memo_text(memo: Dict[str, Any] | None, *, max_chars: int = 240, redact_phone: bool = True) -> str:
    if not memo:
        return ""
    text = ""
    clean = memo.get("cleanText")
    if isinstance(clean, dict):
        text = pick_clean_text(clean)
    if not text:
        raw = memo.get("text")
        if isinstance(raw, str):
            text = raw
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    if redact_phone and text:
        text = _redact_phone(text)
    text = _truncate(text, max_chars)
    return text


def _memo_sort_key(memo: Dict[str, Any]) -> tuple[str, str]:
    created_ts = memo.get("created_at_ts") or ""
    date_val = memo.get("date") or ""
    return (str(created_ts), str(date_val))


def summarize_memos(
    memos: Sequence[Dict[str, Any]] | None,
    *,
    limit: int,
    max_chars: int,
    redact_phone: bool,
) -> Dict[str, Any]:
    if not memos:
        return {"count": 0, "lines": []}
    sorted_memos = sorted(memos, key=_memo_sort_key, reverse=True)
    lines: List[str] = []
    for idx, memo in enumerate(sorted_memos[:limit]):
        snippet = normalize_memo_text(memo, max_chars=max_chars, redact_phone=redact_phone)
        date_val = memo.get("date") or ""
        lines.append(f"{idx + 1}) {date_val} - {snippet}")
    return {"count": len(memos), "lines": lines}


def won_groups_compact_to_markdown(
    compact_data: Dict[str, Any],
    *,
    scope_label: str = "ORG_ALL",
    max_people: int = 60,
    max_deals: int = 200,
    deal_memo_limit: int = 10,
    memo_max_chars: int = 240,
    redact_phone: bool = True,
    max_output_chars: int = 200_000,
) -> str:
    if not compact_data or not isinstance(compact_data, dict) or not compact_data.get("groups"):
        return "데이터가 없습니다."

    org = compact_data.get("organization") or {}
    org_name = org.get("name") or org.get("org_name") or org.get("orgName") or "미입력"
    industry_line = " / ".join(filter(None, [org.get("industry_major") or org.get("industryMajor"), org.get("industry_mid") or org.get("industryMid")]))

    lines: List[str] = []
    char_count = 0
    truncated = False

    def _add(line: str) -> bool:
        nonlocal char_count, truncated
        if truncated:
            return False
        projected = char_count + len(line) + 1
        if projected > max_output_chars:
            lines.append("(truncated due to size limit)")
            truncated = True
            return False
        lines.append(line)
        char_count = projected
        return True

    def _add_block(text: str) -> bool:
        for ln in (text or "").split("\n"):
            if not _add(ln):
                return False
        return True

    _add(f"# {org_name} - compact-info-md/v1.1")
    _add(f"- org_id: {org.get('id') or org.get('org_id') or ''}")
    _add(f"- scope: {scope_label}")
    _add(f"- size: {org.get('size') or org.get('size_group') or org.get('legacy_size_group') or '-'}")
    _add(f"- industry: {industry_line or '-'}")
    _add("")

    _add("## Summary (Org)")
    _add_block(render_summary_table(org.get("summary")))

    scope_summary = sum_summary_blocks([g.get("counterparty_summary") for g in compact_data.get("groups", [])])
    _add("")
    _add("## Summary (Scope)")
    _add_block(render_summary_table(scope_summary))

    for group in compact_data.get("groups", []):
        if truncated:
            break
        people = group.get("people") or []
        deals = group.get("deals") or []
        people_index = {}
        for p in people:
            pid = p.get("id") or p.get("people_id") or p.get("peopleId")
            if pid:
                people_index[pid] = p

        _add("")
        _add("---")
        _add(f"## {group.get('upper_org') or '(상위 조직 미입력)'} / {group.get('team') or '-'}")

        defaults = group.get("deal_defaults") or {}
        default_entries = [(k, v) for k, v in defaults.items() if v is not None]
        if default_entries:
            parts = []
            for k, v in default_entries:
                if k == "day1_teams" and isinstance(v, list):
                    names = ", ".join(str(item.get("name") or item.get("id") or "") for item in v if item)
                    parts.append(f"{k}={names or '(none)'}")
                else:
                    parts.append(f"{k}={v}")
            _add(f"- deal_defaults: {' | '.join(parts)}")

        _add("")
        _add("### Group Won Summary")
        _add_block(render_summary_table(group.get("counterparty_summary")))

        if people:
            _add("")
            _add("### People")
            _add("| Name | Title | Team | Edu | Signals | Last memo |")
            _add("| --- | --- | --- | --- | --- | --- |")
            shown_people = people[: max_people] if max_people else people
            for p in shown_people:
                last_memo = summarize_memos(p.get("memos"), limit=1, max_chars=140, redact_phone=redact_phone)
                memo_cell = "<br>".join(last_memo["lines"]) if last_memo["lines"] else ""
                _add(
                    f"| {md_escape_cell(p.get('name') or p.get('people_name') or '-')} | "
                    f"{md_escape_cell(p.get('title') or '-')} | "
                    f"{md_escape_cell(p.get('team') or '-')} | "
                    f"{md_escape_cell(p.get('edu_area') or '-')} | "
                    f"{md_escape_cell(p.get('signals') or '')} | "
                    f"{md_escape_cell(memo_cell)} |"
                )
            if max_people and len(people) > len(shown_people):
                _add(f"_truncated: {len(people) - len(shown_people)} more people not shown_")

        _add("")
        _add("### Deals")
        shown_deals = deals[: max_deals] if max_deals else deals
        if not shown_deals:
            _add("거래가 없습니다.")
            continue
        _add("| # | Deal | Status | Amount | Contract | Expected | Period | Contact | Exceptions | Memos |")
        _add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for idx, deal in enumerate(shown_deals):
            if truncated:
                break
            deal_name = deal.get("name") or deal.get("deal_name") or "(no name)"
            id_fragment = str(deal.get("id") or "")[:8]
            deal_label = f"{deal_name} ({id_fragment})" if id_fragment else deal_name
            amount_val = deal.get("amount")
            if amount_val is None:
                amount_val = deal.get("expected_amount")
            period = ""
            if deal.get("start_date") and deal.get("end_date"):
                period = f"{deal.get('start_date')}~{deal.get('end_date')}"
            else:
                period = deal.get("start_date") or deal.get("end_date") or ""
            contact = ""
            person = people_index.get(deal.get("people_id") or deal.get("peopleId"))
            if person:
                nm = person.get("name") or person.get("people_name") or ""
                title = f" ({person.get('title')})" if person.get("title") else ""
                contact = f"{nm}{title}"

            exceptions: List[str] = []
            if "owner" in deal and deal.get("owner"):
                exceptions.append(f"owner={deal.get('owner')}")
            if "course_format" in deal and deal.get("course_format"):
                exceptions.append(f"course_format={deal.get('course_format')}")
            if "category" in deal and deal.get("category"):
                exceptions.append(f"category={deal.get('category')}")
            if deal.get("day1_teams"):
                names = ", ".join(str(t.get("name") or t.get("id") or "") for t in deal.get("day1_teams") if t)
                exceptions.append(f"day1_teams={names}")

            memo_summary = summarize_memos(
                deal.get("memos"),
                limit=deal_memo_limit,
                max_chars=memo_max_chars,
                redact_phone=redact_phone,
            )
            memo_cell = ""
            if memo_summary["lines"]:
                memo_cell = f"(총 {memo_summary['count']}개) " + "<br>".join(memo_summary["lines"])

            _add(
                f"| {md_escape_cell(idx + 1)} | "
                f"{md_escape_cell(deal_label)} | "
                f"{md_escape_cell(deal.get('status') or '-')} | "
                f"{md_escape_cell(fmt_won(amount_val))} | "
                f"{md_escape_cell(deal.get('contract_date') or '')} | "
                f"{md_escape_cell(deal.get('expected_date') or deal.get('expected_close_date') or '')} | "
                f"{md_escape_cell(period)} | "
                f"{md_escape_cell(contact)} | "
                f"{md_escape_cell(' | '.join(exceptions))} | "
                f"{md_escape_cell(memo_cell)} |"
            )

        if truncated:
            break
        if max_deals and len(deals) > len(shown_deals):
            _add(f"_truncated: {len(deals) - len(shown_deals)} more deals not shown_")

    return "\n".join(lines)
