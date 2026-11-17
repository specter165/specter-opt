"""Base classes for SPECTER-OPT multi-agent system."""

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
