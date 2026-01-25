from __future__ import annotations

from typing import List

from .counterparty_card.agent import CounterpartyCardAgent
from .counterparty_progress.agent import CounterpartyProgressAgent
from .group_progress.agent import GroupProgressAgent

REPORT_ID_COUNTERPARTY_RISK_DAILY = "counterparty-risk-daily"
REPORT_ID_COUNTERPARTY_PROGRESS_DAILY = "counterparty-progress-daily"
REPORT_ID_GROUP_PROGRESS_DAILY = "group-progress-daily"


def get_agent_chain(report_id: str, mode_key: str) -> List[object]:
    """
    Return the agent chain for a given report_id/mode_key.
    Currently both offline/online use CounterpartyCardAgent v1.
    """
    if report_id == REPORT_ID_COUNTERPARTY_RISK_DAILY and mode_key in {"offline", "online"}:
        return [CounterpartyCardAgent(version="v1")]
    if report_id == REPORT_ID_COUNTERPARTY_PROGRESS_DAILY and mode_key in {"offline", "online"}:
        return [CounterpartyProgressAgent(version="v1")]
    if report_id == REPORT_ID_GROUP_PROGRESS_DAILY and mode_key in {"offline", "online"}:
        return [GroupProgressAgent(version="v1")]
    raise RuntimeError(f"No agent chain registered for report_id={report_id}, mode={mode_key}")
