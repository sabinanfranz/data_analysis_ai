#!/usr/bin/env python3
"""
Generate people-owner mapping workbook from '26 온라인 타겟' sheet and salesmap DB.

Output: people_owner_mapping_from_26_online_targets.xlsx with sheets:
  - result: mapped people rows
  - log: skipped rows and team mismatches

Usage: python scripts/generate_people_owner_mapping_from_online_targets.py
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from openpyxl import Workbook, load_workbook


# PART_STRUCTURE extracted from org_tables_v2.html (source of truth).
PART_STRUCTURE: Dict[str, Dict[str, List[str]]] = {
    "기업교육 1팀": {
        "1파트": ["김솔이", "황초롱", "김정은", "김동찬", "정태윤", "서정연", "오진선", "공새봄", "김별"],
        "2파트": ["강지선", "정하영", "박범규", "하승민", "이은서", "김세연"],
    },
    "기업교육 2팀": {
        "1파트": ["권노을", "이윤지B", "이현진", "김민선", "강연정", "방신우", "홍제환", "정선희"],
        "2파트": ["정다혜", "임재우", "송승희", "손승완", "김윤지", "손지훈", "홍예진"],
        "온라인셀": ["강진우", "강다현", "이수빈"],
    },
    "공공교육팀": {
        "전체": ["이준석", "김미송", "오정민", "조경원", "김다인", "서민정", "김지원", "김진호"],
    },
}


ROOT = Path(__file__).resolve().parent.parent
EXCEL_PATH = ROOT / "dashboard/server/resources/counterparty_targets_2026.xlsx"
DB_PATH = ROOT / "dashboard/server/resources/salesmap_latest.db"
if not DB_PATH.exists():
    DB_PATH = ROOT / "salesmap_latest.db"
OUTPUT_PATH = ROOT / "people_owner_mapping_from_26_online_targets.xlsx"
INPUT_SHEET = "26 온라인 타겟"
RESULT_SHEET = "result"
LOG_SHEET = "log"


def clean_str(value: Optional[object]) -> str:
    return "" if value is None else str(value).strip()


def norm_upper_org(value: Optional[object]) -> str:
    text = clean_str(value)
    return text if text else "미입력"


def parse_assignee(cell_value: Optional[object]) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (assignee, error_reason). error_reason is 'assignee_multi' when skipped.
    """
    if cell_value is None:
        return "", None
    tokens = [token.strip() for token in str(cell_value).split(",")]
    tokens = [tok for tok in tokens if tok]
    if len(tokens) > 1:
        return None, "assignee_multi"
    if len(tokens) == 1:
        return tokens[0], None
    return "", None


def normalize_owner_name(raw_owner: Optional[object]) -> Tuple[str, bool, bool, str]:
    """
    Normalize owner string to just the human name.

    Returns (normalized_name, was_json_candidate, json_name_extracted, parse_error_msg).
    """
    text = clean_str(raw_owner)
    if not text:
        return "", False, False, ""

    stripped = text.strip()
    is_json_candidate = stripped.startswith("{") and stripped.endswith("}")
    json_name_extracted = False
    parse_error = ""

    if is_json_candidate:
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                candidate = parsed.get("name") or parsed.get("displayName")
                if candidate and clean_str(candidate):
                    return clean_str(candidate), True, True, ""
            # fall through to general handling when name missing
        except Exception as exc:  # keep broad to avoid skipping due to ValueError TypeError etc.
            parse_error = f"{exc.__class__.__name__}: {exc}"
        else:
            # JSON parsed but name missing -> fall back
            json_name_extracted = False

    # non-JSON or fallback path
    text_no_extra = stripped
    if "외" in text_no_extra:
        text_no_extra = text_no_extra.split("외", 1)[0].strip()
    for sep in ("(", "（"):
        if sep in text_no_extra:
            text_no_extra = text_no_extra.split(sep, 1)[0].strip()
            break
    return text_no_extra, is_json_candidate, json_name_extracted, parse_error


# minimal assertions to guard key behaviors
assert normalize_owner_name('{"id":"x","name":"정다혜"}')[0] == "정다혜"
assert normalize_owner_name("정다혜")[0] == "정다혜"
assert normalize_owner_name("정다혜 외 1명")[0] == "정다혜"
assert normalize_owner_name("")[0] == ""


def build_org_index(conn: sqlite3.Connection) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = defaultdict(list)
    for org_id, name in conn.execute('SELECT id, "이름" FROM organization'):
        name_clean = clean_str(name)
        if not name_clean:
            continue
        index[name_clean].append(org_id)
    return index


def load_people_by_org(conn: sqlite3.Connection) -> Dict[str, List[sqlite3.Row]]:
    """
    Load all people once (no index on organizationId), grouped by organizationId.
    """
    people_by_org: Dict[str, List[sqlite3.Row]] = defaultdict(list)
    cur = conn.execute('SELECT organizationId,"RecordId","이름","담당자","소속 상위 조직" FROM people')
    for row in cur:
        people_by_org[row["organizationId"]].append(row)
    return people_by_org


def build_name_to_team(part_structure: Dict[str, Dict[str, Iterable[str]]]) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for team, parts in part_structure.items():
        for names in parts.values():
            for name in names:
                key = name.strip()
                if not key:
                    continue
                mapping.setdefault(key, []).append(team)
    return mapping


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    org_index = build_org_index(conn)
    people_by_org = load_people_by_org(conn)
    name_to_team = build_name_to_team(PART_STRUCTURE)

    wb = load_workbook(EXCEL_PATH)
    ws = wb[INPUT_SHEET]

    result_rows: List[Tuple[str, str, str, str, str]] = []
    log_rows: List[Tuple[int, str, str, str, str, int, str]] = []

    skip_counts = defaultdict(int)
    team_mismatch = 0
    team_ambiguous = 0
    owner_json_candidate_count = 0
    owner_json_extracted_count = 0
    owner_json_parse_failed_count = 0
    owner_json_parse_errors: List[str] = []

    for excel_row in range(2, ws.max_row + 1):
        org_name = clean_str(ws.cell(excel_row, 2).value)
        upper_org_raw = ws.cell(excel_row, 3).value
        assignee_cell = ws.cell(excel_row, 4).value

        upper_org_norm = norm_upper_org(upper_org_raw)
        new_assignee, assignee_err = parse_assignee(assignee_cell)

        if not org_name:
            skip_counts["org_name_blank"] += 1
            log_rows.append((excel_row, org_name, upper_org_raw or "", assignee_cell or "", "org_name_blank", 0, ""))
            continue

        if assignee_err:
            skip_counts[assignee_err] += 1
            log_rows.append((excel_row, org_name, upper_org_raw or "", assignee_cell or "", assignee_err, 0, ""))
            continue

        org_ids = org_index.get(org_name, [])
        if not org_ids:
            skip_counts["org_not_found"] += 1
            log_rows.append((excel_row, org_name, upper_org_raw or "", assignee_cell or "", "org_not_found", 0, ""))
            continue
        if len(org_ids) > 1:
            skip_counts["org_ambiguous"] += 1
            note = f"org_ids={org_ids}"
            log_rows.append((excel_row, org_name, upper_org_raw or "", assignee_cell or "", "org_ambiguous", 0, note))
            continue

        org_id = org_ids[0]
        people = people_by_org.get(org_id, [])

        matched_people = [
            person
            for person in people
            if norm_upper_org(person["소속 상위 조직"]) == upper_org_norm
        ]

        if not matched_people:
            skip_counts["people_zero_match"] += 1
            log_rows.append(
                (
                    excel_row,
                    org_name,
                    upper_org_raw or "",
                    assignee_cell or "",
                    "people_zero_match",
                    0,
                    f"people_in_org={len(people)}",
                )
            )
            continue

        for person in matched_people:
            existing_owner_raw = person["담당자"]
            owner_name, owner_json_candidate, owner_json_extracted, owner_json_error = normalize_owner_name(
                existing_owner_raw
            )

            if owner_json_candidate:
                owner_json_candidate_count += 1
            if owner_json_extracted:
                owner_json_extracted_count += 1
            if owner_json_error:
                owner_json_parse_failed_count += 1
                if len(owner_json_parse_errors) < 5:
                    owner_json_parse_errors.append(owner_json_error)

            teams = name_to_team.get(owner_name, [])
            team_name = ""
            if not teams:
                team_mismatch += 1
                log_rows.append(
                    (
                        excel_row,
                        org_name,
                        upper_org_raw or "",
                        assignee_cell or "",
                        "team_not_found",
                        len(matched_people),
                        f"owner_raw={existing_owner_raw}; owner_norm={owner_name}; owner_json_parsed={owner_json_extracted}; error={owner_json_error}",
                    )
                )
            elif len(teams) == 1:
                team_name = teams[0]
            else:
                team_ambiguous += 1
                team_name = ",".join(sorted(set(teams)))
                log_rows.append(
                    (
                        excel_row,
                        org_name,
                        upper_org_raw or "",
                        assignee_cell or "",
                        "team_ambiguous",
                        len(matched_people),
                        f"owner_raw={existing_owner_raw}; owner_norm={owner_name}; owner_json_parsed={owner_json_extracted}; error={owner_json_error}",
                    )
                )

            result_rows.append(
                (
                    clean_str(person["RecordId"]),
                    clean_str(person["이름"]),
                    new_assignee or "",
                    owner_name,
                    team_name,
                )
            )

    out_wb = Workbook()
    res_ws = out_wb.active
    res_ws.title = RESULT_SHEET
    res_ws.append(
        [
            "People - RecordID",
            "People - 이름",
            "People - 담당자",
            "People - 담당자(기존)",
            "People - 담당자(기존) 소속 팀",
        ]
    )
    for row in result_rows:
        res_ws.append(row)

    log_ws = out_wb.create_sheet(LOG_SHEET)
    log_ws.append(
        ["excel_row", "org_name", "upper_org", "assignee", "reason", "matched_people_count", "note"]
    )
    for row in log_rows:
        log_ws.append(list(row))

    out_wb.save(OUTPUT_PATH)

    print(f"Output file: {OUTPUT_PATH}")
    print(f"Result row count: {len(result_rows)}")
    print("Skip counts:")
    for key in [
        "org_not_found",
        "org_ambiguous",
        "assignee_multi",
        "people_zero_match",
        "org_name_blank",
    ]:
        print(f"  {key}: {skip_counts.get(key, 0)}")
    print(f"Team mismatches (not found): {team_mismatch}")
    print(f"Team ambiguous (multiple teams): {team_ambiguous}")
    print(f"Log rows: {len(log_rows)}")
    print("Owner JSON stats:")
    print(f"  json_candidate: {owner_json_candidate_count}")
    print(f"  json_name_extracted: {owner_json_extracted_count}")
    print(f"  json_parse_failed: {owner_json_parse_failed_count}")
    if owner_json_parse_errors:
        print("  sample_errors:", "; ".join(owner_json_parse_errors))


if __name__ == "__main__":
    main()
