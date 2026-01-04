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


class OrgTierTest(TestCase):
    def _build_fixture(self) -> sqlite3.Connection:
        tmpdir = tempfile.TemporaryDirectory()
        self._tmpdir = tmpdir  # keep reference so the directory stays alive
        db_path = Path(tmpdir.name) / "db.sqlite"
        conn = sqlite3.connect(db_path)
        _prepare_schema(conn)
        conn.executemany(
            'INSERT INTO organization VALUES (?, ?)',
            [
                ("org_s0", "대기업A"),
                ("org_p0", "대기업B"),
                ("org_p1", "대기업C"),
                ("org_p2", "대기업D"),
                ("org_none", "대기업E"),
                ("org_samsung", "삼성전자B2B"),
            ],
        )
        conn.executemany(
            'INSERT INTO people VALUES (?, ?, ?, ?)',
            [
                ("p1", "org_s0", "사람1", "상위A"),
                ("p2", "org_p0", "사람2", "상위B"),
                ("p3", "org_p1", "사람3", "상위C"),
                ("p4", "org_p2", "사람4", "상위D"),
                ("p5", "org_none", "사람5", "상위E"),
                ("p6", "org_samsung", "사람6", "상위S"),
            ],
        )
        deals = [
            # S0: 1.2억 -> actually 1.2 billion (1_200_000_000)
            ("d_s0", "p1", "org_s0", "딜_s0", "Won", "집합교육", "1200000000", None, "2025-02-01", None, None, None, "CID1", None),
            # P0: exactly 200,000,000 -> P0
            ("d_p0", "p2", "org_p0", "딜_p0", "Won", "집합교육", "200000000", None, "2025-03-01", None, None, None, "CID2", None),
            # P1: 150,000,000
            ("d_p1", "p3", "org_p1", "딜_p1", "Won", "집합교육", "150000000", None, "2025-04-01", None, None, None, "CID3", None),
            # P2: 70,000,000
            ("d_p2", "p4", "org_p2", "딜_p2", "Won", "집합교육", "70000000", None, "2025-05-01", None, None, None, "CID4", None),
            # Below P2: 40,000,000 -> tier None
            ("d_none", "p5", "org_none", "딜_none", "Won", "집합교육", "40000000", None, "2025-06-01", None, None, None, "CID5", None),
            # Samsung should be excluded even if big
            ("d_samsung", "p6", "org_samsung", "딜_samsung", "Won", "집합교육", "2000000000", None, "2025-07-01", None, None, None, "CID6", None),
            # Online deal should be excluded from tier calc
            ("d_online", "p1", "org_s0", "딜_online", "Won", "구독제(온라인)", "999999999", None, "2025-08-01", None, None, None, "CID7", None),
            # Convert should be excluded
            ("d_convert", "p1", "org_s0", "딜_convert", "Convert", "집합교육", "50000000", None, "2025-09-01", None, None, None, "CID8", None),
            # Course start 2026 -> year should be 2026 and excluded
            ("d_2026", "p1", "org_s0", "딜_2026", "Won", "집합교육", "50000000", None, "2025-12-20", None, "2026-01-10", None, "CID9", None),
        ]
        conn.executemany(
            'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            deals,
        )
        conn.commit()
        return conn

    def tearDown(self) -> None:
        tmpdir = getattr(self, "_tmpdir", None)
        if tmpdir is not None:
            tmpdir.cleanup()

    def test_org_tier_boundaries_and_filters(self) -> None:
        conn = self._build_fixture()
        dq = dn.build_deal_norm(conn)
        self.assertGreater(dq["total_deals_loaded"], 0)

        result = dn.build_org_tier(conn, as_of_date="2025-12-31")
        tiers = result["org_tier_map"]

        self.assertEqual(tiers["org_s0"], "S0")
        self.assertEqual(tiers["org_p0"], "P0")
        self.assertEqual(tiers["org_p1"], "P1")
        self.assertEqual(tiers["org_p2"], "P2")
        self.assertIsNone(tiers["org_none"])
        self.assertIsNone(tiers["org_samsung"])

        # Online/Convert/year-2026 deals must not inflate totals
        row_s0 = conn.execute(
            "SELECT confirmed_amount_2025_won FROM org_tier_runtime WHERE organization_id='org_s0'"
        ).fetchone()
        self.assertEqual(row_s0[0], 1_200_000_000)

        # Summary sanity: counts per tier
        summary_counts = result["summary"]["counts_by_tier"]
        self.assertEqual(summary_counts["S0"], 1)
        self.assertEqual(summary_counts["P0"], 1)
        self.assertEqual(summary_counts["P1"], 1)
        self.assertEqual(summary_counts["P2"], 1)
        self.assertGreaterEqual(summary_counts["NONE"], 2)  # org_none + samsung
        conn.close()
