from dashboard.server.json_compact import compact_won_groups_json


def test_compact_removes_html_body_everywhere():
    raw = {
        "organization": {"id": "org1", "name": "Org1"},
        "groups": [
            {
                "upper_org": "U1",
                "team": "T1",
                "people": [
                    {"id": "p1", "name": "Alice", "memos": [{"date": "2025-01-01", "text": "hi", "htmlBody": "<p>hi</p>"}]}
                ],
                "deals": [
                    {
                        "id": "d1",
                        "status": "Won",
                        "contract_date": "2025-01-01",
                        "amount": 100,
                        "people_id": "p1",
                        "memos": [
                            {"date": "2025-01-01", "cleanText": {"text": "deal memo"}, "htmlBody": "<div>body</div>"},
                        ],
                    }
                ],
            }
        ],
    }

    compact = compact_won_groups_json(raw)

    def _contains_html_body(obj):
        if isinstance(obj, dict):
            if "htmlBody" in obj:
                return True
            return any(_contains_html_body(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_contains_html_body(v) for v in obj)
        return False

    assert not _contains_html_body(compact)
