import unittest

from dashboard.server.agents.daily_report_v2.compaction import RowOutputCompactor, build_part_inputs, MAX_STR_LEN


class CompactionTest(unittest.TestCase):
    def test_allowlist_and_trim(self):
        long_text = "x" * (MAX_STR_LEN + 50)
        output = {
            "likelihood": "HIGH",
            "one_line": long_text,
            "top_reasons": ["reason1", "r" * 600],
            "flags": ["f1", "f2"],
            "numbers": {"target": 1, "actual": 0},
            "unexpected": "should be removed",
            "__meta": {"debug": True},
        }
        compacted = RowOutputCompactor.compact(output, debug=False)
        self.assertIn("likelihood", compacted)
        self.assertIn("one_line", compacted)
        self.assertLessEqual(len(compacted["one_line"]), MAX_STR_LEN + 20)
        self.assertNotIn("unexpected", compacted)
        self.assertNotIn("__meta", compacted)
        self.assertEqual(compacted["top_reasons"][0], "reason1")
        self.assertLessEqual(len(compacted["top_reasons"][1]), MAX_STR_LEN + 20)

    def test_error_row_retains_error(self):
        output = {"error": "something bad", "raw": "secret"}
        compacted = RowOutputCompactor.compact(output, debug=False)
        self.assertIn("error", compacted)
        self.assertNotIn("raw", compacted)

    def test_build_part_inputs_groups_and_min_fields(self):
        rows = [
            {"rowKey": "rk1", "orgId": "O1", "upperOrg": "U1", "tier": "T1", "target": 10, "actual": 5},
            {"rowKey": "rk2", "orgId": "O2", "upperOrg": "U2", "tier": "T2", "target": 20, "actual": 15},
        ]
        outputs = [{"likelihood": "HIGH"}, {"error": "fail"}]
        part_inputs = build_part_inputs(rows, outputs)
        self.assertEqual(len(part_inputs), 2)
        first = part_inputs[0]
        self.assertIn("rows", first)
        self.assertIn("row_agent_output_json", first["rows"][0])


if __name__ == "__main__":
    unittest.main()
