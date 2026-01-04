import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from dashboard.server import deal_normalizer as dn


def _prepare_schema(conn: sqlite3.Connection) -> None:
    conn.execute('CREATE TABLE organization (id TEXT, "이름" TEXT)')
    conn.execute(
        'CREATE TABLE people (id TEXT, organizationId TEXT, "이름" TEXT, "소속 상위 조직" TEXT)'
    )
    conn.execute(
        'CREATE TABLE deal ('
        "id TEXT, peopleId TEXT, organizationId TEXT, "
        '"이름" TEXT, "상태" TEXT, "과정포맷" TEXT, "금액" TEXT, "예상 체결액" TEXT, '
        '"계약 체결일" TEXT, "수주 예정일" TEXT, "수강시작일" TEXT, "수강종료일" TEXT, "코스 ID" TEXT, "성사 가능성" TEXT)'
    )


class DealNormalizerTest(TestCase):
    def test_is_nononline_and_missing_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            conn = sqlite3.connect(db_path)
            _prepare_schema(conn)

            conn.executemany(
                'INSERT INTO organization VALUES (?, ?)',
                [("org1", "조직1"), ("org2", "조직2"), ("org3", "조직3")],
            )
            conn.executemany(
                'INSERT INTO people VALUES (?, ?, ?, ?)',
                [
                    ("p1", "org1", "사람1", "카운터A"),
                    ("p2", "org2", "사람2", "카운터B"),
                    ("p3", "org3", "사람3", "카운터C"),
                ],
            )
            conn.executemany(
                'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [
                    ("d1", "p1", "org1", "딜1", "Won", "구독제(온라인)", "1000", None, None, None, None, None, None, None),
                    ("d2", "p2", "org2", "딜2", "Won", "복합", "1000", None, None, None, None, None, None, None),
                    ("d3", "p3", "org3", "딜3", "Won", None, "1000", None, None, None, None, None, None, None),
                ],
            )
            conn.commit()

            dq = dn.build_deal_norm(conn)
            rows = conn.execute(
                "SELECT deal_id, is_nononline, is_online, process_format_missing_flag FROM deal_norm ORDER BY deal_id"
            ).fetchall()

            self.assertEqual(dq["process_format_missing_count"], 1)
            as_dict = {row[0]: row for row in rows}
            self.assertEqual(as_dict["d1"][1], 0)  # online
            self.assertEqual(as_dict["d1"][2], 1)
            self.assertEqual(as_dict["d2"][1], 1)
            self.assertEqual(as_dict["d3"][1], 1)
            self.assertEqual(as_dict["d3"][3], 1)  # missing flag

            conn.close()

    def test_deal_year_prefers_course_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            conn = sqlite3.connect(db_path)
            _prepare_schema(conn)
            conn.execute('INSERT INTO organization VALUES (?, ?)', ("org1", "조직1"))
            conn.execute('INSERT INTO people VALUES (?, ?, ?, ?)', ("p1", "org1", "사람1", "상위"))
            conn.execute(
                'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    "d1",
                    "p1",
                    "org1",
                    "딜1",
                    "Won",
                    "집합교육",
                    "1000",
                    None,
                    "2025-12-20",
                    None,
                    "2026-01-10",
                    None,
                    None,
                    None,
                ),
            )
            conn.commit()

            dn.build_deal_norm(conn)
            row = conn.execute(
                "SELECT deal_year, contract_signed_date, course_start_date FROM deal_norm WHERE deal_id='d1'"
            ).fetchone()
            self.assertEqual(row[0], 2026)
            self.assertEqual(row[1], "2025-12-20")
            self.assertEqual(row[2], "2026-01-10")
            conn.close()

    def test_convert_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            conn = sqlite3.connect(db_path)
            _prepare_schema(conn)
            conn.execute('INSERT INTO organization VALUES (?, ?)', ("org1", "조직1"))
            conn.execute('INSERT INTO people VALUES (?, ?, ?, ?)', ("p1", "org1", "사람1", "상위"))
            conn.executemany(
                'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [
                    ("d_keep", "p1", "org1", "딜1", "Won", "집합교육", "1000", None, None, None, None, None, None, None),
                    ("d_convert", "p1", "org1", "딜2", "Convert", "집합교육", "1000", None, None, None, None, None, None, None),
                ],
            )
            conn.commit()

            dq = dn.build_deal_norm(conn)
            ids = [row[0] for row in conn.execute("SELECT deal_id FROM deal_norm").fetchall()]
            self.assertEqual(ids, ["d_keep"])
            self.assertEqual(dq["excluded_convert_count"], 1)
            self.assertEqual(dq["total_deals_loaded"], 1)
            conn.close()

    def test_amount_selection_and_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            conn = sqlite3.connect(db_path)
            _prepare_schema(conn)
            conn.execute('INSERT INTO organization VALUES (?, ?)', ("org1", "조직1"))
            conn.executemany(
                'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [
                    ("d_expected", None, "org1", "딜1", "Won", "집합교육", None, "1억", None, None, None, None, None, None),
                    ("d_amount", None, "org1", "딜2", "Won", "집합교육", "50,000,000", "1억", None, None, None, None, None, None),
                    ("d_none", None, "org1", "딜3", "Won", "집합교육", "", "", None, None, None, None, None, None),
                ],
            )
            conn.commit()

            dn.build_deal_norm(conn)
            rows = {
                row["deal_id"]: row
                for row in conn.execute(
                    "SELECT deal_id, amount_source, amount_value, amount_missing_flag, amount_parse_ok FROM deal_norm"
                ).fetchall()
            }

            self.assertEqual(rows["d_expected"]["amount_source"], "EXPECTED")
            self.assertEqual(rows["d_expected"]["amount_value"], 100_000_000)
            self.assertEqual(rows["d_expected"]["amount_parse_ok"], 1)

            self.assertEqual(rows["d_amount"]["amount_source"], "AMOUNT")
            self.assertEqual(rows["d_amount"]["amount_value"], 50_000_000)
            self.assertEqual(rows["d_amount"]["amount_parse_ok"], 1)

            self.assertEqual(rows["d_none"]["amount_source"], "NONE")
            self.assertEqual(rows["d_none"]["amount_value"], 0)
            self.assertEqual(rows["d_none"]["amount_missing_flag"], 1)
            self.assertEqual(rows["d_none"]["amount_parse_ok"], 0)
            conn.close()

    def test_counterparty_missing_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            conn = sqlite3.connect(db_path)
            _prepare_schema(conn)
            conn.execute('INSERT INTO organization VALUES (?, ?)', ("org1", "조직1"))
            conn.execute(
                'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ("d1", None, "org1", "딜1", "Won", "집합교육", "1000", None, None, None, None, None, None, None),
            )
            conn.commit()

            dq = dn.build_deal_norm(conn)
            row = conn.execute(
                "SELECT counterparty_name, counterparty_missing_flag FROM deal_norm WHERE deal_id='d1'"
            ).fetchone()
            self.assertEqual(row[0], dn.COUNTERPARTY_UNKNOWN)
            self.assertEqual(row[1], 1)
            self.assertEqual(dq["counterparty_unclassified_count"], 1)
            conn.close()
