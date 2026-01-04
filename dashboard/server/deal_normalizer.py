from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from . import counterparty_llm as cllm

DB_PATH_ENV = os.getenv("DB_PATH", "salesmap_latest.db")
DB_PATH = Path(DB_PATH_ENV)

ONLINE_DEAL_FORMATS = {"구독제(온라인)", "선택구매(온라인)", "포팅"}
COUNTERPARTY_UNKNOWN = "미분류(카운터파티 없음)"
ORG_UNKNOWN = "(미상)"
ORG_TIER_THRESHOLDS = [
    ("S0", 1_000_000_000),
    ("P0", 200_000_000),
    ("P1", 100_000_000),
    ("P2", 50_000_000),
]
BUCKET_CONFIRMED_CONTRACT = "CONFIRMED_CONTRACT"
BUCKET_CONFIRMED_COMMIT = "CONFIRMED_COMMIT"
BUCKET_EXPECTED_HIGH = "EXPECTED_HIGH"
BUCKET_TYPES = {
    BUCKET_CONFIRMED_CONTRACT,
    BUCKET_CONFIRMED_COMMIT,
    BUCKET_EXPECTED_HIGH,
}
MIN_COVERAGE_BY_MONTH: Dict[int, float] = {
    1: 0.05,
    2: 0.10,
    3: 0.15,
    4: 0.20,
    5: 0.25,
    6: 0.30,
    7: 0.40,
    8: 0.50,
    9: 0.60,
    10: 0.75,
    11: 0.90,
    12: 1.00,
}

# 원본 스키마 → 표준 컬럼명 매핑(후속 단계에서 재사용할 수 있도록 상수로 유지)
SCHEMA_MAP: Dict[str, Dict[str, str]] = {
    "deal": {
        "deal_id": "id",
        "deal_name": '"이름"',
        "status": '"상태"',
        "organization_id": "organizationId",
        "people_id": "peopleId",
        "process_format_raw": '"과정포맷"',
        "amount_raw_primary": '"금액"',
        "amount_raw_fallback": '"예상 체결액"',
        "contract_signed_date_raw": '"계약 체결일"',
        "expected_close_date_raw": '"수주 예정일"',
        "course_start_date_raw": '"수강시작일"',
        "course_end_date_raw": '"수강종료일"',
        "course_id_raw": '"코스 ID"',
        "probability_label_raw": '"성사 가능성"',
    },
    "people": {
        "counterparty_name": '"소속 상위 조직"',
    },
    "organization": {
        "organization_name": '"이름"',
    },
}

# sqlite 연결 유틸: DB_PATH 기본, 외부 스냅샷 경로도 허용
def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        raise FileNotFoundError(f"Database not found at {path}")
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 읽기 전용이지만 안전을 위해 FK 활성화
    try:
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return conn

# deal_norm TEMP TABLE 정의 (순서가 insert 시에도 사용됨)
DEAL_NORM_COLUMNS: Sequence[Tuple[str, str]] = (
    ("deal_id", "TEXT"),
    ("deal_name", "TEXT"),
    ("status", "TEXT"),
    ("organization_id", "TEXT"),
    ("organization_name", "TEXT"),
    ("people_id", "TEXT"),
    ("counterparty_name", "TEXT"),
    ("counterparty_key", "TEXT"),
    ("process_format_raw", "TEXT"),
    ("process_format_missing_flag", "INTEGER"),
    ("is_nononline", "INTEGER"),
    ("is_online", "INTEGER"),
    ("amount_raw_primary", "TEXT"),
    ("amount_raw_fallback", "TEXT"),
    ("amount_source", "TEXT"),
    ("amount_value", "INTEGER"),
    ("amount_won", "INTEGER"),
    ("amount_parse_ok", "INTEGER"),
    ("amount_parse_failed", "INTEGER"),
    ("amount_missing_flag", "INTEGER"),
    ("contract_signed_date_raw", "TEXT"),
    ("expected_close_date_raw", "TEXT"),
    ("course_start_date_raw", "TEXT"),
    ("course_end_date_raw", "TEXT"),
    ("course_id_raw", "TEXT"),
    ("contract_signed_date", "TEXT"),
    ("expected_close_date", "TEXT"),
    ("course_start_date", "TEXT"),
    ("course_end_date", "TEXT"),
    ("base_date", "TEXT"),
    ("deal_year", "INTEGER"),
    ("year_missing_flag", "INTEGER"),
    ("counterparty_missing_flag", "INTEGER"),
    ("org_missing_flag", "INTEGER"),
    ("probability_label_raw", "TEXT"),
    ("pipeline_bucket", "TEXT"),
)


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return any(row[1] == column_name for row in rows)


def _normalize_str(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None


def _parse_float(text: str | None) -> float | None:
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _parse_amount_with_units(text: str) -> Tuple[int, bool]:
    """
    단위(억/천만/만) 기반 금액 파싱.
    """
    parsed_any = False
    remaining = text
    total = 0.0

    if "억" in remaining:
        before, after = remaining.split("억", 1)
        num = _parse_float(before)
        if num is not None:
            parsed_any = True
            total += num * 100_000_000
        remaining = after

    if "천만" in remaining:
        before, after = remaining.split("천만", 1)
        num = _parse_float(before)
        if num is not None:
            parsed_any = True
            total += num * 10_000_000
        remaining = after

    if "만" in remaining:
        before, _ = remaining.split("만", 1)
        num = _parse_float(before)
        if num is not None:
            parsed_any = True
            total += num * 10_000

    if not parsed_any:
        return 0, False
    return int(round(total)), True


def _parse_amount(raw: Any) -> Tuple[int, bool]:
    """
    금액/예상체결액 파싱.
    - 숫자형이면 바로 사용(음수는 실패).
    - 문자열은 통화기호/쉼표 제거 후 단위(억/천만/만) → 숫자 순으로 파싱.
    """
    if raw is None or raw is False:
        return 0, False
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if raw < 0:
            return 0, False
        return int(round(raw)), True

    text = str(raw).strip()
    if not text:
        return 0, False

    cleaned = text.replace("₩", "").replace("원", "").replace(",", "").strip()
    if any(unit in cleaned for unit in ("억", "천만", "만")):
        value, ok = _parse_amount_with_units(cleaned)
        if ok:
            return value, True

    try:
        value = float(cleaned)
        if value < 0:
            return 0, False
        return int(round(value)), True
    except ValueError:
        return 0, False


def _parse_date(raw: Any) -> str | None:
    """
    다양한 문자열 패턴을 YYYY-MM-DD로 정규화.
    허용: YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD / ISO datetime.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()

    text = str(raw).strip()
    if not text:
        return None

    # ISO datetime, 공백 이후 시간 제거
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]

    text = text.replace(".", "-").replace("/", "-")

    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if not match:
        # 20260110 형태
        match = re.match(r"^(\d{4})(\d{2})(\d{2})", text)
    if not match:
        return None

    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _bool_to_int(flag: bool) -> int:
    return 1 if flag else 0


def _prob_tokens(val: Any) -> set[str]:
    if val is None:
        return set()
    if isinstance(val, str):
        try:
            import json

            loaded = json.loads(val)
        except Exception:
            loaded = val
    else:
        loaded = val

    if isinstance(loaded, list):
        tokens: set[str] = set()
        for item in loaded:
            tokens.update(_prob_tokens(item))
        return tokens
    if isinstance(loaded, dict):
        tokens: set[str] = set()
        for v in loaded.values():
            tokens.update(_prob_tokens(v))
        return tokens

    text = str(loaded).strip()
    return {text} if text else set()


def _prob_is_confirmed(val: Any) -> bool:
    tokens = _prob_tokens(val)
    return "확정" in tokens


def _prob_is_high_only(val: Any) -> bool:
    tokens = _prob_tokens(val)
    return "높음" in tokens and "확정" not in tokens


def _classify_bucket(
    status: str | None,
    prob_raw: Any,
    required_fields_ok: bool,
    amount_value: int,
) -> str | None:
    if status in ("Convert", "Lost"):
        return None
    if status == "Won" and required_fields_ok and amount_value > 0:
        return BUCKET_CONFIRMED_CONTRACT
    if status == "Won" or _prob_is_confirmed(prob_raw):
        return BUCKET_CONFIRMED_COMMIT
    if _prob_is_high_only(prob_raw):
        return BUCKET_EXPECTED_HIGH
    return None


def build_deal_norm(conn: sqlite3.Connection, table_name: str = "deal_norm") -> Dict[str, Any]:
    """
    deal/people/organization을 조인하고 금액/날짜/비온라인/카운터파티 플래그를 포함한
    TEMP TABLE deal_norm을 생성한다. Convert 상태는 제외되며 dq_metrics를 반환한다.
    """
    conn.row_factory = sqlite3.Row

    has_course_id = _has_column(conn, "deal", "코스 ID")

    dq_metrics: Dict[str, int] = {
        "total_deals_loaded": 0,
        "excluded_convert_count": 0,
        "amount_missing_count": 0,
        "amount_parse_fail_count": 0,
        "year_missing_count": 0,
        "counterparty_unclassified_count": 0,
        "process_format_missing_count": 0,
    }

    select_course_id = 'd."코스 ID" AS course_id_raw,' if has_course_id else "NULL AS course_id_raw,"
    deal_rows = conn.execute(
        f"""
        SELECT
            d.id AS deal_id,
            d."이름" AS deal_name,
            d."상태" AS status,
            d.organizationId AS organization_id,
            d.peopleId AS people_id,
            d."과정포맷" AS process_format_raw,
            d."금액" AS amount_raw_primary,
            d."예상 체결액" AS amount_raw_fallback,
            d."계약 체결일" AS contract_signed_date_raw,
            d."수주 예정일" AS expected_close_date_raw,
            d."수강시작일" AS course_start_date_raw,
            d."수강종료일" AS course_end_date_raw,
            d."성사 가능성" AS probability_label_raw,
            {select_course_id}
            COALESCE(o."이름", o.id) AS organization_name,
            p."소속 상위 조직" AS counterparty_raw
        FROM deal d
        LEFT JOIN organization o ON o.id = d.organizationId
        LEFT JOIN people p ON p.id = d.peopleId
        """
    ).fetchall()

    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    col_defs = ", ".join([f'"{name}" {ctype}' for name, ctype in DEAL_NORM_COLUMNS])
    conn.execute(f'CREATE TEMP TABLE "{table_name}" ({col_defs})')

    insert_sql = f'INSERT INTO "{table_name}" ({", ".join([name for name, _ in DEAL_NORM_COLUMNS])}) VALUES ({", ".join(["?"] * len(DEAL_NORM_COLUMNS))})'
    norm_rows: List[Tuple[Any, ...]] = []

    for row in deal_rows:
        status = row["status"]
        if status == "Convert":
            dq_metrics["excluded_convert_count"] += 1
            continue

        process_format_raw = row["process_format_raw"]
        process_format_missing = _normalize_str(process_format_raw) is None
        dq_metrics["process_format_missing_count"] += 1 if process_format_missing else 0

        is_nononline = process_format_missing or str(process_format_raw).strip() not in ONLINE_DEAL_FORMATS
        is_online = not is_nononline

        amount_raw_primary = row["amount_raw_primary"]
        amount_raw_fallback = row["amount_raw_fallback"]
        primary_has_value = _normalize_str(amount_raw_primary) is not None
        fallback_has_value = _normalize_str(amount_raw_fallback) is not None

        amount_source = "NONE"
        amount_value = 0
        amount_parse_ok = False

        if primary_has_value:
            amount_source = "AMOUNT"
            amount_value, amount_parse_ok = _parse_amount(amount_raw_primary)
        elif fallback_has_value:
            amount_source = "EXPECTED"
            amount_value, amount_parse_ok = _parse_amount(amount_raw_fallback)

        amount_missing_flag = not primary_has_value and not fallback_has_value
        if amount_missing_flag:
            dq_metrics["amount_missing_count"] += 1
        if amount_source != "NONE" and not amount_parse_ok:
            dq_metrics["amount_parse_fail_count"] += 1

        contract_signed_date = _parse_date(row["contract_signed_date_raw"])
        expected_close_date = _parse_date(row["expected_close_date_raw"])
        course_start_date = _parse_date(row["course_start_date_raw"])
        course_end_date = _parse_date(row["course_end_date_raw"])

        base_date = contract_signed_date or expected_close_date
        deal_year = None
        if course_start_date:
            deal_year = int(course_start_date.split("-")[0])
        elif base_date:
            deal_year = int(base_date.split("-")[0])

        year_missing_flag = deal_year is None
        if year_missing_flag:
            dq_metrics["year_missing_count"] += 1

        organization_name = row["organization_name"] or None
        org_missing_flag = row["organization_id"] is None or organization_name is None
        if org_missing_flag:
            organization_name = organization_name or ORG_UNKNOWN

        counterparty_raw = _normalize_str(row["counterparty_raw"])
        counterparty_missing_flag = row["people_id"] is None or counterparty_raw is None
        if counterparty_missing_flag:
            counterparty_name = COUNTERPARTY_UNKNOWN
            dq_metrics["counterparty_unclassified_count"] += 1
        else:
            counterparty_name = counterparty_raw

        counterparty_key = f"{row['organization_id'] or ''}||{counterparty_name}"

        required_fields_ok = (
            bool(contract_signed_date)
            and bool(course_start_date)
            and bool(course_end_date)
            and _normalize_str(row["course_id_raw"]) is not None
            and amount_value > 0
        )
        bucket = _classify_bucket(status, row["probability_label_raw"], required_fields_ok, amount_value)

        norm_rows.append(
            (
                row["deal_id"],
                row["deal_name"],
                status,
                row["organization_id"],
                organization_name,
                row["people_id"],
                counterparty_name,
                counterparty_key,
                process_format_raw,
                _bool_to_int(process_format_missing),
                _bool_to_int(is_nononline),
                _bool_to_int(is_online),
                amount_raw_primary,
                amount_raw_fallback,
                amount_source,
                int(amount_value),
                int(amount_value),
                _bool_to_int(amount_parse_ok),
                _bool_to_int(amount_source != "NONE" and not amount_parse_ok),
                _bool_to_int(amount_missing_flag),
                row["contract_signed_date_raw"],
                row["expected_close_date_raw"],
                row["course_start_date_raw"],
                row["course_end_date_raw"],
                row["course_id_raw"],
                contract_signed_date,
                expected_close_date,
                course_start_date,
                course_end_date,
                base_date,
                deal_year,
                _bool_to_int(year_missing_flag),
                _bool_to_int(counterparty_missing_flag),
                _bool_to_int(org_missing_flag),
                row["probability_label_raw"],
                bucket,
            )
        )
        dq_metrics["total_deals_loaded"] += 1

    if norm_rows:
        conn.executemany(insert_sql, norm_rows)
    return dq_metrics


def build_org_tier(
    conn: sqlite3.Connection,
    deal_norm_table: str = "deal_norm",
    output_table: str = "org_tier_runtime",
    as_of_date: str | None = None,
) -> Dict[str, Any]:
    """
    2025 비온라인 확정액을 org별로 집계하고 티어(S0/P0/P1/P2)로 분류한다.
    결과는 output_table(TEMP)로 저장하고 org_tier_map/summary를 반환한다.
    """
    conn.row_factory = sqlite3.Row
    if as_of_date is None:
        as_of_date = date.today().isoformat()

    base_rows = conn.execute(
        f"""
        SELECT
            dn.organization_id,
            dn.organization_name,
            dn.amount_won,
            dn.amount_missing_flag,
            dn.deal_id,
            dn.pipeline_bucket
        FROM "{deal_norm_table}" dn
        WHERE 1=1
          AND dn.status != 'Convert'
          AND dn.is_nononline = 1
          AND dn.deal_year = 2025
          AND dn.pipeline_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}')
        """
    ).fetchall()

    org_missing_count = sum(1 for r in base_rows if r["organization_id"] is None)
    amount_zero_count = sum(1 for r in base_rows if (r["amount_won"] or 0) <= 0)

    # org_name 보강을 위해 organization join
    conn.execute(f'DROP TABLE IF EXISTS "{output_table}"')
    conn.execute(
        f"""
        CREATE TEMP TABLE "{output_table}" (
            as_of_date TEXT,
            organization_id TEXT,
            organization_name TEXT,
            confirmed_amount_2025_won INTEGER,
            deal_count_used INTEGER,
            deal_count_amount_zero INTEGER,
            tier TEXT,
            tier_reason TEXT
        )
        """
    )

    agg_rows = conn.execute(
        f"""
        WITH base AS (
            SELECT
                dn.organization_id,
                dn.organization_name,
                COALESCE(dn.amount_won, 0) AS amount_won,
                dn.pipeline_bucket
            FROM "{deal_norm_table}" dn
            WHERE 1=1
              AND dn.status != 'Convert'
              AND dn.is_nononline = 1
              AND dn.deal_year = 2025
              AND dn.pipeline_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}')
              AND dn.organization_id IS NOT NULL
        )
        SELECT
            b.organization_id,
            COALESCE(NULLIF(b.organization_name, ''), o."이름", o.id, '') AS organization_name,
            SUM(b.amount_won) AS confirmed_amount_2025_won,
            COUNT(*) AS deal_count_used,
            SUM(CASE WHEN b.amount_won <= 0 THEN 1 ELSE 0 END) AS deal_count_amount_zero
        FROM base b
        LEFT JOIN organization o ON o.id = b.organization_id
        GROUP BY b.organization_id, organization_name
        """
    ).fetchall()

    org_tier_map: Dict[str, str | None] = {}
    summary_counts: Dict[str, int] = {"S0": 0, "P0": 0, "P1": 0, "P2": 0, "NONE": 0}
    summary_amounts: Dict[str, int] = {"S0": 0, "P0": 0, "P1": 0, "P2": 0, "NONE": 0}
    rows_to_insert: List[Tuple[Any, ...]] = []

    for row in agg_rows:
        org_id = row["organization_id"]
        org_name = row["organization_name"] or ""
        amount = int(row["confirmed_amount_2025_won"] or 0)
        reason = ""
        tier: str | None = None

        if org_name and "삼성전자" in org_name:
            tier = None
            reason = "삼성전자 제외"
        else:
            for label, threshold in ORG_TIER_THRESHOLDS:
                if amount >= threshold:
                    tier = label
                    reason = f">={threshold}"
                    break

        org_tier_map[org_id] = tier
        tier_key = tier or "NONE"
        summary_counts[tier_key] = summary_counts.get(tier_key, 0) + 1
        summary_amounts[tier_key] = summary_amounts.get(tier_key, 0) + amount

        rows_to_insert.append(
            (
                as_of_date,
                org_id,
                org_name,
                amount,
                row["deal_count_used"],
                row["deal_count_amount_zero"],
                tier,
                reason,
            )
        )

    if rows_to_insert:
        placeholders = ", ".join(["?"] * 8)
        conn.executemany(
            f'INSERT INTO "{output_table}" VALUES ({placeholders})',
            rows_to_insert,
        )

    return {
        "as_of_date": as_of_date,
        "org_tier_map": org_tier_map,
        "summary": {
            "counts_by_tier": summary_counts,
            "amounts_by_tier": summary_amounts,
            "org_missing_count": org_missing_count,
            "amount_zero_or_missing_count": amount_zero_count,
            "base_deal_rows": len(base_rows),
        },
        "table": output_table,
    }


def build_counterparty_target_2026(
    conn: sqlite3.Connection,
    deal_norm_table: str = "deal_norm",
    org_tier_table: str = "org_tier_runtime",
    output_table: str = "counterparty_target_2026",
) -> Dict[str, Any]:
    """
    카운터파티별 2025 확정 비온라인 금액(baseline_2025)을 집계하고
    고객사 티어 multiplier로 target_2026을 계산한다.
    - universe: 2025/2026 비온라인 딜에 등장한 모든 (org, counterparty) for tiered orgs
    - baseline: 2025, pipeline_bucket in CONFIRMED_* only, amount_value sum
    """
    conn.row_factory = sqlite3.Row

    conn.execute('DROP TABLE IF EXISTS "tmp_counterparty_universe"')
    conn.execute('DROP TABLE IF EXISTS "tmp_baseline_2025"')
    conn.execute(f'DROP TABLE IF EXISTS "{output_table}"')

    # Universe: 비온라인 & 2025/2026 등장 카운터파티, 티어가 존재하는 org만
    conn.execute(
        f"""
        CREATE TEMP TABLE tmp_counterparty_universe AS
        SELECT DISTINCT
            d.organization_id,
            COALESCE(NULLIF(TRIM(d.counterparty_name), ''), '{COUNTERPARTY_UNKNOWN}') AS counterparty_name
        FROM "{deal_norm_table}" d
        JOIN "{org_tier_table}" t ON t.organization_id = d.organization_id
        WHERE d.is_nononline = 1
          AND d.deal_year IN (2025, 2026)
          AND t.tier IS NOT NULL
        """
    )

    # Baseline 2025 확정액(비온라인, CONFIRMED only, Convert 제외)
    conn.execute(
        f"""
        CREATE TEMP TABLE tmp_baseline_2025 AS
        SELECT
            d.organization_id,
            COALESCE(NULLIF(TRIM(d.counterparty_name), ''), '{COUNTERPARTY_UNKNOWN}') AS counterparty_name,
            SUM(d.amount_value) AS baseline_2025,
            COUNT(*) AS baseline_2025_deal_count,
            SUM(CASE WHEN d.amount_parse_failed = 1 THEN 1 ELSE 0 END) AS baseline_2025_amount_issue_count
        FROM "{deal_norm_table}" d
        WHERE d.is_nononline = 1
          AND d.deal_year = 2025
          AND d.pipeline_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}')
          AND (d.status IS NULL OR d.status != 'Convert')
        GROUP BY d.organization_id, COALESCE(NULLIF(TRIM(d.counterparty_name), ''), '{COUNTERPARTY_UNKNOWN}')
        """
    )

    conn.execute(
        f"""
        CREATE TEMP TABLE "{output_table}" (
            organization_id TEXT,
            counterparty_name TEXT,
            baseline_2025 INTEGER,
            tier TEXT,
            multiplier REAL,
            target_2026 REAL,
            baseline_2025_deal_count INTEGER,
            baseline_2025_amount_issue_count INTEGER,
            is_unclassified_counterparty INTEGER
        )
        """
    )

    conn.execute(
        f"""
        INSERT INTO "{output_table}"
        SELECT
            u.organization_id,
            u.counterparty_name,
            COALESCE(b.baseline_2025, 0) AS baseline_2025,
            t.tier,
            CASE t.tier
                WHEN 'S0' THEN 1.5
                WHEN 'P0' THEN 1.7
                WHEN 'P1' THEN 1.7
                WHEN 'P2' THEN 1.5
                ELSE NULL
            END AS multiplier,
            CASE
                WHEN COALESCE(b.baseline_2025, 0) = 0 THEN 0
                WHEN t.tier = 'S0' THEN COALESCE(b.baseline_2025, 0) * 1.5
                WHEN t.tier = 'P0' THEN COALESCE(b.baseline_2025, 0) * 1.7
                WHEN t.tier = 'P1' THEN COALESCE(b.baseline_2025, 0) * 1.7
                WHEN t.tier = 'P2' THEN COALESCE(b.baseline_2025, 0) * 1.5
                ELSE 0
            END AS target_2026,
            COALESCE(b.baseline_2025_deal_count, 0) AS baseline_2025_deal_count,
            COALESCE(b.baseline_2025_amount_issue_count, 0) AS baseline_2025_amount_issue_count,
            CASE WHEN u.counterparty_name = '{COUNTERPARTY_UNKNOWN}' THEN 1 ELSE 0 END AS is_unclassified_counterparty
        FROM tmp_counterparty_universe u
        JOIN "{org_tier_table}" t ON t.organization_id = u.organization_id
        LEFT JOIN tmp_baseline_2025 b
          ON u.organization_id = b.organization_id
         AND u.counterparty_name = b.counterparty_name
        """
    )

    null_tier_rows = conn.execute(
        f'SELECT COUNT(*) AS cnt FROM "{output_table}" WHERE tier IS NULL'
    ).fetchone()["cnt"]
    if null_tier_rows > 0:
        raise ValueError(f"[counterparty_target_2026] Found {null_tier_rows} rows with NULL tier")

    # 정합성 체크: org별 baseline 합 vs org_tier 확정액 비교
    org_baseline = {
        row["organization_id"]: row["sum_baseline"]
        for row in conn.execute(
            f"""
            SELECT organization_id, SUM(baseline_2025) AS sum_baseline
            FROM "{output_table}"
            GROUP BY organization_id
            """
        ).fetchall()
    }
    org_tier_amounts = {
        row["organization_id"]: row["confirmed_amount_2025_won"]
        for row in conn.execute(
            f"""
            SELECT organization_id, confirmed_amount_2025_won
            FROM "{org_tier_table}"
            """
        ).fetchall()
    }
    org_diff = {
        org: org_baseline.get(org, 0) - (org_tier_amounts.get(org) or 0)
        for org in org_baseline.keys()
    }
    mismatched_orgs = {org: diff for org, diff in org_diff.items() if diff != 0}

    unclassified_summary = conn.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            SUM(baseline_2025) AS baseline_sum
        FROM "{output_table}"
        WHERE is_unclassified_counterparty = 1
        """
    ).fetchone()

    return {
        "table": output_table,
        "null_tier_rows": null_tier_rows,
        "org_baseline_vs_tier_diff": mismatched_orgs,
        "unclassified": {
            "rows": unclassified_summary["rows"],
            "baseline_sum": unclassified_summary["baseline_sum"] or 0,
        },
    }


def _parse_as_of_date(as_of_date: str | None) -> date:
    if as_of_date is None:
        return date.today()
    if isinstance(as_of_date, date):
        return as_of_date
    return datetime.fromisoformat(as_of_date).date()


def build_counterparty_risk_rule(
    conn: sqlite3.Connection,
    as_of_date: str | None = None,
    deal_norm_table: str = "deal_norm",
    org_tier_table: str = "org_tier_runtime",
    counterparty_target_table: str = "counterparty_target_2026",
    output_table: str = "tmp_counterparty_risk_rule",
) -> Dict[str, Any]:
    """
    D4: 2026 확정/예상 집계 → gap/coverage → 규칙 리스크 레벨 계산.
    - 대상: tier(S0~P2) 조직의 카운터파티 (target 기반 + 2026 deal 기반 union)
    - coverage: 2026 비온라인, status!='Convert', pipeline bucket confirmed/expected
    - risk: 월별 min_cov 기준 + pipeline_zero 우선 + target=0 예외
    """
    as_of = _parse_as_of_date(as_of_date)
    current_month = as_of.month
    min_cov = MIN_COVERAGE_BY_MONTH.get(current_month, 1.0)
    severe_threshold = 0.5 * min_cov

    conn.row_factory = sqlite3.Row
    conn.execute(f'DROP TABLE IF EXISTS "{output_table}"')
    conn.execute('DROP TABLE IF EXISTS "tiered_orgs"')
    conn.execute('DROP TABLE IF EXISTS "deals_2026"')
    conn.execute('DROP TABLE IF EXISTS "agg_2026"')
    conn.execute('DROP TABLE IF EXISTS "u_target"')
    conn.execute('DROP TABLE IF EXISTS "u_2026"')
    conn.execute('DROP TABLE IF EXISTS "universe_counterparty"')
    conn.execute('DROP TABLE IF EXISTS "year_unknown_dq"')

    conn.execute(
        f"""
        CREATE TEMP TABLE tiered_orgs AS
        SELECT organization_id, tier
        FROM "{org_tier_table}"
        WHERE tier IN ('S0','P0','P1','P2')
        """
    )

    # 2026 deals with bucket normalization and exclusions
    conn.execute(
        f"""
        CREATE TEMP TABLE deals_2026 AS
        SELECT
            d.organization_id,
            d.counterparty_name,
            d.amount_value AS amount_num,
            d.status,
            d.probability_label_raw AS success_prob,
            d.pipeline_bucket,
            d.amount_parse_failed,
            d.year_missing_flag,
            CASE WHEN d.counterparty_name = '{COUNTERPARTY_UNKNOWN}' THEN 1 ELSE 0 END AS excluded_by_quality,
            CASE
              WHEN d.status IN ('Lost','Convert') THEN 'IGNORE'
              WHEN d.pipeline_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}') AND d.status NOT IN ('Lost','Convert') THEN d.pipeline_bucket
              WHEN d.pipeline_bucket = '{BUCKET_EXPECTED_HIGH}' AND d.status NOT IN ('Lost','Convert') THEN d.pipeline_bucket
              ELSE 'IGNORE'
            END AS agg_bucket
        FROM "{deal_norm_table}" d
        JOIN tiered_orgs t ON t.organization_id = d.organization_id
        WHERE d.is_nononline = 1
          AND d.deal_year = 2026
          AND d.status NOT IN ('Convert','Lost')
        """
    )

    conn.execute(
        f"""
        CREATE TEMP TABLE agg_2026 AS
        SELECT
            organization_id,
            counterparty_name,
            SUM(CASE WHEN agg_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}') THEN amount_num ELSE 0 END) AS confirmed_2026,
            SUM(CASE WHEN agg_bucket = '{BUCKET_EXPECTED_HIGH}' THEN amount_num ELSE 0 END) AS expected_2026,
            SUM(CASE WHEN agg_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}') THEN 1 ELSE 0 END) AS cnt_confirmed_deals_2026,
            SUM(CASE WHEN agg_bucket = '{BUCKET_EXPECTED_HIGH}' THEN 1 ELSE 0 END) AS cnt_expected_deals_2026,
            SUM(CASE WHEN amount_num <= 0 AND agg_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}','{BUCKET_EXPECTED_HIGH}') THEN 1 ELSE 0 END) AS cnt_amount_zero_deals_2026,
            SUM(CASE WHEN amount_parse_failed = 1 AND agg_bucket IN ('{BUCKET_CONFIRMED_CONTRACT}','{BUCKET_CONFIRMED_COMMIT}','{BUCKET_EXPECTED_HIGH}') THEN 1 ELSE 0 END) AS dq_amount_parse_fail_cnt_2026
        FROM deals_2026
        GROUP BY organization_id, counterparty_name
        """
    )

    # year unknown dq (all years, nononline, tiered orgs)
    conn.execute(
        f"""
        CREATE TEMP TABLE year_unknown_dq AS
        SELECT
            d.organization_id,
            d.counterparty_name,
            COUNT(*) AS dq_year_unknown_cnt
        FROM "{deal_norm_table}" d
        JOIN tiered_orgs t ON t.organization_id = d.organization_id
        WHERE d.is_nononline = 1
          AND d.deal_year IS NULL
        GROUP BY d.organization_id, d.counterparty_name
        """
    )

    conn.execute(
        f"""
        CREATE TEMP TABLE u_target AS
        SELECT ct.organization_id, ct.counterparty_name
        FROM "{counterparty_target_table}" ct
        JOIN tiered_orgs t ON t.organization_id = ct.organization_id
        """
    )
    conn.execute(
        """
        CREATE TEMP TABLE u_2026 AS
        SELECT organization_id, counterparty_name
        FROM deals_2026
        """
    )
    conn.execute(
        """
        CREATE TEMP TABLE universe_counterparty AS
        SELECT organization_id, counterparty_name FROM u_target
        UNION
        SELECT organization_id, counterparty_name FROM u_2026
        """
    )

    # Prepare output table
    conn.execute(
        f"""
        CREATE TEMP TABLE "{output_table}" (
            as_of_date TEXT,
            organization_id TEXT,
            organization_name TEXT,
            tier TEXT,
            counterparty_name TEXT,
            baseline_2025_confirmed INTEGER,
            target_2026 REAL,
            confirmed_2026 REAL,
            expected_2026 REAL,
            coverage_2026 REAL,
            gap REAL,
            coverage_ratio REAL,
            pipeline_zero INTEGER,
            risk_level_rule TEXT,
            min_cov_current_month REAL,
            severe_threshold REAL,
            rule_trigger TEXT,
            excluded_by_quality INTEGER,
            cnt_confirmed_deals_2026 INTEGER,
            cnt_expected_deals_2026 INTEGER,
            cnt_amount_zero_deals_2026 INTEGER,
            dq_amount_parse_fail_cnt_2026 INTEGER,
            dq_year_unknown_cnt INTEGER,
            updated_at TEXT
        )
        """
    )

    rows = conn.execute(
        f"""
        SELECT
            u.organization_id,
            t.tier,
            u.counterparty_name,
            COALESCE(o."이름", o.id, '') AS organization_name,
            COALESCE(ct.baseline_2025, 0) AS baseline_2025_confirmed,
            COALESCE(ct.target_2026, 0) AS target_2026,
            COALESCE(a.confirmed_2026, 0) AS confirmed_2026,
            COALESCE(a.expected_2026, 0) AS expected_2026,
            COALESCE(a.cnt_confirmed_deals_2026, 0) AS cnt_confirmed_deals_2026,
            COALESCE(a.cnt_expected_deals_2026, 0) AS cnt_expected_deals_2026,
            COALESCE(a.cnt_amount_zero_deals_2026, 0) AS cnt_amount_zero_deals_2026,
            COALESCE(a.dq_amount_parse_fail_cnt_2026, 0) AS dq_amount_parse_fail_cnt_2026,
            COALESCE(dq.dq_year_unknown_cnt, 0) AS dq_year_unknown_cnt,
            CASE WHEN u.counterparty_name = '{COUNTERPARTY_UNKNOWN}' THEN 1 ELSE 0 END AS excluded_by_quality
        FROM universe_counterparty u
        JOIN tiered_orgs t ON t.organization_id = u.organization_id
        LEFT JOIN {counterparty_target_table} ct
          ON ct.organization_id = u.organization_id
         AND ct.counterparty_name = u.counterparty_name
        LEFT JOIN agg_2026 a
          ON a.organization_id = u.organization_id
         AND a.counterparty_name = u.counterparty_name
        LEFT JOIN year_unknown_dq dq
          ON dq.organization_id = u.organization_id
         AND dq.counterparty_name = u.counterparty_name
        LEFT JOIN organization o ON o.id = u.organization_id
        """
    ).fetchall()

    insert_rows: List[Tuple[Any, ...]] = []
    for row in rows:
        coverage_2026 = (row["confirmed_2026"] or 0) + (row["expected_2026"] or 0)
        target_2026 = row["target_2026"] or 0
        gap = target_2026 - coverage_2026
        pipeline_zero = int(coverage_2026 == 0 and target_2026 > 0)

        if target_2026 == 0:
            coverage_ratio = None
            risk_level = "양호"
            rule_trigger = "TARGET_ZERO"
        else:
            coverage_ratio = coverage_2026 / target_2026 if target_2026 else None
            if pipeline_zero:
                risk_level = "심각"
                rule_trigger = "PIPELINE_ZERO"
            elif coverage_ratio is not None and coverage_ratio < severe_threshold:
                risk_level = "심각"
                rule_trigger = "COVERAGE_BELOW_HALF_MIN"
            elif coverage_ratio is not None and coverage_ratio < min_cov:
                risk_level = "보통"
                rule_trigger = "COVERAGE_BELOW_MIN"
            elif gap <= 0:
                risk_level = "양호"
                rule_trigger = "GAP_COVERED"
            else:
                risk_level = "양호"
                rule_trigger = "ON_TRACK"

        insert_rows.append(
            (
                as_of.isoformat(),
                row["organization_id"],
                row["organization_name"],
                row["tier"],
                row["counterparty_name"],
                row["baseline_2025_confirmed"],
                target_2026,
                row["confirmed_2026"] or 0,
                row["expected_2026"] or 0,
                coverage_2026,
                gap,
                coverage_ratio,
                pipeline_zero,
                risk_level,
                min_cov,
                severe_threshold,
                rule_trigger,
                row["excluded_by_quality"],
                row["cnt_confirmed_deals_2026"],
                row["cnt_expected_deals_2026"],
                row["cnt_amount_zero_deals_2026"],
                row["dq_amount_parse_fail_cnt_2026"],
                row["dq_year_unknown_cnt"],
                datetime.now().isoformat(),
            )
        )

    if insert_rows:
        placeholders = ", ".join(["?"] * len(insert_rows[0]))
        conn.executemany(
            f'INSERT INTO "{output_table}" VALUES ({placeholders})',
            insert_rows,
        )

    null_tier_rows = conn.execute(
        f'SELECT COUNT(*) AS cnt FROM "{output_table}" WHERE tier IS NULL'
    ).fetchone()["cnt"]
    if null_tier_rows > 0:
        raise ValueError(f"[counterparty_risk_rule] Found {null_tier_rows} rows with NULL tier")

    return {
        "table": output_table,
        "row_count": len(insert_rows),
        "null_tier_rows": null_tier_rows,
    }


def _tier_rank(tier: str | None) -> int:
    rank = {"S0": 0, "P0": 1, "P1": 2, "P2": 3}
    return rank.get(tier or "", 99)


def build_counterparty_risk_report(
    as_of_date: str | None = None,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    """
    Orchestrates D1~D4 and returns a JSON-ready counterparty risk report.
    - Builds deal_norm -> org_tier -> counterparty_target_2026 -> tmp_counterparty_risk_rule
    - Computes summary/counts and sorts counterparties by severity/pipeline_zero/tier/gap.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    as_of = _parse_as_of_date(as_of_date)
    generated_at = datetime.now().isoformat()
    db_mtime = datetime.fromtimestamp(db_path.stat().st_mtime).isoformat()
    db_hash = hashlib.sha256(db_mtime.encode("utf-8")).hexdigest()[:16]

    with _connect(db_path) as conn:
        dq_metrics = build_deal_norm(conn)
        org_tier = build_org_tier(conn, as_of_date=as_of.isoformat())
        build_counterparty_target_2026(conn)
        risk_info = build_counterparty_risk_rule(conn, as_of_date=as_of.isoformat())

        rows = conn.execute(
            f"""
            SELECT *
            FROM "{risk_info['table']}"
            """
        ).fetchall()
        # 카운터파티별 2026 상위 딜(금액 desc) 확보: deal_norm이 존재하는 동일 커넥션에서 계산
        top_deals_map: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for r in rows:
            key = (r["organization_id"], r["counterparty_name"])
            deals = conn.execute(
                """
                SELECT
                    deal_id,
                    deal_name,
                    status,
                    probability_label_raw AS possibility,
                    amount_value AS amount,
                    is_nononline,
                    deal_year,
                    course_id_raw,
                    contract_signed_date,
                    expected_close_date,
                    course_start_date,
                    course_end_date
                FROM deal_norm
                WHERE organization_id = ?
                  AND counterparty_name = ?
                  AND deal_year = 2026
                  AND is_nononline = 1
                  AND status NOT IN ('Convert','Lost')
                ORDER BY CAST(amount_value AS INTEGER) DESC, deal_id ASC
                LIMIT ?
                """,
                (r["organization_id"], r["counterparty_name"], cllm.TOP_DEALS_LIMIT),
            ).fetchall()
            top_deals_map[key] = [
                {
                    "deal_id": d["deal_id"],
                    "deal_name": d["deal_name"],
                    "status": d["status"],
                    "possibility": d["possibility"],
                    "amount": d["amount"],
                    "is_nononline": bool(d["is_nononline"]),
                    "deal_year": d["deal_year"],
                    "course_id_exists": bool(d["course_id_raw"]),
                    "start_date": d["course_start_date"],
                    "end_date": d["course_end_date"],
                    "contract_date": d["contract_signed_date"],
                    "expected_close_date": d["expected_close_date"],
                    "last_contact_date": None,
                }
                for d in deals
            ]
        rows_data = []
        for r in rows:
            data = dict(r)
            data["top_deals_2026"] = top_deals_map.get(
                (r["organization_id"], r["counterparty_name"]), []
            )
            rows_data.append(data)

    severity_order = {"심각": 0, "보통": 1, "양호": 2}

    def sort_key(row: Dict[str, Any]) -> Tuple[int, int, int, float, float]:
        gap_abs = abs(row.get("gap") or 0)
        return (
            severity_order.get(row["risk_level_rule"], 3),
            -int(row["pipeline_zero"]),
            _tier_rank(row["tier"]),
            -gap_abs,
            -(row["target_2026"] or 0),
        )

    # 메모 조회를 위해 별도 커넥션을 사용하되, 딜 리스트는 rows_data에 포함된 값을 재사용
    with _connect(db_path) as conn_for_llm:
        llm_cards = cllm.generate_llm_cards(conn_for_llm, rows_data, as_of, db_hash)

    counterparties: List[Dict[str, Any]] = []
    counts = {"severe": 0, "normal": 0, "good": 0, "pipeline_zero": 0}
    tier_group_summary = {
        "S0_P0_P1": {"target": 0, "coverage": 0, "gap": 0},
        "P2": {"target": 0, "coverage": 0, "gap": 0},
    }
    dq_quality = {
        "unknown_year_deals": 0,
        "unknown_amount_deals": dq_metrics.get("amount_missing_count", 0) + dq_metrics.get("amount_parse_fail_count", 0),
        "uncategorized_counterparties": 0,
    }

    for row in sorted(rows_data, key=sort_key):
        severity = row["risk_level_rule"]
        if severity == "심각":
            counts["severe"] += 1
        elif severity == "보통":
            counts["normal"] += 1
        elif severity == "양호":
            counts["good"] += 1
        if row["pipeline_zero"]:
            counts["pipeline_zero"] += 1
        if row["dq_year_unknown_cnt"]:
            dq_quality["unknown_year_deals"] += row["dq_year_unknown_cnt"]
        if row["excluded_by_quality"]:
            dq_quality["uncategorized_counterparties"] += 1

        tier_key = "S0_P0_P1" if row["tier"] in {"S0", "P0", "P1"} else ("P2" if row["tier"] == "P2" else None)
        if tier_key:
            tgt = row["target_2026"] or 0
            cov = row["coverage_2026"] or 0
            tier_group_summary[tier_key]["target"] += tgt
            tier_group_summary[tier_key]["coverage"] += cov
            tier_group_summary[tier_key]["gap"] += tgt - cov

        coverage_ratio = row["coverage_ratio"] if row["coverage_ratio"] is not None else None

        llm_res = llm_cards.get((row["organization_id"], row["counterparty_name"]))
        if llm_res is None:
            blockers = cllm.fallback_blockers(bool(row["pipeline_zero"]), "")
            evidence = cllm.fallback_evidence(row, blockers)
            actions = cllm.fallback_actions(blockers)
            risk_level_llm = row["risk_level_rule"]
        else:
            blockers = llm_res.get("top_blockers", [])
            evidence = llm_res.get("evidence_bullets", [])
            actions = llm_res.get("recommended_actions", [])
            risk_level_llm = llm_res.get("risk_level_llm") or llm_res.get("risk_level") or row["risk_level_rule"]

        counterparties.append(
            {
                "organizationId": row["organization_id"],
                "organizationName": row["organization_name"],
                "counterpartyName": row["counterparty_name"],
                "tier": row["tier"],
                "baseline_2025": row["baseline_2025_confirmed"],
                "target_2026": row["target_2026"],
                "confirmed_2026": row["confirmed_2026"],
                "expected_2026": row["expected_2026"],
                "coverage_2026": row["coverage_2026"],
                "gap": row["gap"],
                "coverage_ratio": coverage_ratio,
                "pipeline_zero": bool(row["pipeline_zero"]),
                "risk_level_rule": row["risk_level_rule"],
                "risk_level_llm": risk_level_llm,
                "top_blockers": blockers,
                "evidence_bullets": evidence,
                "recommended_actions": actions,
                "rule_trigger": row["rule_trigger"],
                "min_cov_current_month": row["min_cov_current_month"],
                "severe_threshold": row["severe_threshold"],
                "excluded_by_quality": bool(row["excluded_by_quality"]),
                "counts": {
                    "cnt_confirmed_deals_2026": row["cnt_confirmed_deals_2026"],
                    "cnt_expected_deals_2026": row["cnt_expected_deals_2026"],
                    "cnt_amount_zero_deals_2026": row["cnt_amount_zero_deals_2026"],
                    "dq_amount_parse_fail_cnt_2026": row["dq_amount_parse_fail_cnt_2026"],
                    "dq_year_unknown_cnt": row["dq_year_unknown_cnt"],
                },
                "deals_top": row.get("top_deals_2026", [])[: cllm.PAYLOAD_DEALS_LIMIT],
            }
        )

    def summarize_group(data: Dict[str, int | float]) -> Dict[str, Any]:
        target = data["target"]
        coverage = data["coverage"]
        gap = data["gap"]
        ratio = None
        if target and target > 0:
            ratio = coverage / target
        return {
            "target": target,
            "coverage": coverage,
            "gap": gap,
            "coverage_ratio": ratio,
        }

    summary = {
        "tier_groups": {
            "S0_P0_P1": summarize_group(tier_group_summary["S0_P0_P1"]),
            "P2": summarize_group(tier_group_summary["P2"]),
        },
        "counts": counts,
    }

    report = {
        "meta": {
            "as_of": as_of.isoformat(),
            "db_version": db_mtime,
            "generated_at": generated_at,
        },
        "summary": summary,
        "data_quality": dq_quality,
        "counterparties": counterparties,
    }

    return report
