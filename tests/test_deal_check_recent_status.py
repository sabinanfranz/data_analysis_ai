import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from dashboard.server import database as db


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (
            id TEXT PRIMARY KEY,
            "이름" TEXT
        );
        CREATE TABLE people (
            id TEXT PRIMARY KEY,
            organizationId TEXT,
            "이름" TEXT,
            "소속 상위 조직" TEXT,
            "팀(명함/메일서명)" TEXT
        );
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            peopleId TEXT,
            organizationId TEXT,
            "이름" TEXT,
            "상태" TEXT,
            "금액" TEXT,
            "예상 체결액" TEXT,
            "계약 체결일" TEXT,
            "생성 날짜" TEXT,
            "과정포맷" TEXT,
            "담당자" TEXT,
            "성사 가능성" TEXT,
            "수주 예정일" TEXT,
            "LOST 확정일" TEXT
        );
        CREATE TABLE memo (
            id TEXT PRIMARY KEY,
            dealId TEXT,
            text TEXT,
            createdAt TEXT
        );
        """
    )

    conn.execute('INSERT INTO organization (id, "이름") VALUES (?, ?)', ("org1", "조직1"))
    conn.execute(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직", "팀(명함/메일서명)") VALUES (?, ?, ?, ?, ?)',
        ("p1", "org1", "담당자1", "본부", "팀A"),
    )

    rows = [
        # Always keep SQL
        ("sql-keep", "p1", "org1", "SQL keep", "SQL", "0", "0", "", "2026-01-10", "오프라인", '["김솔이"]', "", "2026-03-01", ""),
        # Won with contract date inside 10 business days (today=2026-02-02) -> include
        ("won-in", "p1", "org1", "Won In", "Won", "0", "0", "2026-01-25", "2026-01-25", "오프라인", '["김솔이"]', "", "2026-02-28", ""),
        # Won with contract date outside window -> exclude
        ("won-out-contract", "p1", "org1", "Won Out Contract", "Won", "0", "0", "2026-01-15", "2026-01-15", "오프라인", '["김솔이"]', "", "2026-02-28", ""),
        # Won without contract; expected close inside window -> include
        ("won-exp-in", "p1", "org1", "Won Exp In", "Won", "0", "0", "", "2026-01-20", "오프라인", '["김솔이"]', "", "2026-01-30", ""),
        # Won without contract; expected close outside window -> exclude
        ("won-exp-out", "p1", "org1", "Won Exp Out", "Won", "0", "0", "", "2026-01-20", "오프라인", '["김솔이"]', "", "2026-01-16", ""),
        # Lost with confirmed date inside window -> include
        ("lost-in", "p1", "org1", "Lost In", "Lost", "0", "0", "", "2026-01-20", "오프라인", '["김솔이"]', "", "2026-02-28", "2026-01-29"),
        # Lost without confirmed date -> exclude
        ("lost-no-date", "p1", "org1", "Lost No Date", "Lost", "0", "0", "", "2026-01-20", "오프라인", '["김솔이"]', "", "2026-02-28", ""),
    ]
    conn.executemany(
        'INSERT INTO deal (id, peopleId, organizationId, "이름", "상태", "금액", "예상 체결액", "계약 체결일", '
        '"생성 날짜", "과정포맷", "담당자", "성사 가능성", "수주 예정일", "LOST 확정일") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


class DealCheckRecentStatusTest(unittest.TestCase):
    def test_status_window_filters(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db(db_path)
        try:
            with patch("dashboard.server.database._today_kst_date", return_value=date(2026, 2, 2)):
                items = db.get_deal_check("edu1", db_path=db_path)
            ids = {row["dealId"] for row in items}
            self.assertIn("sql-keep", ids)
            self.assertIn("won-in", ids)
            self.assertIn("won-exp-in", ids)
            self.assertIn("lost-in", ids)
            self.assertNotIn("won-out-contract", ids)
            self.assertNotIn("won-exp-out", ids)
            self.assertNotIn("lost-no-date", ids)
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
