import unittest
from datetime import datetime, timezone, timedelta

from dashboard.server.date_kst import kst_date_only, kst_year, kst_ym, kst_yymm


class TestKstDateOnly(unittest.TestCase):
    def test_utc_boundary_crosses_to_next_day(self):
        src = "2025-12-31T15:00:00.000Z"
        self.assertEqual(kst_date_only(src), "2026-01-01")

    def test_iso_with_z_same_day(self):
        src = "2023-08-09T05:47:38.949Z"
        self.assertEqual(kst_date_only(src), "2023-08-09")

    def test_date_only(self):
        self.assertEqual(kst_date_only("2026-01-01"), "2026-01-01")

    def test_compact_digits(self):
        self.assertEqual(kst_date_only("20260110"), "2026-01-10")

    def test_slash_single_digit(self):
        self.assertEqual(kst_date_only("2026/1/5"), "2026-01-05")

    def test_datetime_object_with_tz(self):
        src = datetime(2025, 12, 31, 15, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(kst_date_only(src), "2026-01-01")

    def test_empty_values(self):
        for v in (None, "", "   "):
            self.assertEqual(kst_date_only(v), "")


class TestKstHelpers(unittest.TestCase):
    def test_kst_year(self):
        self.assertEqual(kst_year("2026-02-03"), "2026")
        self.assertIsNone(kst_year(""))

    def test_kst_ym(self):
        self.assertEqual(kst_ym("2026-02-03"), "2026-02")
        self.assertIsNone(kst_ym("bad"))

    def test_kst_yymm(self):
        self.assertEqual(kst_yymm("2026-02-03"), "2602")
        self.assertIsNone(kst_yymm(None))


if __name__ == "__main__":
    unittest.main()
