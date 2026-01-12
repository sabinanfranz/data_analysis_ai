import json
import sqlite3
import tempfile
from pathlib import Path

from dashboard.server import database as db


def _init_minimal_db(path: Path) -> None:
    """Create minimal schema; no deals needed for T-only checks."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (id TEXT PRIMARY KEY, "이름" TEXT);
        CREATE TABLE people (id TEXT PRIMARY KEY, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT);
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            peopleId TEXT,
            organizationId TEXT,
            "이름" TEXT,
            "상태" TEXT,
            "금액" REAL,
            "예상 체결액" REAL,
            "계약 체결일" TEXT,
            "수주 예정일" TEXT,
            "수강시작일" TEXT,
            "수강종료일" TEXT,
            "성사 가능성" TEXT,
            "과정포맷" TEXT,
            "담당자" TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def test_hardcoded_targets_applied(tmp_path):
    """
    하드코딩된 PL_2026_TARGET_FULL 값이 요약 응답에 그대로 반영되는지 확인.
    """
    db_path = tmp_path / "db.sqlite"
    _init_minimal_db(db_path)
    db._PL_PROGRESS_SUMMARY_CACHE.clear()
    summary = db.get_pl_progress_summary(db_path=db_path)
    rows = {row["key"]: row for row in summary["rows"]}
    op_row = rows["OP"]
    rev_row = rows["REV_TOTAL"]
    labor_row = rows["COST_FIXED_LABOR"]
    # 연간 값이 하드코딩된 리소스 값과 동일한지 확인
    assert op_row["values"][f"Y{summary['year']}_T"] == 20.9
    assert rev_row["values"][f"Y{summary['year']}_T"] == 210.0
    assert labor_row["values"][f"Y{summary['year']}_T"] == 76.0
