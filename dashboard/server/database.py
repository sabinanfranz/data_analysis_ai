import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence

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
        amount = _to_number(row["amount"]) or 0.0
        contract_date = row["contract_date"] or ""
        year = str(contract_date)[:4]
        if year in YEARS_FOR_WON:
            entry[f"won{year}"] += amount
        entry["dealCount"] += 1

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


def get_rank_2025_deals(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """
    Aggregate 2025 'Won' deals by organization (total) and course format breakdown.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with _connect(db_path) as conn:
        rows = _fetch_all(
            conn,
            'SELECT '
            '  d.organizationId AS orgId, '
            '  COALESCE(o."이름", d.organizationId) AS orgName, '
            '  d."과정포맷" AS courseFormat, '
            '  SUM(CAST(d."금액" AS REAL)) AS totalAmount '
            "FROM deal d "
            "LEFT JOIN organization o ON o.id = d.organizationId "
            'WHERE d."상태" = ? AND d."계약 체결일" LIKE ? '
            'GROUP BY d.organizationId, orgName, d."과정포맷"',
            ("Won", "2025%"),
        )

    # Accumulate per org and per course format
    orgs: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        org_id = row["orgId"]
        org_name = row["orgName"]
        course = row["courseFormat"]
        amount = _to_number(row["totalAmount"]) or 0.0
        org_entry = orgs.setdefault(
            org_id,
            {"orgId": org_id, "orgName": org_name, "totalAmount": 0.0, "formats": []},
        )
        org_entry["totalAmount"] += amount
        org_entry["formats"].append({"courseFormat": course, "totalAmount": amount})

    # Sort formats per org by amount desc
    for entry in orgs.values():
        entry["formats"].sort(key=lambda x: x["totalAmount"] or 0, reverse=True)

    # Return orgs sorted by totalAmount desc
    ranked = sorted(orgs.values(), key=lambda x: x["totalAmount"] or 0, reverse=True)
    return ranked


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
