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

    def test_context_format_flags_md_and_json(self):
        payload = {
            "orgId": "ORG123",
            "orgName": "샘플회사",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            "target_2026": 100,
            "actual_2026": 50,
            "won_group_json_compact": {"schema_version": "won-groups-json/compact-v1", "groups": []},
        }

        os.environ["OPENAI_API_KEY"] = "dummy"

        # json mode
        os.environ["TARGET_ATTAINMENT_CONTEXT_FORMAT"] = "json"
        with patch(
            "dashboard.server.agents.target_attainment.agent._call_openai_chat_completions",
            return_value='{"likelihood":"HIGH"}',
        ):
            resp_json = self.client.post("/api/llm/target-attainment?include_input=1", json=payload)
        self.assertEqual(resp_json.status_code, 200)
        data_json = resp_json.json()
        self.assertIn("__llm_input", data_json)
        self.assertEqual(data_json["__llm_input"].get("context_format"), "json")

        # md mode
        os.environ["TARGET_ATTAINMENT_CONTEXT_FORMAT"] = "md"
        with patch(
            "dashboard.server.agents.target_attainment.agent._call_openai_chat_completions",
            return_value='{"likelihood":"HIGH"}',
        ):
            resp_md = self.client.post("/api/llm/target-attainment?include_input=1", json=payload)
        self.assertEqual(resp_md.status_code, 200)
        data_md = resp_md.json()
        self.assertIn("__llm_input", data_md)
        self.assertEqual(data_md["__llm_input"].get("context_format"), "md")

    def test_md_conversion_failure_falls_back_to_json(self):
        os.environ["OPENAI_API_KEY"] = "dummy"
        os.environ["TARGET_ATTAINMENT_CONTEXT_FORMAT"] = "md"
        payload = {
            "orgId": "ORG123",
            "orgName": "샘플회사",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            "target_2026": 100,
            "actual_2026": 50,
            "won_group_json_compact": None,
        }
        with patch(
            "dashboard.server.agents.target_attainment.agent._call_openai_chat_completions",
            return_value='{"likelihood":"HIGH"}',
        ):
            resp = self.client.post("/api/llm/target-attainment?include_input=1", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("__llm_input", data)
        self.assertEqual(data["__llm_input"].get("context_source"), "json_fallback")

    def test_markdown_only_request_and_priority_over_json(self):
        os.environ["OPENAI_API_KEY"] = "dummy"
        os.environ["TARGET_ATTAINMENT_CONTEXT_FORMAT"] = "json"  # should be ignored when request_md provided

        md_body = "# Hello\n- item"
        payload_md_only = {
            "orgId": "ORG123",
            "orgName": "샘플회사",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            "target_2026": 100,
            "actual_2026": 50,
            "won_group_markdown": md_body,
        }

        with patch(
            "dashboard.server.agents.target_attainment.agent._call_openai_chat_completions",
            return_value='{"likelihood":"HIGH"}',
        ):
            resp_md = self.client.post("/api/llm/target-attainment?include_input=1", json=payload_md_only)
        self.assertEqual(resp_md.status_code, 200)
        data_md = resp_md.json()
        self.assertIn("__llm_input", data_md)
        self.assertEqual(data_md["__llm_input"].get("context_source"), "request_md")
        self.assertTrue(data_md["__llm_input"].get("context_md_head", "").startswith("# Hello"))

        # both present -> markdown wins
        payload_both = {**payload_md_only, "won_group_json_compact": {"schema_version": "won-groups-json/compact-v1", "groups": []}}
        with patch(
            "dashboard.server.agents.target_attainment.agent._call_openai_chat_completions",
            return_value='{"likelihood":"HIGH"}',
        ):
            resp_both = self.client.post("/api/llm/target-attainment?include_input=1", json=payload_both)
        self.assertEqual(resp_both.status_code, 200)
        data_both = resp_both.json()
        self.assertIn("__llm_input", data_both)
        self.assertEqual(data_both["__llm_input"].get("context_source"), "request_md")

    def test_validation_requires_one_of_markdown_or_json(self):
        os.environ["OPENAI_API_KEY"] = "dummy"
        payload = {
            "orgId": "ORG123",
            "orgName": "샘플회사",
            "upperOrg": "샘플카운터파티",
            "mode": "offline",
            "target_2026": 100,
            "actual_2026": 50,
            # both inputs missing
        }
        resp = self.client.post("/api/llm/target-attainment", json=payload)
        self.assertIn(resp.status_code, {400, 422})
        data = resp.json()
        self.assertTrue("detail" in data or "error" in data)


if __name__ == "__main__":
    unittest.main()
