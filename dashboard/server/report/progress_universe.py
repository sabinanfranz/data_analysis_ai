from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

from ..agents.counterparty_card.agent import gather_deals_for_counterparty, gather_memos
from ..agents.counterparty_progress.schema import CounterpartyKeyV1, CounterpartyProgressInputV1
from ..database import (
    _normalize_counterparty_upper,
    get_rank_2025_top100_counterparty_dri,
    get_won_groups_json,
)
from ..deal_normalizer import MODE_OFFLINE, _connect, build_counterparty_risk_report
from ..json_compact import compact_won_groups_json


@dataclass
class CounterpartyKey:
    org_id: str
    org_name: str
    upper_org: str
    tier: str | None = None


def _key(org_id: str, upper_org: str) -> str:
    return f"{str(org_id or '').strip()}||{_normalize_counterparty_upper(upper_org)}"


def _as_date(val: str) -> date:
    try:
        return date.fromisoformat(val[:10])
    except Exception:
        return date.today()


def _to_float(val: object) -> float:
    try:
        return float(val or 0)
    except Exception:
        return 0.0


def _filter_compact_by_upper(viewer: Dict, upper: str) -> Dict:
    if not viewer:
        return {}
    upper_norm = _normalize_counterparty_upper(upper)
    groups = viewer.get("groups") or []
    filtered = [g for g in groups if _normalize_counterparty_upper(g.get("upper_org")) == upper_norm]
    return {**viewer, "groups": filtered}


_CACHE: Dict[Tuple[str, str, Path], Dict[str, object]] = {}
_COMPACT_CACHE: Dict[Tuple[str, Path], Dict] = {}


def _load_compact(org_id: str, db_path: Path) -> Dict:
    cache_key = (org_id, db_path)
    if cache_key in _COMPACT_CACHE:
        return _COMPACT_CACHE[cache_key]
    try:
        raw = get_won_groups_json(org_id=org_id, db_path=db_path)
        compact = compact_won_groups_json(raw)
    except Exception:
        compact = {}
    _COMPACT_CACHE[cache_key] = compact
    return compact


def _load_base(as_of: str, mode: str, snapshot_db_path: Path) -> Dict[str, object]:
    cache_key = (as_of, mode, snapshot_db_path)
    cached = _CACHE.get(cache_key)
    if cached:
        return cached

    dri = get_rank_2025_top100_counterparty_dri(size="전체", limit=None, offset=0, db_path=snapshot_db_path, debug=False)
    dri_rows = dri.get("rows", []) if isinstance(dri, dict) else []
    dri_map: Dict[str, Dict] = {}
    for r in dri_rows:
        k = _key(r.get("orgId"), r.get("upperOrg"))
        if k and k not in dri_map:
            dri_map[k] = r

    # Risk report rows (rule outputs already applied)
    report = build_counterparty_risk_report(as_of_date=as_of, db_path=snapshot_db_path, mode_key=mode)
    risk_rows = report.get("counterparties", []) if isinstance(report, dict) else []
    risk_map: Dict[str, Dict] = {}
    for r in risk_rows:
        k = _key(r.get("organizationId"), r.get("counterpartyName"))
        if k and k not in risk_map:
            risk_map[k] = r

    db_mtime = snapshot_db_path.stat().st_mtime
    db_hash = hashlib.sha256(str(db_mtime).encode("utf-8")).hexdigest()[:16]

    data = {
        "dri_rows": dri_rows,
        "dri_map": dri_map,
        "risk_rows": risk_rows,
        "risk_map": risk_map,
        "db_hash": db_hash,
    }
    _CACHE[cache_key] = data
    return data


def build_progress_universe(as_of: str, mode: str, snapshot_db_path: Path) -> List[CounterpartyKey]:
    base = _load_base(as_of, mode, snapshot_db_path)
    keys: Dict[str, CounterpartyKey] = {}

    # 1) risk report universe
    for r in base["risk_rows"]:
        org_id = str(r.get("organizationId") or "").strip()
        upper = _normalize_counterparty_upper(r.get("counterpartyName"))
        if not org_id or not upper:
            continue
        k = _key(org_id, upper)
        if k in keys:
            continue
        keys[k] = CounterpartyKey(
            org_id=org_id,
            org_name=(r.get("organizationName") or org_id).strip() or org_id,
            upper_org=upper,
            tier=r.get("tier"),
        )

    # 2) override-only universe (mode-specific)
    for r in base["dri_rows"]:
        org_id = str(r.get("orgId") or "").strip()
        upper = _normalize_counterparty_upper(r.get("upperOrg"))
        if not org_id or not upper:
            continue
        if mode == MODE_OFFLINE:
            if not r.get("target26OfflineIsOverride"):
                continue
        else:
            if not r.get("target26OnlineIsOverride"):
                continue
            if _to_float(r.get("target26Online")) == 0:
                continue
        k = _key(org_id, upper)
        if k in keys:
            continue
        keys[k] = CounterpartyKey(
            org_id=org_id,
            org_name=(r.get("orgName") or org_id).strip() or org_id,
            upper_org=upper,
            tier=r.get("orgTier"),
        )

    return list(keys.values())


def build_l1_payload(key: CounterpartyKey, as_of: str, mode: str, snapshot_db_path: Path) -> CounterpartyProgressInputV1:
    base = _load_base(as_of, mode, snapshot_db_path)
    mode_norm = "online" if mode == "online" else "offline"
    as_of_date = _as_date(as_of)
    key_str = _key(key.org_id, key.upper_org)

    dri_row = base["dri_map"].get(key_str)
    risk_row = base["risk_map"].get(key_str)

    def _build_deals() -> List[Dict]:
        deals_raw = risk_row.get("deals_top") if isinstance(risk_row, dict) else []
        if deals_raw:
            deals: List[Dict] = []
            for d in deals_raw[:10]:
                deal_id = d.get("deal_id") or d.get("id")
                name = d.get("deal_name") or d.get("name") or ""
                status = d.get("status")
                prob = d.get("possibility") or d.get("probability")
                deals.append(
                    {
                        "id": str(deal_id) if deal_id else "",
                        "name": name,
                        "status": status,
                        "probability": [prob] if prob else [],
                        "amount": _to_float(d.get("amount")),
                        "expected_amount": _to_float(d.get("expected_amount")),
                        "contract_date": d.get("contract_date"),
                        "expected_date": d.get("expected_close_date") or d.get("expected_date"),
                        "start_date": d.get("start_date"),
                        "course_format": d.get("course_format"),
                    }
                )
            return deals[:10]
        # Fallback: query directly
        with _connect(snapshot_db_path) as conn:
            deals = gather_deals_for_counterparty(conn, key.org_id, key.upper_org, mode_key=mode_norm)
        result: List[Dict] = []
        for d in deals[:10]:
            prob = d.get("possibility") or d.get("probability")
            result.append(
                {
                    "id": d.get("deal_id") or d.get("id") or "",
                    "name": d.get("deal_name") or d.get("name") or "",
                    "status": d.get("status"),
                    "probability": [prob] if prob else [],
                    "amount": _to_float(d.get("amount")),
                    "expected_amount": _to_float(d.get("expected_amount")),
                    "contract_date": d.get("contract_date"),
                    "expected_date": d.get("expected_close_date") or d.get("expected_date"),
                    "start_date": d.get("start_date"),
                    "course_format": d.get("course_format"),
                }
            )
        return result

    def _build_memos() -> List[Dict]:
        with _connect(snapshot_db_path) as conn:
            return gather_memos(conn, key.org_id, key.upper_org, as_of=as_of_date)

    def _signals(top_deals: List[Dict], memos: List[Dict]) -> Dict:
        open_cnt = 0
        won_cnt = 0
        for d in top_deals:
            st = (d.get("status") or "").strip()
            if st == "Won":
                won_cnt += 1
            elif st and st not in {"Convert", "Lost"}:
                open_cnt += 1
        last_activity = None
        if memos:
            last_activity = (memos[0].get("date") or "")[:10]
        return {"open_deals_cnt": open_cnt, "won_deals_cnt": won_cnt, "last_activity_date": last_activity, "dq_flags": []}

    top_deals = _build_deals()
    memos = _build_memos()

    target = 0.0
    actual = 0.0
    target_override = False
    if mode_norm == "offline":
        target = _to_float(dri_row.get("target26Offline") if dri_row else None)
        actual = _to_float(dri_row.get("cpOffline2026") if dri_row else None)
        target_override = bool(dri_row and dri_row.get("target26OfflineIsOverride"))
    else:
        target = _to_float(dri_row.get("target26Online") if dri_row else None)
        actual = _to_float(dri_row.get("cpOnline2026") if dri_row else None)
        target_override = bool(dri_row and dri_row.get("target26OnlineIsOverride"))

    if dri_row is None and risk_row:
        # Fallback to report numbers (coverage_2026 already includes confirmed+expected)
        target = _to_float(risk_row.get("target_2026"))
        cov = risk_row.get("coverage_2026")
        if cov is None:
            cov = _to_float(risk_row.get("confirmed_2026")) + _to_float(risk_row.get("expected_2026"))
        actual = _to_float(cov)

    viewer_compact = _filter_compact_by_upper(_load_compact(key.org_id, snapshot_db_path), key.upper_org)
    signals = _signals(top_deals, memos)

    return CounterpartyProgressInputV1(
        as_of=as_of,
        report_mode=mode_norm,
        counterparty_key=CounterpartyKeyV1(
            org_id=key.org_id,
            org_name=key.org_name,
            upper_org=key.upper_org,
            tier=key.tier,
        ),
        target_2026=target,
        actual_2026=actual,
        target_is_override=target_override,
        viewer_compact=viewer_compact or None,
        top_deals=top_deals,
        recent_memos=memos[:20],
        signals=signals,
    )


def build_l2_payload(scope: Dict[str, str], l1_outputs: List[Dict], dri_rows: List[Dict], as_of: str, mode: str):
    return {
        "schema_version": "group-progress-input/v1",
        "as_of": as_of,
        "report_mode": "online" if mode == "online" else "offline",
        "scope": scope,
        "rollup": {
            "target_sum_2026": 0,
            "actual_sum_2026": 0,
            "progress_ratio": None,
            "no_progress_cnt": 0,
            "ongoing_cnt": 0,
            "good_progress_cnt": 0,
        },
        "items": [],
    }
