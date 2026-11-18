"""Multi-agent orchestrator for SPECTER-OPT."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from specter_opt.agents.base import Agent, AgentContext, AgentResult
from specter_opt.agents.execution_agent import ExecutionAgent
from specter_opt.agents.reporting_agent import ReportingAgent
from specter_opt.agents.research_agent import ResearchAgent
from specter_opt.agents.risk_agent import RiskAgent
from specter_opt.agents.strategy_agent import StrategyAgent
from specter_opt.agents.supervision_agent import SupervisionAgent


class Orchestrator:
    """Coordinates SPECTER-OPT agents through a shared context."""

    def __init__(self, context: Optional[AgentContext] = None):
        self.context = context or AgentContext()
        self.agents: dict[str, Agent] = {
            "research": ResearchAgent(),
            "supervision": SupervisionAgent(),
            "strategy": StrategyAgent(),
            "risk": RiskAgent(),
            "execution": ExecutionAgent(),
            "reporting": ReportingAgent(),
        }

    def run_agent(self, name: str) -> AgentResult:
        if name not in self.agents:
            return AgentResult(
                agent_name=name,
                success=False,
                errors=[f"Unknown agent: {name}"],
            )
        agent = self.agents[name]
        result = agent.run(self.context)
        self._persist_runlog(name, result)
        return result

    def run_pipeline(self, names: Optional[List[str]] = None) -> List[AgentResult]:
        if names is None:
            names = ["research", "supervision", "strategy", "risk", "execution", "reporting"]
        results: List[AgentResult] = []
        for name in names:
            result = self.run_agent(name)
            results.append(result)
            if self.context.halt and name not in {"risk", "reporting"}:
                # Allow risk and reporting to run even under halt; skip trading agents.
                break
        return results

    def _persist_runlog(self, name: str, result: AgentResult) -> None:
        path = "data/agent_runlog.jsonl"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "agent": name,
                        "success": result.success,
                        "output": result.output,
                        "errors": result.errors,
                    },
                    default=str,
                )
                + "\n"
            )

    def summary(self, results: List[AgentResult]) -> dict:
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "halt": self.context.halt,
            "events": self.context.events,
            "agent_results": [
                {
                    "agent": r.agent_name,
                    "success": r.success,
                    "errors": r.errors,
                }
                for r in results
            ],
        }
