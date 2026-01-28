import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.server import database as db


def _init_inquiry_db(path: Path) -> None:
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
            peopleId TEXT,
            organizationId TEXT,
            "이름" TEXT,
            "상태" TEXT,
            "과정포맷" TEXT,
            "카테고리" TEXT,
            "생성 날짜" TEXT,
            "(온라인)최초 입과 여부" TEXT,
            "담당자" TEXT,
            "예상 체결액" REAL,
            "금액" REAL,
            "수주 예정일" TEXT,
            "계약 체결일" TEXT,
            "수강시작일" TEXT,
            "수강종료일" TEXT,
            "성사 가능성" TEXT,
            "코스 ID" TEXT
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES (?, ?, ?)',
        [
            ("org-1", "오가닉", "대기업"),
            ("org-2", "파크", "중견기업"),
            ("org-3", "미기재", None),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직") VALUES (?, ?, ?, ?)',
        [
            ("p-1", "org-1", "담당자A", "본부A"),
            ("p-2", "org-2", "담당자B", "본부B"),
            ("p-3", "org-3", "담당자C", None),
        ],
    )
    conn.executemany(
        """
        INSERT INTO deal (
            id, peopleId, organizationId, "이름", "상태", "과정포맷", "카테고리", "생성 날짜",
            "(온라인)최초 입과 여부", "담당자", "예상 체결액", "금액", "수주 예정일",
            "계약 체결일", "수강시작일", "수강종료일", "성사 가능성", "코스 ID"
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # 포함: 대기업 / 구독제(온라인) / 온라인, edu1 담당자
            (
                "d-1",
                "p-1",
                "org-1",
                "딜1",
                "Open",
                "구독제(온라인)",
                "온라인",
                "2025-01-05",
                "TRUE",
                '["김솔이"]',
                0.0,
                0.0,
                "2025-02-10",
                None,
                None,
                None,
                "높음",
                "COURSE-1",
            ),
            # 제외: Convert 상태
            (
                "d-2",
                "p-1",
                "org-1",
                "딜-Convert",
                "Convert",
                "구독제(온라인)",
                "온라인",
                "2025-02-01",
                "TRUE",
                '["김솔이"]',
                0.0,
                0.0,
                None,
                None,
                None,
                None,
                "확정",
                "COURSE-2",
            ),
            # 제외: online_first FALSE
            (
                "d-3",
                "p-1",
                "org-1",
                "딜-false",
                "Open",
                "출강",
                "재무회계",
                "2025-03-02",
                "FALSE",
                '["김솔이"]',
                0.0,
                0.0,
                None,
                None,
                None,
                None,
                "높음",
                "COURSE-3",
            ),
            # 포함: 중견 / 출강 / 직무별교육, edu2 담당자
            (
                "d-4",
                "p-2",
                "org-2",
                "딜-edu2",
                "Won",
                "출강",
                "재무회계",
                "2025-01-20",
                "TRUE",
                '["강진우"]',
                100.0,
                50.0,
                "2025-02-20",
                "2025-02-10",
                "2025-03-01",
                "2025-03-10",
                "확정",
                "COURSE-4",
            ),
            # 포함: 미기재 / 미기재 / 기타
            (
                "d-5",
                "p-3",
                "org-3",
                "딜-blank",
                "Open",
                None,
                None,
                "2026-12-05",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "COURSE-5",
            ),
        ],
    )
    conn.commit()
    conn.close()


class PerfMonthlyInquiriesTest(unittest.TestCase):
    def test_summary_rows_and_exclusions(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_inquiry_db(db_path)
        try:
            summary = db.get_perf_monthly_inquiries_summary(db_path=db_path)
            self.assertEqual(summary["months"][0], "2501")
            self.assertEqual(summary["months"][-1], "2612")
            self.assertEqual(len(summary["rows"]), 728)

            row_map = {(r["sizeGroup"], r.get("courseFormat"), r.get("categoryGroup"), r["rowKey"]): r for r in summary["rows"]}
            # 포함 건수 확인
            self.assertEqual(row_map[("대기업", "구독제(온라인)", "온라인", "구독제(온라인)||온라인")]["countByMonth"]["2501"], 1)
            self.assertEqual(row_map[("중견기업", "출강", "직무별교육", "출강||직무별교육")]["countByMonth"]["2501"], 1)
            self.assertEqual(row_map[("미기재", "미기재", "미기재", "미기재||미기재")]["countByMonth"]["2612"], 1)
            # Convert / online_first FALSE 제외
            self.assertEqual(row_map[("대기업", "구독제(온라인)", "온라인", "구독제(온라인)||온라인")]["countByMonth"]["2502"], 0)
            self.assertEqual(row_map[("대기업", "출강", "직무별교육", "출강||직무별교육")]["countByMonth"]["2503"], 1)
            # 롤업 확인 (format-level only)
            self.assertEqual(row_map[("중견기업", "출강", None, "출강||__ALL__")]["countByMonth"]["2501"], 1)

            # 팀 필터 edu2: edu1 담당 건은 제외, edu2는 포함
            summary_edu2 = db.get_perf_monthly_inquiries_summary(db_path=db_path, team="edu2")
            row_map2 = {(r["sizeGroup"], r["courseFormat"], r["categoryGroup"]): r for r in summary_edu2["rows"]}
            self.assertEqual(row_map2[("대기업", "구독제(온라인)", "온라인")]["countByMonth"]["2501"], 0)
            self.assertEqual(row_map2[("중견기업", "출강", "직무별교육")]["countByMonth"]["2501"], 1)
        finally:
            db_path.unlink(missing_ok=True)

    def test_deals_endpoint_fields(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_inquiry_db(db_path)
        try:
            deals = db.get_perf_monthly_inquiries_deals(
                segment="중견기업",
                row="출강||직무별교육",
                month="2501",
                team="edu2",
                db_path=db_path,
            )
            self.assertEqual(deals["dealCount"], 1)
            item = deals["items"][0]
            self.assertEqual(item["dealId"], "d-4")
            self.assertEqual(item["courseFormat"], "출강")
            self.assertIn("category", item)
            self.assertEqual(item["contractDate"], "2025-02-10")
            self.assertEqual(item["amount"], 50.0)
            self.assertEqual(item["expectedAmount"], 100.0)
            self.assertEqual(item["upperOrg"], "본부B")

            # 미기재 카테고리 필터
            deals_blank = db.get_perf_monthly_inquiries_deals(
                segment="미기재",
                row="미기재||미기재",
                month="2612",
                db_path=db_path,
            )
            self.assertEqual(deals_blank["dealCount"], 1)
            self.assertEqual(deals_blank["items"][0]["dealId"], "d-5")
            self.assertIn("category", deals_blank["items"][0])
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
