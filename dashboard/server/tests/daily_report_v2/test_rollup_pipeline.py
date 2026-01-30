import sys
import types
import unittest
from unittest.mock import patch, call

if "httpx" not in sys.modules:
    class _DummyClient:
        def __init__(self, *args, **kwargs): ...
        def __enter__(self): return self
        def __exit__(self, *args, **kwargs): return False
        def post(self, *args, **kwargs): raise RuntimeError("httpx stub")
    sys.modules["httpx"] = types.SimpleNamespace(Client=_DummyClient)

if "fastapi" not in sys.modules:
    class _HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    sys.modules["fastapi"] = types.SimpleNamespace(HTTPException=_HTTPException)

from dashboard.server.agents.daily_report_v2.orchestrator import run_pipeline


class RollupPipelineTest(unittest.TestCase):
    def test_rollup_pipeline_flow_and_debug(self):
        rows = [
            {"rowKey": "r1", "orgId": "O1", "upperOrg": "P1", "target": 1, "actual": 0, "won_group_json_compact": {}},
            {"rowKey": "r2", "orgId": "O2", "upperOrg": "P2", "target": 2, "actual": 1, "won_group_json_compact": {}},
        ]

        ta_calls = []

        def fake_ta(req, variant, debug, nocache=False):
            ta_calls.append((req.orgId, nocache))
            return {"likelihood": "HIGH", "numbers": {"target": req.target_2026, "actual": req.actual_2026}}

        part_stub_output = {"summary": "part ok", "__meta": {"prompt_hash": "ph"}}
        with patch("dashboard.server.agents.daily_report_v2.orchestrator.TargetAttainmentAgent.run", side_effect=fake_ta) as p_ta, \
            patch("dashboard.server.agents.daily_report_v2.orchestrator.PartReportAgent.run", return_value=part_stub_output) as p_pr, \
            patch("dashboard.server.agents.daily_report_v2.orchestrator.DailyRollupAgent.run", return_value={"rollup": "ok", "__meta": {"prompt_hash": "ph2"}}) as p_dr:
            result = run_pipeline("daily.part_rollup", {"rows": rows}, variant="offline", debug=True, nocache=True)

        self.assertIsInstance(result, dict)
        self.assertIn("rows", result)
        self.assertEqual(len(result["rows"]), 2)
        self.assertIn("parts", result)
        self.assertIn("rollup", result)
        self.assertIn("__meta", result)
        self.assertIn("__meta", result["parts"][0]["output"])
        self.assertIn("prompt_hash", result["parts"][0]["output"]["__meta"])
        self.assertEqual(p_pr.call_count, 2)
        p_dr.assert_called_once()
        self.assertTrue(all(nc for _, nc in ta_calls))

    def test_no_meta_when_debug_false(self):
        rows = [{"rowKey": "r1", "orgId": "O1", "upperOrg": "P1", "target": 1, "actual": 0, "won_group_json_compact": {}}]
        with patch("dashboard.server.agents.daily_report_v2.orchestrator.TargetAttainmentAgent.run", return_value={"likelihood": "HIGH"}), \
            patch("dashboard.server.agents.daily_report_v2.orchestrator.PartReportAgent.run", return_value={"summary": "ok"}), \
            patch("dashboard.server.agents.daily_report_v2.orchestrator.DailyRollupAgent.run", return_value={"rollup": "ok"}):
            result = run_pipeline("daily.part_rollup", {"rows": rows}, variant="offline", debug=False, nocache=True)
        self.assertNotIn("__meta", result)
        self.assertNotIn("__meta", result["rows"][0]["output"])
        self.assertNotIn("__meta", result["rollup"])


if __name__ == "__main__":
    unittest.main()
