"""Tests for screener-driven universe selection."""

import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.config import UniverseConfig
from specter_opt.risk import cluster_headroom, compute_cluster_premium
from specter_opt.universe import (
    aggregate_metrics,
    select_universe,
    universe_is_fresh,
    universe_symbols,
)
from types import SimpleNamespace


def _row(product, volume, oi, price, iv_pct, dte=14):
    return {
        "product_code": product,
        "volume": str(volume),
        "open_interest": str(oi),
        "implied_volatility": iv_pct,
        "underlying": {"price": price, "iv": iv_pct},
    }


def _payload(*rows):
    return {"ret_code": 0, "data": {"option_list": list(rows)}}


def test_aggregates_contracts_to_underlying():
    payload = _payload(
        _row("AAA", 1000, 5000, 50.0, 30.0),
        _row("AAA", 2000, 6000, 50.1, 32.0),
        _row("BBB", 700, 4000, 25.0, 40.0),
    )
    metrics = aggregate_metrics(payload["data"]["option_list"])
    assert metrics["AAA"].option_volume == 3000
    assert metrics["AAA"].option_open_interest == 11000
    assert metrics["AAA"].contracts == 2
    # IVs are percent in the feed and median-aggregated, then decimalised.
    assert abs(metrics["AAA"].iv - 0.31) < 1e-9


def test_hard_filters_reject_illiquid_or_odd_symbols():
    cfg = replace(UniverseConfig(), min_option_volume=5000, min_option_open_interest=20000)
    payload = _payload(
        _row("GOOD", 50_000, 80_000, 100.0, 35.0),
        _row("THIN", 100, 80_000, 100.0, 35.0),
        _row("LOWOI", 50_000, 100, 100.0, 35.0),
        _row("PENNY", 50_000, 80_000, 1.0, 35.0),
        _row("WILDIV", 50_000, 80_000, 100.0, 900.0),
    )
    sel = select_universe([payload], cfg)
    assert sel.symbols == ["GOOD"]
    reasons = {e["symbol"]: e["reason"] for e in sel.excluded}
    assert reasons["THIN"] == "low_option_volume"
    assert reasons["LOWOI"] == "low_option_open_interest"
    assert reasons["PENNY"] == "price_out_of_range"
    assert reasons["WILDIV"] == "iv_out_of_range"


def test_ranking_is_deterministic_and_capped():
    rows = [
        _row("AAA", 10_000, 30_000, 50.0, 30.0),
        _row("BBB", 90_000, 30_000, 50.0, 30.0),
        _row("CCC", 10_000, 30_000, 50.0, 30.0),
    ]
    cfg = replace(UniverseConfig(), max_symbols=2, min_option_volume=1000,
                  min_option_open_interest=1000, min_iv=0.0)
    first = select_universe([_payload(*rows)], cfg)
    second = select_universe([_payload(*rows)], cfg)
    assert first.symbols == second.symbols
    # BBB has the volume edge; AAA/CCC tie is broken alphabetically.
    assert first.symbols == ["BBB", "AAA"]
    assert len(first.symbols) == 2


def test_anchors_are_kept_only_if_they_pass_filters():
    cfg = replace(UniverseConfig(), max_symbols=2, min_option_volume=1000,
                  min_option_open_interest=1000, min_iv=0.0,
                  always_include=["SPY", "ILLQ"])
    payload = _payload(
        _row("AAA", 90_000, 30_000, 50.0, 30.0),
        _row("BBB", 80_000, 30_000, 50.0, 30.0),
        _row("SPY", 10_000, 30_000, 700.0, 20.0),
        _row("ILLQ", 10, 30_000, 50.0, 30.0),
    )
    sel = select_universe([payload], cfg)
    # SPY is prepended as an anchor and displaces the weakest ranked symbol.
    assert sel.symbols == ["SPY", "AAA"]
    assert "ILLQ" not in sel.symbols


def test_freshness_ttl():
    now = datetime.now(timezone.utc)
    fresh = {"symbols": ["AAA"], "generated_at": (now - timedelta(hours=1)).isoformat(), "ttl_hours": 8}
    stale = {"symbols": ["AAA"], "generated_at": (now - timedelta(hours=9)).isoformat(), "ttl_hours": 8}
    empty = {"symbols": [], "generated_at": now.isoformat()}
    assert universe_is_fresh(fresh, now=now) is True
    assert universe_is_fresh(stale, now=now) is False
    assert universe_is_fresh(empty, now=now) is False
    assert universe_is_fresh(None, now=now) is False
    assert universe_symbols(fresh) == ["AAA"]


def test_screener_symbols_use_default_cluster():
    membership = {"SPY": ("index",), "QQQ": ("index", "megacap_tech")}
    positions = [
        SimpleNamespace(underlying="AMD", quantity=1, entry_price=10.0, multiplier=100),
    ]
    current = compute_cluster_premium(positions, membership, default_cluster="single_name")
    assert current == {"single_name": 1000.0}
    # Unknown screener symbol inherits the single_name budget, not "no limit".
    assert cluster_headroom(100_000.0, 0.02, current, "MU", membership, "single_name") == 1000.0
    # With no default cluster configured, the symbol is unconstrained.
    assert cluster_headroom(100_000.0, 0.02, current, "MU", membership, "") is None
