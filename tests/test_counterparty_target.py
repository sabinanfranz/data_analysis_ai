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


class CounterpartyTargetTest(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "db.sqlite"
        self.conn = sqlite3.connect(db_path)
        _prepare_schema(self.conn)

    def tearDown(self) -> None:
        if hasattr(self, "conn"):
            self.conn.close()
        self.tmpdir.cleanup()

    def _build_fixture(self) -> None:
        c = self.conn
        c.executemany(
            'INSERT INTO organization VALUES (?, ?)',
            [
                ("org_p0", "중견A"),
                ("org_other", "중견B"),
            ],
        )
        c.executemany(
            'INSERT INTO people VALUES (?, ?, ?, ?)',
            [
                ("p1", "org_p0", "사람1", "CP-Alpha"),
                ("p2", "org_p0", "사람2", "CP-Beta"),
                ("p3", "org_p0", "사람3", None),  # unclassified
                ("p4", "org_other", "사람4", "Other"),
            ],
        )
        deals = [
            # Baseline: confirmed/contract, year 2025, nononline
            ("d_contract", "p1", "org_p0", "딜1", "Won", "집합교육", "200000000", None, "2025-03-01", None, "2025-03-10", "2025-03-11", "CID1", None),
            # HIGH only -> should not count baseline
            ("d_high", "p2", "org_p0", "딜2", "Open", "집합교육", "50000000", None, "2025-04-01", None, "2025-04-05", "2025-04-06", "CID2", "높음"),
            # 2026 only deal to keep universe row
            ("d_2026", "p2", "org_p0", "딜3", "Won", "집합교육", "80000000", None, "2026-01-01", None, "2026-01-05", "2026-01-06", "CID3", None),
            # Convert should be ignored (not present in deal_norm)
            ("d_convert", "p1", "org_p0", "딜4", "Convert", "집합교육", "99999999", None, "2025-02-01", None, "2025-02-02", "2025-02-03", "CID4", None),
            # Unclassified counterparty (upper org NULL)
            ("d_unknown_cp", "p3", "org_p0", "딜5", "Won", "집합교육", "10000000", None, "2025-05-01", None, "2025-05-02", "2025-05-03", "CID5", None),
            # Org_other should not appear (tier likely None)
            ("d_other", "p4", "org_other", "딜6", "Won", "집합교육", "300000000", None, "2025-06-01", None, "2025-06-02", "2025-06-03", "CID6", None),
        ]
        c.executemany(
            'INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            deals,
        )
        c.commit()

    def test_counterparty_target_pipeline(self) -> None:
        self._build_fixture()
        dq = dn.build_deal_norm(self.conn)
        self.assertGreater(dq["total_deals_loaded"], 0)

        # org_tier based on confirmed (contract/commit) -> org_p0 becomes P0 with 200M
        org_tier = dn.build_org_tier(self.conn)
        self.assertEqual(org_tier["org_tier_map"]["org_p0"], "P0")

        result = dn.build_counterparty_target_2026(self.conn)
        table = result["table"]

        rows = {
            (row["organization_id"], row["counterparty_name"]): row
            for row in self.conn.execute(f"SELECT * FROM {table}").fetchall()
        }

        # baseline 200,000,000 * 1.7 = 340,000,000 for CP-Alpha
        cp_alpha = rows[("org_p0", "CP-Alpha")]
        self.assertEqual(cp_alpha["baseline_2025"], 200_000_000)
        self.assertEqual(cp_alpha["tier"], "P0")
        self.assertEqual(cp_alpha["target_2026"], 340_000_000)

        # HIGH-only cp should have baseline 0 (ignored)
        cp_beta = rows[("org_p0", "CP-Beta")]
        self.assertEqual(cp_beta["baseline_2025"], 0)
        self.assertEqual(cp_beta["target_2026"], 0)

        # 2026-only cp still present with baseline 0 (target 0)
        # Counterparty CP-Beta already represents 2026-only row; ensure exists
        self.assertIn(("org_p0", "CP-Beta"), rows)

        # Unclassified counterparty consolidated
        cp_unknown = rows[("org_p0", dn.COUNTERPARTY_UNKNOWN)]
        self.assertEqual(cp_unknown["baseline_2025"], 10_000_000)
        self.assertEqual(cp_unknown["is_unclassified_counterparty"], 1)

        # org_tier vs baseline sums should match (no mismatches)
        self.assertFalse(result["org_baseline_vs_tier_diff"])
