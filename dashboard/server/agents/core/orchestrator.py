from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .artifacts import ArtifactStore
from .types import AgentContext


@dataclass
class AgentRunStat:
    name: str
    version: str
    scope: str
    run_count: int = 0
    success_count: int = 0
    error_count: int = 0
    used_cache_count: int = 0
    fallback_used_count: int = 0
    duration_ms_sum: float = 0.0
    errors: List[str] = field(default_factory=list)


class Orchestrator:
    """
    Minimal single-process orchestrator.
    - No parallelism (SQLite safety)
    - Soft-fail by default (continues other inputs)
    """

    def __init__(self, soft_fail: bool = True) -> None:
        self.soft_fail = soft_fail

    def _toposort(self, agents: Sequence[Any]) -> List[Any]:
        # For now, execute in given order (agents can later expose depends_on)
        return list(agents)

    def run(
        self,
        report_id: str,
        mode_key: str,
        ctx: AgentContext,
        artifacts: ArtifactStore,
        agents: Sequence[Any],
        conn=None,
    ) -> Dict[str, Any]:
        stats: Dict[str, AgentRunStat] = {}
        ordered = self._toposort(agents)
        agent_outputs: Dict[str, Any] = {}

        for agent in ordered:
            scope = getattr(agent, "scope", "report")
            name = getattr(agent, "name", agent.__class__.__name__)
            version = getattr(agent, "version", "v1")
            stat = stats.setdefault(name, AgentRunStat(name=name, version=version, scope=scope))
            start = time.time()
            stat.run_count += 1
            try:
                if scope == "counterparty":
                    rows = artifacts.get("base.counterparty_rows", [])
                    output = agent.run(conn, rows, ctx, cache_dir=ctx.cache_root)
                else:
                    output = agent.run(conn, ctx, artifacts)
                agent_outputs[name] = output
                # Telemetry aggregation (best-effort)
                if isinstance(output, dict):
                    for _k, v in output.items():
                        if isinstance(v, dict) and v.get("used_cache"):
                            stat.used_cache_count += 1
                        if isinstance(v, dict) and v.get("fallback_used"):
                            stat.fallback_used_count += 1
                stat.success_count += 1
            except Exception as exc:  # pragma: no cover - defensive
                stat.error_count += 1
                stat.errors.append(str(exc))
                if not self.soft_fail:
                    raise
            finally:
                stat.duration_ms_sum += (time.time() - start) * 1000.0

        artifacts.set("telemetry.agent_runs", stats)
        return agent_outputs

