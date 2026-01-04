from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
import sqlite3

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional
    OpenAI = None  # type: ignore

from .prompt_loader import load_prompt

PROMPT_VERSION = "v1"
LLM_MODEL = "offline-fallback"
TOP_GAP_K = 20
TOP_DEALS_LIMIT = 10  # payload에는 상위 5개만 사용
PAYLOAD_DEALS_LIMIT = 5
MEMO_WINDOW_DAYS = 180
MEMO_LIMIT = 20
MEMO_TRIM_LEN = 1000
ONLINE_DEAL_FORMATS = {"구독제(온라인)", "선택구매(온라인)", "포팅"}

# LLM env configuration
def _clamp(val: Any, lo: float, hi: float, default: float) -> float:
    try:
        num = float(val)
    except Exception:
        return default
    return max(lo, min(hi, num))


LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_TIMEOUT = _clamp(os.getenv("LLM_TIMEOUT", 15), 5, 60, 15)
LLM_MAX_TOKENS = int(_clamp(os.getenv("LLM_MAX_TOKENS", 512), 128, 2048, 512))
LLM_TEMPERATURE = _clamp(os.getenv("LLM_TEMPERATURE", 0.2), 0.0, 1.0, 0.2)

# Prompts (fixed, 31.6)
SYSTEM_PROMPT_DEFAULT = """너는 B2B 세일즈 리스크 리포트 작성자이자 “근거/액션/블로커 생성기”다.

입력으로 1개 카운터파티에 대한 구조화 JSON(payload)이 주어진다.
너의 임무는 그 입력 JSON에 포함된 사실만 근거로, 지정된 스키마의 “순수 JSON”을 출력하는 것이다.

[절대 금지]
- 확률/성사율/매출/예측(미래 성과 추정) 금지
- 입력 JSON에 없는 사실을 만들어내는 행위(환각) 금지
- 외부 지식/추측/일반론으로 특정 사실을 단정 금지
- 메모 문장을 따옴표로 직접 인용 금지(요약만 가능)

[출력 형식 강제]
- 출력은 반드시 유효한 JSON 1개 객체만 허용한다. (설명 텍스트, 마크다운, 코드블록 금지)
- 출력 키는 정확히 다음 4개만 허용한다:
  1) risk_level
  2) top_blockers
  3) evidence_bullets
  4) recommended_actions
- risk_level 값은 반드시 다음 중 하나: "양호" | "보통" | "심각"
- top_blockers는 길이 0~3의 배열이며, 각 원소는 반드시 아래 10개 라벨 중 하나만 가능:
  "PIPELINE_ZERO" | "BUDGET" | "DECISION_MAKER" | "APPROVAL_DELAY" | "LOW_PRIORITY"
  | "COMPETITOR" | "FIT_UNCLEAR" | "NO_RESPONSE" | "PRICE_TERM" | "SCHEDULE_RESOURCE"
- evidence_bullets는 문자열 배열이며 길이가 정확히 3이어야 한다.
  각 bullet은 한국어 1문장이어야 하며, 최소 1개 bullet에는 입력 JSON의 수치(예: target_2026, confirmed_2026, expected_2026, gap, coverage, lost_90d_count, amount, 날짜 등)가 포함되어야 한다.
- recommended_actions는 문자열 배열이며 길이가 2~3이어야 한다.
  각 action은 한국어 1문장(명령형/행동형)이어야 하며, top_blockers와 논리적으로 정합적이어야 한다.

[중요 규칙]
- 입력 JSON의 risk_rule.rule_risk_level(규칙 결과)은 UI에서 우선 사용된다.
  가능하면 너의 risk_level도 rule_risk_level과 일치시키되,
  만약 다르게 출력한다면 evidence_bullets 중 1개에 “규칙상 리스크는 X로 분류됨”을 반드시 포함하라.
- coverage가 null 또는 "N/A"인 경우, coverage를 근거로 사용하지 말고 gap/pipeline/signal/memo 중심으로 근거를 제시하라.
- 정보가 부족하면 “부족하다”는 점 자체를 데이터 품질/연락/딜 상태 등의 형태로만 표현하고, 새로운 사실을 만들지 마라.
"""

USER_PROMPT_DEFAULT = """아래는 1개 카운터파티의 입력 payload(JSON)이다. 이 JSON에 없는 사실을 절대 만들지 말고, 오직 아래 출력 스키마에 맞는 “순수 JSON”만 출력하라.

[입력 payload]
{{PAYLOAD_JSON}}

[출력 스키마(키 고정)]
{
  "risk_level": "양호|보통|심각",
  "top_blockers": ["PIPELINE_ZERO|BUDGET|DECISION_MAKER|APPROVAL_DELAY|LOW_PRIORITY|COMPETITOR|FIT_UNCLEAR|NO_RESPONSE|PRICE_TERM|SCHEDULE_RESOURCE"],
  "evidence_bullets": ["...", "...", "..."],
  "recommended_actions": ["...", "..."]
}

[생성 규칙]
- evidence_bullets는 정확히 3개, 각 1문장. 최소 1개는 수치 근거를 포함하라.
- 가능하면 evidence_bullets 중 1개는 memos/signals(lost_90d, last_contact_date)을 요약해 반영하라(직접 인용 금지).
- recommended_actions는 2~3개, 각 1문장(명령형/행동형).
- top_blockers는 최대 3개. 반드시 10개 라벨 중에서만 선택.
- action은 blocker에 정합적으로 매핑하라(힌트: PIPELINE_ZERO/예산/승인/의사결정/경쟁/응답없음/가격/일정·리소스/우선순위/fit).
"""

REPAIR_PROMPT_DEFAULT = """너의 이전 출력은 유효한 JSON이 아니거나 스키마를 위반했다.
설명/마크다운/코드블록 없이, 오직 스키마에 맞는 “순수 JSON 1개 객체”만 다시 출력하라.
허용 키는 risk_level, top_blockers, evidence_bullets, recommended_actions 4개뿐이다.
"""

SYSTEM_PROMPT = load_prompt("system_prompt", SYSTEM_PROMPT_DEFAULT)
USER_PROMPT_TEMPLATE = load_prompt("user_prompt", USER_PROMPT_DEFAULT)
REPAIR_PROMPT = load_prompt("repair_prompt", REPAIR_PROMPT_DEFAULT)

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

BLOCKER_ACTIONS: Dict[str, List[str]] = {
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


def norm_str(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = unicodedata.normalize("NFC", s)
    return s


def _round6(x: float) -> float:
    d = Decimal(str(x)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return float(d)


def canonicalize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return _round6(obj)
    if isinstance(obj, str):
        return norm_str(obj)
    if isinstance(obj, list):
        return [canonicalize(v) for v in obj]
    if isinstance(obj, dict):
        items = []
        for k in sorted(obj.keys()):
            kk = norm_str(k) if isinstance(k, str) else str(k)
            items.append((kk, canonicalize(obj[k])))
        return {k: v for k, v in items}
    return norm_str(str(obj))


def canonical_json(payload: dict) -> str:
    canon = canonicalize(payload)
    return json.dumps(canon, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def compute_llm_input_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def select_candidates(rows: Sequence[Any], top_gap_k: int = TOP_GAP_K) -> List[Tuple[str, str]]:
    keys: List[Tuple[str, str]] = []
    base = [(r["organization_id"], r["counterparty_name"]) for r in rows if r["risk_level_rule"] in ("보통", "심각")]
    keys.extend(base)
    others = [
        (r["organization_id"], r["counterparty_name"], abs(r["gap"] or 0), r["target_2026"] or 0)
        for r in rows
        if (r["organization_id"], r["counterparty_name"]) not in keys
    ]
    others = [o for o in others if o[3] > 0]  # target>0만 추가 후보
    others.sort(key=lambda x: x[2], reverse=True)
    for org_id, cp, _gap, _t in others[:top_gap_k]:
        keys.append((org_id, cp))
    # dedupe preserving order
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def slugify(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", text)
    return slug[:200] if slug else "_"


def format_eok(val: float) -> str:
    try:
        num = float(val)
    except Exception:
        return "0.0"
    return f"{num / 1e8:.1f}"


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
    # row may be full counterparty row or risk_rule fragment; use .get to be tolerant
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


def fallback_actions(blockers: List[str]) -> List[str]:
    actions: List[str] = []
    for blk in blockers:
        for act in BLOCKER_ACTIONS.get(blk, []):
            actions.append(act)
            if len(actions) >= 3:
                break
        if len(actions) >= 3:
            break
    if not actions:
        actions = ["핵심 의사결정자와 목적/예산/일정 재합의", "최소 파일럿/샘플 제안으로 진입"]
    return actions[:3]


def load_cache(cache_path: Path, input_hash: str) -> Dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("meta", {}).get("llm_input_hash") == input_hash and data.get("meta", {}).get("prompt_version") == PROMPT_VERSION:
            return data.get("output")
    except Exception:
        return None
    return None


def save_cache(cache_path: Path, meta: Dict[str, Any], output: Dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "output": output}
    try:
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        return


def build_payload(row: Any, deals: List[Dict[str, Any]], memos: List[Dict[str, Any]], as_of: date) -> Dict[str, Any]:
    coverage_ratio = row["coverage_ratio"]
    coverage_ratio = None if coverage_ratio is None else _round6(float(coverage_ratio))
    payload = {
        "as_of_date": as_of.isoformat(),
        "counterparty_key": {
            "organizationId": row["organization_id"],
            "organizationName": row["organization_name"],
            "counterpartyName": row["counterparty_name"],
        },
        "tier": row["tier"],
        "risk_rule": {
            "rule_risk_level": row["risk_level_rule"],
            "pipeline_zero": bool(row["pipeline_zero"]),
            "min_cov_current_month": _round6(float(row["min_cov_current_month"] or 0)),
            "coverage": coverage_ratio,
            "gap": row["gap"],
            "target_2026": row["target_2026"],
            "confirmed_2026": row["confirmed_2026"],
            "expected_2026": row["expected_2026"],
        },
        "signals": {
            "last_contact_date": None,
            "lost_90d_count": 0,
            "lost_90d_reasons": [],
        },
        "top_deals_2026": deals[:PAYLOAD_DEALS_LIMIT],
        "memos": memos[:MEMO_LIMIT],
        "data_quality": {
            "unknown_year_deals": row.get("dq_year_unknown_cnt", 0) or 0,
            "unknown_amount_deals": row.get("dq_amount_parse_fail_cnt_2026", 0) or 0,
            "unclassified_counterparty_deals": 1 if row.get("excluded_by_quality") else 0,
        },
    }
    return payload


def gather_deals_for_counterparty(
    conn: sqlite3.Connection,
    org_id: str,
    counterparty_name: str,
) -> List[Dict[str, Any]]:
    """
    Fallback: deal_norm이 없을 때 deal+people을 직접 조회해 최소 필터로 2026 비온라인 상위 딜을 얻는다.
    규칙: status not in Convert/Lost, 과정포맷 온라인 3종 제외, deal_year=2026 추정.
    """
    def _parse_date(text: Any) -> str | None:
        if text is None:
            return None
        if isinstance(text, (date, datetime)):
            return text.date().isoformat() if isinstance(text, datetime) else text.isoformat()
        s = str(text).strip()
        if not s:
            return None
        if "T" in s:
            s = s.split("T", 1)[0]
        s = s.replace(".", "-").replace("/", "-")
        if " " in s:
            s = s.split(" ", 1)[0]
        try:
            if len(s) == 8 and s.isdigit():
                return datetime.strptime(s, "%Y%m%d").date().isoformat()
            return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
        except Exception:
            return None

    def _parse_amount(raw: Any) -> int:
        if raw is None:
            return 0
        try:
            s = str(raw).replace("₩", "").replace("원", "").replace(",", "").strip()
            return int(float(s))
        except Exception:
            return 0

    rows = conn.execute(
        """
        SELECT
            d.id AS deal_id,
            d."이름" AS deal_name,
            d."상태" AS status,
            d."성사 가능성" AS possibility,
            d."금액" AS amount_primary,
            d."예상 체결액" AS amount_fallback,
            d."과정포맷" AS process_format,
            d."계약 체결일" AS contract_signed_date,
            d."수주 예정일" AS expected_close_date,
            d."수강시작일" AS course_start_date,
            d."수강종료일" AS course_end_date,
            d."코스 ID" AS course_id_raw
        FROM deal d
        LEFT JOIN people p ON p.id = d.peopleId
        WHERE d.organizationId = ?
          AND COALESCE(p."소속 상위 조직",'') = ?
          AND d."상태" NOT IN ('Convert','Lost')
        """,
        (org_id, counterparty_name),
    ).fetchall()

    deals: List[Dict[str, Any]] = []
    for r in rows:
        pf = r["process_format"]
        is_nononline = (pf is None) or (str(pf).strip() not in ONLINE_DEAL_FORMATS)
        if not is_nononline:
            continue
        contract = _parse_date(r["contract_signed_date"])
        expected = _parse_date(r["expected_close_date"])
        start = _parse_date(r["course_start_date"])
        deal_year = None
        if start:
            deal_year = int(start[:4])
        elif contract or expected:
            deal_year = int((contract or expected)[:4])
        if deal_year != 2026:
            continue
        amount = _parse_amount(r["amount_primary"])
        if amount == 0:
            amount = _parse_amount(r["amount_fallback"])
        deals.append(
            {
                "deal_id": r["deal_id"],
                "deal_name": r["deal_name"],
                "status": r["status"],
                "possibility": r["possibility"],
                "amount": amount,
                "is_nononline": True,
                "deal_year": deal_year,
                "course_id_exists": bool(r["course_id_raw"]),
                "start_date": start,
                "end_date": _parse_date(r["course_end_date"]),
                "contract_date": contract,
                "expected_close_date": expected,
                "last_contact_date": None,
            }
        )
    deals.sort(key=lambda d: (-int(d.get("amount") or 0), d.get("deal_id") or ""))
    return deals[:TOP_DEALS_LIMIT]


def _dedupe_memos(memos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for m in memos:
        key = m.get("id") or (m.get("date"), m.get("source"), m.get("text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    return deduped


def gather_memos(
    conn: sqlite3.Connection,
    org_id: str,
    counterparty_name: str,
    as_of: date,
) -> List[Dict[str, Any]]:
    cutoff = (as_of - timedelta(days=MEMO_WINDOW_DAYS)).isoformat()
    memos: List[Dict[str, Any]] = []
    # org memos
    memos += [
        {"id": row["id"], "date": (row["createdAt"] or "")[:10], "source": "organization", "text": norm_str(row["text"] or "")}
        for row in conn.execute(
            "SELECT id, text, createdAt FROM memo WHERE organizationId = ? AND (createdAt IS NULL OR substr(createdAt,1,10) >= ?) ORDER BY createdAt DESC",
            (org_id, cutoff),
        ).fetchall()
    ]
    # deal memos (org-level, 180일)
    memos += [
        {"id": row["id"], "date": (row["createdAt"] or "")[:10], "source": "deal", "text": norm_str(row["text"] or "")}
        for row in conn.execute(
            """
            SELECT m.id, m.text, m.createdAt
            FROM memo m
            JOIN deal d ON d.id = m.dealId
            WHERE d.organizationId = ?
              AND (m.createdAt IS NULL OR substr(m.createdAt,1,10) >= ?)
            ORDER BY m.createdAt DESC
            """,
            (org_id, cutoff),
        ).fetchall()
    ]
    # people memos for this counterparty (people upper org)
    memos += [
        {"id": row["id"], "date": (row["createdAt"] or "")[:10], "source": "people", "text": norm_str(row["text"] or "")}
        for row in conn.execute(
            """
            SELECT m.id, m.text, m.createdAt
            FROM memo m
            JOIN people p ON p.id = m.peopleId
            WHERE p.organizationId = ?
              AND COALESCE(p."소속 상위 조직",'') = ?
              AND (m.createdAt IS NULL OR substr(m.createdAt,1,10) >= ?)
            ORDER BY m.createdAt DESC
            """,
            (org_id, counterparty_name, cutoff),
        ).fetchall()
    ]

    memos = _dedupe_memos(memos)
    memos.sort(key=lambda m: m.get("date") or "", reverse=True)
    trimmed: List[Dict[str, Any]] = []
    for m in memos[:MEMO_LIMIT]:
        text = m["text"][:MEMO_TRIM_LEN]
        trimmed.append({**m, "text": text})
    return trimmed


def run_llm_or_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    def _fallback(reason: str | None = None) -> Dict[str, Any]:
        blockers = fallback_blockers(payload["risk_rule"].get("pipeline_zero"), " ".join([m.get("text", "") for m in payload.get("memos", [])]))
        evidence = fallback_evidence(payload["risk_rule"], blockers)
        actions = fallback_actions(blockers)
        risk_level = payload["risk_rule"].get("rule_risk_level") or "보통"
        return {
            "risk_level": risk_level,
            "top_blockers": blockers,
            "evidence_bullets": evidence[:3],
            "recommended_actions": actions[:3],
            "fallback_used": True,
            "error": reason or None,
        }

    provider = LLM_PROVIDER
    api_key = OPENAI_API_KEY
    if provider != "openai" or not api_key or OpenAI is None:
        return _fallback("llm_disabled_or_missing_key")

    try:
        output = _call_openai(payload)
        output["fallback_used"] = False
        return output
    except Exception as exc:  # pragma: no cover - network dependent
        return _fallback(str(exc))


def _repair_json(bad_text: str) -> Dict[str, Any]:
    if OpenAI is None:
        raise RuntimeError("openai package not available")

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=LLM_BASE_URL or None)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": REPAIR_PROMPT},
    ]
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        timeout=LLM_TIMEOUT,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )
    text = completion.choices[0].message.content or ""
    return json.loads(text)


def _call_openai(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call OpenAI chat completion with fixed system/user prompts.
    """
    if OpenAI is None:
        raise RuntimeError("openai package not available")

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=LLM_BASE_URL or None)
    user_prompt = USER_PROMPT_TEMPLATE.replace(
        "{{PAYLOAD_JSON}}", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        timeout=LLM_TIMEOUT,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )
    text = completion.choices[0].message.content or ""
    try:
        return json.loads(text)
    except Exception:
        # 1st repair attempt
        return _repair_json(text)

def generate_llm_cards(
    conn: sqlite3.Connection,
    risk_rows: Sequence[Dict[str, Any]],
    as_of: date,
    db_hash: str,
    cache_dir: Path = Path("report_cache/llm"),
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    candidates = select_candidates(risk_rows)
    result: Dict[Tuple[str, str], Dict[str, Any]] = {}
    base_dir = cache_dir / as_of.isoformat() / db_hash

    for r in risk_rows:
        key = (r["organization_id"], r["counterparty_name"])
        if key not in candidates:
            continue
        deals = r.get("top_deals_2026") or gather_deals_for_counterparty(conn, r["organization_id"], r["counterparty_name"])
        memos = gather_memos(conn, r["organization_id"], r["counterparty_name"], as_of)
        payload = build_payload(r, deals, memos, as_of)
        input_hash = compute_llm_input_hash(payload)
        cache_path = base_dir / f"{slugify(r['organization_id'])}__{slugify(r['counterparty_name'])}.json"
        cached = load_cache(cache_path, input_hash)
        if cached:
            output = cached
            used_cache = True
        else:
            output = run_llm_or_fallback(payload)
            meta = {
                "as_of_date": as_of.isoformat(),
                "db_hash": db_hash,
                "counterparty_key": {"organizationId": r["organization_id"], "counterpartyName": r["counterparty_name"]},
                "provider": LLM_PROVIDER or "fallback",
                "model": LLM_MODEL,
                "base_url_configured": bool(LLM_BASE_URL),
                "timeout": LLM_TIMEOUT,
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": LLM_TEMPERATURE,
                "prompt_version": PROMPT_VERSION,
                "llm_input_hash": input_hash,
                "created_at": datetime.now().isoformat(),
                "used_cache": False,
                "fallback_used": output.get("fallback_used", False),
                "error": output.get("error"),
            }
            save_cache(cache_path, meta, output)
            used_cache = False
        output = {**output, "risk_level_llm": output.get("risk_level"), "used_cache": used_cache}
        result[key] = output
    return result
