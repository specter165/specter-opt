"""Reporting agent: posts Slack summaries and regenerates dashboard."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from specter_opt.agents.base import Agent, AgentContext, AgentResult


class ReportingAgent(Agent):
    """Agent responsible for Slack updates and dashboard generation."""

    name = "reporting"

    def _run_subprocess(self, cmd: list[str]) -> None:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")

    def run(self, context: AgentContext) -> AgentResult:
        output: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
        errors: list[str] = []

        try:
            self._run_subprocess(
                [sys.executable, "scripts/generate_dashboard.py"]
            )
            output["dashboard_generated"] = True
            context.add_event("Reporting: dashboard regenerated")
        except Exception as e:
            errors.append(str(e))
            context.add_event(f"Reporting dashboard error: {e}")

        try:
            cmd = [
                sys.executable,
                "scripts/daily_slack_update.py",
                "--result",
                context.run_result_path,
            ]
            if not Path(context.run_result_path).exists():
                # EOD-only runs do not produce a run_result; fall back to MCP data.
                cmd.append("--mcp-fallback")
            self._run_subprocess(cmd)
            output["slack_posted"] = True
            context.add_event("Reporting: Slack summary posted")
        except Exception as e:
            errors.append(str(e))
            context.add_event(f"Reporting Slack error: {e}")

        return AgentResult(
            agent_name=self.name,
            success=len(errors) == 0,
            output=output,
            errors=errors,
        )
