import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.server import database as db


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (id TEXT, "이름" TEXT, "기업 규모" TEXT);
        CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT, "담당자" TEXT, "팀(명함/메일서명)" TEXT);
        CREATE TABLE memo (id TEXT, dealId TEXT);
        CREATE TABLE deal (
          id TEXT,
          peopleId TEXT,
          organizationId TEXT,
          "이름" TEXT,
          "상태" TEXT,
          "성사 가능성" TEXT,
          "금액" TEXT,
          "예상 체결액" TEXT,
          "계약 체결일" TEXT,
          "생성 날짜" TEXT,
          "과정포맷" TEXT,
          "담당자" TEXT,
          "수강시작일" TEXT,
          "수강종료일" TEXT,
          "코스 ID" TEXT,
          "(온라인)입과 주기" TEXT,
          "(온라인)최초 입과 여부" TEXT
        );
        """
    )
    conn.execute('INSERT INTO organization VALUES ("org-1","회사A","대기업")')
    conn.execute('INSERT INTO people VALUES ("p-1","org-1","담당자A","HRD본부", \'{"name":"홍길동"}\', "팀A")')
    # Valid online retention deal
    conn.execute(
        'INSERT INTO deal VALUES ("d-1","p-1","org-1","온라인딜1","Won","확정","100000000","0","2025-01-01","2024-12-15","구독제(온라인)",'
        '\'{"name":"홍길동"}\', "2025-02-01","2025-02-28","COURSE-1","월 1회","Y")'
    )
    # Should be filtered out (course format offline)
    conn.execute(
        'INSERT INTO deal VALUES ("d-2","p-1","org-1","오프라인딜","Won","확정","200000000","0","2025-01-02","2024-12-20","집합",'
        '\'{"name":"홍길동"}\', "2025-02-01","2025-02-28","COURSE-2","월 1회","Y")'
    )
    # Memo for d-1
    conn.execute('INSERT INTO memo VALUES ("m-1","d-1")')
    conn.commit()
    conn.close()


class OnlineRetention2026ApiTest(unittest.TestCase):
    def test_online_retention_filters_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            _build_db(db_path)

            res = db.get_ops_2026_online_retention(db_path=db_path)
            items = res["items"]
            self.assertEqual(res["meta"]["rowCount"], len(items))
            self.assertEqual(len(items), 1)
            row = items[0]
            self.assertEqual(row["dealId"], "d-1")
            self.assertEqual(row["status"], "Won")
            self.assertEqual(row["courseFormat"], "구독제(온라인)")
            self.assertEqual(row["memoCount"], 1)
            self.assertGreaterEqual(row["amount"], 0)
            self.assertTrue(row["startDate"])
            self.assertTrue(row["endDate"])
            self.assertIn("홍길동", row["owners"])


if __name__ == "__main__":
    unittest.main()
