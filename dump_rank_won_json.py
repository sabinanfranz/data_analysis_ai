#!/usr/bin/env python3
"""
Fetch top-N 2025 Won-ranked organizations (filtered by size) and dump their
`/orgs/{orgId}/won-groups-json` payloads into individual txt files prefixed
with the rank (e.g., `1_조직명.txt`) under `org_dataset/ranking`, and into
industry-prefixed files (e.g., `IT서비스_조직명.txt`) under `org_dataset/industry`
by looking up 업종 구분(대) from the local `organization` table. Intended to be
run against the local FastAPI backend (`uvicorn dashboard.server.main:app --reload`).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Iterable

import requests


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "unknown"


def fetch_json(session: requests.Session, url: str, *, params: Dict | None = None, retries: int = 3, delay: float = 1.0):
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            if attempt == retries:
                raise
            time.sleep(delay)


def resolve_ranking_output_path(org_name: str, org_id: str, rank: int, out_dir: Path, used_names: Dict[str, str]) -> Path:
    base = sanitize_filename(org_name)
    candidate = base
    if used_names.get(candidate) and used_names[candidate] != org_id:
        candidate = f"{base}_{org_id}"
    used_names[candidate] = org_id
    return out_dir / f"{rank}_{candidate}.txt"


def resolve_industry_output_path(
    org_name: str, org_id: str, industry: str, out_dir: Path, used_names: Dict[str, str]
) -> Path:
    base = sanitize_filename(org_name)
    industry_prefix = sanitize_filename(industry or "미분류")
    candidate = f"{industry_prefix}_{base}"
    if used_names.get(candidate) and used_names[candidate] != org_id:
        candidate = f"{candidate}_{org_id}"
    used_names[candidate] = org_id
    return out_dir / f"{candidate}.txt"


def load_industry_map(db_path: Path, org_ids: Iterable[str]) -> Dict[str, str]:
    ids = [oid for oid in dict.fromkeys(org_ids) if oid]
    if not ids:
        return {}
    if not db_path.exists():
        print(f"[warn] DB not found for industry lookup: {db_path}", file=sys.stderr)
        return {}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        print(f"[warn] Failed to open DB {db_path}: {exc}", file=sys.stderr)
        return {}

    placeholders = ",".join("?" for _ in ids)
    sql = (
        'SELECT id, COALESCE("업종 구분(대)", "업종") as industry '
        f"FROM organization WHERE id IN ({placeholders})"
    )
    try:
        rows = conn.execute(sql, tuple(ids)).fetchall()
    except Exception as exc:
        print(f"[warn] Failed to query organization table for industries: {exc}", file=sys.stderr)
        return {}
    finally:
        conn.close()

    result: Dict[str, str] = {}
    for row in rows:
        industry = row["industry"]
        if industry is None:
            continue
        result[str(row["id"])] = str(industry)
    missing = set(ids) - set(result)
    if missing:
        print(f"[warn] Missing industry rows for {len(missing)} orgs in DB", file=sys.stderr)
    return result


def iter_top_orgs(items: Iterable[dict], limit: int) -> Iterable[dict]:
    count = 0
    for item in items:
        if count >= limit:
            break
        yield item
        count += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dump won-groups JSON for top 2025 Won-ranked orgs.")
    parser.add_argument("--api-base-url", default="http://localhost:8000/api", help="FastAPI base URL (default: %(default)s)")
    parser.add_argument("--size", default="대기업", help='Organization size filter for ranking (default: "대기업")')
    parser.add_argument("--limit", type=int, default=100, help="How many ranked orgs to export (default: 100)")
    parser.add_argument(
        "--output-dir",
        default="org_dataset/ranking",
        help="Directory to write ranked txt files (default: org_dataset/ranking)",
    )
    parser.add_argument(
        "--industry-output-dir",
        default="org_dataset/industry",
        help="Directory to write industry-prefixed txt files (default: org_dataset/industry)",
    )
    parser.add_argument(
        "--db-path",
        default="salesmap_latest.db",
        help="SQLite DB path containing organization table for industry lookup (default: %(default)s)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files instead of skipping")
    parser.add_argument("--delay", type=float, default=0.0, help="Sleep seconds between org fetches (default: 0)")
    args = parser.parse_args(argv)

    base = args.api_base_url.rstrip("/")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    industry_dir = Path(args.industry_output_dir)
    industry_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    try:
        rank_resp = fetch_json(session, f"{base}/rank/2025-deals", params={"size": args.size})
    except Exception as exc:
        print(f"[error] Failed to fetch rank data: {exc}", file=sys.stderr)
        return 1

    rank_items = rank_resp.get("items") or []
    top_items = list(iter_top_orgs(rank_items, args.limit))
    print(f"[info] Retrieved {len(rank_items)} ranked orgs (size={args.size}). Exporting top {len(top_items)}.")

    industry_map = load_industry_map(Path(args.db_path), [item.get("orgId") or item.get("org_id") or "" for item in top_items])

    ranking_used_names: Dict[str, str] = {}
    industry_used_names: Dict[str, str] = {}
    failures: list[tuple[str, str, str]] = []
    ranking_saved = 0
    ranking_skipped = 0
    industry_saved = 0
    industry_skipped = 0

    for rank, item in enumerate(top_items, start=1):
        org_id = item.get("orgId") or item.get("org_id") or ""
        org_name = item.get("orgName") or item.get("org_name") or org_id or "unknown"
        if not org_id:
            failures.append(("missing_id", org_name, "rank item missing orgId"))
            continue

        industry = (industry_map.get(org_id) or "").strip() or "미분류"

        ranking_path = resolve_ranking_output_path(org_name, org_id, rank, out_dir, ranking_used_names)
        industry_path = resolve_industry_output_path(org_name, org_id, industry, industry_dir, industry_used_names)

        ranking_needs_write = args.overwrite or not ranking_path.exists()
        industry_needs_write = args.overwrite or not industry_path.exists()
        if not ranking_needs_write:
            ranking_skipped += 1
        if not industry_needs_write:
            industry_skipped += 1
        if not (ranking_needs_write or industry_needs_write):
            continue

        try:
            payload = fetch_json(session, f"{base}/orgs/{org_id}/won-groups-json")
        except Exception as exc:
            failures.append((org_id, org_name, str(exc)))
            continue

        if ranking_needs_write:
            try:
                with ranking_path.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                ranking_saved += 1
            except Exception as exc:
                failures.append((org_id, org_name, f"ranking write failed: {exc}"))
        if industry_needs_write:
            try:
                with industry_path.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                industry_saved += 1
            except Exception as exc:
                failures.append((org_id, org_name, f"industry write failed: {exc}"))

        if args.delay > 0:
            time.sleep(args.delay)

    print(
        f"[done] Saved {ranking_saved} ranking files to {out_dir} "
        f"(skipped existing: {ranking_skipped})."
    )
    print(
        f"[done] Saved {industry_saved} industry files to {industry_dir} "
        f"(skipped existing: {industry_skipped})."
    )
    if failures:
        print("[warn] Failures:")
        for org_id, org_name, reason in failures:
            print(f"  - {org_id} ({org_name}): {reason}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
