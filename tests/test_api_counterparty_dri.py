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
        CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT, "담당자" TEXT);
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
          "담당자" TEXT
        );
      """
  )
  conn.execute('INSERT INTO organization VALUES ("org-1","알파","대기업")')
  conn.execute('INSERT INTO organization VALUES ("org-2","베타","대기업")')
  conn.execute('INSERT INTO organization VALUES ("org-3","감마","대기업")')
  conn.execute(
      'INSERT INTO people VALUES ("p-1","org-1","담당자A","HRD본부", \'{"id":"64d1cce2d92185a53be6bd09","name":"최예인"}\')'
  )
  conn.execute('INSERT INTO people VALUES ("p-2","org-2","담당자B","BU본부", NULL)')
  conn.execute('INSERT INTO people VALUES ("p-3","org-3","담당자C","전략본부", NULL)')
  deals = [
      # org-1, upper_org HRD본부
      ("d-1", "p-1", "org-1", "딜1", "Won", "확정", "100000000", "0", "2025-01-01", "2024-12-20", "포팅", '{"name":"딜담당자A"}'),
      ("d-2", "p-1", "org-1", "딜2", "Won", "확정", "200000000", "0", "2025-02-01", "2025-01-10", "포팅/SCORM", '{"name":"딜담당자B"}'),
      ("d-3", "p-1", "org-1", "딜3", "Won", "확정", "300000000", "0", "2025-03-01", "2025-02-10", "집합", '{"name":"딜담당자C"}'),
      # org-2, smaller total
      ("d-4", "p-2", "org-2", "딜4", "Won", "확정", "50000000", "0", "2025-01-05", "2024-12-31", "구독제(온라인)", '{"name":"딜담당자B"}'),
      # org-3, large but Lost/Convert should be excluded
      ("d-5", "p-3", "org-3", "딜5", "Lost", "확정", "900000000", "0", "2025-04-01", "2025-03-01", "집합", '{"name":"담당자C"}'),
      ("d-6", "p-3", "org-3", "딜6", "Convert", "확정", "800000000", "0", "2025-05-01", "2025-04-01", "집합", '{"name":"담당자C"}'),
      # org-1, 확정/높음이 아닌 딜(총액 크더라도 cpTotal은 0으로 필터)
      ("d-7", "p-1", "org-1", "딜7", "Open", "낮음", "700000000", "0", "2025-06-01", "2025-05-01", "집합", '{"name":"담당자A"}'),
      ("d-8", "p-1", "org-1", "딜8", "Won", "확정", "400000000", "0", "2026-01-10", "2025-12-15", "구독제(온라인)", '{"name":"딜담당자A"}'),
  ]
  conn.executemany('INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', deals)
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
        self.assertAlmostEqual(target["cpOnline2026"], 400000000)
        self.assertAlmostEqual(target["cpOffline2026"], 0)
        self.assertEqual(set(target["owners2025"]), {"최예인"})

      # org tier present, fallback to 미입력 if missing
      self.assertTrue(all("orgTier" in r for r in rows))

  def test_people_owner_preferred_over_deal_owner(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      res = db.get_rank_2025_top100_counterparty_dri(size="대기업", db_path=db_path)
      rows = res["rows"]

      hrd = next((r for r in rows if r["orgId"] == "org-1" and r["upperOrg"] == "HRD본부"), None)
      self.assertIsNotNone(hrd)
      if hrd:
        self.assertEqual(set(hrd["owners2025"]), {"최예인"})
        self.assertNotIn("딜담당자A", hrd["owners2025"])

      bu = next((r for r in rows if r["orgId"] == "org-2" and r["upperOrg"] == "BU본부"), None)
      self.assertIsNotNone(bu)
      if bu:
        self.assertIn("딜담당자B", bu["owners2025"])
        self.assertAlmostEqual(bu["cpOnline2026"], 0)

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

  def test_excludes_lost_and_convert(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      res = db.get_rank_2025_top100_counterparty_dri(size="대기업", db_path=db_path)
      org_ids = {r["orgId"] for r in res["rows"]}

      # org-3 only has Lost/Convert deals; should not appear in top org rows
      self.assertNotIn("org-3", org_ids)

  def test_filters_zero_total_counterparty(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      res = db.get_rank_2025_top100_counterparty_dri(size="대기업", db_path=db_path)
      rows = res["rows"]
      # org-1/upper_org from d-7 has prob not high -> cpTotal2025 remains 0 and should be filtered out
      zero_total = [r for r in rows if r["orgId"] == "org-1" and r["upperOrg"] == "HRD본부" and r["cpTotal2025"] == 0]
      self.assertEqual(zero_total, [])


if __name__ == "__main__":
  unittest.main()
