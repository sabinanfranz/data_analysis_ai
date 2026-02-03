import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Stub openpyxl to avoid requiring the heavy dependency for these lightweight contract tests
sys.modules.setdefault("openpyxl", SimpleNamespace())
sys.modules.setdefault("openpyxl.styles", SimpleNamespace(Font=lambda *a, **k: None, Alignment=lambda *a, **k: None))

from dashboard.server import database as db


class CloseRateContractTest(unittest.TestCase):
    def test_summary_counts_cover_all_months_and_total_row(self) -> None:
        fake_payload = {
            "rows": [
                {
                    "month": "2501",
                    "size_group": "대기업",
                    "course_group": "구독제(온라인)",
                    "prob_bucket": "confirmed",
                    "owner_names": ["담당자"],
                    "org_id": "org1",
                }
            ],
            "existing_org_ids": set(),
            "snapshot_version": "db_mtime:1",
            "meta_debug": {"total_loaded": 1},
        }
        with patch.object(db, "_load_perf_monthly_close_rate_data", return_value=fake_payload):
            res = db.get_perf_monthly_close_rate_summary(
                from_month="2025-01", to_month="2025-02", cust="all", scope="all"
            )

        expected_months = ["2501", "2502"]
        self.assertEqual(res["months"], expected_months)

        rows = [r for r in res["rows"] if r.get("segment") == "대기업"]
        row_map = {r["rowKey"]: r for r in rows}

        total_row = row_map.get("구독제(온라인)||total")
        self.assertIsNotNone(total_row, "total row should exist for each course/size")
        self.assertEqual(set(total_row["countsByMonth"].keys()), set(expected_months))
        self.assertEqual(total_row["countsByMonth"]["2501"], 1)
        self.assertEqual(total_row["countsByMonth"]["2502"], 0)

        close_rate_row = row_map.get("구독제(온라인)||close_rate")
        self.assertIsNotNone(close_rate_row, "close_rate row should exist")
        self.assertEqual(set(close_rate_row["countsByMonth"].keys()), set(expected_months))
        self.assertEqual(close_rate_row["countsByMonth"]["2501"], 100.0)
        self.assertEqual(close_rate_row["countsByMonth"]["2502"], 0.0)


if __name__ == "__main__":
    unittest.main()
