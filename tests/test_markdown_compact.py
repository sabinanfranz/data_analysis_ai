from dashboard.server.markdown_compact import summarize_memos, won_groups_compact_to_markdown


def _make_memo(idx: int, date: str, ts: str | None = None, text: str = "") -> dict:
    return {
        "date": date,
        "created_at_ts": ts,
        "text": text or f"메모 {idx}",
    }


def test_summarize_memos_uses_created_at_ts_and_limits_to_10():
    memos = []
    # created_at_ts should win over date
    memos.append(_make_memo(1, "2025-01-02", "2025-01-02T23:00:00Z", "late ts"))
    memos.append(_make_memo(2, "2025-01-02", "2025-01-02T22:00:00Z", "early ts"))
    # date fallback when no ts
    memos.append(_make_memo(3, "2025-01-03", None, "no ts newer date"))
    # add extra 14 memos to exceed limit
    for i in range(4, 18):
        memos.append(_make_memo(i, f"2024-12-{i:02d}", None, f"old-{i}"))

    result = summarize_memos(memos, limit=10, max_chars=240, redact_phone=True)

    assert result["count"] == 17
    assert len(result["lines"]) == 10  # limited to latest 10
    # first line should be the latest created_at_ts even though date is older than 2025-01-03 entry
    assert "late ts" in result["lines"][0]
    # second line should be the earlier timestamp on the same date
    assert "early ts" in result["lines"][1]
    # the 2025-01-03 memo (no ts) should appear after the timestamped ones
    assert "2025-01-03" in result["lines"][2]
    # numbering starts at 1)
    assert result["lines"][0].startswith("1)")
    assert result["lines"][-1].startswith("10)")


def test_won_groups_compact_to_markdown_includes_top10_memos_and_count():
    memos = [
        _make_memo(idx, f"2025-01-{idx:02d}", f"2025-01-{idx:02d}T12:00:00Z", f"text-{idx}")
        for idx in range(1, 18)
    ]
    compact = {
        "organization": {"id": "org1", "name": "Org1", "summary": {"won_amount_by_year": {"2023": 0, "2024": 0, "2025": 0}}},
        "groups": [
            {
                "upper_org": "UpperA",
                "team": "TeamA",
                "counterparty_summary": {"won_amount_by_year": {"2023": 0, "2024": 0, "2025": 0}},
                "people": [{"id": "p1", "name": "Alice", "team": "TeamA", "title": "", "edu_area": "", "signals": "", "memos": []}],
                "deals": [
                    {
                        "id": "d1",
                        "name": "Deal1",
                        "people_id": "p1",
                        "status": "Won",
                        "amount": 1000,
                        "contract_date": "2025-01-01",
                        "memos": memos,
                    }
                ],
            }
        ],
    }

    md = won_groups_compact_to_markdown(compact)

    assert "(총 17개)" in md  # total count preserved
    # only top 10 should be rendered (numbers 1) through 10))
    assert "10)" in md
    assert "11)" not in md
    # latest memo text (idx 17) should appear
    assert "text-17" in md.split("(총 17개)")[-1]
