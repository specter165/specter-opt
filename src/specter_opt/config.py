"""SPECTER-OPT configuration and constants."""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class RiskConfig:
    """Internal risk ceilings; official competition rules may be stricter."""

    # Original conservative sizing: 1.0% per trade, 3.0% aggregate,
    # 3 concurrent positions, 5% peak-drawdown halt.
    per_trade_premium_pct: float = 0.010
    aggregate_premium_pct: float = 0.030
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
    # Stricter gates for single-name options: wider wings, thinner books.
    single_name_max_relative_spread: float = 0.03
    single_name_min_open_interest: int = 1000
    # Never hold a contract whose life spans a KNOWN earnings release.
    earnings_blackout: bool = True
    # Moomoo exposes no forward earnings dates, so failing closed on a missing
    # calendar blocked every single name permanently. Trade the name instead,
    # but keep the contract short-dated so an unannounced release cannot sit
    # inside its life for long.
    require_earnings_calendar: bool = False
    unknown_earnings_max_dte: int = 10
    # Correlated-exposure ceiling per cluster, as a fraction of equity.
    cluster_premium_cap_pct: float = 0.02
    # Fallback cluster for symbols discovered by the screener.
    default_cluster: str = "single_name"
    max_quote_age_seconds: float = 10.0
    exit_before_expiry_sessions: int = 1
    cvar_alpha: float = 0.95
    # score = (EV - lambda_risk * CVaR95) / premium. For a long option CVaR95 is
    # close to the whole premium, so lambda=1.0 demanded EV > ~100% of premium
    # and was unsatisfiable by construction. 0.1 still requires the expected
    # edge to clear a tenth of the tail loss before a position is opened.
    lambda_risk: float = 0.1
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
class UniverseConfig:
    """Screener-driven universe selection thresholds."""

    max_symbols: int = 8
    ttl_hours: float = 8.0
    min_option_volume: int = 5_000
    min_option_open_interest: int = 20_000
    min_underlying_price: float = 10.0
    max_underlying_price: float = 5_000.0
    min_iv: float = 0.08
    max_iv: float = 2.0
    # Optional anchors always kept if they pass the filters (empty = fully dynamic).
    always_include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    # Composite score weights over standardised log(volume), log(OI) and IV.
    weight_volume: float = 0.5
    weight_open_interest: float = 0.3
    weight_iv: float = 0.2


@dataclass(frozen=True)
class AgentConfig:
    """Top-level agent configuration."""

    universe: List[str] = field(default_factory=lambda: ["SPY", "QQQ", "NVDA", "AAPL"])
    # Approximate continuous dividend yields; index-level fallback is pricing.dividend_yield.
    dividend_yields: Dict[str, float] = field(
        default_factory=lambda: {
            "SPY": 0.0120,
            "QQQ": 0.0055,
            "NVDA": 0.0003,
            "AAPL": 0.0040,
        }
    )
    # Correlated-exposure clusters: a symbol in N clusters consumes N budgets.
    cluster_membership: Dict[str, Tuple[str, ...]] = field(
        default_factory=lambda: {
            "SPY": ("index",),
            "QQQ": ("index", "megacap_tech"),
            "NVDA": ("megacap_tech",),
            "AAPL": ("megacap_tech",),
        }
    )
    risk: RiskConfig = field(default_factory=RiskConfig)
    universe_selection: UniverseConfig = field(default_factory=UniverseConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fees: FeeConfig = field(default_factory=FeeConfig)
    mode: str = "shadow"  # "shadow", "paper", "halt"
    version: str = "1.1.0"


INDEX_SYMBOLS = frozenset({"SPY", "QQQ", "IWM", "DIA"})


def is_index_symbol(symbol: str) -> bool:
    """True for broad-based ETFs, which get looser liquidity gates."""
    return symbol.upper() in INDEX_SYMBOLS


# Singleton loaded from environment for operational use.
AGENT_CONFIG = AgentConfig(
    mode=os.environ.get("SPECTER_MODE", "shadow"),
)
