import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import statepath_engine as sp

DB_PATH = Path(__file__).resolve().parent.parent.parent / "salesmap_latest.db"
_OWNER_LOOKUP_CACHE: Dict[Path, Dict[str, str]] = {}
YEARS_FOR_WON = {"2023", "2024", "2025"}
ONLINE_COURSE_FORMATS = {"구독제(온라인)", "선택구매(온라인)", "포팅"}
SIZE_GROUPS = ["대기업", "중견기업", "중소기업", "공공기관", "대학교", "기타/미입력"]
PUBLIC_KEYWORDS = ["공단", "공사", "진흥원", "재단", "협회", "청", "시청", "도청", "구청", "교육청", "원"]
_COUNTERPARTY_DRI_CACHE: Dict[Tuple[Path, float, str, int], Dict[str, Any]] = {}
_RANK_2025_SUMMARY_CACHE: Dict[Tuple[Path, float, str, Tuple[int, ...]], Dict[str, Any]] = {}


def _date_only(val: Any) -> str:
    """
    Normalize a datetime-ish value to YYYY-MM-DD. Returns "" when empty/None.
    """
    if val is None:
        return ""
    text = str(val)
    if "T" in text:
        text = text.split("T")[0]
    if " " in text:
        text = text.split(" ")[0]
    return text


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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


EDU1_TEAM_MEMBERS = {
    normalize_owner_name(name)
    for name in [
        "김솔이",
        "황초롱",
        "김정은",
        "김동찬",
        "정태윤",
        "서정연",
        "오진선",
        "강지선",
        "정하영",
        "박범규",
        "하승민",
        "이은서",
        "김세연",
    ]
}


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
        '  FROM deal WHERE "상태" = \'Won\' AND "계약 체결일" LIKE \'2025%\' AND organizationId IS NOT NULL '
        "  GROUP BY organizationId"
        ") w ON w.organizationId = o.id "
        "WHERE 1=1 "
    )
    params: List[Any] = []

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
        rows = _fetch_all(
            conn,
            "SELECT id, text, ownerId, createdAt, updatedAt "
            "FROM memo "
            "WHERE organizationId = ? AND peopleId IS NULL AND dealId IS NULL "
            "ORDER BY createdAt DESC "
            "LIMIT ?",
            (org_id, limit),
        )
    result: List[Dict[str, Any]] = []
    for row in rows:
        owner_id = row["ownerId"]
        result.append(
            {
                **dict(row),
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


def _parse_year_from_text(val: Any) -> str | None:
    if val is None:
        return None
    text = str(val)
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return None


def _year_from_dates(contract_date: Any, expected_date: Any) -> str | None:
    year = _parse_year_from_text(contract_date)
    if year:
        return year
    return _parse_year_from_text(expected_date)


def _amount_fallback(amount: Any, expected: Any) -> float:
    num = _to_number(amount)
    if num is not None and num > 0:
        return num
    num_exp = _to_number(expected)
    if num_exp is not None and num_exp > 0:
        return num_exp
    return 0.0


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
        rows = _fetch_all(
            conn,
            "SELECT id, text, ownerId, createdAt, updatedAt "
            "FROM memo "
            "WHERE peopleId = ? AND (dealId IS NULL OR TRIM(dealId) = '') "
            "ORDER BY createdAt DESC "
            "LIMIT ?",
            (person_id, limit),
        )
    result: List[Dict[str, Any]] = []
    for row in rows:
        owner_id = row["ownerId"]
        result.append(
            {
                **dict(row),
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
        rows = _fetch_all(
            conn,
            "SELECT id, text, ownerId, createdAt, updatedAt "
            "FROM memo "
            "WHERE dealId = ? "
            "ORDER BY createdAt DESC "
            "LIMIT ?",
            (deal_id, limit),
        )
    result: List[Dict[str, Any]] = []
    for row in rows:
        owner_id = row["ownerId"]
        result.append(
            {
                **dict(row),
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

    conditions = ['d."계약 체결일" LIKE ?']
    params: List[Any] = ["2025%"]
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

        conditions_2024 = ['d."상태" = ?', 'd."계약 체결일" LIKE ?']
        params_2024: List[Any] = ["Won", "2024%"]
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
    conditions = ['d."상태" = ?']
    params: List[Any] = ["Won"]
    if size and size != "전체":
        conditions.append('o."기업 규모" = ?')
        params.append(size)
    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  COALESCE(o."업종 구분(대)", "미입력") AS industry_major, '
            '  COALESCE(o.id, d.organizationId) AS org_id, '
            '  SUBSTR(d."계약 체결일", 1, 4) AS year, '
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
            }
        )
        # offline sources
        if amt > 0 and _is_offline(fmt):
            if _is_high(d["probability"], d["status"]) and year == "2025" and start_year != "2026":
                offline25_deals.append(entry["deals"][-1])
            if (
                _is_high(d["probability"], d["status"])
                and year == "2026"
            ) or (
                _is_high(d["probability"], d["status"])
                and year == "2025"
                and start_year == "2026"
            ):
                offline26_deals.append(entry["deals"][-1])

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
    }


def get_rank_2025_deals_people(size: str = "대기업", db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    For organizations (by size) that have Won deals in 2025, return people with all their deals (any status).
    Grouped by person to support People-centric rendering.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    # 단계 A: 2025 Won 보유 조직 집합
    org_conditions = ['d."상태" = ?', 'd."계약 체결일" LIKE ?']
    org_params: List[Any] = ["Won", "2025%"]
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
        memo_rows = _fetch_all(
            conn,
            "SELECT id, dealId, peopleId, organizationId, text, createdAt "
            "FROM memo WHERE organizationId = ?",
            (org_id,),
        )

    # Build memo lookup maps outside connection
    person_memos: Dict[str, List[Dict[str, Any]]] = {}
    deal_memos: Dict[str, List[Dict[str, Any]]] = {}
    org_memos: List[Dict[str, Any]] = []
    for memo in memo_rows:
        date_only = _date_only(memo["createdAt"])
        cleaned = _clean_form_memo(memo["text"])
        if cleaned == "":
            # Skip low-value form memos
            continue
        if cleaned is None:
            entry = {"date": date_only, "text": memo["text"]}
        else:
            # Replace text with structured cleanText
            entry = {"date": date_only, "cleanText": cleaned}
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


def get_edu1_deal_check_sql_deals(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    retention_org_ids: Set[str] = set()
    org_won_2025_total: Dict[str, float] = {}

    with _connect(db_path) as conn:
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
            "WHERE d.\"상태\" = 'SQL'",
        )

    items: List[Dict[str, Any]] = []
    for row in rows:
        owner_names = _parse_owner_names(row["owner_json"])
        if not owner_names:
            continue
        normalized_owners = [normalize_owner_name(name) for name in owner_names if name]
        if not any(name in EDU1_TEAM_MEMBERS for name in normalized_owners):
            continue

        org_id = row["org_id"]
        org_name = row["org_name"] or org_id or "-"
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
                "owners": owner_names,
                "probability": row["probability"],
                "expectedCloseDate": row["expected_close_date"],
                "expectedAmount": _to_number(row["expected_amount"]),
                "memoCount": int(row["memo_count"] or 0),
                "isRetention": bool(org_id and org_id in retention_org_ids),
                "orgWon2025Total": org_won_2025_total.get(org_id, 0.0) if org_id else 0.0,
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


def get_initial_dashboard_data(db_path: Path = DB_PATH) -> Dict[str, Any]:
    """
    Read the SQLite snapshot and return a JSON-serializable structure for the dashboard.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
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
        memo_rows = _fetch_all(
            conn,
            "SELECT id, dealId, peopleId, organizationId, text, createdAt, updatedAt, ownerId "
            "FROM memo",
        )

    organizations = _rows_to_dicts(org_rows)
    people = _rows_to_dicts(people_rows)
    deals = _rows_to_dicts(deal_rows)
    memos = _rows_to_dicts(memo_rows)

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
    stat = db_path.stat()
    snapshot_version = f"db_mtime:{int(stat.st_mtime)}"

    cache_key = (db_path, stat.st_mtime, exclude_org_name or "", tuple(years_list))
    cached = _RANK_2025_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    year_placeholders = ",".join(["?"] * len(years_str))
    params: List[Any] = list(years_str)
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
              SUBSTR(d."계약 체결일", 1, 4) AS year,
              SUM(CAST(d."금액" AS REAL)) AS totalAmount
            FROM deal d
            LEFT JOIN organization o ON o.id = d.organizationId
            WHERE d."상태" = 'Won'
              AND d."계약 체결일" IS NOT NULL
              AND SUBSTR(d."계약 체결일", 1, 4) IN ({year_placeholders})
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


def get_rank_2025_top100_counterparty_dri(
    size: str = "대기업", limit: int = 100, offset: int = 0, db_path: Path = DB_PATH
) -> Dict[str, Any]:
    """
    Top organizations by 2025 Won (size-filtered) with counterparty(upper_org) breakdown and owners list.
    - Online formats: 구독제(온라인)/선택구매(온라인)/포팅 (exact match)
    - Offline: others
    - Sorting: orgWon2025 desc, then cpTotal2025 desc
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    limit = max(1, min(limit or 100, 200))
    offset = max(0, offset or 0)

    cache_key = (db_path, db_path.stat().st_mtime, size or "대기업", limit, offset)
    cached = _COUNTERPARTY_DRI_CACHE.get(cache_key)
    if cached is not None:
        return cached

    conditions = [
        '('
        ' (d."계약 체결일" LIKE ? OR d."수주 예정일" LIKE ?)'
        ' OR (d."계약 체결일" LIKE ? OR d."수주 예정일" LIKE ?)'
        ')'
    ]
    params: List[Any] = ["2025%", "2025%", "2026%", "2026%"]
    if size and size != "전체":
        conditions.append('o."기업 규모" = ?')
        params.append(size)

    online_set = sp.ONLINE_COURSE_FORMATS

    with _connect(db_path) as conn:
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
            "  SELECT * FROM org_sum ORDER BY totalAmount DESC LIMIT ? OFFSET ?"
            ") SELECT * FROM ranked",
            params + [limit, offset],
        )

        top_ids = {row["orgId"] for row in top_orgs}
        if not top_ids:
            return {
                "size": size or "대기업",
                "limit": limit,
                "offset": offset,
                "rows": [],
                "meta": {"orgCount": 0, "rowCount": 0, "offset": offset, "limit": limit},
            }

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
            '  d."수주 예정일" AS expected_date, '
            '  d."수강시작일" AS start_date, '
            '  d."성사 가능성" AS probability '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            "LEFT JOIN people p ON p.id = d.peopleId "
            f"WHERE {' AND '.join(conditions)} AND d.organizationId IN ({placeholders}) ",
            params + list(top_ids),
        )

    def _norm_text(val: Any) -> str:
        text = (val or "").strip()
        return text if text else "미입력"

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
        upper = _norm_text(row["upper_org"])
        key = (org_id, upper)
        entry = cp_map.setdefault(
            key,
            {
                "orgId": org_id,
                "upperOrg": upper,
                "cpOnline2025": 0.0,
                "cpOffline2025": 0.0,
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
            elif not is_offline:
                entry["cpOnline2025"] += amount
                entry["cpTotal2025"] += amount
                entry["dealCount2025"] += 1
            # 2025 + start 2026 오프라인 → 26 가산
            if is_offline and start_year == "2026":
                entry["cpOffline2026"] += amount
        if prob_high and year == "2026" and is_offline:
            entry["cpOffline2026"] += amount

    # owners: fetch minimal rows for top orgs only
    owner_rows: List[sqlite3.Row] = []
    with _connect(db_path) as conn:
        owner_rows = _fetch_all(
            conn,
            'SELECT d.organizationId AS orgId, COALESCE(p."소속 상위 조직","미입력") AS upper_org, d."담당자" AS owner_json '
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

    for row in owner_rows:
        org_id = row["orgId"]
        upper = _norm_text(row["upper_org"])
        key = (org_id, upper)
        if key not in cp_map:
            continue
        entry = cp_map[key]
        owner_names = _parse_owner_names(row["owner_json"])
        if owner_names:
            for name in owner_names:
                entry["owners2025"].add(name)
        else:
            entry["owners2025"].add("미입력")

    rows: List[Dict[str, Any]] = []
    for (org_id, upper), cp in cp_map.items():
        org_entry = org_lookup.get(org_id, {})
        rows.append(
            {
                "orgId": org_id,
                "orgName": cp.get("orgName", org_id),
                "orgTier": _compute_grade(org_entry.get("total", 0.0)),
                "orgWon2025": org_entry.get("total", 0.0),
                "orgOnline2025": 0.0 if org_id not in org_lookup else None,  # populated below
                "orgOffline2025": 0.0 if org_id not in org_lookup else None,
                "upperOrg": upper,
                "cpOnline2025": cp["cpOnline2025"],
                "cpOffline2025": cp["cpOffline2025"],
                "cpTotal2025": cp["cpTotal2025"],
                "cpOffline2026": cp.get("cpOffline2026", 0.0),
                "owners2025": sorted(cp["owners2025"]) if cp.get("owners2025") else [],
                "dealCount2025": cp["dealCount2025"],
            }
        )

    # set org online/offline from org_lookup
    for row in rows:
        org_entry = org_lookup.get(row["orgId"], {})
        row["orgOnline2025"] = org_entry.get("online", 0.0)
        row["orgOffline2025"] = org_entry.get("offline", 0.0)

    rows.sort(key=lambda r: (-r["orgWon2025"], -r["cpTotal2025"]))

    result = {
        "size": size or "대기업",
        "limit": limit,
        "offset": offset,
        "rows": rows,
        "meta": {"orgCount": len(top_orgs), "rowCount": len(rows), "offset": offset, "limit": limit},
    }
    _COUNTERPARTY_DRI_CACHE[cache_key] = result
    return result
