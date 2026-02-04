import sqlite3

from dashboard.server.database import _row_get


def test_row_get_with_sqlite_row_returns_value():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE t(createdAt TEXT, other TEXT)")
    conn.execute("INSERT INTO t VALUES (?, ?)", ("2023-01-01T00:00:00Z", "x"))
    row = conn.execute("SELECT createdAt, other FROM t LIMIT 1").fetchone()

    assert isinstance(row, sqlite3.Row)
    assert _row_get(row, "createdAt") == "2023-01-01T00:00:00Z"
    assert _row_get(row, "missing", "default") == "default"
