import sqlite3
from pathlib import Path

from dashboard.server import database as db


def test_compute_existing_org_ids_handles_sqlite_row(tmp_path: Path) -> None:
    # Prepare minimal DB with required columns
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE people (
            id TEXT PRIMARY KEY,
            organizationId TEXT
        );
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            peopleId TEXT,
            organizationId TEXT,
            "상태" TEXT,
            "코스 ID" TEXT,
            "수강시작일" TEXT,
            "수강종료일" TEXT,
            "계약 체결일" TEXT,
            "금액" REAL
        );
        """
    )
    conn.execute('INSERT INTO people (id, organizationId) VALUES (?, ?)', ("p1", "orgA"))
    conn.execute(
        'INSERT INTO deal (id, peopleId, organizationId, "상태", "코스 ID", "수강시작일", "수강종료일", "계약 체결일", "금액") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "d1",
            "p1",
            "orgA",
            "Won",
            "C-001",
            "2025-01-10",
            "2025-02-10",
            "2025-01-15",
            123.0,
        ),
    )
    conn.commit()
    conn.close()

    result = db._compute_existing_org_ids_for_2025(db_path)
    assert isinstance(result, set)
    assert "orgA" in result
