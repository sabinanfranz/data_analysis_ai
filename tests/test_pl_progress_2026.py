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
            "소속 상위 조직" TEXT
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
            "수주 예정일" TEXT,
            "수강시작일" TEXT,
            "수강종료일" TEXT,
            "성사 가능성" TEXT,
            "과정포맷" TEXT,
            "담당자" TEXT
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "이름") VALUES (?, ?)',
        [
            ("org-1", "조직1"),
            ("org-2", "조직2"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직") VALUES (?, ?, ?, ?)',
        [
            ("p-1", "org-1", "고객A", "본부A"),
            ("p-2", "org-2", "고객B", "본부B"),
        ],
    )
    deal_rows = [
        # Online, 높음, 금액 사용, 2026-01 full month
        ("d-1", "p-1", "org-1", "딜1", "SQL", 100_000_000, None, None, None, "2026-01-01", "2026-01-31", "높음", "구독제 (온라인)", '["담당A"]'),
        # Offline, 확정, 금액 없음 → 예상 체결액 사용, 2026-01~02跨월
        ("d-2", "p-2", "org-2", "딜2", "Open", None, 200_000_000, None, None, "2026-01-15", "2026-02-14", "확정", "집합", '["담당B"]'),
        # Offline, Won fallback when probability missing
        ("d-3", "p-1", "org-1", "딜3", "Won", 300_000_000, None, None, None, "2026-03-01", "2026-03-10", None, "집합", '["담당A"]'),
        # Missing end date → excluded (missing_dates)
        ("d-4", "p-1", "org-1", "딜4", "SQL", 100_000_000, None, None, None, "2026-04-01", None, "높음", "집합", '["담당A"]'),
        # Missing amount/expected → excluded (missing_amount)
        ("d-5", "p-1", "org-1", "딜5", "SQL", None, None, None, None, "2026-05-01", "2026-05-10", "확정", "집합", '["담당A"]'),
    ]
    placeholders = ",".join(["?"] * len(deal_rows[0]))
    conn.executemany(
        f'INSERT INTO deal ("id","peopleId","organizationId","이름","상태","금액","예상 체결액","계약 체결일","수주 예정일","수강시작일","수강종료일","성사 가능성","과정포맷","담당자") VALUES ({placeholders})',
        deal_rows,
    )
    conn.commit()
    conn.close()


class PlProgress2026Test(unittest.TestCase):
    def test_summary_and_deals(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db(db_path)
        try:
            summary = db.get_pl_progress_summary(db_path=db_path)
            months = summary["months"]
            self.assertEqual(months[0], "2601")
            self.assertEqual(months[-1], "2612")
            rows = {row["key"]: row for row in summary["rows"]}
            rev_online = rows["REV_ONLINE"]["values"]
            rev_offline = rows["REV_OFFLINE"]["values"]

            # Target 그대로 반영 (온라인+출강 합계)
            self.assertAlmostEqual(rows["REV_TOTAL"]["values"]["2601_T"], 5.8)
            self.assertAlmostEqual(rows["REV_OFFLINE"]["values"]["2605_T"], 12.4)

            # Recognized amounts (E) from deals
            self.assertAlmostEqual(rev_online["2601_E"], 1.0)
            self.assertAlmostEqual(rev_offline["2601_E"], 34 / 31, places=4)  # 17/31 * 2억 / 1e8
            self.assertAlmostEqual(rev_offline["2602_E"], 28 / 31, places=4)
            self.assertAlmostEqual(rev_offline["2603_E"], 3.0)

            meta_excluded = summary["meta"]["excluded"]
            self.assertEqual(meta_excluded.get("missing_dates"), 1)
            self.assertEqual(meta_excluded.get("missing_amount"), 1)

            deals_online = db.get_pl_progress_deals(year=2026, month="2601", rail="ONLINE", db_path=db_path)
            self.assertEqual(deals_online["meta"]["total"], 1)
            item = deals_online["items"][0]
            self.assertEqual(item["dealId"], "d-1")
            self.assertAlmostEqual(item["recognizedAmount"], 1.0)
            self.assertEqual(item["amountUsed"], 100_000_000)

            deals_total_feb = db.get_pl_progress_deals(year=2026, month="2602", rail="TOTAL", db_path=db_path)
            self.assertEqual(deals_total_feb["meta"]["total"], 1)
            feb_item = deals_total_feb["items"][0]
            self.assertEqual(feb_item["dealId"], "d-2")
            self.assertAlmostEqual(feb_item["recognizedAmount"], 28 / 31, places=4)
            self.assertEqual(feb_item["amountUsed"], 200_000_000)
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
