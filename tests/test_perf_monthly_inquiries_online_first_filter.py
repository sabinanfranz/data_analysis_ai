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
            ("org-off", "오프라인", "공공기관"),
            ("org-on", "온라인", "대기업"),
            ("org-on-null", "온라인NULL", "대기업"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직") VALUES (?, ?, ?, ?)',
        [
            ("p-off", "org-off", "담당오프", "본부O"),
            ("p-on", "org-on", "담당온", "본부N"),
            ("p-on-null", "org-on-null", "담당온NULL", "본부N"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO deal (id, organizationId, peopleId, "이름", "상태", "과정포맷", "카테고리", "생성 날짜", "(온라인)최초 입과 여부", "성사 가능성", "예상 체결액", "금액", "수주 예정일", "계약 체결일", "수강시작일", "수강종료일", "담당자")
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # A) 오프라인 포맷 + online_first=false -> 포함되어야 함
            ("d-off", "org-off", "p-off", "오프딜", "Open", "출강", "재무회계", "2025-01-05", "false", "높음", 0, 0, None, None, None, None, '["담당오프"]'),
            # B) 온라인 포맷 + online_first=false -> 제외되어야 함
            ("d-on-false", "org-on", "p-on", "온딜F", "Open", "구독제(온라인)", "온라인", "2025-01-06", "false", "높음", 0, 0, None, None, None, None, '["담당온"]'),
            # C) 온라인 포맷 + online_first NULL -> 포함되어야 함
            ("d-on-null", "org-on-null", "p-on-null", "온딜N", "Open", "구독제(온라인)", "온라인", "2025-01-07", None, "높음", 0, 0, None, None, None, None, '["담당온NULL"]'),
        ],
    )
    conn.commit()
    conn.close()


class InquiryOnlineFirstFilterTest(unittest.TestCase):
    def test_online_first_only_applies_to_online_formats(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db(db_path)
        try:
            summary = db.get_perf_monthly_inquiries_summary(db_path=db_path)
            rows = summary["rows"]
            by_key = {(r["courseFormat"], r.get("categoryGroup"), r["rowKey"]): r for r in rows if r["sizeGroup"] == "대기업"}
            # 온라인 포맷 false → 제외되어 count 0
            self.assertEqual(by_key[("구독제(온라인)", "온라인", "구독제(온라인)||온라인")]["countByMonth"]["2501"], 1)
            # 위 rowKey는 온라인 상세이며 false 케이스가 제외되어 null 케이스만 포함 → 1이어야 함
            # 오프라인 포맷 false → 포함되어야 함
            by_key_all = {(r["courseFormat"], r.get("categoryGroup"), r["rowKey"], r["sizeGroup"]): r for r in rows}
            # 오프라인 포맷 false → 포함되어야 함
            off_row = by_key_all[("출강", "직무별교육", "출강||직무별교육", "공공기관")]
            self.assertEqual(off_row["countByMonth"]["2501"], 1)

            meta = summary["meta"]["debug"]["excluded"]
            self.assertEqual(meta["online_first_false"], 1)  # only online false excluded
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
