"""Base classes for SPECTER-OPT multi-agent system."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class AgentContext:
    """Shared context passed between agents."""

    account_id: str = "5830137"
    market_id: int = 100
    mode: str = "paper"
    snapshot_path: str = "data/snapshot_fresh.json"
    run_result_path: str = "data/run_result_paper.json"
    mcp_positions_path: str = "data/mcp_positions.json"
    mcp_orders_path: str = "data/mcp_orders.json"
    mcp_cash_path: str = "data/mcp_cash.json"
    intents_path: str = "data/intents.jsonl"
    risk_state_path: str = "data/risk_state.json"
    pending_orders_path: str = "data/pending_paper_orders.jsonl"
    pending_history_path: str = "data/pending_paper_orders_history.jsonl"
    dashboard_path: str = "data/dashboard.html"
    slack_env_path: str = "data/.slack_webhook.env"
    timestamp_utc: Optional[datetime] = None
    data: Dict[str, Any] = field(default_factory=dict)
    events: List[str] = field(default_factory=list)
    halt: bool = False

    def add_event(self, message: str) -> None:
        self.events.append(f"{datetime.utcnow().isoformat()} — {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "market_id": self.market_id,
            "mode": self.mode,
            "snapshot_path": self.snapshot_path,
            "run_result_path": self.run_result_path,
            "mcp_positions_path": self.mcp_positions_path,
            "mcp_orders_path": self.mcp_orders_path,
            "mcp_cash_path": self.mcp_cash_path,
            "intents_path": self.intents_path,
            "risk_state_path": self.risk_state_path,
            "pending_orders_path": self.pending_orders_path,
            "pending_history_path": self.pending_history_path,
            "dashboard_path": self.dashboard_path,
            "slack_env_path": self.slack_env_path,
            "timestamp_utc": self.timestamp_utc.isoformat() if self.timestamp_utc else None,
            "data": self.data,
            "events": self.events,
            "halt": self.halt,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentContext":
        ts = d.get("timestamp_utc")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return cls(
            account_id=d.get("account_id", "5830137"),
            market_id=d.get("market_id", 100),
            mode=d.get("mode", "paper"),
            snapshot_path=d.get("snapshot_path", "data/snapshot_fresh.json"),
            run_result_path=d.get("run_result_path", "data/run_result_paper.json"),
            mcp_positions_path=d.get("mcp_positions_path", "data/mcp_positions.json"),
            mcp_orders_path=d.get("mcp_orders_path", "data/mcp_orders.json"),
            mcp_cash_path=d.get("mcp_cash_path", "data/mcp_cash.json"),
            intents_path=d.get("intents_path", "data/intents.jsonl"),
            risk_state_path=d.get("risk_state_path", "data/risk_state.json"),
            pending_orders_path=d.get("pending_orders_path", "data/pending_paper_orders.jsonl"),
            pending_history_path=d.get("pending_history_path", "data/pending_paper_orders_history.jsonl"),
            dashboard_path=d.get("dashboard_path", "data/dashboard.html"),
            slack_env_path=d.get("slack_env_path", "data/.slack_webhook.env"),
            timestamp_utc=ts,
            data=d.get("data", {}),
            events=d.get("events", []),
            halt=d.get("halt", False),
        )


@dataclass
class AgentResult:
    """Result returned by an agent run."""

    agent_name: str
    success: bool
    output: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)


class Agent(ABC):
    """Abstract base class for SPECTER-OPT agents."""

    name: str = "base"

    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent's responsibility and return a result."""
        ...


def load_json_document(path: str) -> Dict[str, Any]:
    """Load a JSON file, tolerating a second appended document.

    Cloud agents sometimes append a second JSON blob to a data file; strict
    json.load would then raise "Extra data" and abort the whole cycle.
    """
    from pathlib import Path as _Path
    if not _Path(path).exists():
        return {}
    with open(path, "r") as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        value, _ = json.JSONDecoder().raw_decode(text.lstrip())
        return value
