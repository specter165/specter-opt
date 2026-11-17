"""Order execution supervisor with idempotency and reconciliation."""

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from specter_opt.broker import BrokerAdapter, BrokerOrder, OrderIntent


@dataclass
class PersistedIntent:
    intent_id: str
    symbol: str
    side: str
    quantity: int
    price: Optional[float]
    order_type: str
    reason: str
    expected_premium: float
    status: str
    order_id: Optional[str] = None
    fill_qty: int = 0
    avg_fill_price: Optional[float] = None
    created_at_utc: Optional[str] = None
    updated_at_utc: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class ExecutionSupervisor:
    """Persisted intents and reconciliation."""

    def __init__(self, intent_file: str):
        self.intent_file = intent_file
        self.intents: Dict[str, PersistedIntent] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.intent_file):
            return
        try:
            with open(self.intent_file, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    self.intents[d["intent_id"]] = PersistedIntent(**d)
        except Exception:
            self.intents = {}

    def _append(self, intent: PersistedIntent) -> None:
        os.makedirs(os.path.dirname(self.intent_file), exist_ok=True)
        with open(self.intent_file, "a") as f:
            f.write(json.dumps(intent.to_dict(), default=str) + "\n")

    def new_intent(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: Optional[float],
        order_type: str,
        reason: str,
        expected_premium: float,
    ) -> OrderIntent:
        intent_id = f"{datetime.now(pytz.UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        ts = datetime.now(pytz.UTC).isoformat()
        pi = PersistedIntent(
            intent_id=intent_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            reason=reason,
            expected_premium=expected_premium,
            status="PENDING",
            created_at_utc=ts,
            updated_at_utc=ts,
        )
        self.intents[intent_id] = pi
        self._append(pi)
        return OrderIntent(
            intent_id=intent_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            reason=reason,
            expected_premium=expected_premium,
            timestamp_utc=datetime.fromisoformat(ts),
        )

    def mark_submitted(self, intent_id: str, order_id: Optional[str]) -> None:
        pi = self.intents.get(intent_id)
        if not pi:
            return
        pi.status = "SUBMITTED"
        pi.order_id = order_id
        pi.updated_at_utc = datetime.now(pytz.UTC).isoformat()
        self._append(pi)

    def reconcile_order(self, broker_order: BrokerOrder) -> None:
        pi = self.intents.get(broker_order.intent_id)
        if not pi:
            return
        pi.status = broker_order.status
        pi.order_id = broker_order.order_id
        pi.fill_qty = broker_order.filled_qty
        pi.avg_fill_price = broker_order.avg_fill_price
        pi.updated_at_utc = datetime.now(pytz.UTC).isoformat()
        self._append(pi)

    def reconcile_all(self, broker: BrokerAdapter) -> List[BrokerOrder]:
        """Reconcile open intents with broker state."""
        broker_orders = broker.list_open_orders()
        for o in broker_orders:
            self.reconcile_order(o)
        return broker_orders

    def active_intents(self) -> List[PersistedIntent]:
        return [pi for pi in self.intents.values() if pi.status in ("PENDING", "SUBMITTED", "NEW", "PARTIAL_FILLED")]

    def duplicate_exists(self, symbol: str, side: str, price: Optional[float], within_seconds: int = 60) -> bool:
        now = datetime.now(pytz.UTC)
        for pi in self.intents.values():
            if pi.symbol != symbol or pi.side != side:
                continue
            if pi.status in ("CANCELLED", "REJECTED", "FILLED"):
                continue
            try:
                created = datetime.fromisoformat(pi.created_at_utc or "")
                if created.tzinfo is None:
                    created = pytz.UTC.localize(created)
                if (now - created).total_seconds() <= within_seconds:
                    return True
            except Exception:
                continue
        return False
