import unittest
from datetime import date

from dashboard.server import counterparty_llm as cllm


class CounterpartyLlmFallbackTest(unittest.TestCase):
    def test_fallback_evidence_accepts_risk_rule(self):
        # risk_rule payload fragment without coverage_ratio should not raise
        risk_rule = {
            "target_2026": 200_000_000,
            "confirmed_2026": 0,
            "expected_2026": 100_000_000,
            "coverage": 0.5,
            "gap": 100_000_000,
            "min_cov_current_month": 0.9,
            "pipeline_zero": False,
        }
        blockers = ["PIPELINE_ZERO"]
        evidence = cllm.fallback_evidence(risk_rule, blockers)
        self.assertEqual(len(evidence), 3)

    def test_run_llm_or_fallback_survives_minimal_payload(self):
        payload = {
            "as_of_date": date.today().isoformat(),
            "counterparty_key": {
                "organizationId": "org",
                "organizationName": "Org",
                "counterpartyName": "CP",
            },
            "tier": "P1",
            "risk_rule": {
                "rule_risk_level": "보통",
                "pipeline_zero": False,
                "min_cov_current_month": 0.1,
                "coverage": 0.2,
                "gap": 50_000_000,
                "target_2026": 100_000_000,
                "confirmed_2026": 0,
                "expected_2026": 20_000_000,
            },
            "signals": {},
            "top_deals_2026": [],
            "memos": [],
            "data_quality": {},
        }
        res = cllm.run_llm_or_fallback(payload)
        self.assertIn("evidence_bullets", res)
        self.assertEqual(len(res["evidence_bullets"]), 3)
        self.assertGreaterEqual(len(res.get("recommended_actions", [])), 2)


if __name__ == "__main__":
    unittest.main()
