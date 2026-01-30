import os
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from dashboard.server.main import app
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi not installed in this environment")
class NocacheApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_nocache_flag_propagates(self):
        os.environ["OPENAI_API_KEY"] = "dummy"
        payload = {
            "orgId": "ORG123",
            "orgName": "샘플회사",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            "target_2026": 100,
            "actual_2026": 50,
            "won_group_json_compact": {"schema_version": "won-groups-json/compact-v1", "groups": []},
        }
        called = []

        def fake_run(req, *, variant, debug, nocache=False, payload_bytes=None):
            called.append(nocache)
            return {"ok": True}

        with patch("dashboard.server.agents.target_attainment.agent.TargetAttainmentAgent.run", side_effect=fake_run):
            resp = self.client.post("/api/llm/target-attainment?nocache=1", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(called and called[0] is True)


if __name__ == "__main__":
    unittest.main()
