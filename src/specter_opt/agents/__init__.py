"""Multi-agent orchestration for SPECTER-OPT."""

from .base import Agent, AgentContext, AgentResult
from .research_agent import ResearchAgent
from .strategy_agent import StrategyAgent
from .risk_agent import RiskAgent
from .execution_agent import ExecutionAgent
from .reporting_agent import ReportingAgent
from .orchestrator import Orchestrator

__all__ = [
    "Agent",
    "AgentContext",
    "AgentResult",
    "ResearchAgent",
    "StrategyAgent",
    "RiskAgent",
    "ExecutionAgent",
    "ReportingAgent",
    "Orchestrator",
]
