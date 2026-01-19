from __future__ import annotations

import re
from typing import Any, Dict, List

from ..core.canonicalize import format_eok

BLOCKER_REGEX: Dict[str, re.Pattern] = {
    "BUDGET": re.compile(r"(?:예산|budget|동결|삭감|재무|비용\s?승인|budget\s?freeze|capex|opex)", re.IGNORECASE),
    "APPROVAL_DELAY": re.compile(r"(?:승인|결재|품의|구매|조달|발주|법무|계약서?|내부\s?검토|프로세스|rfp|입찰)", re.IGNORECASE),
    "DECISION_MAKER": re.compile(r"(?:의사\s?결정|결정권자?|권한|임원|스폰서|챔피언|담당자\s?(?:변경|바뀜)|퇴사|이직|조직\s?개편)", re.IGNORECASE),
    "COMPETITOR": re.compile(r"(?:경쟁사?|타사|다른\s?업체|기존\s?업체|대체|벤더|내재화|in[-\s]?house|인하우스)", re.IGNORECASE),
    "NO_RESPONSE": re.compile(r"(?:무응답|회신\s?없음|답\s?없음|연락\s?두절|연락\s?안됨|잠수|미팅\s?(?:불가|취소)|노쇼|no\s?response)", re.IGNORECASE),
    "PRICE_TERM": re.compile(r"(?:가격|단가|견적|비싸|할인|조건|지불\s?조건|정산|payment\s?term|마진)", re.IGNORECASE),
    "SCHEDULE_RESOURCE": re.compile(r"(?:일정|스케줄|리소스|인력|운영|여력|기간|착수|킥오프|start|kick\s?off|kickoff)", re.IGNORECASE),
    "LOW_PRIORITY": re.compile(r"(?:우선\s?순위|후순위|지금\s?아님|나중에|추후|보류|홀드|내년|later)", re.IGNORECASE),
    "FIT_UNCLEAR": re.compile(r"(?:니즈|요구\s?사항|적합|맞춤|범위|정의\s?필요|불명확|fit|scope)", re.IGNORECASE),
}

BLOCKER_PRIORITY = [
    "APPROVAL_DELAY",
    "DECISION_MAKER",
    "BUDGET",
    "PRICE_TERM",
    "NO_RESPONSE",
    "COMPETITOR",
    "SCHEDULE_RESOURCE",
    "LOW_PRIORITY",
    "FIT_UNCLEAR",
]

ACTION_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "offline": {
        "PIPELINE_ZERO": ["의사결정자 맵핑", "니즈 재발굴", "시퀀스·세미나로 접점 생성"],
        "BUDGET": ["예산 라인/승인 프로세스 확인", "ROI·성과 사례 제시", "단계형 제안으로 진입"],
        "DECISION_MAKER": ["조직도/스폰서 재확인", "챔피언 대체군 확보"],
        "APPROVAL_DELAY": ["구매·법무 체크리스트 확보", "마감 타임라인 합의"],
        "LOW_PRIORITY": ["임원/사업 아젠다와 연결 재정의", "타이밍/로드맵 재설계"],
        "COMPETITOR": ["비교표+레퍼런스 제시", "차별 포인트 1페이지 제안"],
        "FIT_UNCLEAR": ["니즈 인터뷰", "맞춤 커리큘럼/파일럿 제안"],
        "NO_RESPONSE": ["관계 리셋(다른 접점)", "내부 소개/추천 루트 탐색"],
        "PRICE_TERM": ["패키징/옵션 재구성", "조건 재설계/분리 제안"],
        "SCHEDULE_RESOURCE": ["일정 후보 3개 제안", "운영 리소스 사전 확보"],
    },
    "online": {},  # 채워지지 않은 항목은 offline 템플릿을 재사용한다.
}


def _get_actions(blocker: str, mode_key: str) -> List[str]:
    mode_map = ACTION_TEMPLATES.get(mode_key) or {}
    actions = mode_map.get(blocker)
    if actions:
        return actions
    return ACTION_TEMPLATES["offline"].get(blocker, [])


def fallback_blockers(pipeline_zero: bool, memo_text: str) -> List[str]:
    if pipeline_zero:
        return ["PIPELINE_ZERO"]
    scores: Dict[str, int] = {}
    for label, pattern in BLOCKER_REGEX.items():
        matches = pattern.findall(memo_text or "")
        if matches:
            scores[label] = len(matches)
    if not scores:
        return ["FIT_UNCLEAR"]
    sorted_labels = sorted(scores.items(), key=lambda kv: (-kv[1], BLOCKER_PRIORITY.index(kv[0]) if kv[0] in BLOCKER_PRIORITY else 99))
    result = [lbl for lbl, _ in sorted_labels[:3]]
    return result or ["FIT_UNCLEAR"]


def fallback_evidence(row: Any, blockers: List[str]) -> List[str]:
    tgt = (row.get("target_2026") if isinstance(row, dict) else None) or 0
    conf = (row.get("confirmed_2026") if isinstance(row, dict) else None) or 0
    exp = (row.get("expected_2026") if isinstance(row, dict) else None) or 0
    cov_ratio = None
    if isinstance(row, dict):
        cov_ratio = row.get("coverage_ratio", row.get("coverage"))
    gap = (row.get("gap") if isinstance(row, dict) else None) or 0
    min_cov = 0
    if isinstance(row, dict):
        min_cov = row.get("min_cov_current_month", 0) or 0
    bullets = []
    bullets.append(f"2026 타겟 {format_eok(tgt)}억 대비 확정 {format_eok(conf)}억, 예상 {format_eok(exp)}억으로 gap {format_eok(gap)}억이 남아 있습니다.")
    if tgt > 0 and cov_ratio is not None:
        bullets.append(f"현재 커버리지는 {cov_ratio*100:.1f}%로 이번 달 최소 기대치({min_cov*100:.1f}%) 대비 부족합니다.")
    else:
        bullets.append("타겟이 0이거나 커버리지 계산 불가하여 gap 중심으로 판단해야 합니다.")
    if row.get("pipeline_zero"):
        bullets.append("2026 확정/예상 파이프라인이 0으로 설정돼 있습니다.")
    else:
        bullets.append("데이터 품질·연락/메모 근거는 추가 생성 예정입니다.")
    return bullets[:3]


def fallback_actions(blockers: List[str], mode_key: str = "offline") -> List[str]:
    mode = mode_key if mode_key in ACTION_TEMPLATES else "offline"
    actions: List[str] = []
    for blk in blockers:
        for act in _get_actions(blk, mode):
            actions.append(act)
            if len(actions) >= 3:
                break
        if len(actions) >= 3:
            break
    if not actions:
        actions = ["핵심 의사결정자와 목적/예산/일정 재합의", "최소 파일럿/샘플 제안으로 진입"]
    return actions[:3]

