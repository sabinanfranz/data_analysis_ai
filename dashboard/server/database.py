import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set

DB_PATH = Path(__file__).resolve().parent.parent.parent / "salesmap_latest.db"
_OWNER_LOOKUP_CACHE: Dict[Path, Dict[str, str]] = {}
YEARS_FOR_WON = {"2023", "2024", "2025"}


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
        'SELECT id, COALESCE("이름", id) AS name, "기업 규모" AS size, '
        '"팀" AS team_json, "담당자" AS owner_json '
        "FROM organization "
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

    query += "ORDER BY name LIMIT ? OFFSET ?"
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
                "dealCount": entry["dealCount"],
            }
        )

    # Sort by total amount desc (sum of years)
    result.sort(key=lambda x: (x["won2023"] + x["won2024"] + x["won2025"]), reverse=True)
    return result


def get_rank_2025_deals(size: str = "전체", db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    Aggregate 2025 'Won' deals by organization (total) and course format breakdown.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    conditions = ['d."상태" = ?', 'd."계약 체결일" LIKE ?']
    params: List[Any] = ["Won", "2025%"]
    if size and size != "전체":
        conditions.append('o."기업 규모" = ?')
        params.append(size)

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  d.organizationId AS orgId, '
            '  COALESCE(o."이름", d.organizationId) AS orgName, '
            '  o."업종 구분(대)" AS industry_major, '
            '  o."업종 구분(중)" AS industry_mid, '
            '  d."과정포맷" AS courseFormat, '
            '  SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            f"WHERE {' AND '.join(conditions)} "
            'GROUP BY d.organizationId, orgName, industry_major, industry_mid, d."과정포맷"',
            params,
        )

    # Accumulate per org and per course format
    orgs: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        org_id = row["orgId"]
        org_name = row["orgName"]
        industry_major = row["industry_major"]
        industry_mid = row["industry_mid"]
        course = row["courseFormat"]
        amount = _to_number(row["totalAmount"]) or 0.0
        org_entry = orgs.setdefault(
            org_id,
            {
                "orgId": org_id,
                "orgName": org_name,
                "industryMajor": industry_major,
                "industryMid": industry_mid,
                "totalAmount": 0.0,
                "formats": [],
            },
        )
        if not org_entry.get("orgName") and org_name:
            org_entry["orgName"] = org_name
        if not org_entry.get("industryMajor") and industry_major:
            org_entry["industryMajor"] = industry_major
        if not org_entry.get("industryMid") and industry_mid:
            org_entry["industryMid"] = industry_mid
        org_entry["totalAmount"] += amount
        org_entry["formats"].append({"courseFormat": course, "totalAmount": amount})

    # Sort formats per org by amount desc
    for entry in orgs.values():
        entry["formats"].sort(key=lambda x: x["totalAmount"] or 0, reverse=True)

    # Return orgs sorted by totalAmount desc
    ranked = sorted(orgs.values(), key=lambda x: x["totalAmount"] or 0, reverse=True)
    return ranked


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

    def _date_only(val: Any) -> str:
        if val is None:
            return ""
        text = str(val)
        if "T" in text:
            text = text.split("T")[0]
        if " " in text:
            text = text.split(" ")[0]
        return text

    def _webform_names(raw: Any) -> List[str]:
        data = _safe_json_load(raw)
        names: List[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name")
                    if name:
                        names.append(str(name))
                elif item:
                    names.append(str(item))
        return names

    with _connect(db_path) as conn:
        org_rows = _fetch_all(
            conn,
            'SELECT id, COALESCE("이름", id) AS name, "기업 규모" AS size, "업종" AS industry '
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
        }

        people_rows = _fetch_all(
            conn,
            'SELECT id, COALESCE("이름", id) AS name, "소속 상위 조직" AS upper_org, '
            '"팀(명함/메일서명)" AS team_signature, "직급(명함/메일서명)" AS title_signature, '
            '"담당 교육 영역" AS edu_area, "제출된 웹폼 목록" AS webforms '
            "FROM people WHERE organizationId = ?",
            (org_id,),
        )
        people_map: Dict[str, Dict[str, Any]] = {}
        for row in people_rows:
            pid = row["id"]
            upper = _normalize_upper(row["upper_org"])
            team_sig = _normalize_team(row["team_signature"])
            people_map[pid] = {
                "id": pid,
                "name": row["name"],
                "upper_org": upper,
                "team": team_sig,
                "team_signature": row["team_signature"],
                "title_signature": row["title_signature"],
                "edu_area": row["edu_area"],
                "webforms": _webform_names(row["webforms"]),
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
        entry = {"date": date_only, "text": memo["text"]}
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
                "created_at": row["created_at"],
                "name": row["name"],
                "team": row["team"],
                "owner": owner_name,
                "status": row["status"],
                "probability": row["probability"],
                "expected_date": row["expected_date"],
                "expected_amount": _to_number(row["expected_amount"]),
                "lost_confirmed_at": row["lost_confirmed_at"],
                "lost_reason": row["lost_reason"],
                "course_format": row["course_format"],
                "category": row["category"],
                "contract_date": row["contract_date"],
                "amount": _to_number(row["amount"]),
                "start_date": row["start_date"],
                "end_date": row["end_date"],
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
