import unittest
from unittest.mock import patch

from dashboard.server import database as db


class CloseRateSummaryMetricsTest(unittest.TestCase):
    def test_summary_contains_total_and_close_rate(self) -> None:
        fake_payload = {
            "rows": [
                {
                    "month": "2501",
                    "size_group": "대기업",
                    "course_group": "구독제(온라인)",
                    "prob_bucket": "confirmed",
                    "owner_names": ["김솔이"],
                    "org_id": "org1",
                },
                {
                    "month": "2501",
                    "size_group": "대기업",
                    "course_group": "구독제(온라인)",
                    "prob_bucket": "high",
                    "owner_names": ["김솔이"],
                    "org_id": "org1",
                },
            ],
            "existing_org_ids": {"org1"},
            "snapshot_version": "db_mtime:1",
            "meta_debug": {"total_loaded": 2},
        }

        with patch.object(db, "_load_perf_monthly_close_rate_data", return_value=fake_payload):
            res = db.get_perf_monthly_close_rate_summary(
                from_month="2025-01", to_month="2025-12", cust="all", scope="all"
            )

        rows = res["rows"]
        row_keys = {r["rowKey"] for r in rows if r.get("level") == 2}
        expected_suffixes = {"total", "confirmed", "high", "low", "lost", "close_rate"}
        for suf in expected_suffixes:
            key = f"구독제(온라인)||{suf}"
            assert key in row_keys, f"missing rowKey {key}"

        # close_rate should be (2/2)*100=100.0
        rate_row = next(r for r in rows if r.get("rowKey") == "구독제(온라인)||close_rate")
        assert rate_row["countsByMonth"]["2501"] == 100.0


if __name__ == "__main__":
    unittest.main()
