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
          "담당자" TEXT,
          "상태" TEXT,
          "성사 가능성" TEXT,
          "금액" TEXT,
          "예상 체결액" TEXT,
          "수주 예정일" TEXT,
          "계약 체결일" TEXT,
          "수강시작일" TEXT,
          "수강종료일" TEXT,
          "과정포맷" TEXT,
          "카테고리" TEXT,
          "코스 ID" TEXT,
          "(온라인)입과 주기" TEXT,
          "(온라인)입과 첫 회차" TEXT,
          "강사 이름1" TEXT,
          "강사비1" TEXT,
          "제안서 작성 여부" TEXT,
          "업로드 제안서명" TEXT,
          "생성 날짜" TEXT
        );
        CREATE TABLE people (
          id TEXT,
          "이름" TEXT,
          "소속 상위 조직" TEXT,
          "팀(명함/메일서명)" TEXT,
          "직급(명함/메일서명)" TEXT,
          "담당 교육 영역" TEXT,
          organizationId TEXT
        );
        CREATE TABLE organization (
          id TEXT,
          "이름" TEXT,
          "기업 규모" TEXT
        );
        """
    )
    conn.execute(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES ("org1", "테스트기업", "대기업")'
    )
    conn.execute(
        'INSERT INTO people (id, "이름", "소속 상위 조직", "팀(명함/메일서명)", "직급(명함/메일서명)", "담당 교육 영역", organizationId) '
        'VALUES ("p1", "강지선", "HQ", "1팀", "팀장", "AI", "org1")'
    )
    deals = [
        (
            "deal_old",
            "org1",
            "p1",
            "이전딜",
            '["강지선"]',
            "Won",
            "확정",
            "",  # 금액 없음 -> R2 후보
            "0",
            "2024-09-30",
            "2024-09-30",
            "2024-10-05",
            "2024-10-10",
            "출강",
            "기타",
            "COURSE-OLD",
            "",
            "",
            "홍길동",
            "",
            "",
            "",
            "2024.09.30 10:00:00",
        ),
        (
            "deal_new",
            "org1",
            "p1",
            "신규딜",
            '["강지선"]',
            "Won",
            "확정",
            "",  # 금액 없음 -> R2 발생
            "0",
            "2024-10-10",
            "2024-10-10",
            "2024-11-01",
            "2024-11-10",
            "출강",
            "기타",
            "COURSE-NEW",
            "",
            "",
            "홍길동",
            "",
            "",
            "",
            "2024-10-02T00:30:00Z",
        ),
    ]
    conn.executemany(
        'INSERT INTO deal (id, organizationId, peopleId, "이름", "담당자", "상태", "성사 가능성", "금액", "예상 체결액", "수주 예정일", "계약 체결일", "수강시작일", "수강종료일", "과정포맷", "카테고리", "코스 ID", "(온라인)입과 주기", "(온라인)입과 첫 회차", "강사 이름1", "강사비1", "제안서 작성 여부", "업로드 제안서명", "생성 날짜") '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        deals,
    )
    conn.commit()
    conn.close()


class TestQcSinceFilter(unittest.TestCase):
    def test_pre_since_date_is_excluded(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            _build_db(Path(tmp.name))
            res = db.get_qc_deal_errors_summary(team="all", db_path=Path(tmp.name))
            self.assertEqual(res["meta"]["dq"]["excluded_before_since"], 1)
            # Only the post-cutoff deal should remain.
            total_deals_included = sum(p["dealCount"] for p in res["people"])
            self.assertEqual(total_deals_included, 1)


if __name__ == "__main__":
    unittest.main()
