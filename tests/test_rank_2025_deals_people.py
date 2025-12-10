import sqlite3
import tempfile
from pathlib import Path

from dashboard.server import database as db


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (
            id TEXT PRIMARY KEY,
            "이름" TEXT,
            "기업 규모" TEXT
        );
        CREATE TABLE people (
            id TEXT PRIMARY KEY,
            organizationId TEXT,
            "이름" TEXT,
            "소속 상위 조직" TEXT,
            "팀(명함/메일서명)" TEXT,
            "직급(명함/메일서명)" TEXT,
            "담당 교육 영역" TEXT
        );
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            peopleId TEXT,
            organizationId TEXT,
            "이름" TEXT,
            "상태" TEXT,
            "금액" REAL,
            "예상 체결액" REAL,
            "계약 체결일" TEXT,
            "과정포맷" TEXT
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES (?, ?, ?)',
        [
            ("org-1", "오가닉", "대기업"),
            ("org-2", "미드", "중견기업"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직", "팀(명함/메일서명)", "직급(명함/메일서명)", "담당 교육 영역") '
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("p-1", "org-1", "담당자A", "HQ", "팀A", "부장", "교육A"),
            ("p-2", "org-1", "담당자B", "BU", "팀B", "차장", "교육B"),
            ("p-3", "org-2", "담당자C", "ZU", "팀C", "과장", "교육C"),
        ],
    )
    conn.executemany(
        'INSERT INTO deal (id, peopleId, organizationId, "이름", "상태", "금액", "예상 체결액", "계약 체결일", "과정포맷") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("d-1", "p-1", "org-1", "딜1", "Won", 100.0, 120.0, "2025-01-01", "온라인"),
            ("d-2", None, "org-2", "딜2", "Won", 200.0, 220.0, "2025-05-01", "오프라인"),
            ("d-3", "p-1", "org-1", "딜3", "Won", 300.0, 0.0, "2024-12-31", "혼합"),  # year mismatch
            ("d-4", "p-1", "org-1", "딜4", "Lost", 400.0, 0.0, "2025-02-01", "온라인"),  # status mismatch
            ("d-5", "p-2", "org-1", "딜5", "Won", 500.0, 0.0, "2025-03-03", "온라인"),  # second person
            ("d-6", "p-3", "org-2", "딜6", "Won", 50.0, 0.0, "2025-03-04", "온라인"),  # for org-2 total
        ],
    )
    conn.commit()
    conn.close()


def test_rank_2025_deals_people_filters_and_fields() -> None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        db_path = Path(tmp.name)
    _init_db(db_path)
    try:
        # 기본 size=대기업 → org-1만 포함, person 단위 2개
        items = db.get_rank_2025_deals_people(db_path=db_path)
        assert len(items) == 2
        person_map = {row["personId"]: row for row in items}

        p1 = person_map["p-1"]
        assert p1["orgId"] == "org-1"
        assert p1["orgName"] == "오가닉"
        assert p1["upper_org"] == "HQ"
        assert len(p1["deals"]) == 3  # 딜1, 딜3, 딜4 (상태/연도 무관)
        names = {d["dealName"] for d in p1["deals"]}
        assert {"딜1", "딜3", "딜4"} <= names

        p2 = person_map["p-2"]
        assert len(p2["deals"]) == 1
        assert p2["deals"][0]["dealName"] == "딜5"

        # size=전체 → 중견 포함, peopleId NULL 딜도 포함되어야 함
        all_items = db.get_rank_2025_deals_people(size="전체", db_path=db_path)
        org_ids = [r["orgId"] for r in all_items]
        assert "org-2" in org_ids
        # 정렬: org-1 total(600) > org-2 total(50), upper_org/team desc within org
        assert all_items[0]["orgId"] == "org-1"
        assert all_items[1]["orgId"] == "org-1"
        assert all_items[-1]["orgId"] == "org-2"
    finally:
        db_path.unlink(missing_ok=True)
