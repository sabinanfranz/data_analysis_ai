import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from dashboard.server.agents.core.types import AgentContext, LLMConfig
from dashboard.server.agents.counterparty_card.agent import CounterpartyCardAgent, PAYLOAD_DEALS_LIMIT


def _setup_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE memo (id TEXT, text TEXT, createdAt TEXT, dealId TEXT, peopleId TEXT, organizationId TEXT)')
    conn.execute(
        'CREATE TABLE deal (id TEXT, peopleId TEXT, organizationId TEXT, "이름" TEXT, "상태" TEXT, "과정포맷" TEXT, "금액" TEXT, "예상 체결액" TEXT, '
        '"계약 체결일" TEXT, "수주 예정일" TEXT, "수강시작일" TEXT, "수강종료일" TEXT, "코스 ID" TEXT, "성사 가능성" TEXT)'
    )
    conn.execute('CREATE TABLE people (id TEXT, organizationId TEXT, "소속 상위 조직" TEXT)')
    return conn


def test_counterparty_card_agent_fallback_outputs_lengths():
    conn = _setup_db()
    risk_rows = [
        {
            "organization_id": "org1",
            "organization_name": "Org",
            "counterparty_name": "CP",
            "tier": "P0",
            "baseline_2025_confirmed": 0,
            "target_2026": 100_000_000,
            "confirmed_2026": 0,
            "expected_2026": 0,
            "coverage_2026": 0,
            "gap": 100_000_000,
            "coverage_ratio": 0,
            "pipeline_zero": True,
            "risk_level_rule": "심각",
            "min_cov_current_month": 0.1,
            "severe_threshold": 0.05,
            "excluded_by_quality": False,
            "dq_year_unknown_cnt": 0,
            "dq_amount_parse_fail_cnt_2026": 0,
            "cnt_confirmed_deals_2026": 0,
            "cnt_expected_deals_2026": 0,
            "cnt_amount_zero_deals_2026": 0,
            "top_deals_2026": [
                {
                    "deal_id": "d1",
                    "deal_name": "Deal 1",
                    "status": "Open",
                    "possibility": "높음",
                    "amount": 50_000_000,
                    "is_nononline": True,
                    "deal_year": 2026,
                    "course_id_exists": True,
                    "start_date": "2026-01-02",
                    "end_date": None,
                    "contract_date": None,
                    "expected_close_date": None,
                    "last_contact_date": None,
                }
            ],
        }
    ]
    cache_dir = Path(tempfile.mkdtemp())
    ctx = AgentContext(
        report_id="counterparty-risk-daily",
        mode_key="offline",
        as_of_date=date(2026, 1, 1),
        db_hash="hash123",
        snapshot_db_path=Path(""),
        cache_root=cache_dir,
        llm=LLMConfig.from_env(),
    )
    agent = CounterpartyCardAgent()
    result = agent.run(conn, risk_rows, ctx, cache_dir=cache_dir)
    output = result[("org1", "CP")]
    assert output["risk_level_llm"] in {"양호", "보통", "심각"}
    assert 1 <= len(output["top_blockers"]) <= 3
    assert len(output["evidence_bullets"]) == 3
    assert 2 <= len(output["recommended_actions"]) <= 3
    assert len(output.get("deals_top", risk_rows[0]["top_deals_2026"][:PAYLOAD_DEALS_LIMIT])) >= 1

