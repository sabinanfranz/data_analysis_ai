import sys
import types
import unittest
from unittest.mock import patch

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

from dashboard.server.agents.daily_rollup.agent import DailyRollupAgent


class DailyRollupAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        import os
        os.environ["OPENAI_API_KEY"] = "dummy"

    def _input(self):
        return {
            "variant_key": "offline",
            "date": "2026-01-01",
            "parts": [
                {"part_name": "P1", "part_report_json": {"summary": "ok"}},
                {"part_name": "P2", "part_report_json": {"error": "x"}},
            ],
        }

    def test_basic_run_and_meta(self):
        agent = DailyRollupAgent()
        with patch("dashboard.server.agents.daily_rollup.agent._call_openai_chat_completions", return_value='{"rollup":"ok"}'):
            out = agent.run(self._input(), variant="offline", debug=False, nocache=True)
        self.assertIsInstance(out, dict)
        self.assertNotIn("__meta", out)

        with patch("dashboard.server.agents.daily_rollup.agent._call_openai_chat_completions", return_value='{"rollup":"ok"}'):
            out2 = agent.run(self._input(), variant="offline", debug=True, nocache=True)
        self.assertIn("__meta", out2)
        self.assertIn("prompt_hash", out2["__meta"])

    def test_repair(self):
        agent = DailyRollupAgent()
        calls = iter(["broken", '{"fixed":true}'])

        def fake_call(*args, **kwargs):
            return next(calls)

        with patch("dashboard.server.agents.daily_rollup.agent._call_openai_chat_completions", side_effect=fake_call):
            out = agent.run(self._input(), variant="offline", debug=True, nocache=True)
        self.assertIsInstance(out, dict)
        self.assertNotEqual(out.get("error"), "LLM_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
