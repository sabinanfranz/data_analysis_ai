import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
import types
import os

# Stub openpyxl to avoid heavy dependency during unit test import path.
if "openpyxl" not in sys.modules:
    sys.modules["openpyxl"] = types.SimpleNamespace(load_workbook=lambda *args, **kwargs: None, Workbook=None)

from dashboard.server import database as db


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE deal (
          id TEXT,
          "코스 ID" TEXT,
          "이름" TEXT,
          "담당자" TEXT,
          "상태" TEXT,
          "성사 가능성" TEXT,
          "계약 체결일" TEXT,
          "수주 예정일" TEXT,
          "금액" TEXT,
          "예상 체결액" TEXT,
          "수강시작일" TEXT,
          "수강종료일" TEXT
        );
        """
    )
    rows = [
        # Report candidate: edu1 팀장 포함, 모든 필수 필드 있음
        (
            "d-report",
            "COURSE-1",
            "매출신고딜",
            '["김별"]',
            "Won",
            "확정",
            "2026-01-10",
            "2026-01-10",
            "100000000",
            "0",
            "2026-02-01",
            "2026-02-28",
        ),
        # 누락(start_date) → report 제외
        (
            "d-missing-start",
            "COURSE-2",
            "누락딜",
            '["김별"]',
            "Won",
            "확정",
            "2026-01-15",
            "2026-01-15",
            "150000000",
            "0",
            "",
            "2026-02-20",
        ),
        # Review 후보: 확정/높음, 계약일 없음, 수주예정일로 매칭
        (
            "d-review",
            "",
            "검수딜",
            '["강지선"]',
            "Open",
            "높음",
            "",
            "2026-01-20",
            "",
            "200000000",
            "",
            "",
        ),
        # 공공팀 샘플: 공공교육팀 roster 확인
        (
            "d-public",
            "COURSE-P1",
            "공공딜",
            '["이준석"]',
            "Won",
            "확정",
            "2026-01-05",
            "2026-01-05",
            "50000000",
            "0",
            "2026-01-10",
            "2026-01-31",
        ),
        # 2025-12 review 전용 (확정/높음, report 조건 불충족 -> review 포함)
        (
            "d-review-202512",
            "",
            "검수딜-이전월",
            '["강지선"]',
            "Open",
            "확정",
            "",
            "2025-12-15",
            "",
            "120000000",
            "",
            "",
        ),
        # 2025-12 report 조건 충족 → review에서 제외되어야 함
        (
            "d-report-202512",
            "COURSE-202512",
            "매출신고딜-이전월",
            '["강지선"]',
            "Won",
            "확정",
            "2025-12-03",
            "2025-12-03",
            "80000000",
            "0",
            "2025-12-10",
            "2025-12-20",
        ),
        # 2026-01 review 조건이지만 비매출입과 태그 → review에서 제외되어야 함
        (
            "d-review-nonrev",
            "",
            "검수딜-타겟[비매출입과]",
            '["강지선"]',
            "Open",
            "확정",
            "",
            "2026-01-22",
            "",
            "30000000",
            "",
            "",
        ),
    ]
    conn.executemany("INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


class MonthlyRevenueReportTest(unittest.TestCase):
    def test_report_and_review_split_and_team_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            _build_db(db_path)

            res = db.get_qc_monthly_revenue_report(
                team="edu1", year=2026, month=1, history_from="2025-12", db_path=db_path
            )
            report_ids = {r["dealId"] for r in res["reportDeals"]}
            review_ids = {r["dealId"] for r in res["reviewDeals"]}

            self.assertIn("d-report", report_ids)
            self.assertNotIn("d-missing-start", report_ids)  # start/end 누락
            self.assertIn("d-review", review_ids)
            self.assertIn("d-missing-start", review_ids)  # Won이지만 신고 요건 미충족 → 검수 대상
            self.assertNotIn("d-report", review_ids)  # report에 포함된 딜은 review에서 제외
            self.assertNotIn("d-review-nonrev", review_ids)  # 비매출입과 태그는 제외

            # 금액 파싱 확인
            report_row = next(r for r in res["reportDeals"] if r["dealId"] == "d-report")
            self.assertEqual(report_row["amount"], 100000000.0)
            self.assertEqual(res["counts"]["report"], 1)
            self.assertEqual(res["counts"]["review"], 2)

            # 공공팀 호출 시 공공 roster만 포함
            res_public = db.get_qc_monthly_revenue_report(team="public", year=2026, month=1, db_path=db_path)
            public_ids = {r["dealId"] for r in res_public["reportDeals"]}
            self.assertIn("d-public", public_ids)
            self.assertNotIn("d-report", public_ids)

            # Review history: selected month first, then previous month with non-zero deals, report deals excluded
            history = res.get("reviewHistory") or []
            self.assertGreaterEqual(len(history), 1)
            self.assertEqual(history[0]["monthKey"], "2026-01")
            # 2025-12 should appear and include only the review deal, not the report one
            dec_section = next((h for h in history if h["monthKey"] == "2025-12"), None)
            self.assertIsNotNone(dec_section)
            if dec_section:
                dec_ids = {d["dealId"] for d in dec_section["deals"]}
                self.assertIn("d-review-202512", dec_ids)
                self.assertNotIn("d-report-202512", dec_ids)
            # Selected month history must also exclude non-revenue tag
            jan_section = next((h for h in history if h["monthKey"] == "2026-01"), None)
            if jan_section:
                jan_ids = {d["dealId"] for d in jan_section["deals"]}
                self.assertNotIn("d-review-nonrev", jan_ids)

    def test_history_from_future_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            _build_db(db_path)
            with self.assertRaises(ValueError):
                db.get_qc_monthly_revenue_report(team="edu1", year=2026, month=1, history_from="2026-02", db_path=db_path)

    def test_missing_accounting_report_deals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            _build_db(db_path)

            # Add two prior-month report-eligible deals (2025-02, 2025-03)
            conn = sqlite3.connect(db_path)
            conn.execute(
                'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    "d-report-202502",
                    "COURSE-202502",
                    "과거딜-1",
                    '["김별"]',
                    "Won",
                    "확정",
                    "2025-02-10",
                    "2025-02-10",
                    "110000000",
                    "0",
                    "2025-03-01",
                    "2025-03-31",
                ),
            )
            conn.execute(
                'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    "d-report-202503",
                    "COURSE-202503",
                    "과거딜-2",
                    '["김별"]',
                    "Won",
                    "확정",
                    "2025-03-12",
                    "2025-03-12",
                    "120000000",
                    "0",
                    "2025-04-01",
                    "2025-04-30",
                ),
            )
            conn.commit()
            conn.close()

            # accounting file only includes 2025 course for d-report-202502
            acct_path = Path(tmpdir) / "accounting.tsv"
            acct_path.write_text("코스ID\t기타\nCOURSE202502\tfoo\n", encoding="utf-8")
            os.environ["ACCOUNTING_DATA_PATH"] = str(acct_path)
            try:
                res = db.get_qc_monthly_revenue_report(
                    team="edu1", year=2025, month=4, history_from="2025-01", db_path=db_path
                )
                missing = res.get("missingAccountingDeals") or []
                missing_ids = {m["dealId"] for m in missing}
                self.assertIn("d-report-202503", missing_ids)  # not in accounting
                self.assertNotIn("d-report-202502", missing_ids)  # in accounting
                self.assertEqual(res.get("counts", {}).get("missingAccounting"), len(missing))
            finally:
                os.environ.pop("ACCOUNTING_DATA_PATH", None)


if __name__ == "__main__":
    unittest.main()
