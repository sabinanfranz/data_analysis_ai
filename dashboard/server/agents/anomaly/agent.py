from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .schema import AnomalyInput
from ..core.json_guard import ensure_json_object_or_error


class AnomalyAgent:
    """
    Skeleton placeholder for anomaly scan (optional).
    """

    def __init__(self, *, prompt_dir: Path | None = None, version: str = "v1") -> None:
        self.prompt_dir = prompt_dir or Path(__file__).resolve().parent / "prompts"
        self.version = version

    def run(self, input: AnomalyInput | Dict[str, Any], *, variant: str, debug: bool, nocache: bool = False) -> Dict[str, Any]:
        try:
            _ = input if isinstance(input, AnomalyInput) else AnomalyInput(**input)
        except Exception as exc:
            return {"error": str(exc)}
        # Not implemented yet; return placeholder JSON object
        return {"error": "ANOMALY_AGENT_NOT_IMPLEMENTED"}
