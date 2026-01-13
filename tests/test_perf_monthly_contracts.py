import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard.server import database as db


def _init_db(path: Path, with_course_id: bool = True) -> None:
    conn = sqlite3.connect(path)
    course_col = '"코스 ID" TEXT,' if with_course_id else ""
    conn.executescript(
        f"""
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
            "금액" REAL,
            "예상 체결액" REAL,
            "계약 체결일" TEXT,
            "수주 예정일" TEXT,
            "수강시작일" TEXT,
            "수강종료일" TEXT,
            "성사 가능성" TEXT,
            "과정포맷" TEXT,
            {course_col if course_col else ""}
            "담당자" TEXT
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES (?, ?, ?)',
        [
            ("org-1", "오가닉", "대기업"),
            ("org-2", "삼성전자", "대기업"),
            ("org-3", "파크", "공공기관"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직") VALUES (?, ?, ?, ?)',
        [
            ("p-1", "org-1", "고객A", "본부A"),
            ("p-2", "org-2", "고객B", "본부B"),
            ("p-3", "org-3", "고객C", None),
        ],
    )
    deal_columns = [
        "id",
        "peopleId",
        "organizationId",
        "이름",
        "상태",
        "금액",
        "예상 체결액",
        "계약 체결일",
        "수주 예정일",
        "수강시작일",
        "수강종료일",
        "성사 가능성",
        "과정포맷",
        "담당자",
    ]
    if with_course_id:
        deal_columns.insert(-1, "코스 ID")

    placeholders = ",".join(["?"] * len(deal_columns))
    col_sql = ", ".join(f'"{c}"' for c in deal_columns)
    rows = [
        # Row1: Won + start/end + courseId + amount → 계약 체결
        ("d-1", "p-1", "org-1", "딜1", "Won", 100.0, None, "2025-01-15", None, "2025-01-05", "2025-01-20", "확정", "집합", "COURSE-1" if with_course_id else None, '["데이원A"]'),
        # Row2: Won but missing start/end → 확정으로 Row2, month from expected_date
        ("d-2", "p-2", "org-2", "딜2", "Won", None, 200.0, None, "2025-02-10", None, None, "확정", "구독제(온라인)", "COURSE-2" if with_course_id else None, '["데이원B"]'),
        # Row3: 높음 only, offline, non-major size, fallback to expected_amount
        ("d-3", "p-3", "org-3", "딜3", "Open", None, 300.0, "2026-03-01", None, None, None, "높음", "집합", "COURSE-3" if with_course_id else None, '["데이원C"]'),
        # Row3: 높음 only, online major size, expected_date provides month
        ("d-4", "p-1", "org-1", "딜4", "Won", None, 50.0, None, "2025-06-15", None, None, '["높음"]', "구독제(온라인)", "COURSE-4" if with_course_id else None, '["데이원A"]'),
    ]
    if not with_course_id:
        rows = [tuple(v for i, v in enumerate(row) if i != 13) for row in rows]  # drop course id slot when absent
    conn.executemany(
        f"INSERT INTO deal ({col_sql}) VALUES ({placeholders})",
        [tuple(r) for r in rows],
    )
    conn.commit()
    conn.close()


def _init_db_with_team_filter(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE organization (id TEXT PRIMARY KEY, "이름" TEXT, "기업 규모" TEXT);
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
            "코스 ID" TEXT,
            "담당자" TEXT
        );
        """
    )
    conn.executemany(
        'INSERT INTO organization (id, "이름", "기업 규모") VALUES (?, ?, ?)',
        [
            ("org-1", "A사", "대기업"),
            ("org-2", "B사", "대기업"),
        ],
    )
    conn.executemany(
        'INSERT INTO people (id, organizationId, "이름", "소속 상위 조직") VALUES (?, ?, ?, ?)',
        [
            ("p-1", "org-1", "담당1", "본부1"),
            ("p-2", "org-2", "담당2", "본부2"),
        ],
    )
    conn.executemany(
        'INSERT INTO deal (id, peopleId, organizationId, "이름", "상태", "금액", "예상 체결액", "계약 체결일", "수주 예정일", "수강시작일", "수강종료일", "성사 가능성", "과정포맷", "코스 ID", "담당자") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            # edu1 담당자(김솔이)
            (
                "d-edu1",
                "p-1",
                "org-1",
                "딜-edu1",
                "Won",
                100.0,
                None,
                "2025-01-10",
                None,
                "2025-01-05",
                "2025-01-20",
                "확정",
                "집합",
                "COURSE-EDU1",
                '["김솔이"]',
            ),
            # edu2 담당자(강진우)
            (
                "d-edu2",
                "p-2",
                "org-2",
                "딜-edu2",
                "Won",
                200.0,
                None,
                "2025-01-12",
                None,
                "2025-01-06",
                "2025-01-25",
                "확정",
                "집합",
                "COURSE-EDU2",
                '["강진우"]',
            ),
        ],
    )
    conn.commit()
    conn.close()


class PerfMonthlyContractsTest(unittest.TestCase):
    def test_summary_and_deals_alignment(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db(db_path)
        try:
            summary = db.get_perf_monthly_amounts_summary(db_path=db_path)
            months = summary["months"]
            self.assertEqual(months[0], "2501")
            self.assertEqual(months[-1], "2612")
            seg_map = {seg["key"]: seg for seg in summary["segments"]}

            def row_dict(seg_key: str) -> dict:
                seg = seg_map[seg_key]
                return {row["key"]: row for row in seg["rows"]}

            all_rows = row_dict("ALL")
            # Total row present and first
            self.assertEqual(list(seg_map["ALL"]["rows"])[0]["key"], "TOTAL")
            # Row1 priority: only 계약 체결에 합산
            self.assertEqual(all_rows["CONTRACT"]["byMonth"]["2501"], 100.0)
            self.assertEqual(all_rows["CONFIRMED"]["byMonth"]["2502"], 200.0)
            self.assertEqual(all_rows["HIGH"]["byMonth"]["2603"], 300.0)
            self.assertEqual(all_rows["HIGH"]["byMonth"]["2506"], 50.0)
            # TOTAL = sum of three buckets
            self.assertEqual(all_rows["TOTAL"]["byMonth"]["2501"], 100.0)
            self.assertEqual(all_rows["TOTAL"]["byMonth"]["2502"], 200.0)
            self.assertEqual(all_rows["TOTAL"]["byMonth"]["2506"], 50.0)
            self.assertEqual(all_rows["TOTAL"]["byMonth"]["2603"], 300.0)

            self.assertEqual(all_rows["CONTRACT"]["dealCountByMonth"]["2501"], 1)
            self.assertEqual(all_rows["CONFIRMED"]["dealCountByMonth"]["2502"], 1)

            samsung_online = row_dict("SAMSUNG_ONLINE")
            self.assertEqual(samsung_online["CONFIRMED"]["byMonth"]["2502"], 200.0)

            non_samsung_online_major = row_dict("NON_SAMSUNG_ONLINE_MAJOR_SIZE")
            self.assertEqual(non_samsung_online_major["HIGH"]["byMonth"]["2506"], 50.0)

            offline_non_major = row_dict("OFFLINE_NON_MAJOR_SIZE")
            self.assertEqual(offline_non_major["HIGH"]["byMonth"]["2603"], 300.0)

            deals = db.get_perf_monthly_amounts_deals(segment="SAMSUNG_ONLINE", row="CONFIRMED", month="2502", db_path=db_path)
            self.assertEqual(deals["dealCount"], 1)
            self.assertAlmostEqual(deals["totalAmount"], 200.0)
            item = deals["items"][0]
            self.assertEqual(item["orgName"], "삼성전자")
            self.assertEqual(item["amountUsed"], 200.0)
            self.assertEqual(item["expectedAmount"], 200.0)

            # TOTAL drilldown includes all buckets
            total_deals = db.get_perf_monthly_amounts_deals(segment="ALL", row="TOTAL", month="2501", db_path=db_path)
            self.assertEqual(total_deals["dealCount"], 1)
            self.assertAlmostEqual(total_deals["totalAmount"], 100.0)
            total_deals_2506 = db.get_perf_monthly_amounts_deals(segment="ALL", row="TOTAL", month="2506", db_path=db_path)
            self.assertEqual(total_deals_2506["dealCount"], 1)
            self.assertAlmostEqual(total_deals_2506["totalAmount"], 50.0)

            # Drilldown for high offline non-major
            deals_offline = db.get_perf_monthly_amounts_deals(segment="OFFLINE_NON_MAJOR_SIZE", row="HIGH", month="2603", db_path=db_path)
            self.assertEqual(deals_offline["dealCount"], 1)
            self.assertAlmostEqual(deals_offline["totalAmount"], 300.0)
            self.assertEqual(deals_offline["items"][0]["dealName"], "딜3")
        finally:
            db_path.unlink(missing_ok=True)

    def test_missing_course_id_column_fallback(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db(db_path, with_course_id=False)
        try:
            summary = db.get_perf_monthly_amounts_summary(db_path=db_path)
            seg_map = {seg["key"]: seg for seg in summary["segments"]}
            all_rows = {row["key"]: row for row in seg_map["ALL"]["rows"]}
            # Row1 should still accept when course id column is missing (treated as unknown, not crash)
            self.assertEqual(all_rows["CONTRACT"]["byMonth"]["2501"], 100.0)
        finally:
            db_path.unlink(missing_ok=True)

    def test_team_filtering(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = Path(tmp.name)
        _init_db_with_team_filter(db_path)
        try:
            summary_all = db.get_perf_monthly_amounts_summary(db_path=db_path)
            seg_map = {seg["key"]: seg for seg in summary_all["segments"]}
            all_total = {row["key"]: row for row in seg_map["ALL"]["rows"]}["TOTAL"]
            self.assertEqual(all_total["byMonth"]["2501"], 300.0)
            self.assertEqual(all_total["dealCountByMonth"]["2501"], 2)

            summary_edu1 = db.get_perf_monthly_amounts_summary(db_path=db_path, team="edu1")
            seg_map1 = {seg["key"]: seg for seg in summary_edu1["segments"]}
            total1 = {row["key"]: row for row in seg_map1["ALL"]["rows"]}["TOTAL"]
            self.assertEqual(total1["byMonth"]["2501"], 100.0)
            self.assertEqual(total1["dealCountByMonth"]["2501"], 1)

            summary_edu2 = db.get_perf_monthly_amounts_summary(db_path=db_path, team="edu2")
            seg_map2 = {seg["key"]: seg for seg in summary_edu2["segments"]}
            total2 = {row["key"]: row for row in seg_map2["ALL"]["rows"]}["TOTAL"]
            self.assertEqual(total2["byMonth"]["2501"], 200.0)
            self.assertEqual(total2["dealCountByMonth"]["2501"], 1)

            deals1 = db.get_perf_monthly_amounts_deals(segment="ALL", row="TOTAL", month="2501", team="edu1", db_path=db_path)
            self.assertEqual(deals1["dealCount"], 1)
            self.assertEqual(deals1["items"][0]["dealId"], "d-edu1")
            self.assertAlmostEqual(deals1["totalAmount"], 100.0)

            deals2 = db.get_perf_monthly_amounts_deals(segment="ALL", row="TOTAL", month="2501", team="edu2", db_path=db_path)
            self.assertEqual(deals2["dealCount"], 1)
            self.assertEqual(deals2["items"][0]["dealId"], "d-edu2")
            self.assertAlmostEqual(deals2["totalAmount"], 200.0)
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
