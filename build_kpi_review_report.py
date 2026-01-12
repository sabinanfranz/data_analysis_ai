#!/usr/bin/env python3
"""
Build a static KPI review report HTML with inline data.

Chunk 1 scope: extract deal rows from SQLite, filter Convert, slice by years,
inline JSON into an HTML template, and emit a single-file report that opens
with a double-click. No KPI calculations or interactive tabs yet.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ONLINE_FORMATS = ["구독제(온라인)", "선택구매(온라인)", "포팅"]
TEMPLATE_PATH = Path("templates") / "kpi_review_report.template.html"
DEFAULT_DB = "salesmap_latest.db"
DEFAULT_EXISTING_ORGS = Path("data") / "existing_orgs_2025_eval.txt"


@dataclass
class DealColumns:
    deal_id: str
    owner: str
    status: str
    created_at: Optional[str]
    contract_date: Optional[str]
    amount: Optional[str]
    course_format: Optional[str]
    net_percent: Optional[str]
    org_id: Optional[str]
    org_name: Optional[str]
    org_table_id: Optional[str]


class FriendlySchemaError(RuntimeError):
    pass


def _parse_years(years_str: str) -> List[int]:
    years: List[int] = []
    for raw in years_str.split(","):
        val = raw.strip()
        if not val:
            continue
        try:
            years.append(int(val))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid year value: {val}") from exc
    if not years:
        raise argparse.ArgumentTypeError("At least one year must be provided.")
    return years


def parse_owner_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    text = str(value).strip()
    if not text:
        return None

    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and parsed:
                candidate = parsed[0]
                if isinstance(candidate, dict):
                    name_val = candidate.get("name") or candidate.get("ownerName") or candidate.get("displayName") or candidate.get("label")
                    if isinstance(name_val, str):
                        name_val = name_val.strip()
                        if name_val:
                            return name_val
            if isinstance(parsed, dict):
                name_val = parsed.get("name") or parsed.get("ownerName") or parsed.get("displayName") or parsed.get("label")
                if isinstance(name_val, str):
                    name_val = name_val.strip()
                    if name_val:
                        return name_val
        except Exception:
            pass

    return text


def _normalize_org_key(name: str) -> str:
    text = name.lower()
    for token in ("주식회사", "(주)", "㈜"):
        text = text.replace(token, "")
    text = re.sub(r"[\s\(\)\-\_,\.]", "", text)
    return text


def _load_existing_orgs(path: Path) -> Tuple[List[str], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Existing orgs file not found: {path}")
    raw_items = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    keys: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        key = _normalize_org_key(item)
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return raw_items, keys


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    if not rows:
        tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        raise FriendlySchemaError(
            f"Table '{table}' not found. Available tables: {', '.join(tables) if tables else '(none)'}"
        )
    return [row["name"] for row in rows]


def _pick_column(columns: Sequence[str], candidates: Sequence[str], *, required: bool, label: str) -> Optional[str]:
    for cand in candidates:
        if cand in columns:
            return cand
    if required:
        raise FriendlySchemaError(
            f"Missing required column for '{label}'. Tried: {', '.join(candidates)}. "
            f"Available columns: {', '.join(columns)}"
        )
    return None


def _detect_columns(conn: sqlite3.Connection) -> DealColumns:
    deal_cols = _table_columns(conn, "deal")
    org_cols: List[str] = []
    try:
        org_cols = _table_columns(conn, "organization")
    except FriendlySchemaError:
        org_cols = []

    def pick_deal(cands: Sequence[str], required: bool, label: str) -> Optional[str]:
        return _pick_column(deal_cols, cands, required=required, label=label)

    def pick_org(cands: Sequence[str], required: bool, label: str) -> Optional[str]:
        return _pick_column(org_cols, cands, required=required, label=label) if org_cols else None

    net_col = pick_deal(
        [
            "netPercent",
            "net",
            "NET",
            "net%",
            "NET%",
            "공헌이익률",
            "공헌이익률(%)",
            "공헌이익률 %",
        ],
        required=False,
        label="netPercent",
    )

    return DealColumns(
        deal_id=pick_deal(["dealId", "deal_id", "id", "dealID"], required=True, label="dealId"),
        owner=pick_deal(["담당자", "owner", "Owner", "담당자명", "담당"], required=True, label="owner"),
        status=pick_deal(["상태", "status", "Status"], required=True, label="status"),
        created_at=pick_deal(["생성 날짜", "createdAt", "created_at", "생성날짜"], required=False, label="createdAt"),
        contract_date=pick_deal(
            ["계약 체결일", "계약체결일", "contractDate", "contract_date", "계약일"], required=False, label="contractDate"
        ),
        amount=pick_deal(["금액", "amount", "Amount"], required=False, label="amount"),
        course_format=pick_deal(["과정포맷", "category1", "course_format", "courseFormat"], required=False, label="courseFormat"),
        net_percent=net_col,
        org_id=pick_deal(["organizationId", "orgId", "organization_id", "조직ID", "회사ID"], required=False, label="organizationId"),
        org_name=pick_org(["이름", "name", "Name", "조직명"], required=False, label="organization.name"),
        org_table_id=pick_org(["id", "organizationId", "orgId"], required=False, label="organization.id"),
    )


def _col_expr(table_alias: str, col: Optional[str]) -> str:
    return f'{table_alias}."{col}"' if col else "NULL"


def _parse_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value)
    match = re.match(r"^(\d{4})", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _row_to_deal(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _load_deals(conn: sqlite3.Connection, cols: DealColumns) -> List[Dict[str, Any]]:
    select_parts = [
        f'{_col_expr("d", cols.deal_id)} AS deal_id',
        f'{_col_expr("d", cols.owner)} AS owner_name',
        f'{_col_expr("d", cols.status)} AS status',
        f'{_col_expr("d", cols.created_at)} AS created_at',
        f'{_col_expr("d", cols.contract_date)} AS contract_date',
        f'{_col_expr("d", cols.amount)} AS amount',
        f'{_col_expr("d", cols.course_format)} AS course_format',
        f'{_col_expr("d", cols.net_percent)} AS net_percent',
    ]

    org_name_expr = None
    join_clause = ""
    if cols.org_id and cols.org_name and cols.org_table_id:
        org_name_expr = f'COALESCE({_col_expr("o", cols.org_name)}, {_col_expr("d", cols.org_id)}, {_col_expr("d", cols.deal_id)})'
        join_clause = f'LEFT JOIN organization o ON {_col_expr("o", cols.org_table_id)} = {_col_expr("d", cols.org_id)}'
    elif cols.org_id:
        org_name_expr = f'COALESCE({_col_expr("d", cols.org_id)}, {_col_expr("d", cols.deal_id)})'
    else:
        org_name_expr = _col_expr("d", cols.deal_id)

    select_parts.append(f"{org_name_expr} AS org_name")

    query = f"SELECT {', '.join(select_parts)} FROM deal d {join_clause}"
    rows = conn.execute(query).fetchall()
    return [_row_to_deal(row) for row in rows]


def _default_out_path(years: List[int]) -> Path:
    today = datetime.now().strftime("%Y%m%d")
    year_part = "vs".join(str(y) for y in sorted(years))
    filename = f"2025성과평가_개인KPI_검수용_{year_part}_{today}.html"
    return Path(filename)


def build_payload(
    db_path: Path,
    existing_orgs_path: Path,
    years: List[int],
) -> Dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    data_generated_at = None
    if db_path.exists():
        data_generated_at = datetime.fromtimestamp(db_path.stat().st_mtime, tz=timezone.utc).isoformat()

    existing_raw, existing_keys = _load_existing_orgs(existing_orgs_path)

    with _connect(db_path) as conn:
        cols = _detect_columns(conn)
        all_deals = _load_deals(conn, cols)

    total_before = len(all_deals)
    deals_after_convert: List[Dict[str, Any]] = []
    for item in all_deals:
        status_val = str(item.get("status") or "").strip()
        if status_val.lower() == "convert":
            continue
        deals_after_convert.append(item)

    deal_count_after_convert = len(deals_after_convert)

    year_parse_fail_created = 0
    year_parse_fail_contract = 0
    filtered_deals: List[Dict[str, Any]] = []
    for item in deals_after_convert:
        lead_year = _parse_year(item.get("created_at"))
        contract_year = _parse_year(item.get("contract_date"))
        if lead_year is None:
            year_parse_fail_created += 1
        if contract_year is None:
            year_parse_fail_contract += 1

        if (lead_year in years) or (contract_year in years):
            filtered_deals.append(item)

    deal_count_after_year_filter = len(filtered_deals)

    # Project to the JSON schema expected by the template
    deals_payload: List[Dict[str, Any]] = []
    owner_set: set[str] = set()
    for item in filtered_deals:
        owner_name = parse_owner_name(item.get("owner_name")) or ""
        if owner_name:
            owner_set.add(owner_name)
        deals_payload.append(
            {
                "dealId": item.get("deal_id"),
                "ownerName": owner_name,
                "orgName": item.get("org_name") or item.get("deal_id"),
                "status": item.get("status"),
                "createdAt": item.get("created_at"),
                "contractDate": item.get("contract_date"),
                "amount": item.get("amount"),
                "courseFormat": item.get("course_format"),
                "netPercent": item.get("net_percent") if cols.net_percent else None,
            }
        )

    return {
        "generatedAt": generated_at,
        "dataGeneratedAt": data_generated_at,
        "years": years,
        "onlineFormats": ONLINE_FORMATS,
        "existingOrgsRaw": existing_raw,
        "existingOrgKeys": existing_keys,
        "deals": deals_payload,
        "meta": {
            "dbPath": str(db_path),
            "dealCountBeforeFilters": total_before,
            "dealCountAfterConvertFilter": deal_count_after_convert,
            "dealCountAfterYearFilter": deal_count_after_year_filter,
            "uniqueOwnerCount": len(owner_set),
            "netPercentColumn": cols.net_percent if cols.net_percent else "__NONE__",
            "yearParseFailuresCreatedAt": year_parse_fail_created,
            "yearParseFailuresContractDate": year_parse_fail_contract,
        },
    }


def _load_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return path.read_text(encoding="utf-8")


def _render_html(template_text: str, data: Dict[str, Any]) -> str:
    data_json = json.dumps(data, ensure_ascii=False)
    # Prevent closing script tags from breaking the inline JSON
    data_json = data_json.replace("</", "<\\/")
    return template_text.replace("__DATA_JSON__", data_json)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Build static KPI review report HTML (Chunk 1).")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite snapshot DB")
    parser.add_argument("--out", default=None, help="Output HTML path")
    parser.add_argument(
        "--existing-orgs",
        default=str(DEFAULT_EXISTING_ORGS),
        help="Path to existing orgs list (one name per line)",
    )
    parser.add_argument("--years", default="2024,2025", help="Comma-separated list of years (e.g. 2024,2025)")

    args = parser.parse_args(argv)
    years = _parse_years(args.years)
    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"DB file not found: {db_path}")

    out_path = Path(args.out) if args.out else _default_out_path(years)
    existing_orgs_path = Path(args.existing_orgs)

    data = build_payload(db_path, existing_orgs_path, years)
    template_text = _load_template(TEMPLATE_PATH)
    rendered = _render_html(template_text, data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"✅ Report generated: {out_path}")


if __name__ == "__main__":
    main()
