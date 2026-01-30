import unittest

from dashboard.server.agents.core import json_guard


class JsonGuardTest(unittest.TestCase):
    def test_parse_json_object_plain(self):
        text = '{"a":1,"b":"c"}'
        self.assertEqual(json_guard.parse_json_object(text), {"a": 1, "b": "c"})

    def test_parse_json_object_code_fence(self):
        text = "```json\n{\"x\":2}\n```"
        self.assertEqual(json_guard.parse_json_object(text), {"x": 2})

    def test_parse_json_object_with_noise(self):
        text = "blah prefix {\"z\":3} trailing words"
        self.assertEqual(json_guard.parse_json_object(text), {"z": 3})

    def test_ensure_json_object_or_error_when_fail(self):
        text = "not a json"
        result = json_guard.ensure_json_object_or_error(text)
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertIn("raw", result)
        self.assertLessEqual(len(result["raw"]), json_guard.MAX_RAW_LEN + 20)


if __name__ == "__main__":
    unittest.main()
