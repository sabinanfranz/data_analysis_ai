import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.server import database as db


def _init_db(path: Path) -> None:
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
            "생성 날짜" TEXT,
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
    conn.executemany(
        'INSERT INTO organization (id, "이름") VALUES (?, ?)',
        [
            ("orgA", "알파"),
            ("orgB", "베타"),
            ("orgC", "감마"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직", "팀(명함/메일서명)") VALUES (?, ?, ?, ?, ?)',
        [
            ("pA", "orgA", "사람A", "HRD본부", "팀A"),
            ("pB", "orgB", "사람B", "BU본부", "팀B"),
            ("pC", "orgC", "사람C", "HRD본부", "팀C"),
        ],
    )
    conn.executemany(
        'INSERT INTO deal (id, peopleId, organizationId, "이름", "상태", "금액", "예상 체결액", "계약 체결일", '
        '"생성 날짜", "과정포맷", "담당자", "성사 가능성", "수주 예정일") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("won-a", None, "orgA", "Won A", "Won", "100", "999", "2025-01-10", "2025-01-10", "", "", "", ""),
            ("won-b", None, "orgB", "Won B", "Won", None, "300", "2025-02-02", "2025-02-02", "", "", "", ""),
            (
                "deal-a0",
                "pA",
                "orgA",
                "딜 A0",
                "SQL",
                "0",
                "500",
                "",
                "2025-01-01",
                "오프라인",
                '["황초롱"]',
                "높음",
                "2025-03-01",
            ),
            (
                "deal-a1",
                "pA",
                "orgA",
                "딜 A1",
                "SQL",
                "0",
                "700",
                "",
                "2025-02-01",
                "오프라인",
                "김솔이B",
                "높음",
                "2025-03-10",
            ),
            (
                "deal-b1",
                "pB",
                "orgB",
                "딜 B1",
                "SQL",
                "0",
                "900",
                "",
                "2025-03-01",
                "오프라인",
                '{"name": "김세연"}',
                "높음",
                "2025-04-01",
            ),
            (
                "deal-b2",
                "pB",
                "orgB",
                "딜 B2",
                "SQL",
                "0",
                "900",
                "",
                "2025-04-01",
                "오프라인",
                "홍길동",
                "높음",
                "2025-05-01",
            ),
            (
                "won-c",
                None,
                "orgC",
                "Won C",
                "Won",
                "200",
                None,
                "2025-01-05",
                "2025-01-05",
                "",
                "",
                "",
                "",
            ),
            (
                "deal-c1",
                "pC",
                "orgC",
                "딜 C1",
                "SQL",
                "0",
                "300",
                "",
                "2025-01-15",
                "온라인",
                '["권노을"]',
                "높음",
                "2025-02-01",
            ),
            (
                "deal-c2",
                "pC",
                "orgC",
                "딜 C2",
                "SQL",
                "0",
                "300",
                "",
                "2025-01-20",
                "온라인",
                "비멤버",
                "높음",
                "2025-02-02",
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO memo (id, dealId, text, createdAt) VALUES (?, ?, ?, ?)",
        [
            ("m1", "deal-a1", "첫 메모", "2025-02-02"),
            ("m2", "deal-a1", "두번째 메모", "2025-02-03"),
        ],
    )
    conn.commit()
    conn.close()


class DealCheckTest(unittest.TestCase):
    def test_deal_check_team_filters_and_retention(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db(db_path)
        try:
            items = db.get_deal_check("edu1", db_path=db_path)
            deal_ids = [row["dealId"] for row in items]
            self.assertEqual(deal_ids, ["deal-a0", "deal-a1", "deal-b1"])

            self.assertTrue(all(row["isRetention"] for row in items if row["orgId"] == "orgA"))
            self.assertTrue(all(not row["isRetention"] for row in items if row["orgId"] == "orgB"))

            memo_item = next(row for row in items if row["dealId"] == "deal-a1")
            self.assertEqual(memo_item["memoCount"], 2)
            self.assertEqual(memo_item["orgWon2025Total"], 100.0)

            self.assertNotIn("deal-b2", deal_ids)

            edu2_items = db.get_deal_check("edu2", db_path=db_path)
            edu2_ids = [row["dealId"] for row in edu2_items]
            self.assertEqual(edu2_ids, ["deal-c1"])
            edu2_row = edu2_items[0]
            self.assertEqual(edu2_row["orgId"], "orgC")
            self.assertTrue(edu2_row["isRetention"])
            self.assertEqual(edu2_row["orgWon2025Total"], 200.0)

            with self.assertRaises(ValueError):
                db.get_deal_check("unknown", db_path=db_path)
        finally:
            db_path.unlink(missing_ok=True)
