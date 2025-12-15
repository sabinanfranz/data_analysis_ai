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
        CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT);
        CREATE TABLE deal (
          id TEXT,
          peopleId TEXT,
          organizationId TEXT,
          "이름" TEXT,
          "상태" TEXT,
          "금액" TEXT,
          "예상 체결액" TEXT,
          "계약 체결일" TEXT,
          "생성 날짜" TEXT,
          "과정포맷" TEXT,
          "담당자" TEXT
        );
      """
  )
  conn.execute('INSERT INTO organization VALUES ("org-1","알파","대기업")')
  conn.execute('INSERT INTO organization VALUES ("org-2","베타","대기업")')
  conn.execute('INSERT INTO people VALUES ("p-1","org-1","담당자A","HRD본부")')
  conn.execute('INSERT INTO people VALUES ("p-2","org-2","담당자B","BU본부")')
  deals = [
      # org-1, upper_org HRD본부
      ("d-1", "p-1", "org-1", "딜1", "Won", "100000000", "0", "2025-01-01", "2024-12-20", "포팅", '{"name":"담당자A"}'),
      ("d-2", "p-1", "org-1", "딜2", "Won", "200000000", "0", "2025-02-01", "2025-01-10", "포팅/SCORM", '{"name":"담당자A"}'),
      ("d-3", "p-1", "org-1", "딜3", "Won", "300000000", "0", "2025-03-01", "2025-02-10", "집합", '{"name":"담당자C"}'),
      # org-2, smaller total
      ("d-4", "p-2", "org-2", "딜4", "Won", "50000000", "0", "2025-01-05", "2024-12-31", "구독제(온라인)", '{"name":"담당자B"}'),
  ]
  conn.executemany('INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?)', deals)
  conn.commit()
  conn.close()


class CounterpartyDriApiTest(unittest.TestCase):
  def test_counterparty_online_offline_and_sort(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      res = db.get_rank_2025_top100_counterparty_dri(size="대기업", db_path=db_path)
      rows = res["rows"]
      self.assertGreaterEqual(len(rows), 2)

      # rows sorted by org total desc then cp total desc
      sorted_rows = sorted(rows, key=lambda r: (-r["orgWon2025"], -r["cpTotal2025"]))
      self.assertEqual(rows, sorted_rows)

      # find org-1 HRD본부 row
      target = next((r for r in rows if r["orgId"] == "org-1" and r["upperOrg"] == "HRD본부"), None)
      self.assertIsNotNone(target)
      if target:
        # online should count 포팅 only (not 포팅/SCORM)
        self.assertAlmostEqual(target["cpOnline2025"], 100000000)
        self.assertAlmostEqual(target["cpOffline2025"], 500000000)
        self.assertAlmostEqual(target["cpTotal2025"], target["cpOnline2025"] + target["cpOffline2025"])
        self.assertIn("담당자A", target["owners2025"])
        self.assertIn("담당자C", target["owners2025"])

      # org tier present, fallback to 미입력 if missing
      self.assertTrue(all("orgTier" in r for r in rows))

  def test_offset_limit(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      res1 = db.get_rank_2025_top100_counterparty_dri(size="대기업", limit=1, offset=0, db_path=db_path)
      res2 = db.get_rank_2025_top100_counterparty_dri(size="대기업", limit=1, offset=1, db_path=db_path)

      self.assertEqual(res1["meta"]["offset"], 0)
      self.assertEqual(res2["meta"]["offset"], 1)
      self.assertLessEqual(len(res1["rows"]), 1)
      self.assertLessEqual(len(res2["rows"]), 1)
      # offset 1 should skip the top org
      if res1["rows"] and res2["rows"]:
        self.assertNotEqual(res1["rows"][0]["orgId"], res2["rows"][0]["orgId"])


if __name__ == "__main__":
  unittest.main()
