import unittest
import sys
import types
from datetime import date

# Stub openpyxl to avoid heavy dependency when importing database module.
if "openpyxl" not in sys.modules:
    sys.modules["openpyxl"] = types.SimpleNamespace(load_workbook=lambda *args, **kwargs: None, Workbook=None)

from dashboard.server import database as db


class DateKstNormalizationTest(unittest.TestCase):
    def test_z_timestamp_same_day(self):
        src = "2023-08-09T05:47:38.949Z"
        self.assertEqual(db._date_only(src), "2023-08-09")
        self.assertEqual(db._month_key_from_text(src), "2308")
        self.assertEqual(db._parse_date(src), date(2023, 8, 9))

    def test_z_timestamp_rollover_to_next_day_kst(self):
        # 2025-12-31 15:00 UTC == 2026-01-01 00:00 KST
        src = "2025-12-31T15:00:00.000Z"
        self.assertEqual(db._date_only(src), "2026-01-01")
        self.assertEqual(db._month_key_from_text(src), "2601")
        self.assertEqual(db._parse_date(src), date(2026, 1, 1))

    def test_plain_date_and_month(self):
        self.assertEqual(db._date_only("2026-01-01"), "2026-01-01")
        self.assertEqual(db._month_key_from_text("2026-01-01"), "2601")
        self.assertEqual(db._month_key_from_text("2026-01"), "2601")


if __name__ == "__main__":
    unittest.main()
