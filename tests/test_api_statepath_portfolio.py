import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
  from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional for test envs without fastapi extras
  TestClient = None

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
          "과정포맷" TEXT
        );
      """
  )
  conn.execute('INSERT INTO organization VALUES ("org-1","알파","대기업")')
  conn.execute('INSERT INTO organization VALUES ("org-2","베타","중견")')
  conn.execute('INSERT INTO people VALUES ("p-1","org-1","담당자A","HRD본부")')
  conn.execute('INSERT INTO people VALUES ("p-2","org-2","담당자B","BU본부")')
  deals = [
      # org-1: 2024 1억, 2025 3억
      ("d-1", "p-1", "org-1", "딜1", "Won", "100000000", "0", "2024-05-01", "2024-04-20", "구독제(온라인)"),
      ("d-2", "p-1", "org-1", "딜2", "Won", "300000000", "0", "2025-03-10", "2025-03-01", "선택구매(온라인)"),
      # org-2: only 2025 5천만 (0.5억)
      ("d-3", "p-2", "org-2", "딜3", "Won", "0", "50000000", "2025-02-15", "2025-02-01", "집합"),
  ]
  conn.executemany('INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?)', deals)
  conn.commit()
  conn.close()


class StatepathPortfolioTest(unittest.TestCase):
  def test_segment_and_search_filter(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      # segment filter
      res = db.get_statepath_portfolio(size_group="대기업", db_path=db_path)
      items = res["items"]
      self.assertEqual(len(items), 1)
      row = items[0]
      self.assertEqual(row["orgId"], "org-1")
      self.assertEqual(row["sizeGroup"], "대기업")
      self.assertAlmostEqual(row["companyTotalEok2024"], 1.0, places=3)
      self.assertEqual(row["companyBucket2024"], "P1")
      self.assertAlmostEqual(row["companyTotalEok2025"], 3.0, places=3)
      self.assertEqual(row["companyBucket2025"], "P0")
      # underscore aliases
      self.assertEqual(row["org_id"], "org-1")
      self.assertEqual(row["segment"], "대기업")
      self.assertEqual(row["company_bucket_2025"], "P0")
      # V1 enrichment
      self.assertIn("company_online_bucket_2024", row)
      self.assertIn("company_offline_bucket_2024", row)
      self.assertIn("cells_2024", row)
      self.assertIn("cells_2025", row)
      self.assertIn("HRD_ONLINE", row["cells_2025"])
      self.assertIn("bucket", row["cells_2025"]["HRD_ONLINE"])

      # search filter should exclude
      res_search = db.get_statepath_portfolio(size_group="전체", search="알파", db_path=db_path)
      self.assertEqual(len(res_search["items"]), 1)
      res_search_none = db.get_statepath_portfolio(size_group="전체", search="없는회사", db_path=db_path)
      self.assertEqual(len(res_search_none["items"]), 0)

  def test_api_endpoint_returns_items(self) -> None:
    if TestClient is None:
      self.skipTest("fastapi.testclient not available")
    from dashboard.server.main import app  # local import to avoid hard dependency when missing
    with tempfile.TemporaryDirectory() as tmpdir:
      db_path = Path(tmpdir) / "db.sqlite"
      _build_db(db_path)

      # patch DB_PATH-dependent call via wrapper
      original_fn = db.get_statepath_portfolio
      def _wrapped(**kwargs):
        return original_fn(db_path=db_path, **kwargs)

      client = TestClient(app)
      # monkeypatch router-level reference
      import dashboard.server.org_tables_api as api_module
      api_module.db.get_statepath_portfolio = _wrapped  # type: ignore
      try:
        resp = client.get("/api/statepath/portfolio-2425", params={"segment": "대기업", "limit": 10})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertGreaterEqual(len(data["items"]), 1)
        self.assertEqual(data["meta"]["segment"], "대기업")
      finally:
        api_module.db.get_statepath_portfolio = original_fn  # type: ignore


if __name__ == "__main__":
  unittest.main()
