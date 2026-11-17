"""Contract screening, scenario repricing, robust-edge/CVaR ranking and sizing."""

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np

from specter_opt.broker import OptionContract
from specter_opt.config import AgentConfig, is_index_symbol
from specter_opt.fees import option_fees, round_lot_quantity
from specter_opt.forecasting import ScenarioSet
from specter_opt.pricing import american_tree_raw, bsm_price


@dataclass
class Candidate:
    contract: OptionContract
    model: str
    horizon: int
    entry_ask: float
    exit_bids: np.ndarray
    net_pnl: np.ndarray
    ev: float
    cvar95: float
    robust_edge: float
    score: float
    rejection_reasons: List[str] = field(default_factory=list)
    allowed_qty: int = 0
    expected_entry_premium: float = 0.0


def _days_to_years(dte: int) -> float:
    return max(dte, 0) / 365.0


def screen_contract(contract: OptionContract, config: AgentConfig) -> List[str]:
    reasons = []
    r = config.risk
    if contract.right not in ("CALL", "PUT"):
        reasons.append("invalid_right")
    if contract.ask <= 0:
        reasons.append("no_ask")
    if is_index_symbol(contract.underlying):
        max_spread, min_oi = r.max_relative_spread, r.min_open_interest
    else:
        max_spread = r.single_name_max_relative_spread
        min_oi = r.single_name_min_open_interest
    if contract.spread > max_spread:
        reasons.append("wide_spread")
    if contract.open_interest < min_oi:
        reasons.append("low_oi")
    if contract.quote_age_seconds > r.max_quote_age_seconds:
        reasons.append("stale_quote")
    return reasons


def evaluate_candidate(
    contract: OptionContract,
    scenarios: ScenarioSet,
    config: AgentConfig,
    model: str = "M0",
    horizon: int = 1,
    exit_spread_factor: float = 1.0,
    dividend_yield: Optional[float] = None,
) -> Candidate:
    """Reprice contract under each scenario and compute EV/CVaR."""
    r = config.pricing.risk_free_rate
    q = config.pricing.dividend_yield if dividend_yield is None else dividend_yield
    multiplier = contract.multiplier
    entry_ask = contract.ask

    tau_entry = _days_to_years(horizon)
    tau_exit = max(0.0, tau_entry - horizon / 365.0)

    exit_bids = np.empty(len(scenarios.spots))
    for i, (S, iv) in enumerate(zip(scenarios.spots, scenarios.ivs)):
        # Conservative executable exit bid: model bid minus half-spread estimate
        model_price = american_tree_raw(S, contract.strike, tau_exit, r, q, iv, contract.right, n_steps=30)
        spread_penalty = exit_spread_factor * (contract.ask - contract.bid) * 0.5
        exit_bids[i] = max(model_price - spread_penalty, 0.0)

    # Entry cost
    fee_entry = option_fees(1, entry_ask, multiplier, config.fees).total_entry
    fee_exit = option_fees(1, float(np.median(exit_bids)), multiplier, config.fees).total_exit

    # Per-contract net P&L
    gross_exit = multiplier * exit_bids
    gross_entry = multiplier * entry_ask
    net_pnl = gross_exit - gross_entry - fee_entry - fee_exit

    ev = float(np.mean(net_pnl))
    losses = -net_pnl
    cvar95 = float(compute_cvar(losses, config.risk.cvar_alpha))

    # Robust edge with model uncertainty placeholder U = 0 for M0 baseline
    U = 0.0
    robust_edge = ev - U

    premium_at_risk = gross_entry + fee_entry
    score = (robust_edge - config.risk.lambda_risk * cvar95) / max(premium_at_risk, 1e-9)

    reasons = screen_contract(contract, config)
    if robust_edge <= 0:
        reasons.append("nonpositive_robust_edge")
    if score < config.risk.min_score_threshold:
        reasons.append(f"score_below_threshold:{score:.4f}")

    return Candidate(
        contract=contract,
        model=model,
        horizon=horizon,
        entry_ask=entry_ask,
        exit_bids=exit_bids,
        net_pnl=net_pnl,
        ev=ev,
        cvar95=cvar95,
        robust_edge=robust_edge,
        score=score,
        rejection_reasons=reasons,
        expected_entry_premium=gross_entry,
    )


def compute_cvar(losses: np.ndarray, alpha: float = 0.95) -> float:
    """Sample CVaR of losses at level alpha."""
    if len(losses) == 0:
        return 0.0
    var = np.quantile(losses, alpha)
    tail = losses[losses >= var]
    if len(tail) == 0:
        return float(var)
    return float(np.mean(tail))


def rank_candidates(candidates: List[Candidate]) -> List[Candidate]:
    survivors = [c for c in candidates if not c.rejection_reasons]
    return sorted(survivors, key=lambda c: c.score, reverse=True)


def size_candidate(
    candidate: Candidate,
    equity: float,
    existing_premium: float,
    pending_premium: float,
    reserved_premium: float,
    config: AgentConfig,
) -> int:
    """Integer quantity under premium limits and fee minima."""
    r = config.risk
    multiplier = candidate.contract.multiplier
    ask = candidate.entry_ask

    trade_budget = equity * r.per_trade_premium_pct
    agg_budget = equity * r.aggregate_premium_pct - existing_premium - pending_premium - reserved_premium
    budget = min(trade_budget, agg_budget)
    if budget <= 0:
        return 0

    # Iteratively solve q*ask*multiplier + fees(q) <= budget
    q = 0
    while True:
        q_next = q + 1
        premium = q_next * ask * multiplier
        fees = option_fees(q_next, ask, multiplier, config.fees).total_entry
        if premium + fees > budget:
            break
        q = q_next
    return round_lot_quantity(q)
