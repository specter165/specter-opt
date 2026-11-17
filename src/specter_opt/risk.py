"""Portfolio risk controls, reservations and fail-closed state.

RiskGuard is deterministic; the LLM cannot override deny decisions.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pytz

from specter_opt.config import AgentConfig, RiskConfig
from specter_opt.fees import option_fees


@dataclass
class RiskState:
    """Persisted risk baseline and reservations."""

    day_start_equity: float = 0.0
    peak_equity: float = 0.0
    last_equity: float = 0.0
    orders_submitted_today: int = 0
    ny_date: Optional[str] = None
    halted: bool = False
    halt_reason: str = ""
    reservations: Dict[str, float] = field(default_factory=dict)
    version: str = "1.0.0"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RiskState":
        return cls(**d)


class RiskGuard:
    """Deterministic risk gate."""

    def __init__(self, config: AgentConfig, state_file: Optional[str] = None):
        self.risk = config.risk
        self.fees = config.fees
        self.state_file = state_file or config.execution.state_file
        self.state = self._load_state()

    def _load_state(self) -> RiskState:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    return RiskState.from_dict(json.load(f))
            except Exception:
                pass
        return RiskState()

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2, default=str)

    def reset_day(self, equity: float, ny_date: date) -> None:
        self.state.day_start_equity = equity
        self.state.peak_equity = equity
        self.state.last_equity = equity
        self.state.orders_submitted_today = 0
        self.state.ny_date = ny_date.isoformat()
        self.state.reservations.clear()
        self.save_state()

    def update_equity(self, equity: float, ny_date: date) -> Tuple[bool, str]:
        """Update baselines; return (can_trade_new_risk, reason)."""
        ny_date_str = ny_date.isoformat()
        if self.state.ny_date != ny_date_str:
            self.reset_day(equity, ny_date)

        self.state.last_equity = equity
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

        if self.state.halted:
            return False, f"global_halt:{self.state.halt_reason}"

        daily_loss = 1.0 - equity / max(self.state.day_start_equity, 1e-9)
        if daily_loss >= self.risk.daily_equity_loss_block_pct:
            return False, f"daily_loss_{daily_loss:.4f}"

        drawdown = 1.0 - equity / max(self.state.peak_equity, 1e-9)
        if drawdown >= self.risk.peak_drawdown_halt_pct:
            self.state.halted = True
            self.state.halt_reason = f"peak_drawdown_{drawdown:.4f}"
            self.save_state()
            return False, self.state.halt_reason

        self.save_state()
        return True, "ok"

    def reserve_premium(self, intent_id: str, amount: float) -> None:
        self.state.reservations[intent_id] = amount
        self.save_state()

    def release_reservation(self, intent_id: str) -> None:
        self.state.reservations.pop(intent_id, None)
        self.save_state()

    def reserved_premium(self) -> float:
        return sum(self.state.reservations.values())

    def can_enter(
        self,
        equity: float,
        quantity: int,
        ask: float,
        multiplier: int,
        fee_result,
        existing_positions_premium: float,
        pending_order_premium: float,
        ny_date: date,
    ) -> Tuple[bool, str, int]:
        """Evaluate single new-entry risk. Returns (allowed, reason, allowed_qty)."""
        can_trade, reason = self.update_equity(equity, ny_date)
        if not can_trade:
            return False, reason, 0

        if self.state.orders_submitted_today >= self.risk.max_orders_per_us_trading_day:
            return False, "daily_order_limit", 0

        # Per-trade budget including entry fees
        trade_budget = equity * self.risk.per_trade_premium_pct
        entry_premium = quantity * ask * multiplier
        total_entry_cost = entry_premium + fee_result.total_entry
        if total_entry_cost > trade_budget:
            # Reduce quantity to fit budget
            if ask * multiplier <= 0:
                return False, "zero_ask", 0
            max_qty = int((trade_budget - fee_result.total_entry) / (ask * multiplier))
            max_qty = max(0, max_qty)
            if max_qty == 0:
                return False, "per_trade_budget", 0
            quantity = max_qty
            entry_premium = quantity * ask * multiplier
            total_entry_cost = entry_premium + option_fees(
                quantity, ask, multiplier, self.fees
            ).total_entry

        # Aggregate premium ceiling
        aggregate = (
            entry_premium
            + existing_positions_premium
            + pending_order_premium
            + self.reserved_premium()
        )
        if aggregate > equity * self.risk.aggregate_premium_pct:
            return False, "aggregate_premium_limit", 0

        return True, "ok", quantity

    def count_order_submitted(self) -> None:
        self.state.orders_submitted_today += 1
        self.save_state()

    def manual_halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason
        self.save_state()

    def manual_resume(self) -> None:
        self.state.halted = False
        self.state.halt_reason = ""
        self.save_state()


def compute_portfolio_exposure(
    positions: List[dict],
    underlyings: List[str],
) -> Dict[str, float]:
    """Aggregate premium and delta by underlying from position records."""
    exposure = {u: {"premium": 0.0, "delta_dollar": 0.0, "qty": 0} for u in underlyings}
    for p in positions:
        u = p.get("underlying")
        if u not in exposure:
            continue
        qty = p.get("quantity", 0)
        premium = p.get("entry_premium", 0.0) * qty
        delta_dollar = p.get("delta", 0.0) * p.get("underlying_price", 0.0) * qty * p.get("multiplier", 100)
        exposure[u]["premium"] += premium
        exposure[u]["delta_dollar"] += delta_dollar
        exposure[u]["qty"] += qty
    return exposure
