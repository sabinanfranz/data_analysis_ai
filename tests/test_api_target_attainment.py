import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.server.main import app


class TargetAttainmentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_returns_json_when_llm_not_configured(self):
        os.environ.pop("OPENAI_API_KEY", None)
        payload = {
            "orgId": "ORG123",
            "orgName": "샘플회사",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            "target_2026": 1000000000,
            "actual_2026": 250000000,
            "won_group_json_compact": {"schema_version": "won-groups-json/compact-v1", "groups": []},
        }
        resp = self.client.post("/api/llm/target-attainment", json=payload)
        self.assertIn("application/json", resp.headers.get("content-type", ""))
        data = resp.json()
        self.assertIsInstance(data, dict)
        self.assertIn("error", data)

    def test_validation_error_is_json(self):
        os.environ.pop("OPENAI_API_KEY", None)
        payload = {
            "orgId": "ORG123",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            # target_2026 missing
            "actual_2026": 250000000,
            "won_group_json_compact": {"schema_version": "won-groups-json/compact-v1", "groups": []},
        }
        resp = self.client.post("/api/llm/target-attainment", json=payload)
        self.assertIn("application/json", resp.headers.get("content-type", ""))
        data = resp.json()
        self.assertIsInstance(data, dict)
        self.assertIn("detail", data)

    def test_payload_too_large_returns_413(self):
        os.environ["OPENAI_API_KEY"] = "dummy"
        big_blob = "x" * 600_000
        payload = {
            "orgId": "ORG123",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            "target_2026": 1,
            "actual_2026": 0,
            "won_group_json_compact": {"schema_version": "won-groups-json/compact-v1", "blob": big_blob},
        }
        resp = self.client.post("/api/llm/target-attainment", json=payload)
        self.assertEqual(resp.status_code, 413)
        data = resp.json()
        self.assertIn("detail", data)
        self.assertEqual(data["detail"].get("error"), "PAYLOAD_TOO_LARGE")

    def test_debug_meta_present_when_debug_flag(self):
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
        with patch(
            "dashboard.server.agents.target_attainment.agent._call_openai_chat_completions",
            return_value='{"likelihood":"HIGH"}',
        ):
            resp = self.client.post("/api/llm/target-attainment?debug=1", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("__meta", data)
        self.assertIn("input_hash", data["__meta"])
        self.assertIn("payload_bytes", data["__meta"])
        self.assertIn("prompt_hash", data["__meta"])

        # debug off -> no __meta
        with patch(
            "dashboard.server.agents.target_attainment.agent._call_openai_chat_completions",
            return_value='{"likelihood":"HIGH"}',
        ):
            resp2 = self.client.post("/api/llm/target-attainment", json=payload)
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertNotIn("__meta", data2)


if __name__ == "__main__":
    unittest.main()
