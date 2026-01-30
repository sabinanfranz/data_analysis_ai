import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
import types

# Stub openpyxl to avoid heavy dependency during import.
if "openpyxl" not in sys.modules:
    sys.modules["openpyxl"] = types.SimpleNamespace(load_workbook=lambda *args, **kwargs: None, Workbook=None)

from dashboard.server import database as db


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE deal (
          id TEXT,
          organizationId TEXT,
          peopleId TEXT,
          "이름" TEXT,
          "과정포맷" TEXT,
          "카테고리" TEXT,
          "상태" TEXT,
          "성사 가능성" TEXT,
          "예상 체결액" TEXT,
          "금액" TEXT,
          "수주 예정일" TEXT,
          "계약 체결일" TEXT,
          "수강시작일" TEXT,
          "수강종료일" TEXT,
          "담당자" TEXT,
          "생성 날짜" TEXT,
          "코스 ID" TEXT
        );
        CREATE TABLE people (
          id TEXT,
          organizationId TEXT,
          "이름" TEXT,
          "소속 상위 조직" TEXT,
          "팀(명함/메일서명)" TEXT,
          "직급(명함/메일서명)" TEXT,
          "담당 교육 영역" TEXT
        );
        CREATE TABLE organization (
          id TEXT,
          "이름" TEXT,
          "기업 규모" TEXT
        );
        """
    )
    conn.execute(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES ("org1", "테스트조직", "대기업")'
    )
    conn.execute(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직", "팀(명함/메일서명)", "직급(명함/메일서명)", "담당 교육 영역") '
        'VALUES ("p1", "org1", "강지선", "HQ", "1팀", "팀장", "AI")'
    )
    deals = [
        (
            "deal_dot",
            "org1",
            "p1",
            "DOT 날짜 딜",
            "구독제(온라인)",
            "생성형AI",
            "Open",
            "확정",
            "0",
            "",
            "",
            "",
            "",
            "",
            '["강지선"]',
            "2026.01.10 09:30:00",
            "COURSE-1",
        ),
        (
            "deal_utc_boundary",
            "org1",
            "p1",
            "UTC 경계 딜",
            "구독제(온라인)",
            "생성형AI",
            "Open",
            "확정",
            "0",
            "",
            "",
            "",
            "",
            "",
            '["강지선"]',
            "2025-12-31T15:00:00Z",
            "COURSE-2",
        ),
    ]
    conn.executemany(
        'INSERT INTO deal (id, organizationId, peopleId, "이름", "과정포맷", "카테고리", "상태", "성사 가능성", "예상 체결액", "금액", "수주 예정일", "계약 체결일", "수강시작일", "수강종료일", "담당자", "생성 날짜", "코스 ID") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        deals,
    )
    conn.commit()
    conn.close()


class TestMonthlyInquiriesDateParsing(unittest.TestCase):
    def test_dot_and_utc_dates_count_in_2601(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            _build_db(Path(tmp.name))
            res = db.get_perf_monthly_inquiries_summary(db_path=Path(tmp.name), debug=True)
            target_row = next(
                r
                for r in res["rows"]
                if r["level"] == 1 and r["sizeGroup"] == "대기업" and r["courseFormat"] == "구독제(온라인)"
            )
            self.assertEqual(target_row["countByMonth"]["2601"], 2)


if __name__ == "__main__":
    unittest.main()
