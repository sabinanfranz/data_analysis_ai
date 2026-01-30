import sys
import types
import unittest
from unittest.mock import patch

# Stub external deps if missing
if "httpx" not in sys.modules:
    class _Timeout(Exception):
        pass
    class _ReadTimeout(_Timeout):
        pass
    class _ConnectTimeout(_Timeout):
        pass
    class _TimeoutException(_Timeout):
        pass
    class _DummyClient:
        def __init__(self, *args, **kwargs): ...
    sys.modules["httpx"] = types.SimpleNamespace(
        ReadTimeout=_ReadTimeout,
        ConnectTimeout=_ConnectTimeout,
        TimeoutException=_TimeoutException,
        HTTPStatusError=Exception,
        Client=_DummyClient,
    )

if "fastapi" not in sys.modules:
    class _HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    sys.modules["fastapi"] = types.SimpleNamespace(HTTPException=_HTTPException)

import httpx

from dashboard.server.agents.target_attainment.agent import (
    _call_openai_chat_completions,
    _post_openai_once,
    TargetAttainmentAgent,
)
from dashboard.server.agents.target_attainment.schema import TargetAttainmentRequest


class TargetAttainmentTimeoutTest(unittest.TestCase):
    def test_retry_on_timeout_succeeds(self):
        side_effects = [httpx.ReadTimeout("timeout"), {"choices": [{"message": {"content": "ok"}}]}]
        with patch("dashboard.server.agents.target_attainment.agent._post_openai_once", side_effect=side_effects) as mock_post:
            out = _call_openai_chat_completions(
                [{"role": "user", "content": "hi"}],
                model="m",
                base_url="http://x",
                api_key="k",
                timeout_total=120,
                temperature=0,
                max_tokens=10,
                retry=1,
            )
        self.assertEqual(out, "ok")
        self.assertEqual(mock_post.call_count, 2)
        first_timeout = mock_post.call_args_list[0].kwargs["timeout"]
        self.assertAlmostEqual(first_timeout, 60, delta=0.1)

    def test_retry_timeout_returns_error_json(self):
        with patch("dashboard.server.agents.target_attainment.agent._post_openai_once", side_effect=httpx.ReadTimeout("timeout")):
            import os
            os.environ["OPENAI_API_KEY"] = "dummy"
            req = TargetAttainmentRequest(
                orgId="O1",
                orgName="N",
                upperOrg="U",
                mode="offline",
                target_2026=1,
                actual_2026=0,
                won_group_json_compact={"groups": []},
            )
            agent = TargetAttainmentAgent()
            out = agent.run(req, variant="offline", debug=False, nocache=True)
        self.assertIsInstance(out, dict)
        self.assertEqual(out.get("error"), "LLM_CALL_TIMEOUT")
        self.assertIn("timeout_total_s", out)
        self.assertIn("attempts", out)


if __name__ == "__main__":
    unittest.main()
