"""Moomoo paper-account adapter populated from MCP tool results.

The assistant calls MCP tools and feeds the responses into this adapter;
the adapter itself does not call MCP tools so it remains testable offline.
"""

from typing import Dict, List

from specter_opt.broker import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerOrder,
    OptionContract,
    OrderIntent,
    Position,
)


class MoomooPaperBroker(BrokerAdapter):
    """Static adapter constructed from already-queried MCP data."""

    def __init__(
        self,
        account: dict,
        positions: List[dict],
        open_orders: List[dict],
        option_chains: Dict[str, List[dict]],
        underlying_quotes: Dict[str, dict],
        order_placer=None,
        order_canceller=None,
    ):
        self._account = account
        self._positions = positions
        self._open_orders = open_orders
        self._option_chains = option_chains
        self._underlying_quotes = underlying_quotes
        self._order_placer = order_placer
        self._order_canceller = order_canceller

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=str(self._account.get("account_id", "")),
            account_title=self._account.get("account_title", ""),
            market_id=int(self._account.get("market_id", 0)),
            equity=float(self._account.get("equity", 0.0)),
            cash=float(self._account.get("cash", 0.0)),
            buying_power=float(self._account.get("buying_power", 0.0)),
            is_paper=bool(self._account.get("is_paper", True)),
        )

    def list_positions(self) -> List[Position]:
        out = []
        for p in self._positions:
            out.append(
                Position(
                    symbol=p.get("symbol", ""),
                    underlying=p.get("underlying", ""),
                    right=p.get("right", ""),
                    strike=float(p.get("strike", 0.0)),
                    expiry=p.get("expiry", ""),
                    quantity=int(p.get("quantity", 0)),
                    entry_price=float(p.get("entry_price", 0.0)),
                    multiplier=int(p.get("multiplier", 100)),
                    market_price=float(p.get("market_price", 0.0)),
                    unrealized_pnl=float(p.get("unrealized_pnl", 0.0)),
                    delta=p.get("delta"),
                )
            )
        return out

    def list_open_orders(self) -> List[BrokerOrder]:
        out = []
        for o in self._open_orders:
            out.append(
                BrokerOrder(
                    order_id=o.get("order_id"),
                    intent_id=o.get("intent_id", ""),
                    symbol=o.get("symbol", ""),
                    side=o.get("side", ""),
                    quantity=int(o.get("quantity", 0)),
                    price=o.get("price"),
                    order_type=o.get("order_type", ""),
                    status=o.get("status", "UNKNOWN"),
                    filled_qty=int(o.get("filled_qty", 0)),
                    avg_fill_price=o.get("avg_fill_price"),
                )
            )
        return out

    def get_option_chain(self, underlying: str, expiry_range_days: int = 30) -> List[OptionContract]:
        out = []
        for c in self._option_chains.get(underlying, []):
            out.append(
                OptionContract(
                    symbol=c.get("symbol", ""),
                    underlying=c.get("underlying", underlying),
                    right=c.get("right", "CALL"),
                    strike=float(c.get("strike", 0.0)),
                    expiry=c.get("expiry", ""),
                    multiplier=int(c.get("multiplier", 100)),
                    bid=float(c.get("bid", 0.0)),
                    ask=float(c.get("ask", 0.0)),
                    bid_size=int(c.get("bid_size", 0)),
                    ask_size=int(c.get("ask_size", 0)),
                    open_interest=int(c.get("open_interest", 0)),
                    volume=int(c.get("volume", 0)),
                    iv=c.get("iv"),
                    delta=c.get("delta"),
                    gamma=c.get("gamma"),
                    theta=c.get("theta"),
                    vega=c.get("vega"),
                    quote_age_seconds=float(c.get("quote_age_seconds", 0.0)),
                )
            )
        return out

    def get_underlying_quote(self, underlying: str) -> dict:
        return self._underlying_quotes.get(underlying, {})

    def place_order(self, intent: OrderIntent) -> BrokerOrder:
        if self._order_placer is None:
            raise RuntimeError("No order_placer configured; running in read-only mode")
        return self._order_placer(intent)

    def cancel_order(self, order_id: str) -> BrokerOrder:
        if self._order_canceller is None:
            raise RuntimeError("No order_canceller configured")
        return self._order_canceller(order_id)

    def get_fills(self, order_id: str) -> List[dict]:
        return []
