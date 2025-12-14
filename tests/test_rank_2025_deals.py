import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from dashboard.server import database as db


def build_rank_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE organization (id TEXT, "이름" TEXT, "기업 규모" TEXT)')
    conn.execute('CREATE TABLE deal (id TEXT, organizationId TEXT, "상태" TEXT, "계약 체결일" TEXT, "금액" TEXT, "과정포맷" TEXT)')
    conn.executemany(
        'INSERT INTO organization VALUES (?,?,?)',
        [
            ("org_s0", "S0 Co", "대기업"),
            ("org_p1", "P1 Co", "대기업"),
            ("org_p4", "P4 Co", "대기업"),
        ],
    )
    # amounts are in 원; thresholds are in 억 (1e8)
    deals = [
        ("d1", "org_s0", "Won", "2025-01-01", str(12 * 1e8), "구독제(온라인)"),  # online 12억
        ("d1b", "org_s0", "Won", "2024-05-01", str(5 * 1e8), "집합교육"),  # 2024 총액 5억 -> grade P1
        ("d2", "org_p1", "Won", "2025-02-02", str(1.5 * 1e8), "집합교육"),  # offline 1.5억 -> P1
        ("d2b", "org_p1", "Won", "2024-06-06", str(0.5 * 1e8), "집합교육"),  # 0.5억 -> P2 in 2024
        ("d3", "org_p4", "Won", "2025-03-03", str(0.15 * 1e8), "포팅"),  # online 0.15억 -> P4
        ("d4", "org_p1", "Lost", "2025-04-04", str(10 * 1e8), "집합교육"),  # ignored (not Won)
    ]
    conn.executemany('INSERT INTO deal VALUES (?,?,?,?,?,?)', deals)
    conn.commit()
    conn.close()


class Rank2025DealsTest(TestCase):
    def test_rank_2025_deals_grade_and_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            build_rank_db(db_path)

            items = db.get_rank_2025_deals(db_path=db_path)
            self.assertEqual(len(items), 3)
            filtered = db.get_rank_2025_deals(size="대기업", db_path=db_path)
            self.assertEqual(len(filtered), 3)  # size filter matches all
            # Sorted by total desc
            self.assertEqual(items[0]["orgId"], "org_s0")
            self.assertEqual(items[0]["grade"], "S0")
            self.assertAlmostEqual(items[0]["onlineAmount"], 12 * 1e8)
            self.assertAlmostEqual(items[0]["offlineAmount"], 0.0)

            p1 = next(i for i in items if i["orgId"] == "org_p1")
            self.assertEqual(p1["grade"], "P1")  # 1.5억 -> P1
            self.assertAlmostEqual(p1["onlineAmount"], 0.0)
            self.assertAlmostEqual(p1["offlineAmount"], 1.5 * 1e8)
            self.assertEqual(p1["grade2024"], "P2")
            self.assertAlmostEqual(p1["totalAmount2024"], 0.5 * 1e8)

            p4 = next(i for i in items if i["orgId"] == "org_p4")
            self.assertEqual(p4["grade"], "P4")
            self.assertAlmostEqual(p4["onlineAmount"], 0.15 * 1e8)
            self.assertAlmostEqual(p4["offlineAmount"], 0.0)
            self.assertEqual(p4["grade2024"], "P5")
            self.assertAlmostEqual(p4["totalAmount2024"], 0.0)

            s0 = items[0]
            self.assertEqual(s0["grade2024"], "P0")
            self.assertAlmostEqual(s0["totalAmount2024"], 5 * 1e8)
