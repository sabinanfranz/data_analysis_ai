import unittest

from dashboard.server import statepath_engine as sp


class BucketAndLaneTest(unittest.TestCase):
    def test_bucket_company(self):
        self.assertEqual(sp.bucket_company(0), "Ø")
        self.assertEqual(sp.bucket_company(0.099), "P5")
        self.assertEqual(sp.bucket_company(0.1), "P4")
        self.assertEqual(sp.bucket_company(0.249), "P4")
        self.assertEqual(sp.bucket_company(0.25), "P3")
        self.assertEqual(sp.bucket_company(0.49), "P3")
        self.assertEqual(sp.bucket_company(0.5), "P2")
        self.assertEqual(sp.bucket_company(0.99), "P2")
        self.assertEqual(sp.bucket_company(1.0), "P1")
        self.assertEqual(sp.bucket_company(1.99), "P1")
        self.assertEqual(sp.bucket_company(2.0), "P0")
        self.assertEqual(sp.bucket_company(9.99), "P0")
        self.assertEqual(sp.bucket_company(10.0), "S0")

    def test_infer_lane(self):
        self.assertEqual(sp.infer_lane("HRD 부문"), "HRD")
        self.assertEqual(sp.infer_lane("인재개발원"), "HRD")
        self.assertEqual(sp.infer_lane("미입력"), "BU")


class StatePathBuildTest(unittest.TestCase):
    def test_statepath_from_compact_summary(self):
        compact = {
            "organization": {"id": "org-1", "name": "회사"},
            "groups": [
                {
                    "upper_org": "HRD Alpha",
                    "counterparty_summary": {
                        "won_amount_by_year": {"2025": 2_000_000_000},
                        "won_amount_online_by_year": {"2025": 1_000_000_000},
                        "won_amount_offline_by_year": {"2025": 1_000_000_000},
                    },
                },
                {
                    "upper_org": "BU Beta",
                    "counterparty_summary": {
                        "won_amount_by_year": {"2024": 1_000_000_000, "2025": 3_000_000_000},
                        "won_amount_online_by_year": {"2025": 2_000_000_000},
                        "won_amount_offline_by_year": {"2025": 1_000_000_000},
                    },
                },
            ],
        }
        item = sp.build_statepath(compact)
        states = item["year_states"]
        self.assertGreater(states["2025"]["total_eok"], 0)
        path_events = item["path_2024_to_2025"]["events"]
        self.assertTrue(any(ev["type"] == "OPEN" for ev in path_events))
        self.assertIn(item["ops_reco"]["next_objective_type"], {"OPEN", "SCALE_UP", "RETENTION"})

    def test_deal_fallback(self):
        compact = {
            "organization": {"id": "org-2", "name": "회사2"},
            "groups": [
                {
                    "upper_org": "BU",
                    "deals": [
                        {
                            "status": "Won",
                            "contract_date": "2025-01-01",
                            "amount": 100_000_000,
                            "course_format": "집합교육",
                        }
                    ],
                }
            ],
        }
        item = sp.build_statepath(compact)
        self.assertGreater(item["year_states"]["2025"]["total_eok"], 0)


if __name__ == "__main__":
    unittest.main()
