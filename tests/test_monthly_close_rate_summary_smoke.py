import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Stub openpyxl to avoid heavy dependency when importing dashboard.server modules
sys.modules.setdefault("openpyxl", SimpleNamespace())
sys.modules.setdefault("openpyxl.styles", SimpleNamespace(Font=lambda *a, **k: None, Alignment=lambda *a, **k: None))

from dashboard.server import database as db


class CloseRateSummarySmokeTest(unittest.TestCase):
    def test_summary_no_keyerror_with_mock_payload(self) -> None:
        fake_payload = {
            "rows": [
                {
                    "month": "2501",
                    "size_group": "대기업",
                    "course_group": "구독제(온라인)",
                    "prob_bucket": "confirmed",
                    "owner_names": ["김솔이"],
                    "org_id": "org1",
                }
            ],
            "existing_org_ids": {"org1"},
            "snapshot_version": "db_mtime:1",
            "meta_debug": {"total_loaded": 1},
        }

        with patch.object(db, "_load_perf_monthly_close_rate_data", return_value=fake_payload):
            res = db.get_perf_monthly_close_rate_summary(
                from_month="2025-01", to_month="2025-12", cust="all", scope="all"
            )
        self.assertIn("months", res)
        self.assertIn("rows", res)
        self.assertEqual(res["months"][0], "2501")
        # should not raise and should include meta
        self.assertIn("meta", res)


if __name__ == "__main__":
    unittest.main()
