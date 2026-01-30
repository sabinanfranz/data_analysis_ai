from __future__ import annotations

from typing import Any, Dict

from .target_attainment.agent import TargetAttainmentAgent
from .part_report.agent import PartReportAgent
from .daily_rollup.agent import DailyRollupAgent
from .anomaly.agent import AnomalyAgent


def get_daily_report_chain(pipeline_id: str, variant: str) -> Dict[str, Any]:
    """
    Daily Report V2 registry (separate from legacy risk registry).
    Returns a lightweight spec the orchestrator can interpret.
    """
    if pipeline_id == "row.target_attainment":
        return {
            "pipeline_id": pipeline_id,
            "variant": variant,
            "kind": "linear",
            "steps": [
                {"name": "target_attainment", "version": "v1", "runner": TargetAttainmentAgent},
            ],
        }

    if pipeline_id == "part.part_report":
        return {
            "pipeline_id": pipeline_id,
            "variant": variant,
            "kind": "linear",
            "steps": [
                {"name": "part_report", "version": "v1", "runner": PartReportAgent},
            ],
        }

    if pipeline_id == "daily.part_rollup":
        return {
            "pipeline_id": pipeline_id,
            "variant": variant,
            "kind": "dag",
            "dag": {"name": "daily_part_rollup_v1", "runner": DailyRollupAgent},
        }

    if pipeline_id == "daily.anomaly_scan":
        return {
            "pipeline_id": pipeline_id,
            "variant": variant,
            "kind": "linear",
            "steps": [{"name": "anomaly_scan", "version": "v1", "runner": AnomalyAgent}],
        }

    raise KeyError(f"Unknown pipeline_id: {pipeline_id}")
