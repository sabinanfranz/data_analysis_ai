import pathlib

def test_no_memo_get_createdAt_usage():
    path = pathlib.Path('dashboard/server/database.py')
    text = path.read_text(encoding='utf-8')
    assert 'memo.get("createdAt")' not in text, "memo.get(\"createdAt\") reintroduced in database.py"
