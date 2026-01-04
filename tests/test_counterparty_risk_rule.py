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


class CounterpartyRiskRuleTest(TestCase):
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
                ("org_p1", "중견B"),
            ],
        )
        c.executemany(
            'INSERT INTO people VALUES (?, ?, ?, ?)',
            [
                ("p1", "org_p0", "사람1", "CP-Alpha"),
                ("p2", "org_p0", "사람2", "CP-Beta"),
                ("p3", "org_p0", "사람3", None),
                ("p4", "org_p1", "사람4", "CP-Gamma"),
            ],
        )

        deals = [
            # 2025 baseline for org_p0
            ("d_base_alpha", "p1", "org_p0", "B1", "Won", "집합교육", "200000000", None, "2025-02-01", None, "2025-02-02", "2025-02-03", "CIDB1", None),
            ("d_base_beta", "p2", "org_p0", "B2", "Won", "집합교육", "120000000", None, "2025-02-10", None, "2025-02-11", "2025-02-12", "CIDB2", None),
            # 2026: CP-Alpha has no deals -> pipeline_zero
            # 2026: CP-Beta has confirmed 30,000,000 => coverage_ratio 0.147 with target 204,000,000 -> 보통
            ("d_2026_beta", "p2", "org_p0", "C1", "Won", "집합교육", "30000000", None, "2026-03-01", None, "2026-03-05", "2026-03-06", "CIDC1", None),
            # 2026: CP-Gamma target 0 (org_p1 baseline 0) but has expected high -> coverage_ratio NULL, risk 양호
            ("d_2026_gamma", "p4", "org_p1", "C2", "Open", "집합교육", "50000000", None, "2026-04-01", None, "2026-04-05", "2026-04-06", "CIDC2", "높음"),
            # 2026: Unclassified counterparty, no coverage (pipeline_zero)
            ("d_2026_unknown", "p3", "org_p0", "C3", "Won", "집합교육", "10000000", None, "2026-05-01", None, "2026-05-02", "2026-05-03", "CIDC3", None),
            # Convert should be ignored
            ("d_convert", "p1", "org_p0", "C4", "Convert", "집합교육", "999999999", None, "2026-06-01", None, "2026-06-02", "2026-06-03", "CIDC4", None),
        ]
        c.executemany('INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', deals)
        c.commit()

    def test_risk_rule_pipeline(self) -> None:
        self._build_fixture()
        dq = dn.build_deal_norm(self.conn)
        self.assertGreater(dq["total_deals_loaded"], 0)

        org_tier = dn.build_org_tier(self.conn)
        self.assertEqual(org_tier["org_tier_map"]["org_p0"], "P0")
        # org_p1 baseline=0 => tier None (not in S0~P2)
        self.assertIsNone(org_tier["org_tier_map"].get("org_p1"))

        dn.build_counterparty_target_2026(self.conn)
        result = dn.build_counterparty_risk_rule(self.conn, as_of_date="2026-04-15")

        rows = {
            (row["organization_id"], row["counterparty_name"]): row
            for row in self.conn.execute(
                "SELECT organization_id, counterparty_name, target_2026, confirmed_2026, expected_2026, coverage_2026, gap, coverage_ratio, pipeline_zero, risk_level_rule, rule_trigger, excluded_by_quality FROM tmp_counterparty_risk_rule"
            )
        }

        # CP-Alpha: target 340, coverage 0 -> pipeline_zero + 심각
        cp_alpha = rows[("org_p0", "CP-Alpha")]
        self.assertEqual(cp_alpha["target_2026"], 340_000_000)
        self.assertEqual(cp_alpha["coverage_2026"], 0)
        self.assertEqual(cp_alpha["pipeline_zero"], 1)
        self.assertEqual(cp_alpha["risk_level_rule"], "심각")
        self.assertEqual(cp_alpha["rule_trigger"], "PIPELINE_ZERO")

        # CP-Beta: coverage 30M, target 204M, month=Apr(min_cov=0.20, severe=0.10) -> 보통
        cp_beta = rows[("org_p0", "CP-Beta")]
        self.assertAlmostEqual(cp_beta["coverage_ratio"], 30_000_000 / 204_000_000)
        self.assertEqual(cp_beta["risk_level_rule"], "보통")
        self.assertEqual(cp_beta["rule_trigger"], "COVERAGE_BELOW_MIN")

        # Unclassified counterparty flagged + pipeline_zero severe
        cp_unknown = rows[("org_p0", dn.COUNTERPARTY_UNKNOWN)]
        self.assertEqual(cp_unknown["excluded_by_quality"], 1)
        self.assertEqual(cp_unknown["pipeline_zero"], 0)
        self.assertEqual(cp_unknown["risk_level_rule"], "양호")

        # CP-Gamma (org_p1) not included because org_p1 tier not in S0~P2 (baseline 0)
        self.assertNotIn(("org_p1", "CP-Gamma"), rows)

        self.assertEqual(result["null_tier_rows"], 0)
