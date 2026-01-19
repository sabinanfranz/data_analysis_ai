from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

from .agents.core.canonicalize import (
    canonical_json,
    canonicalize,
    compute_llm_input_hash,
    norm_str,
    slugify,
)
from .agents.core.types import AgentContext, LLMConfig
from .agents.counterparty_card.agent import (
    CounterpartyCardAgent,
    PAYLOAD_DEALS_LIMIT,
    TOP_DEALS_LIMIT,
    TOP_GAP_K,
    gather_deals_for_counterparty,
    gather_memos,
    select_candidates,
)
from .agents.counterparty_card.fallback import fallback_actions, fallback_blockers, fallback_evidence

# Thin adapter around CounterpartyCardAgent to preserve legacy API.
DEFAULT_CACHE_DIR = Path("report_cache/llm")
DEFAULT_PROMPT_VERSION = "v1"


def _as_date(val: Any) -> date:
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val))


def generate_llm_cards(
    conn: sqlite3.Connection,
    risk_rows: Sequence[Dict[str, Any]],
    as_of: date,
    db_hash: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    mode_key: str = "offline",
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Legacy entrypoint preserved for deal_normalizer.
    """
    as_of_date = _as_date(as_of)
    try:
        db_info = conn.execute("PRAGMA database_list").fetchone()
        snap_path = Path(db_info["file"]) if db_info and db_info["file"] else Path("")
    except Exception:
        snap_path = Path("")
    ctx = AgentContext(
        report_id="counterparty-risk-daily",
        mode_key=mode_key,
        as_of_date=as_of_date,
        db_hash=db_hash,
        snapshot_db_path=snap_path,
        cache_root=cache_dir,
        llm=LLMConfig.from_env(),
    )
    agent = CounterpartyCardAgent(version=DEFAULT_PROMPT_VERSION)
    return agent.run(conn, risk_rows, ctx, cache_dir=cache_dir)


__all__ = [
    "generate_llm_cards",
    "compute_llm_input_hash",
    "canonical_json",
    "canonicalize",
    "norm_str",
    "slugify",
    "fallback_blockers",
    "fallback_evidence",
    "fallback_actions",
    "select_candidates",
    "gather_deals_for_counterparty",
    "gather_memos",
    "TOP_GAP_K",
    "TOP_DEALS_LIMIT",
    "PAYLOAD_DEALS_LIMIT",
]
