import sqlite3
import tempfile
from pathlib import Path
import unittest

from dashboard.server import database as db


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (
            id TEXT PRIMARY KEY,
            "기업 규모" TEXT
        );
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            organizationId TEXT,
            "상태" TEXT,
            "계약 체결일" TEXT,
            "금액" REAL
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "기업 규모") VALUES (?, ?)',
        [
            ("org-1", "대기업"),
            ("org-2", "중견기업"),
            ("org-3", None),
        ],
    )
    conn.executemany(
        'INSERT INTO deal (id, organizationId, "상태", "계약 체결일", "금액") VALUES (?, ?, ?, ?, ?)',
        [
            ("d-1", "org-1", "Won", "2023-01-02", 100.0),
            ("d-2", "org-1", "Won", "2024-05-10", 200.0),
            ("d-3", "org-2", "Won", "2025-03-01", 300.0),
            ("d-4", "org-2", "Lost", "2024-03-01", 999.0),  # should be ignored
            ("d-5", "org-3", "Won", "2025-12-31", 400.0),  # size missing -> 미입력
            ("d-6", "org-3", "Won", "2025-01-01", 50.0),
            ("d-7", "org-1", "Won", "2022-12-31", 500.0),  # year out of scope
        ],
    )
    conn.commit()
    conn.close()


class WonTotalsBySizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        _init_db(Path(self.tmp.name))

    def tearDown(self) -> None:
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_totals_grouped_by_size_and_year(self):
        results = db.get_won_totals_by_size(db_path=Path(self.tmp.name))
        lookup = {row["size"]: row for row in results}

        self.assertIn("대기업", lookup)
        self.assertIn("중견기업", lookup)
        self.assertIn("미입력", lookup)

        self.assertEqual(lookup["대기업"]["won2023"], 100.0)
        self.assertEqual(lookup["대기업"]["won2024"], 200.0)
        self.assertEqual(lookup["대기업"]["won2025"], 0.0)

        self.assertEqual(lookup["중견기업"]["won2023"], 0.0)
        self.assertEqual(lookup["중견기업"]["won2024"], 0.0)
        self.assertEqual(lookup["중견기업"]["won2025"], 300.0)

        self.assertEqual(lookup["미입력"]["won2023"], 0.0)
        self.assertEqual(lookup["미입력"]["won2024"], 0.0)
        self.assertEqual(lookup["미입력"]["won2025"], 450.0)


if __name__ == "__main__":
    unittest.main()
