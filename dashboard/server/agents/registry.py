from __future__ import annotations

from typing import List

from .counterparty_card.agent import CounterpartyCardAgent

REPORT_ID_COUNTERPARTY_RISK_DAILY = "counterparty-risk-daily"


def get_agent_chain(report_id: str, mode_key: str) -> List[object]:
    """
    Return the agent chain for a given report_id/mode_key.
    Currently both offline/online use CounterpartyCardAgent v1.
    """
    if report_id == REPORT_ID_COUNTERPARTY_RISK_DAILY and mode_key in {"offline", "online"}:
        return [CounterpartyCardAgent(version="v1")]
    raise RuntimeError(f"No agent chain registered for report_id={report_id}, mode={mode_key}")

