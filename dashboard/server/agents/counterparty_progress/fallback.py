from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Tuple

from .schema import CounterpartyProgressInputV1

RECENT_DAYS = 60


def _parse_yyyy_mm_dd(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _money_brief(amount: float) -> str:
    try:
        a = float(amount or 0)
    except Exception:
        a = 0.0
    if a >= 100_000_000:
        return f"{a/100_000_000:.1f}억"
    if a >= 10_000:
        return f"{a/10_000:.0f}만"
    return f"{a:.0f}원"


def _compute_counts(payload: CounterpartyProgressInputV1) -> Tuple[int, int]:
    open_cnt = int(payload.signals.open_deals_cnt or 0)
    won_cnt = int(payload.signals.won_deals_cnt or 0)
    if open_cnt == 0 and won_cnt == 0 and payload.top_deals:
        for d in payload.top_deals:
            st = (d.status or "").strip()
            if st in ("Lost", "Convert"):
                continue
            if st == "Won":
                won_cnt += 1
            else:
                open_cnt += 1
    return open_cnt, won_cnt


def decide_progress_status(payload: CounterpartyProgressInputV1) -> str:
    as_of = _parse_yyyy_mm_dd(payload.as_of) or date.today()
    cutoff = as_of - timedelta(days=RECENT_DAYS)

    target = float(payload.target_2026 or 0)
    actual = float(payload.actual_2026 or 0)

    open_cnt, won_cnt = _compute_counts(payload)

    last_act = _parse_yyyy_mm_dd(payload.signals.last_activity_date)
    has_recent_last_act = bool(last_act and last_act >= cutoff)

    has_recent_memo = False
    for m in payload.recent_memos:
        md = _parse_yyyy_mm_dd(m.date)
        if md and md >= cutoff:
            has_recent_memo = True
            break

    has_recent_activity = has_recent_last_act or has_recent_memo

    has_won = won_cnt > 0
    ratio = (actual / target) if target > 0 else None

    if has_won:
        weak_and_stalled = (
            target > 0
            and ratio is not None
            and ratio < 0.10
            and actual <= 0
            and open_cnt == 0
            and not has_recent_activity
        )
        if weak_and_stalled:
            return "ONGOING"
        if (actual > 0) or (open_cnt > 0) or has_recent_activity or (target <= 0):
            return "GOOD_PROGRESS"
        return "ONGOING"

    if (actual > 0) or (open_cnt > 0) or has_recent_activity:
        return "ONGOING"

    return "NO_PROGRESS"


def decide_confidence(payload: CounterpartyProgressInputV1) -> str:
    score = 0
    if payload.top_deals:
        score += 2
    if payload.recent_memos:
        score += 2
    if payload.signals.last_activity_date:
        score += 1
    if (payload.target_2026 or 0) > 0:
        score += 1
    if (payload.actual_2026 or 0) > 0:
        score += 1

    if score >= 5:
        return "HIGH"
    if score >= 3:
        return "MED"
    return "LOW"


def build_fallback_result(payload: CounterpartyProgressInputV1) -> dict:
    as_of = payload.as_of
    target = float(payload.target_2026 or 0)
    actual = float(payload.actual_2026 or 0)
    status = decide_progress_status(payload)
    confidence = decide_confidence(payload)

    open_cnt, won_cnt = _compute_counts(payload)

    ratio_str = ""
    if target > 0:
        try:
            ratio_str = f" (진척 {actual/target*100:.0f}%)"
        except Exception:
            ratio_str = ""

    if status == "NO_PROGRESS":
        headline = "2026 진척 신호가 부족해 파이프라인 재가동이 필요함"
        actions = [
            "담당자 접점을 1회 생성하고(콜/메일) 니즈·예산·일정 3가지를 확인하라.",
            "다음 미팅 또는 제안 일정 1개를 확정해 후속 액션을 고정하라.",
        ]
    elif status == "ONGOING":
        headline = "논의/파이프라인은 있으나 2026 체결 확정은 제한적임"
        actions = [
            "가장 큰 오픈 딜 1건의 다음 스텝(결정권자·일정·승인)과 마감일을 합의하라.",
            "최근 메모/딜 업데이트를 정리해 핵심 이슈 1개를 질문 리스트로 전환하라.",
        ]
    else:
        headline = "2026 체결 신호가 확인되며 확장·클로징 중심으로 진행 중"
        actions = [
            "확정/체결된 범위를 기준으로 추가 차수·확장 스코프를 제안하라.",
            "성과·레퍼런스를 3줄로 정리해 내부 공유 및 후속 소개 경로를 확보하라.",
        ]

    if len(actions) == 2 and status != "NO_PROGRESS" and target > 0 and actual == 0:
        actions.append("목표 대비 잔여 갭을 메우기 위한 추가 파이프라인 후보 1~2개를 발굴하라.")

    if target > 0:
        b1 = f"2026 목표 {_money_brief(target)} 대비 현재 actual {_money_brief(actual)}{ratio_str}."
    else:
        b1 = f"2026 목표가 0으로 설정되어 있어 진척률 산정이 제한됨(현재 actual {_money_brief(actual)})."

    b2 = f"파이프라인 신호: 오픈 딜 {open_cnt}건, Won {won_cnt}건(상위 딜 {len(payload.top_deals)}건/최근 메모 {len(payload.recent_memos)}건)."

    last_act = _parse_yyyy_mm_dd(payload.signals.last_activity_date)
    if last_act:
        days = (_parse_yyyy_mm_dd(as_of) or date.today()) - last_act
        b3 = f"최근 활동일 {last_act.isoformat()} 기준으로 {days.days}일 경과했으며 입력 정보 범위 내에서만 판단함."
    else:
        b3 = "최근 활동일 정보가 없거나 제한적이어서 입력 정보 범위 내에서만 판단함."

    if confidence == "LOW" and "제한적" not in b3:
        b3 = "입력 데이터(딜/메모/활동)가 제한적이어서 입력 정보 범위 내에서만 판단함."

    evidence = [b1, b2, b3][:3]
    actions = actions[:3]

    return {
        "progress_status": status,
        "confidence": confidence,
        "headline": headline,
        "evidence_bullets": evidence,
        "recommended_actions": actions,
    }
