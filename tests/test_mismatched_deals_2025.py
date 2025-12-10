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
            "이름" TEXT,
            "기업 규모" TEXT
        );
        CREATE TABLE people (
            id TEXT PRIMARY KEY,
            organizationId TEXT,
            "이름" TEXT
        );
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            peopleId TEXT,
            organizationId TEXT,
            "이름" TEXT,
            "상태" TEXT,
            "계약 체결일" TEXT,
            "금액" REAL
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES (?, ?, ?)',
        [
            ("org-a", "Alpha Corp", "대기업"),
            ("org-b", "Beta Corp", "대기업"),
            ("org-c", "Gamma Corp", "중견기업"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름") VALUES (?, ?, ?)',
        [
            ("p-1", "org-b", "Person One"),   # mismatch target
            ("p-2", "org-a", "Person Two"),   # matching org
            ("p-3", "org-b", "Person Three"), # mismatch with mid-size deal org
            ("p-4", None, "No Org"),          # should be ignored
        ],
    )
    conn.executemany(
        'INSERT INTO deal (id, peopleId, organizationId, "이름", "상태", "계약 체결일", "금액") '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        [
            ("d-1", "p-1", "org-a", "Mismatch Deal", "Won", "2025-02-01", 100.0),  # mismatch, 대기업
            ("d-2", "p-2", "org-a", "Matching Deal", "Won", "2025-03-01", 50.0),   # same org, excluded
            ("d-3", "p-1", "org-a", "Old Year Deal", "Won", "2024-01-01", 70.0),   # wrong year
            ("d-4", "p-3", "org-c", "Mid Mismatch", "Won", "2025-04-01", 30.0),    # mid-size org, included when size=전체
            ("d-5", "p-1", "org-a", "Lost Deal", "Lost", "2025-05-01", 999.0),     # not Won
        ],
    )
    conn.commit()
    conn.close()


class MismatchedDeals2025Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        _init_db(Path(self.tmp.name))

    def tearDown(self) -> None:
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_mismatches_filtered_by_size(self):
        results = db.get_mismatched_deals(size="대기업", db_path=Path(self.tmp.name))
        ids = {row["dealId"] for row in results}
        self.assertEqual(ids, {"d-1", "d-3", "d-5"})

    def test_includes_other_sizes_when_requested(self):
        results = db.get_mismatched_deals(size="전체", db_path=Path(self.tmp.name))
        ids = {row["dealId"] for row in results}
        self.assertIn("d-1", ids)
        self.assertIn("d-4", ids)  # mid-size org is included when not filtering by size
        self.assertNotIn("d-2", ids)  # matching org
        # now we include other years/status; d-3 matches size filter above, so it will appear there


if __name__ == "__main__":
    unittest.main()
