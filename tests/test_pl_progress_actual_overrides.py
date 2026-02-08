import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.server import database as db


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE deal (
            id TEXT PRIMARY KEY
        );
        """
    )
    conn.commit()
    conn.close()


class PlProgressActualOverridesTest(unittest.TestCase):
    def setUp(self) -> None:
        db._PL_PROGRESS_ACTUAL_FILE_CACHE.clear()

    def test_actual_overrides_parsing_and_year_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "sample.db"
            _init_db(db_path)

            actual_path = tmp_path / "actual.txt"
            with actual_path.open("w", encoding="utf-8") as f:
                json.dump(
                    [
                        {
                            "category": "총매출",
                            "data": {
                                "2601": {"A": 6.65},
                                "2602": {"A": "7.10"},
                                "2501": {"A": 3.0},
                            },
                        },
                        {
                            "category": "└ 온라인 매출",
                            "data": {
                                "2601": {"A": "-"},
                            },
                        },
                        {
                            "category": "OP",
                            "data": {
                                "2601": {"A": -2.9},
                            },
                        },
                        {
                            "category": "미매핑 항목",
                            "data": {
                                "2601": {"A": 1.23},
                            },
                        },
                    ],
                    f,
                    ensure_ascii=False,
                )

            result = db.get_pl_progress_actual_overrides(
                year=2026,
                db_path=db_path,
                resource_path=actual_path,
            )

            self.assertEqual(result["year"], 2026)
            self.assertEqual(result["months"], ["2601", "2602"])
            self.assertEqual(result["overrides"]["REV_TOTAL"]["2601"], 6.65)
            self.assertEqual(result["overrides"]["REV_TOTAL"]["2602"], 7.1)
            self.assertNotIn("2501", result["overrides"]["REV_TOTAL"])
            self.assertIsNone(result["overrides"]["REV_ONLINE"]["2601"])
            self.assertEqual(result["overrides"]["OP"]["2601"], -2.9)
            self.assertEqual(result["meta"]["rowCount"], 3)
            self.assertEqual(result["meta"]["monthCount"], 2)
            self.assertEqual(result["meta"]["snapshot_version"], f"db_mtime:{int(db_path.stat().st_mtime)}")
            self.assertIn("미매핑 항목", result["meta"]["unmapped_categories"])

    def test_missing_actual_resource_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "sample.db"
            _init_db(db_path)
            missing_path = tmp_path / "missing_actual.txt"
            with self.assertRaises(FileNotFoundError):
                db.get_pl_progress_actual_overrides(
                    year=2026,
                    db_path=db_path,
                    resource_path=missing_path,
                )


if __name__ == "__main__":
    unittest.main()
