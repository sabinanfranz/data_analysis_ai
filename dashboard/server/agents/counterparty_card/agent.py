from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

from ..core.artifacts import ArtifactStore
from ..core.cache_store import load as load_cache, save_atomic as save_cache
from ..core.canonicalize import canonical_json, compute_llm_input_hash, norm_str, slugify
from ..core.json_guard import parse_json, validate_output
from ..core.prompt_store import PromptStore
from ..core.types import AgentContext, LLMConfig
from .fallback import fallback_actions, fallback_blockers, fallback_evidence
from .schema import CounterpartyCardOutput, CounterpartyCardPayload
from ... import date_kst

TOP_GAP_K = 20
TOP_DEALS_LIMIT = 10  # payload에는 상위 5개만 사용
PAYLOAD_DEALS_LIMIT = 5
MEMO_WINDOW_DAYS = 180
MEMO_LIMIT = 20
MEMO_TRIM_LEN = 1000
ONLINE_DEAL_FORMATS = {"구독제(온라인)", "선택구매(온라인)", "포팅"}
DATE_KST_MODE = os.getenv("DATE_KST_MODE", "legacy").lower()
if DATE_KST_MODE not in {"legacy", "shadow", "strict"}:
    DATE_KST_MODE = "legacy"


def _date_kst_mode() -> str:
    return DATE_KST_MODE


def _is_strict_mode() -> bool:
    return _date_kst_mode() == "strict"


def _is_shadow_mode() -> bool:
    return _date_kst_mode() == "shadow"


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


def _normalize_mode(mode: str) -> str:
    return "online" if mode == "online" else "offline"


def _parse_date_legacy(text: Any) -> str | None:
    if text is None:
        return None
    if isinstance(text, (date,)):
        return text.isoformat()
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
            return date.fromisoformat(f"{s[:4]}-{s[4:6]}-{s[6:]}").isoformat()
        return date.fromisoformat(s).isoformat()
    except Exception:
        return None


def _parse_date(text: Any) -> str | None:
    if _is_strict_mode():
        val = date_kst.kst_date_only(text)
        return val or None
    return _parse_date_legacy(text)


def _parse_amount(raw: Any) -> int:
    if raw is None:
        return 0
    try:
        s = str(raw).replace("₩", "").replace("원", "").replace(",", "").strip()
        return int(float(s))
    except Exception:
        return 0


def gather_deals_for_counterparty(
    conn: sqlite3.Connection,
    org_id: str,
    counterparty_name: str,
    mode_key: str = "offline",
) -> List[Dict[str, Any]]:
    """
    Fallback: deal_norm이 없을 때 deal+people을 직접 조회해 최소 필터로 2026 딜을 얻는다.
    규칙: status not in Convert/Lost, 과정포맷 온라인 3종 제외/포함, deal_year=2026 추정.
    """
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
    mode = _normalize_mode(mode_key)
    for r in rows:
        pf = r["process_format"]
        is_nononline = (pf is None) or (str(pf).strip() not in ONLINE_DEAL_FORMATS)
        is_online = not is_nononline
        if mode == "offline" and not is_nononline:
            continue
        if mode == "online" and not is_online:
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
                "is_nononline": is_nononline,
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


def gather_memos(
    conn: sqlite3.Connection,
    org_id: str,
    counterparty_name: str,
    as_of: date,
) -> List[Dict[str, Any]]:
    cutoff = (as_of - timedelta(days=MEMO_WINDOW_DAYS)).isoformat()
    memos: List[Dict[str, Any]] = []
    memos += [
        {"id": row["id"], "date": (row["createdAt"] or "")[:10], "source": "organization", "text": norm_str(row["text"] or "")}
        for row in conn.execute(
            "SELECT id, text, createdAt FROM memo WHERE organizationId = ? AND (createdAt IS NULL OR substr(createdAt,1,10) >= ?) ORDER BY createdAt DESC",
            (org_id, cutoff),
        ).fetchall()
    ]
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

    seen = set()
    deduped = []
    for m in memos:
        key = m.get("id") or (m.get("date"), m.get("source"), m.get("text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    deduped.sort(key=lambda m: m.get("date") or "", reverse=True)
    trimmed: List[Dict[str, Any]] = []
    for m in deduped[:MEMO_LIMIT]:
        text = m["text"][:MEMO_TRIM_LEN]
        trimmed.append({**m, "text": text})
    return trimmed


class CounterpartyCardAgent:
    name = "counterparty_card"
    scope = "counterparty"

    def __init__(self, version: str = "v1") -> None:
        self.version = version
        self.prompts = PromptStore()

    def _build_payload(self, row: Dict[str, Any], deals: List[Dict[str, Any]], memos: List[Dict[str, Any]], as_of: date, mode: str) -> Dict[str, Any]:
        coverage_ratio = row["coverage_ratio"]
        coverage_ratio = None if coverage_ratio is None else float(coverage_ratio)
        payload = {
            "report_mode": mode,
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
                "min_cov_current_month": float(row["min_cov_current_month"] or 0),
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
        return CounterpartyCardPayload.model_validate(payload).model_dump()

    def _llm_disabled(self, llm_cfg: LLMConfig) -> bool:
        return not llm_cfg.is_enabled() or OpenAI is None

    def _call_llm(self, payload_json: str, prompts: Dict[str, str], llm_cfg: LLMConfig):
        if self._llm_disabled(llm_cfg):
            return None, "llm_disabled_or_missing_key"
        client = OpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url or None)
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"].replace("{{PAYLOAD_JSON}}", payload_json)},
        ]
        completion = client.chat.completions.create(
            model=llm_cfg.model,
            messages=messages,
            timeout=llm_cfg.timeout,
            max_tokens=llm_cfg.max_tokens,
            temperature=llm_cfg.temperature,
        )
        text = completion.choices[0].message.content or ""
        return text, None

    def _repair_json(self, bad_text: str, prompts: Dict[str, str], llm_cfg: LLMConfig):
        if self._llm_disabled(llm_cfg):
            return None, "llm_disabled_or_missing_key"
        client = OpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url or None)
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["repair"]},
        ]
        completion = client.chat.completions.create(
            model=llm_cfg.model,
            messages=messages,
            timeout=llm_cfg.timeout,
            max_tokens=llm_cfg.max_tokens,
            temperature=llm_cfg.temperature,
        )
        text = completion.choices[0].message.content or ""
        try:
            return json.loads(text), None
        except Exception as exc:
            return None, str(exc)

    def _fallback_output(self, payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
        blockers = fallback_blockers(payload["risk_rule"].get("pipeline_zero"), " ".join([m.get("text", "") for m in payload.get("memos", [])]))
        evidence = fallback_evidence(payload["risk_rule"], blockers)
        actions = fallback_actions(blockers, mode_key=mode)
        risk_level = payload["risk_rule"].get("rule_risk_level") or "보통"
        return {
            "risk_level": risk_level,
            "top_blockers": blockers,
            "evidence_bullets": evidence[:3],
            "recommended_actions": actions[:3],
            "fallback_used": True,
        }

    def _run_model(self, payload: Dict[str, Any], prompts: Dict[str, str], llm_cfg: LLMConfig, mode: str) -> Dict[str, Any]:
        payload_json = canonical_json(payload)
        raw_text, err = self._call_llm(payload_json, prompts, llm_cfg)
        if err or raw_text is None:
            return self._fallback_output(payload, mode)
        parsed, perr = parse_json(raw_text)
        if perr:
            repaired, rerr = self._repair_json(raw_text, prompts, llm_cfg)
            parsed = repaired if rerr is None else None
        if parsed is None:
            return self._fallback_output(payload, mode)
        ok, verr = validate_output(parsed, lambda obj: CounterpartyCardOutput.model_validate(obj))
        if not ok or verr:
            return self._fallback_output(payload, mode)
        model = CounterpartyCardOutput.model_validate(parsed)
        output = model.model_dump()
        output["fallback_used"] = False
        return output

    def run(
        self,
        conn: sqlite3.Connection,
        risk_rows: Sequence[Dict[str, Any]],
        ctx: AgentContext,
        cache_dir: Path | None = None,
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        mode = _normalize_mode(ctx.mode_key)
        prompts = self.prompts.load_set(mode, self.version)
        cache_root = cache_dir or ctx.cache_root
        artifacts = ArtifactStore()
        artifacts.set("base.counterparty_rows", risk_rows)

        result: Dict[Tuple[str, str], Dict[str, Any]] = {}
        candidates = select_candidates(risk_rows)
        base_dir = Path(cache_root) / ctx.as_of_date.isoformat() / ctx.db_hash / mode

        for r in risk_rows:
            key = (r["organization_id"], r["counterparty_name"])
            if key not in candidates:
                continue
            deals = r.get("top_deals_2026") or gather_deals_for_counterparty(
                conn, r["organization_id"], r["counterparty_name"], mode_key=mode
            )
            memos = gather_memos(conn, r["organization_id"], r["counterparty_name"], ctx.as_of_date)
            payload = self._build_payload(r, deals, memos, ctx.as_of_date, mode)
            input_hash = compute_llm_input_hash(payload)
            cache_path = base_dir / f"{slugify(r['organization_id'])}__{slugify(r['counterparty_name'])}.json"
            cached = load_cache(cache_path)
            if cached:
                meta = cached.get("meta", {})
                if meta.get("llm_input_hash") == input_hash and meta.get("prompt_version") == self.version:
                    output = cached.get("output", {})
                    output = {
                        **output,
                        "risk_level_llm": output.get("risk_level"),
                        "used_cache": True,
                        "llm_meta": meta,
                    }
                    result[key] = output
                    continue
            output = self._run_model(payload, prompts, ctx.llm, mode)
            meta = {
                "as_of_date": ctx.as_of_date.isoformat(),
                "db_hash": ctx.db_hash,
                "counterparty_key": {"organizationId": r["organization_id"], "counterpartyName": r["counterparty_name"]},
                "provider": ctx.llm.provider or "fallback",
                "model": ctx.llm.model,
                "base_url_configured": bool(ctx.llm.base_url),
                "timeout": ctx.llm.timeout,
                "max_tokens": ctx.llm.max_tokens,
                "temperature": ctx.llm.temperature,
                "prompt_version": self.version,
                "llm_input_hash": input_hash,
                "created_at": date.today().isoformat(),
                "used_cache": False,
                "fallback_used": output.get("fallback_used", False),
                "mode": mode,
                "agent": self.name,
                "agent_version": self.version,
            }
            save_cache(cache_path, {"meta": meta, "output": output})
            output = {
                **output,
                "risk_level_llm": output.get("risk_level"),
                "used_cache": False,
                "llm_meta": meta,
            }
            result[key] = output

        artifacts.set("agent.counterparty_card.outputs", result)
        return result
