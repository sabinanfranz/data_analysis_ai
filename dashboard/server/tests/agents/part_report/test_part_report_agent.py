import sys
import types
import unittest
from unittest.mock import patch

# Stub external deps if missing
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

from dashboard.server.agents.part_report.agent import PartReportAgent


class PartReportAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        import os
        os.environ["OPENAI_API_KEY"] = "dummy"

    def _sample_input(self):
        return {
            "variant_key": "offline",
            "part_name": "P1",
            "rows": [
                {"orgId": "O1", "upperOrg": "U1", "tier": "T1", "target": 10, "actual": 5, "row_agent_output_json": {"likelihood": "HIGH"}},
                {"orgId": "O2", "upperOrg": "U1", "tier": "T2", "target": 20, "actual": 3, "row_agent_output_json": {"error": "fail"}},
            ],
        }

    def test_run_success_and_meta(self):
        agent = PartReportAgent()
        with patch("dashboard.server.agents.part_report.agent._call_openai_chat_completions", return_value='{"summary":"ok"}'):
            out = agent.run(self._sample_input(), variant="offline", debug=False, nocache=True)
        self.assertIsInstance(out, dict)
        self.assertNotIn("__meta", out)

        with patch("dashboard.server.agents.part_report.agent._call_openai_chat_completions", return_value='{"summary":"ok"}'):
            out2 = agent.run(self._sample_input(), variant="offline", debug=True, nocache=True)
        self.assertIn("__meta", out2)
        self.assertIn("prompt_hash", out2["__meta"])

    def test_repair_path(self):
        agent = PartReportAgent()
        calls = iter(["not json", '{"fixed":true}'])

        def fake_call(*args, **kwargs):
            return next(calls)

        # above will still use real call unless patched; patch now
        with patch("dashboard.server.agents.part_report.agent._call_openai_chat_completions", side_effect=fake_call):
            out = agent.run(self._sample_input(), variant="offline", debug=True, nocache=True)
        self.assertIsInstance(out, dict)
        self.assertNotEqual(out.get("error"), "LLM_NOT_CONFIGURED")
        self.assertIn("__meta", out)

    def test_nocache_forces_call(self):
        agent = PartReportAgent()
        with patch("dashboard.server.agents.part_report.agent._call_openai_chat_completions", return_value='{"a":1}') as mock_call:
            agent.run(self._sample_input(), variant="offline", debug=False, nocache=True)
            agent.run(self._sample_input(), variant="offline", debug=False, nocache=True)
        self.assertGreaterEqual(mock_call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
