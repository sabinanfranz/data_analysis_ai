import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.server import database as db


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (id TEXT, "이름" TEXT, "기업 규모" TEXT);
        CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT, "팀(명함/메일서명)" TEXT, "직급(명함/메일서명)" TEXT, "담당 교육 영역" TEXT);
        CREATE TABLE deal (id TEXT, peopleId TEXT, organizationId TEXT, "이름" TEXT, "상태" TEXT, "금액" TEXT, "계약 체결일" TEXT, "담당자" TEXT);
        """
    )
    conn.execute('INSERT INTO organization VALUES ("org-1","회사","대기업")')
    conn.execute(
        'INSERT INTO people VALUES ("p-1","org-1","담당자A","부문A","팀A","직급","영역")'
    )
    conn.execute(
        'INSERT INTO people VALUES ("p-2","org-1","담당자B","부문A","팀B","직급","영역")'
    )
    deals = [
        (
            "d-1",
            "p-1",
            "org-1",
            "딜1",
            "Won",
            "100",
            "2025-01-10",
            json.dumps({"name": "오너1"}),
        ),
        (
            "d-2",
            "p-2",
            "org-1",
            "딜2",
            "Won",
            "200",
            "2025-03-01",
            json.dumps({"name": "오너2"}),
        ),
        (
            "d-3",
            "p-1",
            "org-1",
            "딜3",
            "Won",
            "50",
            "2024-12-31",
            json.dumps({"name": "오너3"}),
        ),
    ]
    conn.executemany(
        'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?)',
        deals,
    )
    conn.commit()
    conn.close()


class WonSummaryOwnersTest(unittest.TestCase):
    def test_won_summary_includes_owners2025(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            _build_db(db_path)

            items = db.get_won_summary_by_upper_org("org-1", db_path=db_path)
            self.assertEqual(len(items), 1)
            row = items[0]
            self.assertEqual(sorted(row["owners2025"]), ["오너1", "오너2"])
            # owners (all years) should include 2024 오너도 포함
            self.assertIn("오너3", row["owners"])


if __name__ == "__main__":
    unittest.main()
