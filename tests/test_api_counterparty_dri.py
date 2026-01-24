import sqlite3
import tempfile
import unittest
from pathlib import Path

import openpyxl

from dashboard.server import counterparty_targets_2026 as ct
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


def _write_targets(path: Path, offline_rows: list[tuple], online_rows: list[tuple]) -> None:
  wb = openpyxl.Workbook()
  ws = wb.active
  ws.title = "26 출강 타겟"
  offline_headers = ["기업명", "카운터파티", "26 출강 타겟"]
  if offline_rows and len(offline_rows[0]) == 4:
    offline_headers.insert(1, "orgId")
  ws.append(offline_headers)
  for row in offline_rows:
    if len(row) == 4:
      org, org_id, upper, val = row
      ws.append([org, org_id, upper, val])
    else:
      org, upper, val = row
      ws.append([org, upper, val])

  ws2 = wb.create_sheet("26 온라인 타겟")
  online_headers = ["기업명", "카운터파티", "26 온라인 타겟"]
  if online_rows and len(online_rows[0]) == 4:
    online_headers.insert(1, "orgId")
  ws2.append(online_headers)
  for row in online_rows:
    if len(row) == 4:
      org, org_id, upper, val = row
      ws2.append([org, org_id, upper, val])
    else:
      org, upper, val = row
      ws2.append([org, upper, val])
  wb.save(path)


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
        self.assertIn("target26Offline", target)
        self.assertIn("target26Online", target)
        self.assertFalse(target.get("target26OfflineIsOverride", False))
        self.assertFalse(target.get("target26OnlineIsOverride", False))

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

  def test_targets_summary(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      res = db.get_rank_2025_counterparty_dri_targets_summary(size="대기업", db_path=db_path)
      self.assertIn("totals", res)
      totals = res["totals"]
      self.assertGreater(totals["cpOffline2025"], 0)
      self.assertGreater(totals["target26Offline"], 0)
      self.assertGreater(totals["cpOnline2025"], 0)

  def test_excel_only_override_injected_as_tier_n(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      conn = sqlite3.connect(db_path)
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
      conn.execute('INSERT INTO organization VALUES ("org-a","비지에프리테일","대기업")')
      conn.execute('INSERT INTO people VALUES ("p-other","org-a","담당자A","다른팀", NULL)')
      conn.execute('INSERT INTO people VALUES ("p-target","org-a","담당자B","인프라 운영팀", NULL)')
      conn.execute(
          'INSERT INTO deal VALUES ("d-1","p-other","org-a","딜1","Won","확정","100000000","0","2025-01-01","2024-12-20","집합","{}")'
      )
      conn.commit()
      conn.close()

      xlsx_path = Path(tmpdir) / "targets.xlsx"
      _write_targets(
          xlsx_path,
          offline_rows=[],
          online_rows=[("비지에프리테일", "인프라운영팀", 1.2)],
      )

      original_path = ct.RESOURCE_PATH
      try:
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})
        ct.RESOURCE_PATH = xlsx_path
        res = db.get_rank_2025_top100_counterparty_dri(size="대기업", db_path=db_path)
      finally:
        ct.RESOURCE_PATH = original_path
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})

      rows = res["rows"]
      target = next((r for r in rows if r["orgName"] == "비지에프리테일" and r["upperOrg"] == "인프라운영팀"), None)
      self.assertIsNotNone(target)
      if target:
        self.assertEqual(target["orgTier"], "N")
        self.assertAlmostEqual(target["target26Online"], 1.2 * 1e8)
        self.assertTrue(target["target26OnlineIsOverride"])
        self.assertEqual(target["cpTotal2025"], 0)

  def test_override_keeps_zero_total_row(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      conn = sqlite3.connect(db_path)
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
      conn.execute('INSERT INTO organization VALUES ("org-b","테스트B","대기업")')
      conn.execute('INSERT INTO people VALUES ("p-b","org-b","담당자B","팀B", NULL)')
      # 2026 deal only -> cpTotal2025 stays 0 but org appears
      conn.execute(
          'INSERT INTO deal VALUES ("d-b1","p-b","org-b","딜B","Won","확정","200000000","0","2026-02-01","2025-12-15","집합","{}")'
      )
      conn.commit()
      conn.close()

      xlsx_path = Path(tmpdir) / "targets.xlsx"
      _write_targets(
          xlsx_path,
          offline_rows=[("테스트B", "팀B", 0.5)],
          online_rows=[],
      )

      original_path = ct.RESOURCE_PATH
      try:
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})
        ct.RESOURCE_PATH = xlsx_path
        res = db.get_rank_2025_top100_counterparty_dri(size="대기업", db_path=db_path)
      finally:
        ct.RESOURCE_PATH = original_path
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})

      rows = res["rows"]
      target = next((r for r in rows if r["orgName"] == "테스트B" and r["upperOrg"] == "팀B"), None)
      self.assertIsNotNone(target)
      if target:
        self.assertEqual(target["cpTotal2025"], 0)
        self.assertTrue(target["target26OfflineIsOverride"])
        self.assertAlmostEqual(target["target26Offline"], 0.5 * 1e8)

  def test_override_diagnostics_when_match_fails(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      conn = sqlite3.connect(db_path)
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
      conn.execute('INSERT INTO organization VALUES ("org-c","유효조직","대기업")')
      conn.execute('INSERT INTO people VALUES ("p-c","org-c","담당자C","다른팀", NULL)')
      conn.execute(
          'INSERT INTO deal VALUES ("d-c","p-c","org-c","딜C","Won","확정","50000000","0","2025-01-10","2024-12-01","집합","{}")'
      )
      conn.commit()
      conn.close()

      xlsx_path = Path(tmpdir) / "targets.xlsx"
      _write_targets(
          xlsx_path,
          offline_rows=[("없는회사", "진단팀", 1.0)],
          online_rows=[],
      )

      original_path = ct.RESOURCE_PATH
      try:
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})
        ct.RESOURCE_PATH = xlsx_path
        res = db.get_rank_2025_top100_counterparty_dri(size="대기업", db_path=db_path, debug=True)
      finally:
        ct.RESOURCE_PATH = original_path
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})

      diags = res["meta"].get("overrideDiagnostics") or []
      target = next((d for d in diags if d.get("orgName") == "없는회사"), None)
      self.assertIsNotNone(target)
      if target:
        self.assertEqual(target.get("org_match_count"), 0)
        self.assertFalse(target.get("upper_org_exists_in_people"))
        self.assertFalse(target.get("has_deal_row_already"))

  def test_override_regressions_exact_match(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      conn = sqlite3.connect(db_path)
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
      conn.execute('INSERT INTO organization VALUES ("org-samsung","삼성전자","전체")')
      conn.execute('INSERT INTO organization VALUES ("org-naver","네이버","전체")')
      conn.execute('INSERT INTO organization VALUES ("org-lg","엘지전자","전체")')
      conn.execute('INSERT INTO people VALUES ("p-s","org-samsung","담당자S","Talent Development  ", NULL)')
      conn.execute('INSERT INTO people VALUES ("p-n","org-naver","담당자N","HR LEADER CLASS", NULL)')
      conn.execute('INSERT INTO people VALUES ("p-l","org-lg","담당자L","CTO 조직", NULL)')
      # add minimal deals so orgs are included in top set
      conn.execute(
          'INSERT INTO deal VALUES ("d-s","p-s","org-samsung","딜S","Won","확정","100000000","0","2025-01-01","2024-12-01","집합","{}")'
      )
      conn.execute(
          'INSERT INTO deal VALUES ("d-n","p-n","org-naver","딜N","Won","확정","80000000","0","2025-02-01","2025-01-01","집합","{}")'
      )
      conn.execute(
          'INSERT INTO deal VALUES ("d-l","p-l","org-lg","딜L","Won","확정","60000000","0","2025-03-01","2025-02-01","포팅","{}")'
      )
      conn.commit()
      conn.close()

      xlsx_path = Path(tmpdir) / "targets.xlsx"
      _write_targets(
          xlsx_path,
          offline_rows=[
              ("삼성전자", "Talent Development", 1.1),
              ("네이버", "HR LEADER CLASS", 2.2),
          ],
          online_rows=[
              ("엘지전자", "CTO 조직", 3.3),
          ],
      )

      original_path = ct.RESOURCE_PATH
      try:
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})
        ct.RESOURCE_PATH = xlsx_path
        res = db.get_rank_2025_top100_counterparty_dri(size="전체", db_path=db_path)
      finally:
        ct.RESOURCE_PATH = original_path
        ct._CACHE.update({"mtime": None, "offline": {}, "online": {}, "meta": {}})

      rows = res["rows"]
      pair_checks = [
          ("삼성전자", "Talent Development", "target26OfflineIsOverride"),
          ("네이버", "HR LEADER CLASS", "target26OfflineIsOverride"),
          ("엘지전자", "CTO 조직", "target26OnlineIsOverride"),
      ]
      for org_name, upper, flag in pair_checks:
        target = next((r for r in rows if r["orgName"] == org_name and r["upperOrg"] == upper), None)
        self.assertIsNotNone(target, f"missing override row for {org_name} | {upper}")
        if target:
          self.assertTrue(target.get(flag), f"override flag missing for {org_name} | {upper}")


if __name__ == "__main__":
  unittest.main()
