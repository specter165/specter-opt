"""SPECTER-OPT agent orchestrator.

Pipeline: data → validate → forecast → price/screen → optimize → risk gate → execute/no-trade.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pytz

from specter_opt.audit import DecisionLog
from specter_opt.broker import BrokerAdapter, OptionContract, OrderIntent, Position
from specter_opt.calendar import TradingCalendar, now_utc, ny_now
from specter_opt.config import AgentConfig, is_index_symbol
from specter_opt.execution import ExecutionSupervisor
from specter_opt.fees import option_fees
from specter_opt.forecasting import build_joint_scenarios
from specter_opt.pricing import american_tree, implied_volatility
from specter_opt.risk import (
    RiskGuard,
    cluster_headroom,
    compute_cluster_premium,
    compute_portfolio_exposure,
)
from specter_opt.selection import Candidate, evaluate_candidate, rank_candidates, size_candidate


@dataclass
class AgentAction:
    action: str  # HOLD, ENTER, EXIT, CANCEL, HALT
    intent: Optional[OrderIntent] = None
    symbol: str = ""
    reason: str = ""
    candidate_summary: Optional[dict] = None


@dataclass
class AgentRunResult:
    actions: List[AgentAction]
    account_title: str = ""
    equity: float = 0.0
    mode: str = "shadow"
    halted: bool = False
    top_candidate: Optional[dict] = None
    rejection_reasons: List[str] = field(default_factory=list)
    timestamp_utc: Optional[str] = None


class SpecterAgent:
    def __init__(
        self,
        config: AgentConfig,
        broker: BrokerAdapter,
        earnings_dates: Optional[Dict[str, List[str]]] = None,
        universe: Optional[List[str]] = None,
    ):
        self.config = config
        self.broker = broker
        self.risk = RiskGuard(config)
        self.exec_supervisor = ExecutionSupervisor(config.execution.intent_file)
        self.decision_log = DecisionLog(config.execution.decision_log)
        self.calendar = TradingCalendar(config.execution.timezone)
        self.earnings_dates = earnings_dates or {}
        # Screener-selected universe wins; config.universe is the fallback.
        self.universe = list(universe) if universe else list(config.universe)

    def _div_yield(self, underlying: str) -> float:
        """Per-underlying continuous dividend yield, with index-level fallback."""
        y = self.config.dividend_yields.get(underlying)
        return self.config.pricing.dividend_yield if y is None else y

    def _next_earnings(self, underlying: str) -> Optional[date]:
        today = ny_now().date()
        dates = []
        for raw in self.earnings_dates.get(underlying, []):
            try:
                d = date.fromisoformat(str(raw)[:10])
            except Exception:
                continue
            if d >= today:
                dates.append(d)
        return min(dates) if dates else None

    def _earnings_blocked(self, underlying: str) -> Tuple[bool, str]:
        """Fail closed for single names without a usable earnings calendar."""
        if not self.config.risk.earnings_blackout:
            return False, ""
        if is_index_symbol(underlying):
            return False, ""
        if self._next_earnings(underlying) is not None:
            return False, ""
        if self.config.risk.require_earnings_calendar:
            return True, "missing_earnings_calendar"
        return False, ""

    def verify_account(self) -> Tuple[bool, str, dict]:
        """Verify paper account identity and simulated status."""
        try:
            account = self.broker.get_account()
        except Exception as e:
            return False, f"account_read_error:{e}", {}
        ok = (
            self.config.execution.paper_account_title_substring in account.account_title
            and account.market_id == self.config.execution.paper_market_id
            and account.is_paper
        )
        if not ok:
            return False, f"account_identity_mismatch:{account.account_title}", account.__dict__
        return True, "ok", account.__dict__

    def _fetch_option_chains(self, underlyings: List[str]) -> Dict[str, List[OptionContract]]:
        chains = {}
        for u in underlyings:
            try:
                chains[u] = self.broker.get_option_chain(u, expiry_range_days=self.config.risk.max_dte + 2)
            except Exception as e:
                self.decision_log.write("FETCH_CHAIN_ERROR", str(e), {"underlying": u})
                chains[u] = []
        return chains

    def _fetch_underlying_quotes(self, underlyings: List[str]) -> Dict[str, dict]:
        quotes = {}
        for u in underlyings:
            try:
                quotes[u] = self.broker.get_underlying_quote(u)
            except Exception as e:
                self.decision_log.write("FETCH_QUOTE_ERROR", str(e), {"underlying": u})
                quotes[u] = {}
        return quotes

    def _filter_chain(
        self,
        contracts: List[OptionContract],
        underlying_price: float,
        underlying: str,
    ) -> List[OptionContract]:
        """Apply eligibility filters including delta range via IV estimate."""
        r = self.config.risk
        is_index = is_index_symbol(underlying)
        max_spread = r.max_relative_spread if is_index else r.single_name_max_relative_spread
        min_oi = r.min_open_interest if is_index else r.single_name_min_open_interest
        next_earnings = None if is_index else self._next_earnings(underlying)
        q = self._div_yield(underlying)
        filtered = []
        for c in contracts:
            if c.underlying != underlying:
                continue
            # Calendar DTE: require expiry date string ISO
            try:
                expiry = date.fromisoformat(c.expiry)
                dte = (expiry - ny_now().date()).days
            except Exception:
                continue
            if not (r.min_dte <= dte <= r.max_dte):
                continue
            # Never hold a contract across an earnings release.
            if r.earnings_blackout and next_earnings is not None and expiry >= next_earnings:
                continue
            if c.bid <= 0 or c.ask <= 0:
                continue
            if c.spread > max_spread:
                continue
            if c.open_interest < min_oi:
                continue
            if c.quote_age_seconds > r.max_quote_age_seconds:
                continue
            # Estimate |delta| via BSM using mid price and given IV if present
            iv = c.iv
            if iv is None or iv <= 0:
                mid = c.mid
                tau = max(dte, 0) / 365.0
                iv, _ = implied_volatility(
                    mid,
                    underlying_price,
                    c.strike,
                    tau,
                    self.config.pricing.risk_free_rate,
                    q,
                    c.right,
                    american=True,
                    n_steps=20,
                )
            if iv is None or iv <= 0:
                continue
            tau = max(dte, 0) / 365.0
            pr = american_tree(
                underlying_price,
                c.strike,
                tau,
                self.config.pricing.risk_free_rate,
                q,
                iv,
                c.right,
                n_steps=30,
            )
            if abs(pr.delta) < r.min_abs_delta or abs(pr.delta) > r.max_abs_delta:
                continue
            # Enrich contract with greeks
            filtered.append(
                OptionContract(
                    symbol=c.symbol,
                    underlying=c.underlying,
                    right=c.right,
                    strike=c.strike,
                    expiry=c.expiry,
                    multiplier=c.multiplier,
                    bid=c.bid,
                    ask=c.ask,
                    bid_size=c.bid_size,
                    ask_size=c.ask_size,
                    open_interest=c.open_interest,
                    volume=c.volume,
                    iv=iv,
                    delta=pr.delta,
                    gamma=pr.gamma,
                    theta=pr.theta,
                    vega=pr.vega,
                    quote_age_seconds=c.quote_age_seconds,
                )
            )
        return filtered

    def _impute_underlying_iv(
        self,
        underlyings: List[str],
        quotes: Dict[str, dict],
        chains: Dict[str, List[OptionContract]],
    ) -> None:
        """Fill missing underlying IV from the chain's near-the-money contracts.

        Broker quote payloads do not always carry an underlying implied vol, and
        the forecast needs one. Deriving it from the chain is local data, not a
        guess about direction, so it is safe to impute; we log every imputation.
        """
        for u in underlyings:
            q = quotes.get(u) or {}
            raw = q.get("iv")
            try:
                iv = float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                iv = 0.0
            if iv > 0:
                continue
            price = 0.0
            try:
                price = float(q.get("last", 0.0) or 0.0)
            except (TypeError, ValueError):
                price = 0.0
            if price <= 0:
                continue
            usable = [c for c in chains.get(u, []) if c.iv and c.iv > 0]
            if not usable:
                continue
            usable.sort(key=lambda c: abs(c.strike - price))
            sample = [float(c.iv) for c in usable[:8]]
            imputed = sorted(sample)[len(sample) // 2]
            q = dict(q)
            q["iv"] = imputed
            quotes[u] = q
            self.decision_log.write(
                "IMPUTE_IV", "chain_near_money_median", {"underlying": u, "iv": imputed}
            )

    def _build_forecasts(
        self,
        underlyings: List[str],
        quotes: Dict[str, dict],
        returns_cache: Dict[str, np.ndarray],
    ) -> Dict[str, dict]:
        cfg = self.config.forecast
        scenarios = {}
        # For MVP: equal zero-drift for all; M1+ would use returns cache and features.
        for u in underlyings:
            price = quotes[u].get("last", 0.0)
            raw_iv = quotes[u].get("iv")
            try:
                iv = float(raw_iv) if raw_iv is not None else 0.20
            except (TypeError, ValueError):
                iv = 0.20
            if iv <= 0:
                iv = 0.20
            if price <= 0:
                continue
            rets = returns_cache.get(u, np.zeros(60))
            from specter_opt.forecasting import EWMAStudentTForecast
            for h in cfg.horizons:
                model = "M0"
                scen = EWMAStudentTForecast(
                    lambda_=cfg.ewma_lambda,
                    nu=cfg.student_nu,
                    seed=cfg.random_seed,
                    paths=cfg.scenario_paths,
                ).generate(u, price, iv, rets, h, model=model)
                scenarios[(u, h)] = scen
        return scenarios

    def run(self, returns_cache: Optional[Dict[str, np.ndarray]] = None) -> AgentRunResult:
        underlyings = list(self.universe)
        ts = now_utc().isoformat()
        result = AgentRunResult(actions=[], mode=self.config.mode, timestamp_utc=ts)

        # 1. Account verification (fail-closed)
        ok, reason, account = self.verify_account()
        result.account_title = account.get("account_title", "")
        result.equity = account.get("equity", 0.0)
        if not ok:
            result.rejection_reasons.append(reason)
            self.risk.manual_halt(f"account_verification:{reason}")
            self.decision_log.write("HALT", reason, account)
            result.halted = True
            result.actions.append(AgentAction("HOLD", reason=f"account_verification:{reason}"))
            return result

        # 2. Reconciliation
        positions = self.broker.list_positions()
        open_orders = self.broker.list_open_orders()
        self.exec_supervisor.reconcile_all(self.broker)

        # 3. Risk state update
        equity = account["equity"]
        ny_date = ny_now().date()
        can_trade, risk_reason = self.risk.update_equity(equity, ny_date)
        result.halted = self.risk.state.halted

        # 4. Calendar check
        if not self.calendar.is_trading_day(ny_date):
            result.rejection_reasons.append("not_trading_day")
            self.decision_log.write("HOLD", "not_trading_day", {"ny_date": ny_date.isoformat()})
            return result

        # 5. Market data
        quotes = self._fetch_underlying_quotes(underlyings)
        chains = self._fetch_option_chains(underlyings)

        # 6. Build scenarios
        returns_cache = returns_cache or {u: np.zeros(60) for u in underlyings}
        self._impute_underlying_iv(underlyings, quotes, chains)
        scenarios = self._build_forecasts(underlyings, quotes, returns_cache)

        # 7. Screen and evaluate candidates
        candidates: List[Candidate] = []
        for u in underlyings:
            price = quotes.get(u, {}).get("last", 0.0)
            if price <= 0:
                result.rejection_reasons.append(f"{u}:missing_quote")
                self.decision_log.write(
                    "SKIP_UNDERLYING", "missing_quote", {"underlying": u}
                )
                continue
            blocked, block_reason = self._earnings_blocked(u)
            if blocked:
                result.rejection_reasons.append(f"{u}:{block_reason}")
                self.decision_log.write(
                    "SKIP_UNDERLYING", block_reason, {"underlying": u}
                )
                continue
            filtered = self._filter_chain(chains.get(u, []), price, u)
            for c in filtered:
                for h in self.config.forecast.horizons:
                    scen = scenarios.get((u, h))
                    if scen is None:
                        continue
                    cand = evaluate_candidate(
                        c,
                        scen,
                        self.config,
                        model="M0",
                        horizon=h,
                        dividend_yield=self._div_yield(u),
                    )
                    candidates.append(cand)

        ranked = rank_candidates(candidates)

        # Compute existing/pending premium
        existing_premium = sum(p.quantity * p.entry_price * p.multiplier for p in positions)
        pending_premium = sum(
            o.quantity * (o.price or 0.0) * 100 for o in open_orders
        )  # multiplier fallback handled by broker records
        cluster_current = compute_cluster_premium(
            positions,
            self.config.cluster_membership,
            self.config.risk.default_cluster,
        )

        # 8. Select top candidate under limits
        selected: Optional[Candidate] = None
        for cand in ranked:
            qty = size_candidate(
                cand,
                equity,
                existing_premium,
                pending_premium,
                self.risk.reserved_premium(),
                self.config,
            )
            if qty <= 0:
                cand.rejection_reasons.append("zero_sized")
                continue
            fee_result = option_fees(qty, cand.entry_ask, cand.contract.multiplier, self.config.fees)
            headroom = cluster_headroom(
                equity,
                self.config.risk.cluster_premium_cap_pct,
                cluster_current,
                cand.contract.underlying,
                self.config.cluster_membership,
                self.config.risk.default_cluster,
            )
            allowed, reason, allowed_qty = self.risk.can_enter(
                equity,
                qty,
                cand.entry_ask,
                cand.contract.multiplier,
                fee_result,
                existing_premium,
                pending_premium,
                ny_date,
                cluster_headroom=headroom,
            )
            if not allowed:
                cand.rejection_reasons.append(f"risk_gate:{reason}")
                continue
            cand.allowed_qty = allowed_qty
            selected = cand
            break

        # 9. Decide action
        if not can_trade:
            result.rejection_reasons.append(risk_reason)
            result.actions.append(AgentAction("HOLD", reason=risk_reason))
            self.decision_log.write("HOLD", risk_reason, {"equity": equity})
        elif selected is None:
            result.rejection_reasons.append("no_candidate")
            result.actions.append(AgentAction("HOLD", reason="no_candidate"))
            if ranked:
                result.top_candidate = self._candidate_summary(ranked[0])
            self.decision_log.write(
                "NO_TRADE",
                "no_candidate_passed",
                {
                    "candidate_count": len(candidates),
                    "ranked_count": len(ranked),
                    "top_candidate": result.top_candidate,
                },
            )
        else:
            # Build limit order intent at mid or slight conservative offset
            price = self._entry_price(selected.contract)
            # Check for duplicate before persisting the intent to avoid self-matching
            if self.exec_supervisor.duplicate_exists(
                selected.contract.symbol, "BUY", price, within_seconds=60
            ):
                self.decision_log.write(
                    "DUPLICATE_PREVENTED",
                    "intent_exists",
                    {"symbol": selected.contract.symbol, "price": price},
                )
                result.rejection_reasons.append("duplicate_intent")
                result.actions.append(AgentAction("HOLD", reason="duplicate_intent"))
                return result

            intent = self.exec_supervisor.new_intent(
                symbol=selected.contract.symbol,
                side="BUY",
                quantity=selected.allowed_qty,
                price=price,
                order_type="LIMIT",
                reason=f"robust_edge={selected.robust_edge:.2f},cvar95={selected.cvar95:.2f},score={selected.score:.4f}",
                expected_premium=selected.expected_entry_premium * selected.allowed_qty,
            )
            action = AgentAction(
                "ENTER",
                intent=intent,
                symbol=selected.contract.symbol,
                reason=intent.reason,
                candidate_summary=self._candidate_summary(selected),
            )
            result.actions.append(action)
            result.top_candidate = self._candidate_summary(selected)
            self.risk.reserve_premium(intent.intent_id, intent.expected_premium)
            self.decision_log.write(
                "ENTER_INTENT",
                intent.reason,
                {
                    "intent_id": intent.intent_id,
                    "symbol": intent.symbol,
                    "quantity": intent.quantity,
                    "price": intent.price,
                    "candidate": result.top_candidate,
                },
            )
            if self.config.mode == "paper":
                try:
                    order = self.broker.place_order(intent)
                    self.exec_supervisor.mark_submitted(intent.intent_id, order.order_id)
                    self.risk.count_order_submitted()
                    self.decision_log.write(
                        "ORDER_SUBMITTED",
                        "ok",
                        {
                            "intent_id": intent.intent_id,
                            "order_id": order.order_id,
                            "status": order.status,
                        },
                    )
                except Exception as e:
                    self.decision_log.write("ORDER_SUBMIT_ERROR", str(e), intent.__dict__)
            else:
                self.decision_log.write("SHADOW_HOLD", "shadow_mode", intent.__dict__)

        return result

    def _candidate_summary(self, cand: Candidate) -> dict:
        return {
            "symbol": cand.contract.symbol,
            "underlying": cand.contract.underlying,
            "right": cand.contract.right,
            "strike": cand.contract.strike,
            "expiry": cand.contract.expiry,
            "bid": cand.contract.bid,
            "ask": cand.contract.ask,
            "iv": cand.contract.iv,
            "delta": cand.contract.delta,
            "ev": cand.ev,
            "cvar95": cand.cvar95,
            "robust_edge": cand.robust_edge,
            "score": cand.score,
            "allowed_qty": cand.allowed_qty,
            "rejection_reasons": cand.rejection_reasons,
        }

    def _entry_price(self, contract: OptionContract) -> Optional[float]:
        if not self.config.execution.order_type_limit:
            return None
        offset = self.config.execution.entry_offset_to_mid
        if contract.bid > 0 and contract.ask > 0:
            mid = 0.5 * (contract.bid + contract.ask)
            # Round down to nearest cent
            return round(mid - offset, 2)
        return round(contract.ask, 2)
