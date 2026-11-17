"""Broker interface and Moomoo paper-account adapter.

The concrete adapter is implemented by the runner that has access to MCP tools.
This module defines data contracts and a mock broker for tests.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    underlying: str
    right: str  # CALL / PUT
    strike: float
    expiry: str  # ISO date
    multiplier: int
    bid: float
    ask: float
    bid_size: int = 0
    ask_size: int = 0
    open_interest: int = 0
    volume: int = 0
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    quote_age_seconds: float = 0.0
    last_trade: Optional[str] = None

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return 0.5 * (self.bid + self.ask)
        return self.ask if self.ask > 0 else self.bid

    @property
    def spread(self) -> float:
        if self.mid > 0:
            return (self.ask - self.bid) / self.mid
        return float("inf")


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    account_title: str
    market_id: int
    equity: float
    cash: float
    buying_power: float
    is_paper: bool = True
    timestamp_utc: Optional[datetime] = None


@dataclass(frozen=True)
class Position:
    symbol: str
    underlying: str
    right: str
    strike: float
    expiry: str
    quantity: int
    entry_price: float
    multiplier: int
    market_price: float
    unrealized_pnl: float
    delta: Optional[float] = None


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    symbol: str
    side: str  # BUY / SELL
    quantity: int
    price: Optional[float]
    order_type: str  # LIMIT / MARKET
    reason: str
    expected_premium: float
    timestamp_utc: datetime


@dataclass
class BrokerOrder:
    order_id: Optional[str]
    intent_id: str
    symbol: str
    side: str
    quantity: int
    price: Optional[float]
    order_type: str
    status: str  # PENDING_NEW, NEW, PARTIAL_FILLED, FILLED, CANCELLED, REJECTED, UNKNOWN
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None


class BrokerAdapter(ABC):
    """Abstract broker adapter."""

    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        raise NotImplementedError

    @abstractmethod
    def list_positions(self) -> List[Position]:
        raise NotImplementedError

    @abstractmethod
    def list_open_orders(self) -> List[BrokerOrder]:
        raise NotImplementedError

    @abstractmethod
    def get_option_chain(self, underlying: str, expiry_range_days: int = 30) -> List[OptionContract]:
        raise NotImplementedError

    @abstractmethod
    def get_underlying_quote(self, underlying: str) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, intent: OrderIntent) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def get_fills(self, order_id: str) -> List[Dict]:
        raise NotImplementedError


class MockBroker(BrokerAdapter):
    """In-memory mock broker for unit tests and shadow mode."""

    def __init__(self, initial_equity: float = 100000.0, account_title: str = "Mock Paper", market_id: int = 100):
        self.equity = initial_equity
        self.cash = initial_equity
        self.account_title = account_title
        self.market_id = market_id
        self.positions: List[Position] = []
        self.orders: List[BrokerOrder] = []
        self.option_chains: Dict[str, List[OptionContract]] = {}
        self.underlying_quotes: Dict[str, dict] = {}
        self._order_counter = 0

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="MOCK",
            account_title=self.account_title,
            market_id=self.market_id,
            equity=self.equity,
            cash=self.cash,
            buying_power=self.cash,
            is_paper=True,
        )

    def list_positions(self) -> List[Position]:
        return list(self.positions)

    def list_open_orders(self) -> List[BrokerOrder]:
        return [o for o in self.orders if o.status in ("PENDING_NEW", "NEW", "PARTIAL_FILLED")]

    def get_option_chain(self, underlying: str, expiry_range_days: int = 30) -> List[OptionContract]:
        return self.option_chains.get(underlying, [])

    def get_underlying_quote(self, underlying: str) -> Dict:
        return self.underlying_quotes.get(underlying, {"last": 100.0, "bid": 99.99, "ask": 100.01})

    def place_order(self, intent: OrderIntent) -> BrokerOrder:
        self._order_counter += 1
        order = BrokerOrder(
            order_id=f"MOCK-{self._order_counter}",
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            price=intent.price,
            order_type=intent.order_type,
            status="NEW",
        )
        self.orders.append(order)
        return order

    def cancel_order(self, order_id: str) -> BrokerOrder:
        for o in self.orders:
            if o.order_id == order_id:
                o.status = "CANCELLED"
                return o
        return BrokerOrder(order_id=order_id, intent_id="", symbol="", side="", quantity=0, price=None, order_type="", status="UNKNOWN")

    def get_fills(self, order_id: str) -> List[Dict]:
        return []
