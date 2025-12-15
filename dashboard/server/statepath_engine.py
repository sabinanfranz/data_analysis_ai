from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

ONLINE_COURSE_FORMATS = {"구독제(온라인)", "선택구매(온라인)", "포팅"}
YEAR_ORDER = ["2024", "2025"]
BUCKET_ORDER = ["Ø", "P5", "P4", "P3", "P2", "P1", "P0", "S0"]
HRD_KEYWORDS = [
    "HRD",
    "HR",
    "인사",
    "피플",
    "경영지원",
    "CHO",
    "PEOPLE",
    "TALENT",
    "인재",
    "교육",
    "육성",
    "러닝",
    "LEARNING",
    "L&D",
    "아카데미",
    "연수",
    "인력개발",
    "인력지원",
    "기업문화",
    "경영관리",
    "경력개발",
    "사업지원",
    "Human",
    "성장지원",
    "인재개발",
    "조직문화",
]


def normalize_text(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def is_missing_text(val: Any) -> bool:
    return normalize_text(val) == ""


def amount_to_eok(val: Any) -> float:
    try:
        num = float(val)
    except (TypeError, ValueError):
        return 0.0
    return num / 1e8


def infer_lane(upper_org: Any) -> str:
    text = normalize_text(upper_org)
    if not text or text == "미입력":
        return "BU"
    upper = text.upper()
    for kw in HRD_KEYWORDS:
        if kw.upper() in upper:
            return "HRD"
    return "BU"


def infer_rail_from_deal(deal: Dict[str, Any]) -> str:
    fmt = deal.get("course_format") or deal.get("format") or ""
    if isinstance(fmt, str) and fmt in ONLINE_COURSE_FORMATS:
        return "ONLINE"
    return "OFFLINE"


def extract_year(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return None


def bucket_company(amount_eok: float) -> str:
    if amount_eok <= 0:
        return "Ø"
    if amount_eok < 0.1:
        return "P5"
    if amount_eok < 0.25:
        return "P4"
    if amount_eok < 0.5:
        return "P3"
    if amount_eok < 1.0:
        return "P2"
    if amount_eok < 2.0:
        return "P1"
    if amount_eok < 10.0:
        return "P0"
    return "S0"


def bucket_rail(amount_eok: float) -> str:
    # rail 버킷은 회사 구간의 절반 임계값 사용
    if amount_eok <= 0:
        return "Ø"
    if amount_eok < 0.05:
        return "P5"
    if amount_eok < 0.125:
        return "P4"
    if amount_eok < 0.25:
        return "P3"
    if amount_eok < 0.5:
        return "P2"
    if amount_eok < 1.0:
        return "P1"
    if amount_eok < 5.0:
        return "P0"
    return "S0"


def rail_cell_key(lane: str, rail: str) -> str:
    return f"{lane}_{rail}"


def extract_group_agg(group: Dict[str, Any]) -> Dict[str, Any]:
    upper_org = group.get("upper_org") or group.get("upperOrg")
    lane = infer_lane(upper_org)
    # base structure
    amounts: Dict[str, Dict[str, float]] = {y: {"ONLINE": 0.0, "OFFLINE": 0.0} for y in YEAR_ORDER}

    summary = group.get("counterparty_summary") or {}
    has_summary = False
    summary_years: set[str] = set()
    if isinstance(summary, dict):
        won_by_year = summary.get("won_amount_by_year") or {}
        online_by_year = summary.get("won_amount_online_by_year") or {}
        offline_by_year = summary.get("won_amount_offline_by_year") or {}
        for year in YEAR_ORDER:
            if year in won_by_year or year in online_by_year or year in offline_by_year:
                summary_years.add(year)
                total = amount_to_eok(won_by_year.get(year))
                online = amount_to_eok(online_by_year.get(year))
                offline = amount_to_eok(offline_by_year.get(year))
                if total > 0 or online > 0 or offline > 0:
                    has_summary = True
                amounts[year]["ONLINE"] += online
                amounts[year]["OFFLINE"] += offline
                # total은 online/offline 합으로 간접 검증

    # deals fallback per year lacking summary data
    deals = group.get("deals") or []
    if isinstance(deals, list):
        for deal in deals:
            if not isinstance(deal, dict):
                continue
            status = deal.get("status")
            if status != "Won":
                continue
            year = (
                extract_year(deal.get("contract_date"))
                or extract_year(deal.get("start_date"))
                or extract_year(deal.get("created_at"))
                or extract_year(deal.get("expected_date"))
            )
            if year not in YEAR_ORDER:
                continue
            if year in summary_years:
                continue
            amount_val = deal.get("amount")
            amount_num = float(amount_val) if _is_number(amount_val) else None
            if (amount_num is None or math.isclose(amount_num, 0.0)) and _is_number(deal.get("expected_amount")):
                amount_num = float(deal.get("expected_amount"))
            if amount_num is None or amount_num <= 0:
                continue
            rail = infer_rail_from_deal(deal)
            amounts[year][rail] += amount_to_eok(amount_num)

    return {"upper_org": upper_org, "lane": lane, "amounts": amounts}


def aggregate_company(group_aggs: List[Dict[str, Any]]) -> Dict[str, Any]:
    cells = {y: {"HRD_ONLINE": 0.0, "HRD_OFFLINE": 0.0, "BU_ONLINE": 0.0, "BU_OFFLINE": 0.0} for y in YEAR_ORDER}
    for agg in group_aggs:
        lane = agg["lane"]
        amounts = agg["amounts"]
        for year in YEAR_ORDER:
            online = amounts[year]["ONLINE"]
            offline = amounts[year]["OFFLINE"]
            cells[year][rail_cell_key(lane, "ONLINE")] += online
            cells[year][rail_cell_key(lane, "OFFLINE")] += offline
    return cells


def build_state(company_cells: Dict[str, Dict[str, float]], year: str) -> Dict[str, Any]:
    cells = company_cells.get(year, {})
    hrd_online = cells.get("HRD_ONLINE", 0.0)
    hrd_offline = cells.get("HRD_OFFLINE", 0.0)
    bu_online = cells.get("BU_ONLINE", 0.0)
    bu_offline = cells.get("BU_OFFLINE", 0.0)
    total = hrd_online + hrd_offline + bu_online + bu_offline
    online_total = hrd_online + bu_online
    offline_total = hrd_offline + bu_offline
    hrd_total = hrd_online + hrd_offline
    bu_total = bu_online + bu_offline
    state_cells = {
        "HRD_ONLINE": {"amt_eok": hrd_online, "bucket": bucket_rail(hrd_online)},
        "HRD_OFFLINE": {"amt_eok": hrd_offline, "bucket": bucket_rail(hrd_offline)},
        "BU_ONLINE": {"amt_eok": bu_online, "bucket": bucket_rail(bu_online)},
        "BU_OFFLINE": {"amt_eok": bu_offline, "bucket": bucket_rail(bu_offline)},
    }
    return {
        "year": year,
        "total_eok": total,
        "online_eok": online_total,
        "offline_eok": offline_total,
        "hrd_eok": hrd_total,
        "bu_eok": bu_total,
        "bucket": bucket_company(total),
        "bucket_online": bucket_rail(online_total),
        "bucket_offline": bucket_rail(offline_total),
        "cells": state_cells,
    }


def build_path(state_2024: Dict[str, Any], state_2025: Dict[str, Any]) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []

    def compare_bucket(cell: str, prev: str, curr: str) -> None:
        if prev == curr:
            return
        if prev == "Ø" and curr != "Ø":
            events.append({"type": "OPEN", "cell": cell, "from": prev, "to": curr})
        elif prev != "Ø" and curr == "Ø":
            events.append({"type": "CLOSE", "cell": cell, "from": prev, "to": curr})
        elif BUCKET_ORDER.index(curr) > BUCKET_ORDER.index(prev):
            events.append({"type": "SCALE_UP", "cell": cell, "from": prev, "to": curr})
        else:
            events.append({"type": "SCALE_DOWN", "cell": cell, "from": prev, "to": curr})

    for cell in ["HRD_ONLINE", "HRD_OFFLINE", "BU_ONLINE", "BU_OFFLINE"]:
        prev = state_2024["cells"][cell]["bucket"]
        curr = state_2025["cells"][cell]["bucket"]
        compare_bucket(cell, prev, curr)

    if state_2024["bucket"] != state_2025["bucket"]:
        events.append(
            {
                "type": "COMPANY_SCALE_CHANGE",
                "from": state_2024["bucket"],
                "to": state_2025["bucket"],
            }
        )
    if state_2024["bucket_online"] != state_2025["bucket_online"]:
        events.append(
            {
                "type": "RAIL_SCALE_CHANGE",
                "rail": "ONLINE",
                "from": state_2024["bucket_online"],
                "to": state_2025["bucket_online"],
            }
        )
    if state_2024["bucket_offline"] != state_2025["bucket_offline"]:
        events.append(
            {
                "type": "RAIL_SCALE_CHANGE",
                "rail": "OFFLINE",
                "from": state_2024["bucket_offline"],
                "to": state_2025["bucket_offline"],
            }
        )

    return {
        "from_state_code": state_2024["bucket"],
        "to_state_code": state_2025["bucket"],
        "events": events,
        "seed": infer_seed(state_2024, state_2025),
    }


def infer_seed(state_2024: Dict[str, Any], state_2025: Dict[str, Any]) -> str:
    h24 = state_2024["hrd_eok"]
    b24 = state_2024["bu_eok"]
    h25 = state_2025["hrd_eok"]
    b25 = state_2025["bu_eok"]
    if h24 > 0 and b24 <= 0 and b25 > 0:
        return "H→B"
    if b24 > 0 and h24 <= 0 and h25 > 0:
        return "B→H"
    if (h24 <= 0 and b24 <= 0) and (h25 > 0 and b25 > 0):
        return "SIMUL"
    return "NONE"


def qa_checks(
    state_2024: Dict[str, Any],
    state_2025: Dict[str, Any],
    group_aggs: List[Dict[str, Any]],
    org_summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    flags: List[str] = []
    if state_2024["total_eok"] <= 0 and state_2025["total_eok"] <= 0:
        flags.append("no_won_amount")
    if org_summary:
        won_by_year = org_summary.get("won_amount_by_year") or {}
        org_2025 = amount_to_eok(won_by_year.get("2025"))
        company_2025 = state_2025["total_eok"]
        if org_2025 and not math.isclose(org_2025, company_2025, rel_tol=0.05):
            flags.append("org_summary_mismatch_2025")
    return {
        "flags": flags,
        "checks": {
          "y2024_ok": state_2024["total_eok"] >= 0,
          "y2025_ok": state_2025["total_eok"] >= 0,
        },
    }


# -------------------------- Recommendation layer --------------------------
def infer_next_objective_type(events: List[Dict[str, Any]], state_2025: Dict[str, Any]) -> str:
    if any(ev["type"] in ("CLOSE", "SCALE_DOWN") for ev in events):
        return "RETENTION"
    has_open_cell = any(v["bucket"] == "Ø" for v in state_2025["cells"].values())
    if has_open_cell:
        return "OPEN"
    return "SCALE_UP"


def pick_next_target_cell(state_2025: Dict[str, Any]) -> str:
    scores: List[Tuple[str, float]] = []
    for cell, data in state_2025["cells"].items():
        amt = data["amt_eok"]
        bucket = data["bucket"]
        if bucket == "Ø":
            score = 100.0
        else:
            score = max(0.0, 10.0 - BUCKET_ORDER.index(bucket)) + max(0.0, 5.0 - amt)
        scores.append((cell, score))
    scores.sort(key=lambda x: (-x[1], x[0]))
    return scores[0][0] if scores else "BU_ONLINE"


def recommend_counterparties(group_aggs: List[Dict[str, Any]], target_cell: str) -> List[Dict[str, Any]]:
    lane_target, rail_target = target_cell.split("_")
    opposites = {"ONLINE": "OFFLINE", "OFFLINE": "ONLINE"}
    target_rail_opposite = opposites.get(rail_target, "OFFLINE")

    def totals(agg: Dict[str, Any], year: str) -> float:
        return agg["amounts"][year]["ONLINE"] + agg["amounts"][year]["OFFLINE"]

    groups_sorted = sorted(group_aggs, key=lambda g: totals(g, "2025"), reverse=True)
    if not groups_sorted:
        return []
    pick_ids = set()
    result: List[Dict[str, Any]] = []

    def as_entry(rank: str, agg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "rank": rank,
            "group_id": agg.get("upper_org"),
            "upper_org": agg.get("upper_org"),
            "lane": agg.get("lane"),
            "amt_2024_eok": totals(agg, "2024"),
            "amt_2025_eok": totals(agg, "2025"),
            "online_2025_eok": agg["amounts"]["2025"]["ONLINE"],
            "offline_2025_eok": agg["amounts"]["2025"]["OFFLINE"],
        }

    # A: current sponsor
    first = groups_sorted[0]
    result.append(as_entry("A", first))
    pick_ids.add(first.get("upper_org"))

    # B: adjacent sponsor
    b_candidate = None
    for g in groups_sorted:
        if g.get("upper_org") in pick_ids:
            continue
        if g.get("lane") != lane_target:
            continue
        if g["amounts"]["2025"][target_rail_opposite] > 0:
            b_candidate = g
            break
    if not b_candidate:
        for g in groups_sorted:
            if g.get("upper_org") in pick_ids:
                continue
            if g.get("lane") == lane_target:
                b_candidate = g
                break
    if not b_candidate:
        b_candidate = first
    result.append(as_entry("B", b_candidate))
    pick_ids.add(b_candidate.get("upper_org"))

    # C: bridge sponsor (신규 2025 우선)
    new_candidates = [
        g
        for g in groups_sorted
        if g.get("upper_org") not in pick_ids
        and g["amounts"]["2024"]["ONLINE"] + g["amounts"]["2024"]["OFFLINE"] <= 0
        and (g["amounts"]["2025"]["ONLINE"] + g["amounts"]["2025"]["OFFLINE"]) > 0
    ]
    if new_candidates:
        c_candidate = new_candidates[0]
    else:
        c_candidate = None
        for g in groups_sorted[1:3]:
            if g.get("upper_org") in pick_ids:
                continue
            c_candidate = g
            break
        if not c_candidate:
            c_candidate = first
    result.append(as_entry("C", c_candidate))

    return result


ACTION_TEMPLATES = {
    "OPEN": "신규 셀 오픈: 대상 셀을 위한 첫 Won 딜을 설계하세요.",
    "CLOSE": "이탈 셀 복구: 잃은 셀을 원인 분석 후 재오픈 계획 수립.",
    "SCALE_UP": "규모 확장: 성장한 셀의 추가 업셀 기회를 확보합니다.",
    "SCALE_DOWN": "축소 대응: 감소 원인 파악 후 방어 플랜 수립.",
    "COMPANY_SCALE_CHANGE": "회사 등급 변화: 회사 총액 변화에 맞춰 전략 재정렬.",
    "RAIL_SCALE_CHANGE": "채널 변화: 온라인/오프라인 비중 변화를 점검합니다.",
}


def build_action_play_top3(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    plays: List[Dict[str, Any]] = []
    for ev in events:
        t = ev.get("type")
        if t in seen:
            continue
        seen.add(t)
        text = ACTION_TEMPLATES.get(t)
        if text:
            plays.append({"type": t, "text": text})
        if len(plays) >= 3:
            break
    return plays


# -------------------------- Entrypoint --------------------------
def build_statepath(compact_json: Dict[str, Any]) -> Dict[str, Any]:
    org = compact_json.get("organization") or {}
    groups = compact_json.get("groups") or []
    group_aggs = [extract_group_agg(g) for g in groups]
    company_cells = aggregate_company(group_aggs)
    state_2024 = build_state(company_cells, "2024")
    state_2025 = build_state(company_cells, "2025")
    path = build_path(state_2024, state_2025)
    target_cell = pick_next_target_cell(state_2025)
    ops = {
        "next_objective_type": infer_next_objective_type(path["events"], state_2025),
        "next_target_cell": target_cell,
        "target_counterparties": recommend_counterparties(group_aggs, target_cell),
        "action_play_top3": build_action_play_top3(path["events"]),
    }
    qa = qa_checks(state_2024, state_2025, group_aggs, org.get("summary"))
    return {
        "company_name": org.get("name") or org.get("id"),
        "year_states": {"2024": state_2024, "2025": state_2025},
        "path_2024_to_2025": path,
        "ops_reco": ops,
        "qa": qa,
    }


def _is_number(val: Any) -> bool:
    try:
        float(val)
        return True
    except Exception:
        return False
