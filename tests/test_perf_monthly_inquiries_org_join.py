import sqlite3
import tempfile
import unittest
from pathlib import Path

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
            "이름" TEXT,
            "소속 상위 조직" TEXT
        );
        CREATE TABLE deal (
            id TEXT PRIMARY KEY,
            organizationId TEXT,
            peopleId TEXT,
            "이름" TEXT,
            "상태" TEXT,
            "과정포맷" TEXT,
            "카테고리" TEXT,
            "생성 날짜" TEXT,
            "(온라인)최초 입과 여부" TEXT,
            "성사 가능성" TEXT,
            "예상 체결액" REAL,
            "금액" REAL,
            "수주 예정일" TEXT,
            "계약 체결일" TEXT,
            "수강시작일" TEXT,
            "수강종료일" TEXT,
            "담당자" TEXT
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES (?, ?, ?)',
        [
            ("ORG_UNIV", "대학조직", "대학교"),
            ("ORG_PUB", "공공조직", "공공기관"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직") VALUES (?, ?, ?, ?)',
        [
            ("P_UNIV", "ORG_UNIV", "담당대학", "본부U"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO deal (id, organizationId, peopleId, "이름", "상태", "과정포맷", "카테고리", "생성 날짜", "(온라인)최초 입과 여부", "성사 가능성", "예상 체결액", "금액", "수주 예정일", "계약 체결일", "수강시작일", "수강종료일", "담당자")
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # A) deal org NULL, people org = ORG_UNIV (대학교) → 대학교로 집계되어야 함
            ("D_UNIV", None, "P_UNIV", "대학딜", "Open", "출강", "재무회계", "2025-02-01", None, "높음", 0, 0, None, None, None, None, '["담당대학"]'),
            # B) deal org = ORG_PUB (공공기관) → 공공기관으로 집계되어야 함
            ("D_PUB", "ORG_PUB", None, "공공딜", "Open", "출강", "재무회계", "2025-02-02", None, "높음", 0, 0, None, None, None, None, '["담당공공"]'),
        ],
    )
    conn.commit()
    conn.close()


class InquiryOrgJoinTest(unittest.TestCase):
    def test_org_join_and_size_pass_through(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db(db_path)
        try:
            summary = db.get_perf_monthly_inquiries_summary(db_path=db_path)
            rows = summary["rows"]
            # 대학교 카테고리 상세 rowKey: 출강||직무별교육 (재무회계 → 직무별교육)
            rows_map = {
                (r["sizeGroup"], r["courseFormat"], r.get("categoryGroup"), r["rowKey"]): r for r in rows
            }
            univ_row = rows_map[("대학교", "출강", "직무별교육", "출강||직무별교육")]
            pub_row = rows_map[("공공기관", "출강", "직무별교육", "출강||직무별교육")]
            self.assertEqual(univ_row["countByMonth"]["2502"], 1)
            self.assertEqual(pub_row["countByMonth"]["2502"], 1)

            debug = summary["meta"]["debug"]
            self.assertGreaterEqual(debug["join_source"]["people_org_used"], 1)
            self.assertGreaterEqual(debug["join_source"]["deal_org_used"], 1)
            size_raw_counts = debug["value_counts"]["size_raw_counts"]
            self.assertEqual(size_raw_counts.get("대학교"), 1)
            self.assertEqual(size_raw_counts.get("공공기관"), 1)
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
