import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Set

def parse_webforms_field(raw: Any) -> Iterable[str]:
    if raw is None:
        return []
    if isinstance(raw, (dict, list)):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except Exception:
            return []
    if isinstance(data, list):
        ids: list[str] = []
        for item in data:
            if isinstance(item, dict):
                val = item.get("id") or item.get("name")
                if val:
                    ids.append(str(val))
            elif item:
                ids.append(str(item))
        return ids
    return []

def main() -> None:
    parser = argparse.ArgumentParser(description="Collect unique webform IDs from people referenced by deals")
    parser.add_argument("--db-path", default="salesmap_latest.db", help="Path to SQLite DB")
    parser.add_argument("--limit-sample", type=int, default=10, help="Sample size to show")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        people_ids = {row[0] for row in conn.execute('SELECT DISTINCT peopleId FROM deal WHERE peopleId IS NOT NULL AND TRIM(peopleId) <> ""')}
        if not people_ids:
            print("No peopleId found in deal table.")
            return
        placeholders = ",".join("?" for _ in people_ids)
        query = f'SELECT id, "제출된 웹폼 목록" AS webforms FROM people WHERE id IN ({placeholders})'
        webform_ids: Set[str] = set()
        missing_column = False
        try:
            for row in conn.execute(query, tuple(people_ids)):
                webform_ids.update(parse_webforms_field(row["webforms"]))
        except sqlite3.OperationalError as exc:
            if "제출된 웹폼 목록" in str(exc):
                missing_column = True
            else:
                raise
        if missing_column:
            print("Column '제출된 웹폼 목록' not found in people table.")
            return
        print(f"Unique webform IDs count: {len(webform_ids)}")
        if args.limit_sample > 0:
            sample = sorted(webform_ids)[: args.limit_sample]
            print("Sample:", sample)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
