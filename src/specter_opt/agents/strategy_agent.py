"""Strategy agent: runs SPECTER-OPT and generates order intents."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from specter_opt.agents.base import Agent, AgentContext, AgentResult


class StrategyAgent(Agent):
    """Agent responsible for strategy evaluation and intent generation."""

    name = "strategy"

    def _run_subprocess(self, cmd: list[str]) -> Dict[str, Any]:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
        return json.loads(result.stdout)

    def run(self, context: AgentContext) -> AgentResult:
        output: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
        errors: list[str] = []

        if not Path(context.snapshot_path).exists():
            errors.append(f"Snapshot not found: {context.snapshot_path}")
            context.add_event(f"Strategy agent error: {errors[-1]}")
            return AgentResult(agent_name=self.name, success=False, errors=errors)

        try:
            result = self._run_subprocess(
                [
                    sys.executable,
                    "scripts/run_moomoo_paper.py",
                    "--snapshot",
                    context.snapshot_path,
                    "--mode",
                    context.mode,
                    "--assistant-submits",
                    "--out",
                    context.run_result_path,
                ]
            )
            output["agent_action"] = result.get("actions", ["HOLD"])[0]
            output["equity"] = result.get("equity")
            output["halted"] = result.get("halted", False)
            output["reason"] = result.get("rejection_reasons", ["unknown"])[0]
            output["top_candidate"] = result.get("top_candidate")

            context.data["run_result"] = result
            context.halt = bool(result.get("halted", False))

            pending = []
            if Path(context.pending_orders_path).exists():
                with open(context.pending_orders_path, "r") as f:
                    pending = [json.loads(line) for line in f if line.strip()]
            output["pending_intents"] = pending
            context.data["pending_intents"] = pending

            context.add_event(
                f"Strategy: action={output['agent_action']}, reason={output['reason']}, "
                f"pending={len(pending)}, halted={output['halted']}"
            )
        except Exception as e:
            errors.append(str(e))
            context.add_event(f"Strategy agent error: {e}")

        return AgentResult(
            agent_name=self.name,
            success=len(errors) == 0,
            output=output,
            errors=errors,
        )
