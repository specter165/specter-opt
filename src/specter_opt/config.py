"""SPECTER-OPT configuration and constants."""

import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class RiskConfig:
    """Internal risk ceilings; official competition rules may be stricter."""

    per_trade_premium_pct: float = 0.005
    aggregate_premium_pct: float = 0.03
    max_concurrent_positions: int = 3
    daily_equity_loss_block_pct: float = 0.02
    peak_drawdown_halt_pct: float = 0.05
    max_orders_per_us_trading_day: int = 20
    allow_short_options: bool = False
    allow_borrowing: bool = False
    allow_uncovered: bool = False
    min_dte: int = 7
    max_dte: int = 21
    min_abs_delta: float = 0.35
    max_abs_delta: float = 0.70
    max_relative_spread: float = 0.05
    min_open_interest: int = 500
    max_quote_age_seconds: float = 10.0
    exit_before_expiry_sessions: int = 1
    cvar_alpha: float = 0.95
    lambda_risk: float = 1.0
    min_score_threshold: float = 0.0
    max_premium_stop_pct: float = 0.30


@dataclass(frozen=True)
class ForecastConfig:
    """M0-M3 model ladder settings."""

    horizons: List[int] = field(default_factory=lambda: [1, 2, 3])
    ewma_lambda: float = 0.94
    student_nu: float = 5.0
    scenario_paths: int = 5000
    random_seed: Optional[int] = 42
    use_ridge: bool = False
    use_regime: bool = False
    use_skew: bool = False


@dataclass(frozen=True)
class PricingConfig:
    """Pricing and tree configuration."""

    tree_steps_per_day: int = 5
    max_tree_steps: int = 100
    iv_max_iter: int = 50
    iv_tol: float = 1e-6
    risk_free_rate: float = 0.045
    dividend_yield: float = 0.013


@dataclass(frozen=True)
class ExecutionConfig:
    """Execution and operational settings."""

    paper_account_title_substring: str = "Qoder AI Paper Trading Agent Challenge"
    paper_market_id: int = 100
    timezone: str = "America/New_York"
    presentation_timezone: str = "Asia/Singapore"
    order_type_limit: bool = True
    entry_offset_to_mid: float = 0.0
    poll_interval_seconds: int = 30
    max_submit_retries: int = 3
    state_file: str = "data/risk_state.json"
    intent_file: str = "data/intents.jsonl"
    decision_log: str = "decision-logs/decisions.jsonl"


@dataclass(frozen=True)
class FeeConfig:
    """Competition simulator fee schedule (per contract, per side where applicable)."""

    commission_per_contract_premium_above: float = 0.65
    commission_per_contract_premium_at_or_below: float = 0.15
    commission_premium_threshold: float = 0.10
    min_per_order: float = 1.99
    platform_per_contract: float = 0.30
    activity_per_contract: float = 0.00279
    regulatory_per_contract: float = 0.015
    # Applied to both entry and exit per side; exact rounding verified at implementation.


@dataclass(frozen=True)
class AgentConfig:
    """Top-level agent configuration."""

    risk: RiskConfig = field(default_factory=RiskConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fees: FeeConfig = field(default_factory=FeeConfig)
    mode: str = "shadow"  # "shadow", "paper", "halt"
    version: str = "1.0.0"


# Singleton loaded from environment for operational use.
AGENT_CONFIG = AgentConfig(
    mode=os.environ.get("SPECTER_MODE", "shadow"),
)
