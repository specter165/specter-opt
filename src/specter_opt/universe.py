"""Deterministic universe selection from Moomoo option-screener output.

The screener ranks option *contracts*. This module aggregates them to the
underlying level (volume, open interest, implied volatility), applies hard
liquidity/price/IV filters, and returns a ranked, capped symbol list.

Selection is deterministic: same input -> same output, with ties broken by
symbol. No LLM judgement is involved, so the universe cannot drift silently.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from specter_opt.config import UniverseConfig


@dataclass
class SymbolMetrics:
    symbol: str
    option_volume: float = 0.0
    option_open_interest: float = 0.0
    iv: float = 0.0
    price: float = 0.0
    contracts: int = 0
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "option_volume": int(self.option_volume),
            "option_open_interest": int(self.option_open_interest),
            "iv": round(self.iv, 6),
            "price": round(self.price, 4),
            "contracts": self.contracts,
            "score": round(self.score, 6),
        }


@dataclass
class UniverseSelection:
    as_of: str
    generated_at: str
    ttl_hours: float
    symbols: List[str] = field(default_factory=list)
    metrics: Dict[str, dict] = field(default_factory=dict)
    excluded: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "ttl_hours": self.ttl_hours,
            "symbols": self.symbols,
            "metrics": self.metrics,
            "excluded": self.excluded,
        }


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_iv(value: Optional[float]) -> Optional[float]:
    """Screener IVs arrive in percent (27.7); return a decimal (0.277)."""
    if value is None or value <= 0:
        return None
    return value / 100.0 if value > 3.0 else value


def _iter_option_rows(payload: Any) -> Iterable[dict]:
    """Accept a raw quote_option_screen response or the bare data envelope."""
    if payload is None:
        return []
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        rows = data.get("option_list") or data.get("list") or []
    else:
        rows = data
    return [r for r in rows if isinstance(r, dict)]


def aggregate_metrics(option_rows: Iterable[dict]) -> Dict[str, SymbolMetrics]:
    """Aggregate contract rows to per-underlying volume, OI and IV."""
    out: Dict[str, SymbolMetrics] = {}
    iv_samples: Dict[str, List[float]] = {}
    for row in option_rows:
        symbol = str(row.get("product_code") or "").upper().strip()
        if not symbol:
            continue
        m = out.setdefault(symbol, SymbolMetrics(symbol=symbol))
        m.contracts += 1
        m.option_volume += _to_float(row.get("volume")) or 0.0
        m.option_open_interest += _to_float(row.get("open_interest")) or 0.0

        underlying = row.get("underlying") or {}
        price = _to_float(underlying.get("price"))
        if price and m.price <= 0:
            m.price = price

        iv = _normalise_iv(_to_float(underlying.get("iv")))
        if iv is None:
            iv = _normalise_iv(_to_float(row.get("implied_volatility")))
        if iv is not None:
            iv_samples.setdefault(symbol, []).append(iv)

    for symbol, samples in iv_samples.items():
        out[symbol].iv = float(statistics.median(samples))
    return out


def _zscore(values: List[float]) -> List[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return [0.0] * len(values)
    return [(v - mean) / sd for v in values]


def _reject_reason(m: SymbolMetrics, cfg: UniverseConfig, symbol: str) -> Optional[str]:
    if symbol in {s.upper() for s in cfg.exclude}:
        return "excluded_by_config"
    if m.price <= 0:
        return "missing_underlying_price"
    if not (cfg.min_underlying_price <= m.price <= cfg.max_underlying_price):
        return "price_out_of_range"
    if m.option_volume < cfg.min_option_volume:
        return "low_option_volume"
    if m.option_open_interest < cfg.min_option_open_interest:
        return "low_option_open_interest"
    if m.iv <= 0:
        return "missing_iv"
    if not (cfg.min_iv <= m.iv <= cfg.max_iv):
        return "iv_out_of_range"
    return None


def select_universe(
    option_payloads: List[Any],
    cfg: UniverseConfig,
    as_of: Optional[str] = None,
) -> UniverseSelection:
    """Rank underlyings from one or more screener payloads.

    Hard filters first, then a composite z-score over log(volume), log(OI) and
    IV. Anchors from ``always_include`` are prepended if they survive filters.
    """
    rows: List[dict] = []
    for payload in option_payloads:
        rows.extend(_iter_option_rows(payload))

    metrics = aggregate_metrics(rows)
    eligible: List[SymbolMetrics] = []
    excluded: List[dict] = []
    for symbol in sorted(metrics):
        reason = _reject_reason(metrics[symbol], cfg, symbol)
        if reason:
            excluded.append({"symbol": symbol, "reason": reason})
        else:
            eligible.append(metrics[symbol])

    if eligible:
        vol_z = _zscore([math.log1p(m.option_volume) for m in eligible])
        oi_z = _zscore([math.log1p(m.option_open_interest) for m in eligible])
        iv_z = _zscore([m.iv for m in eligible])
        for m, vz, oz, iz in zip(eligible, vol_z, oi_z, iv_z):
            m.score = cfg.weight_volume * vz + cfg.weight_open_interest * oz + cfg.weight_iv * iz

        # Deterministic order: score desc, then option volume, then symbol.
        eligible.sort(key=lambda m: (-m.score, -m.option_volume, m.symbol))

    chosen = eligible[: max(cfg.max_symbols, 0)]
    symbols = [m.symbol for m in chosen]

    anchors = [s.upper() for s in cfg.always_include]
    for anchor in reversed(anchors):
        if anchor in metrics and anchor not in symbols:
            if _reject_reason(metrics[anchor], cfg, anchor) is None:
                symbols.insert(0, anchor)
    symbols = symbols[: max(cfg.max_symbols, 0)]

    now = datetime.now(timezone.utc)
    return UniverseSelection(
        as_of=as_of or now.date().isoformat(),
        generated_at=now.isoformat(),
        ttl_hours=cfg.ttl_hours,
        symbols=symbols,
        metrics={m.symbol: m.to_dict() for m in eligible},
        excluded=excluded,
    )


def load_universe(path: str) -> Optional[dict]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def universe_is_fresh(payload: Optional[dict], ttl_hours: Optional[float] = None, now: Optional[datetime] = None) -> bool:
    """True when a cached selection is within its TTL and non-empty."""
    if not payload or not payload.get("symbols"):
        return False
    ttl = ttl_hours if ttl_hours is not None else float(payload.get("ttl_hours") or 8.0)
    try:
        generated = datetime.fromisoformat(str(payload.get("generated_at")))
    except Exception:
        return False
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - generated <= timedelta(hours=ttl)


def universe_symbols(payload: Optional[dict]) -> List[str]:
    if not payload:
        return []
    return [str(s).upper() for s in payload.get("symbols", []) if str(s).strip()]
