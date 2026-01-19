from __future__ import annotations

from typing import Any, Dict, List, Tuple

from dashboard.server.agents.counterparty_card.fallback import (
    fallback_actions,
    fallback_blockers,
    fallback_evidence,
)


def _ensure_lists(row: Dict[str, Any], output: Dict[str, Any], mode_key: str) -> Tuple[List[str], List[str], List[str]]:
    blockers = output.get("top_blockers") or []
    evidence = output.get("evidence_bullets") or []
    actions = output.get("recommended_actions") or []

    if not blockers:
        blockers = fallback_blockers(bool(row.get("pipeline_zero")), "")
    if not evidence or len(evidence) != 3:
        evidence = fallback_evidence(row, blockers)
    if not actions or not (2 <= len(actions) <= 3):
        actions = fallback_actions(blockers, mode_key=mode_key)
    # Trim/pad evidence to exactly 3
    evidence = (evidence + [""] * 3)[:3]
    actions = actions[:3]
    blockers = blockers[:3]
    return blockers, evidence, actions


def merge_counterparty_card_outputs(
    base_rows: List[Dict[str, Any]],
    card_outputs: Dict[Tuple[str, str], Dict[str, Any]],
    mode_key: str,
    report_id: str,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for row in base_rows:
        key = (row["organization_id"], row["counterparty_name"])
        output = card_outputs.get(key) or {}
        blockers, evidence, actions = _ensure_lists(row, output, mode_key)
        risk_level_llm = output.get("risk_level_llm") or output.get("risk_level") or row.get("risk_level_rule")
        llm_meta = output.get("llm_meta", {})
        llm_meta = {
            **{
                "mode": mode_key,
                "report_id": report_id,
                "used_cache": output.get("used_cache", False),
                "fallback_used": output.get("fallback_used", True),
            },
            **llm_meta,
        }
        merged.append(
            {
                **row,
                "top_blockers": blockers,
                "evidence_bullets": evidence,
                "recommended_actions": actions,
                "risk_level_llm": risk_level_llm,
                "llm_meta": llm_meta,
            }
        )
    return merged

