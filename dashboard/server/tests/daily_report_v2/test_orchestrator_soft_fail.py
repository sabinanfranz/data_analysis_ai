import sys
import types
import unittest
from unittest.mock import patch

# Provide minimal httpx stub to import agent in environments without httpx installed
if "httpx" not in sys.modules:
    class _DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args, **kwargs):
            return False

        def post(self, *args, **kwargs):
            raise RuntimeError("httpx stub")

    sys.modules["httpx"] = types.SimpleNamespace(Client=_DummyClient)

if "fastapi" not in sys.modules:
    class _HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    sys.modules["fastapi"] = types.SimpleNamespace(HTTPException=_HTTPException)

from dashboard.server.agents.daily_report_v2.orchestrator import run_pipeline


class OrchestratorSoftFailTest(unittest.TestCase):
    def test_soft_fail_row_level(self):
        rows = [
            {"rowKey": "r1", "orgId": "O1", "upperOrg": "U1", "target": 1, "actual": 0, "won_group_json_compact": {}},
            {"rowKey": "r2", "orgId": "O2", "upperOrg": "U2", "target": 1, "actual": 0, "won_group_json_compact": {}},
        ]

        def fake_run(req, variant, debug, nocache=False):
            if req.orgId == "O1":
                return {"likelihood": "HIGH"}
            raise RuntimeError("boom")

        with patch("dashboard.server.agents.daily_report_v2.orchestrator.TargetAttainmentAgent.run", side_effect=fake_run), \
            patch("dashboard.server.agents.daily_report_v2.orchestrator.PartReportAgent.run", return_value={"summary": "ok"}), \
            patch("dashboard.server.agents.daily_report_v2.orchestrator.DailyRollupAgent.run", return_value={"rollup": "ok"}):
            result = run_pipeline("daily.part_rollup", {"rows": rows}, variant="offline", debug=False, nocache=True)

        self.assertIsInstance(result, dict)
        self.assertIn("rows", result)
        self.assertEqual(len(result["rows"]), 2)
        self.assertNotIn("__meta", result)
        row_map = {r["rowKey"]: r["output"] for r in result["rows"]}
        self.assertIn("likelihood", row_map["r1"])
        self.assertIn("error", row_map["r2"])
        self.assertNotIn("__meta", row_map["r1"])
        self.assertNotIn("__meta", row_map["r2"])


if __name__ == "__main__":
    unittest.main()
