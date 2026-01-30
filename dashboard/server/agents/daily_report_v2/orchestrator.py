from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from ..target_attainment.agent import TargetAttainmentAgent
from ..target_attainment.schema import TargetAttainmentRequest
from ..part_report.agent import PartReportAgent
from ..part_report.schema import PartReportInput, PartReportRow
from ..daily_rollup.agent import DailyRollupAgent
from ..daily_rollup.schema import DailyRollupInput, PartRollupItem
from .compaction import RowOutputCompactor, build_part_inputs
from ..daily_report_v2_registry import get_daily_report_chain
from ..anomaly.agent import AnomalyAgent
from ..anomaly.schema import AnomalyInput


def _row_key(row: Dict[str, Any], idx: int) -> str:
    return (
        row.get("rowKey")
        or row.get("key")
        or row.get("id")
        or row.get("orgId")
        or row.get("org_id")
        or f"idx:{idx}"
    )


def _row_to_request(row: Dict[str, Any], variant: str) -> TargetAttainmentRequest:
    return TargetAttainmentRequest(
        orgId=row.get("orgId") or row.get("org_id") or "",
        orgName=row.get("orgName") or row.get("org_name"),
        upperOrg=row.get("upperOrg") or row.get("upper_org") or "",
        mode=variant or row.get("mode") or "offline",
        target_2026=row.get("target_2026") if row.get("target_2026") is not None else row.get("target") or 0,
        actual_2026=row.get("actual_2026") if row.get("actual_2026") is not None else row.get("actual") or 0,
        won_group_json_compact=row.get("won_group_json_compact") or row.get("wonGroupCompact") or {},
    )


MAX_CONCURRENCY = int(os.getenv("DAILY_REPORT_V2_MAX_CONCURRENCY", "4") or "4")


def _submit_target_attainment(agent: TargetAttainmentAgent, row: Dict[str, Any], variant: str, debug: bool, nocache: bool):
    req = _row_to_request(row, variant)
    return agent.run(req, variant=variant, debug=debug, nocache=nocache)


def run_pipeline(pipeline_id: str, payload: Any, *, variant: str, debug: bool, nocache: bool = False) -> Dict[str, Any]:
    spec = get_daily_report_chain(pipeline_id, variant)
    start = time.monotonic()

    if pipeline_id == "row.target_attainment":
        try:
            req = payload if isinstance(payload, TargetAttainmentRequest) else TargetAttainmentRequest(**payload)
            result = TargetAttainmentAgent().run(req, variant=variant, debug=debug, nocache=nocache)
            return result
        except Exception as exc:
            return {"error": str(exc)}

    if pipeline_id == "daily.part_rollup":
        rows = []
        if isinstance(payload, dict):
            rows = payload.get("rows", [])
        elif isinstance(payload, list):
            rows = payload
        if not isinstance(rows, list):
            return {"error": "INVALID_ROWS"}

        agent = TargetAttainmentAgent()
        raw_outputs: List[Dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=max(1, MAX_CONCURRENCY)) as executor:
            futures = {}
            for idx, row in enumerate(rows):
                rk = _row_key(row, idx)
                fut = executor.submit(_submit_target_attainment, agent, row, variant, debug, nocache)
                futures[fut] = rk
            for fut in as_completed(futures):
                rk = futures[fut]
                try:
                    out = fut.result()
                except Exception as exc:
                    out = {"error": str(exc)}
                raw_outputs.append({"rowKey": rk, "output": out})

        # preserve input order by sorting on rowKey order in rows
        key_index = { _row_key(row, idx): idx for idx, row in enumerate(rows) }
        raw_outputs.sort(key=lambda x: key_index.get(x["rowKey"], 0))

        compacted: List[Dict[str, Any]] = []
        for item in raw_outputs:
            compacted.append(
                {"rowKey": item["rowKey"], "output": RowOutputCompactor.compact(item["output"], debug=debug)}
            )

        part_inputs = build_part_inputs(rows, [c["output"] for c in compacted])

        # PartReport fan-out (can share same concurrency guard)
        part_agent = PartReportAgent()
        part_outputs: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, MAX_CONCURRENCY)) as executor:
            part_futures = {}
            for part in part_inputs:
                part_input_model = PartReportInput(
                    variant_key=variant,
                    part_name=part.get("part_name") or part.get("upperOrg") or "__unknown__",
                    rows=[PartReportRow(**r) for r in part["rows"]],
                )
                fut = executor.submit(part_agent.run, part_input_model, variant=variant, debug=debug, nocache=nocache)
                part_futures[fut] = part.get("part_name") or part.get("upperOrg") or "__unknown__"
            for fut in as_completed(part_futures):
                pname = part_futures[fut]
                try:
                    out = fut.result()
                except Exception as exc:
                    out = {"error": str(exc)}
                part_outputs.append({"part_name": pname, "output": out})
        part_outputs.sort(key=lambda x: str(x["part_name"]))

        # Daily rollup (single)
        rollup_agent = DailyRollupAgent()
        rollup_input = DailyRollupInput(
            variant_key=variant,
            date=payload.get("date") if isinstance(payload, dict) else None,
            parts=[PartRollupItem(part_name=p["part_name"], part_report_json=p["output"]) for p in part_outputs],
        )
        try:
            rollup_output = rollup_agent.run(rollup_input, variant=variant, debug=debug, nocache=nocache)
        except Exception as exc:
            rollup_output = {"error": str(exc)}

        result: Dict[str, Any] = {
            "pipeline_id": pipeline_id,
            "rows": compacted,
            "parts": part_outputs,
            "rollup": rollup_output,
        }
        if debug:
            result["__meta"] = {
                "pipeline_id": pipeline_id,
                "row_count": len(rows),
                "part_count": len(part_outputs),
                "duration_ms": int((time.monotonic() - start) * 1000),
            }
        return result

    if pipeline_id == "part.part_report":
        try:
            part_input = payload if isinstance(payload, PartReportInput) else PartReportInput(**payload)
            out = PartReportAgent().run(part_input, variant=variant, debug=debug, nocache=nocache)
            return out
        except Exception as exc:
            return {"error": str(exc)}

    if pipeline_id == "daily.anomaly_scan":
        try:
            anomaly_input = payload if isinstance(payload, AnomalyInput) else AnomalyInput(**payload)
            out = AnomalyAgent().run(anomaly_input, variant=variant, debug=debug, nocache=nocache)
            return out
        except Exception as exc:
            return {"error": str(exc)}

    return {"error": f"Unknown pipeline_id: {pipeline_id}"}
