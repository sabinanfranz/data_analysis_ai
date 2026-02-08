import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.server import database as db


def _init_db_with_created_at(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (
            id TEXT PRIMARY KEY,
            "이름" TEXT
        );
        CREATE TABLE people (
            id TEXT PRIMARY KEY,
            organizationId TEXT,
            "이름" TEXT,
            "소속 상위 조직" TEXT,
            "팀(명함/메일서명)" TEXT
        );
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            peopleId TEXT,
            organizationId TEXT,
            "이름" TEXT,
            "상태" TEXT,
            "금액" TEXT,
            "예상 체결액" TEXT,
            "계약 체결일" TEXT,
            createdAt TEXT,
            "과정포맷" TEXT,
            "담당자" TEXT,
            "성사 가능성" TEXT,
            "수주 예정일" TEXT
        );
        CREATE TABLE memo (
            id TEXT PRIMARY KEY,
            dealId TEXT,
            text TEXT,
            createdAt TEXT
        );
        """
    )
    conn.execute('INSERT INTO organization (id, "이름") VALUES (?, ?)', ("org1", "테스트회사"))
    conn.execute(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직", "팀(명함/메일서명)") VALUES (?, ?, ?, ?, ?)',
        ("person1", "org1", "담당자A", "상위조직", "팀A"),
    )
    conn.execute(
        'INSERT INTO deal (id, peopleId, organizationId, "이름", "상태", "금액", "예상 체결액", "계약 체결일", createdAt, "과정포맷", "담당자", "성사 가능성", "수주 예정일") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "deal1",
            "person1",
            "org1",
            "딜1",
            "SQL",
            "0",
            "100",
            "",
            "2025-01-03",
            "오프라인",
            '["황초롱"]',
            "높음",
            "2025-02-01",
        ),
    )
    conn.commit()
    conn.close()


class DealCheckCreatedAtFallbackTest(unittest.TestCase):
    def test_deal_check_uses_created_at_fallback_column(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db_with_created_at(db_path)
        try:
            items = db.get_deal_check("edu1", db_path=db_path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["dealId"], "deal1")
            self.assertEqual(items[0]["createdAt"], "2025-01-03")
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

