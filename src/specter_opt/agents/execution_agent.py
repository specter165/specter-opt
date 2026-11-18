"""Execution agent: submits pending intents and reconciles fills."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from specter_opt.agents.base import Agent, AgentContext, AgentResult


class ExecutionAgent(Agent):
    """Agent responsible for order submission and fill reconciliation."""

    name = "execution"

    def _load_jsonl(self, path: str) -> List[Dict[str, Any]]:
        records = []
        if not Path(path).exists():
            return records
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def _archive_pending(self, context: AgentContext, intents: List[Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(context.pending_history_path), exist_ok=True)
        with open(context.pending_history_path, "a") as f:
            for intent in intents:
                intent["archived_at_utc"] = datetime.utcnow().isoformat()
                f.write(json.dumps(intent, default=str) + "\n")

    def _clear_pending(self, context: AgentContext) -> None:
        if Path(context.pending_orders_path).exists():
            with open(context.pending_orders_path, "w") as f:
                f.write("")

    def run(self, context: AgentContext) -> AgentResult:
        output: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "submitted": [],
            "skipped": [],
        }
        errors: list[str] = []

        pending = context.data.get("pending_intents") or self._load_jsonl(context.pending_orders_path)
        exits = context.data.get("exit_intents") or []

        if context.halt:
            if exits:
                output["note"] = "Global halt active: processing only protective exits"
                context.add_event("Execution: halt active, processing only exits")
                pending = []
            else:
                output["note"] = "Execution skipped: global halt active"
                context.add_event("Execution: skipped due to halt")
                return AgentResult(agent_name=self.name, success=True, output=output)

        all_intents = (pending or []) + (exits or [])
        if not all_intents:
            output["note"] = "No pending intents or exits"
            context.add_event("Execution: no pending intents or exits")
            return AgentResult(agent_name=self.name, success=True, output=output)

        # This agent is deterministic scaffolding. Actual MCP submission must be done by
        # the assistant because scripts cannot call MCP tools directly. We record which
        # intents would be submitted and leave them in the pending file for the assistant.
        for intent in all_intents:
            symbol = intent.get("symbol")
            if not symbol:
                output["skipped"].append({"intent": intent, "reason": "missing symbol"})
                continue
            output["submitted"].append(intent)
            side = intent.get("side", 1)
            context.add_event(f"Execution: ready to submit {symbol} side={side} qty={intent.get('quantity')} @ {intent.get('price')}")

        if output["submitted"]:
            self._archive_pending(context, output["submitted"])
            self._clear_pending(context)
            # The pending file is now empty; the assistant must submit via MCP using
            # the archived intents. For full automation, the assistant reads the archive
            # and calls sim_trade_input_order for each submitted intent.
            output["note"] = f"{len(output['submitted'])} intents archived for assistant submission"
        else:
            output["note"] = "No valid intents to submit"

        return AgentResult(
            agent_name=self.name,
            success=len(errors) == 0,
            output=output,
            errors=errors,
        )
