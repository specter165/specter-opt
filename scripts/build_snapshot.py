#!/usr/bin/env python3
"""Build a SPECTER-OPT snapshot from pre-fetched MCP JSON files.

Inputs:
  --account        sim_trade_cash_info JSON
  --positions      sim_trade_position_list JSON
  --orders         sim_trade_history_order_list JSON (optional)
  --spy-chain      quote_option_chain JSON for US.SPY
  --qqq-chain      quote_option_chain JSON for US.QQQ
  --spy-quote      quote_stock_quote JSON for US.SPY
  --qqq-quote      quote_stock_quote JSON for US.QQQ
  --returns-cache  returns_cache JSON (optional)

Output:
  snapshot JSON suitable for scripts/run_moomoo_paper.py

Example:
  python scripts/build_snapshot.py \
    --account data/mcp_cash.json \
    --positions data/mcp_positions.json \
    --spy-chain data/mcp_spy_chain.json \
    --qqq-chain data/mcp_qqq_chain.json \
    --spy-quote data/mcp_spy_quote.json \
    --qqq-quote data/mcp_qqq_quote.json \
    --returns-cache data/returns_cache.json \
    --out data/snapshot_live.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def parse_account(cash_info: dict, account_list_entry: dict) -> dict:
    """Build account snapshot from sim_trade_cash_info + sim_trade_account_list entry."""
    data = cash_info.get("data", {})
    return {
        "account_id": str(account_list_entry.get("account_id", "")),
        "account_title": account_list_entry.get("account_title", ""),
        "market_id": int(account_list_entry.get("market_id", 0)),
        "equity": float(data.get("total_asset", 0.0)),
        "cash": float(data.get("balance", 0.0)),
        "buying_power": float(data.get("max_power_long", 0.0)),
        "is_paper": True,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def parse_positions(positions_json: dict) -> List[dict]:
    """Normalize sim_trade_position_list output.

    The paper API keeps CLOSED rows with qty "0". Those are not holdings and
    must not count toward max_concurrent_positions, so drop them here.
    """
    rows = positions_json.get("data", {}).get("positions", [])
    out = []
    for p in rows:
        # Position list schema varies by market; normalize best-effort.
        quantity = int(p.get("qty", p.get("quantity", 0)) or 0)
        if quantity <= 0:
            continue
        out.append({
            "symbol": p.get("code", p.get("symbol", "")),
            "underlying": _underlying_from_code(p.get("code", p.get("symbol", ""))),
            "right": p.get("right", ""),
            "strike": float(p.get("strike", 0.0) or 0.0),
            "expiry": p.get("expiry", ""),
            "quantity": quantity,
            "entry_price": float(p.get("cost_price", p.get("entry_price", 0.0)) or 0.0),
            "multiplier": int(p.get("multiplier", 100) or 100),
            "market_price": float(p.get("nominal_price", p.get("market_price", 0.0)) or 0.0),
            "unrealized_pnl": float(p.get("pl_ratio_val", p.get("unrealized_pnl", 0.0)) or 0.0),
            "delta": p.get("delta"),
        })
    return out


_ORDER_STATUS = {
    1: "NEW", 2: "SUBMITTED", 3: "PARTIAL_FILLED", 4: "FILLED",
    5: "CANCELLED", 6: "REJECTED", 7: "EXPIRED",
}
_LIVE_ORDER_STATUSES = ("NEW", "SUBMITTED", "PARTIAL_FILLED", "PENDING_NEW")


def parse_orders(orders_json: Optional[dict]) -> List[dict]:
    if not orders_json:
        return []
    rows = orders_json.get("data", {}).get("orders", [])
    out = []
    for o in rows:
        raw_status = o.get("order_status", o.get("status", "UNKNOWN"))
        # sim_trade_* returns numeric statuses; history/mock use strings.
        if isinstance(raw_status, int):
            status = _ORDER_STATUS.get(raw_status, str(raw_status))
        else:
            status = str(raw_status).upper()
        if status not in _LIVE_ORDER_STATUSES:
            continue
        quantity = int(o.get("qty", o.get("quantity", 0)) or 0)
        filled = int(o.get("dealt_qty", o.get("filled_qty", 0)) or 0)
        if quantity <= 0 or filled >= quantity:
            continue
        out.append({
            "order_id": o.get("order_id", o.get("id", "")),
            "intent_id": "",
            "symbol": o.get("code", o.get("symbol", "")),
            "side": str(o.get("order_side", o.get("side", ""))).upper(),
            "quantity": quantity,
            "price": _to_float_or_none(o.get("price")),
            "order_type": str(o.get("order_type", "LIMIT")).upper(),
            "status": status,
            "filled_qty": filled,
            "avg_fill_price": _to_float_or_none(o.get("dealt_avg_price", o.get("avg_fill_price"))),
        })
    return out


def _underlying_from_code(code: str) -> str:
    if not code:
        return ""
    # US.SPY260123C500000 -> SPY; US.NVDA260123C500000 -> NVDA; US.SPY -> SPY
    body = code.split(".")[-1]
    m = re.match(r"^([A-Z]+)\d{6}[CP]\d+$", body)
    if m:
        return m.group(1)
    return body


def _to_float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_iv(value: Any) -> Optional[float]:
    """Moomoo returns option IV in percent (23.65); the engine expects a decimal.

    Values above 3.0 are treated as percent. Returns None for missing/zero so
    the engine can fall back to IV inversion from the mid price.
    """
    iv = _to_float_or_none(value)
    if iv is None or iv <= 0:
        return None
    return iv / 100.0 if iv > 3.0 else iv


def parse_option_chain(chain_json: dict, underlying: str) -> List[dict]:
    rows = chain_json.get("data", {}).get("option_chain", [])
    out = []
    for c in rows:
        out.append({
            "symbol": c.get("code", ""),
            "underlying": underlying,
            "right": c.get("option_type", "CALL").upper(),
            "strike": float(c.get("strike_price", 0.0)),
            "expiry": c.get("strike_time", ""),
            "multiplier": int(c.get("lot_size", 100) or 100),
            "bid": 0.0,
            "ask": 0.0,
            "bid_size": 0,
            "ask_size": 0,
            "open_interest": 0,
            "volume": 0,
            "iv": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "quote_age_seconds": 0.0,
        })
    return out


def parse_stock_quote(quote_json: dict, code: str) -> dict:
    for q in quote_json.get("data", {}).get("quote_list", []):
        if q.get("code") == code:
            return {
                "last": float(q.get("last_price", 0.0) or q.get("price", 0.0)),
                "bid": float(q.get("bid_price", 0.0)),
                "ask": float(q.get("ask_price", 0.0)),
                "iv": normalize_iv(q.get("option_ex_data", {}).get("implied_volatility")),
            }
    return {}


def merge_quotes(chain: List[dict], quote_map: Dict[str, dict]) -> List[dict]:
    """Enrich chain entries with market-snapshot bid/ask/greeks if available."""
    for c in chain:
        q = quote_map.get(c["symbol"], {})
        if q:
            c["bid"] = float(q.get("bid", 0.0) or c["bid"])
            c["ask"] = float(q.get("ask", 0.0) or c["ask"])
            c["bid_size"] = int(q.get("bid_size", 0) or c["bid_size"])
            c["ask_size"] = int(q.get("ask_size", 0) or c["ask_size"])
            c["open_interest"] = int(q.get("open_interest", 0) or c["open_interest"])
            c["volume"] = int(q.get("volume", 0) or c["volume"])
            c["iv"] = normalize_iv(q.get("iv")) if q.get("iv") is not None else c["iv"]
            for g in ("delta", "gamma", "theta", "vega"):
                c[g] = q.get(g) if q.get(g) is not None else c[g]
            c["quote_age_seconds"] = float(q.get("quote_age_seconds", 0.0) or c["quote_age_seconds"])
    return [c for c in chain if c["ask"] > 0]


def build_quote_map(snapshot_json: Optional[dict]) -> Dict[str, dict]:
    if not snapshot_json:
        return {}
    out = {}
    for q in snapshot_json.get("data", {}).get("snapshot_list", []):
        code = q.get("code", "")
        # quote_market_snapshot for US options exposes greeks and OI as top-level fields
        out[code] = {
            "bid": float(q.get("bid_price", 0.0)),
            "ask": float(q.get("ask_price", 0.0)),
            "bid_size": int(q.get("bid_vol", 0)),
            "ask_size": int(q.get("ask_vol", 0)),
            "open_interest": int(q.get("option_open_interest", 0) or q.get("open_interest", 0)),
            "volume": int(q.get("volume", 0)),
            "iv": normalize_iv(q.get("option_implied_volatility")),
            "delta": q.get("delta"),
            "gamma": q.get("gamma"),
            "theta": q.get("theta"),
            "vega": q.get("vega"),
            "quote_age_seconds": 0.0,
        }
    return out


def main():
    parser = argparse.ArgumentParser(description="Build SPECTER-OPT snapshot from MCP JSON files")
    parser.add_argument("--account", required=True, help="sim_trade_cash_info JSON")
    parser.add_argument("--account-meta", required=True, help="sim_trade_account_list entry JSON or full list")
    parser.add_argument("--positions", required=True, help="sim_trade_position_list JSON")
    parser.add_argument("--orders", help="sim_trade_history_order_list JSON")
    parser.add_argument("--chain", action="append", default=[], metavar="SYM=PATH",
                        help="quote_option_chain JSON for SYM, repeatable (e.g. NVDA=data/nvda_chain.json)")
    parser.add_argument("--quote", action="append", default=[], metavar="SYM=PATH",
                        help="quote_stock_quote JSON for SYM, repeatable (e.g. NVDA=data/nvda_quote.json)")
    parser.add_argument("--spy-chain", help="(legacy) quote_option_chain JSON for US.SPY")
    parser.add_argument("--qqq-chain", help="(legacy) quote_option_chain JSON for US.QQQ")
    parser.add_argument("--spy-quote", help="(legacy) quote_stock_quote JSON")
    parser.add_argument("--qqq-quote", help="(legacy) quote_stock_quote JSON")
    parser.add_argument("--earnings", help="JSON map {symbol: [YYYY-MM-DD, ...]} for earnings blackout")
    parser.add_argument("--universe", help="data/universe.json from build_universe.py; restricts and orders the universe")
    parser.add_argument("--option-snapshot", help="quote_market_snapshot JSON for option contracts")
    parser.add_argument("--returns-cache", help="returns_cache JSON")
    parser.add_argument("--out", default="data/snapshot_live.json", help="Output path")
    args = parser.parse_args()

    def _kv(items, label):
        out = {}
        for item in items:
            if "=" not in item:
                parser.error(f"--{label} expects SYM=PATH, got {item!r}")
            sym, path = item.split("=", 1)
            out[sym.upper()] = path
        return out

    chain_paths = _kv(args.chain, "chain")
    quote_paths = _kv(args.quote, "quote")
    for sym, path in (("SPY", args.spy_chain), ("QQQ", args.qqq_chain)):
        if path:
            chain_paths.setdefault(sym, path)
    for sym, path in (("SPY", args.spy_quote), ("QQQ", args.qqq_quote)):
        if path:
            quote_paths.setdefault(sym, path)
    if not chain_paths or not quote_paths:
        parser.error("provide at least one --chain and one --quote (or legacy --spy-chain/--spy-quote)")
    missing_quotes = sorted(set(chain_paths) - set(quote_paths))
    if missing_quotes:
        parser.error(f"missing --quote for: {', '.join(missing_quotes)}")

    cash = load_json(args.account)
    account_meta = load_json(args.account_meta)
    # Allow full account list or single entry
    if isinstance(account_meta, dict) and "accounts" in account_meta.get("data", {}):
        entries = account_meta["data"]["accounts"]
        account_entry = next((a for a in entries if a.get("account_id") == "5830137"), entries[0])
    elif isinstance(account_meta, dict):
        account_entry = account_meta
    else:
        account_entry = {}

    account = parse_account(cash, account_entry)
    positions = parse_positions(load_json(args.positions))
    open_orders = parse_orders(load_json(args.orders) if args.orders else None)

    option_snapshot = build_quote_map(load_json(args.option_snapshot) if args.option_snapshot else None)

    chains: Dict[str, List[dict]] = {}
    quotes_by_symbol: Dict[str, dict] = {}
    for sym, path in chain_paths.items():
        chains[sym] = merge_quotes(parse_option_chain(load_json(path), sym), option_snapshot)
    for sym, path in quote_paths.items():
        quotes_by_symbol[sym] = parse_stock_quote(load_json(path), f"US.{sym}")

    snapshot = {
        "account": account,
        "positions": positions,
        "open_orders": open_orders,
        "option_chains": chains,
        "underlying_quotes": quotes_by_symbol,
    }

    if args.earnings:
        try:
            snapshot["earnings_dates"] = load_json(args.earnings)
        except Exception:
            # Fail closed downstream: single names without a calendar are skipped.
            print(f"WARNING: could not read earnings calendar {args.earnings}; single names will be skipped")

    if args.universe:
        from specter_opt.universe import universe_symbols

        requested = universe_symbols(load_json(args.universe))
        usable, dropped = [], []
        for sym in requested:
            if sym in chains and sym in quotes_by_symbol:
                usable.append(sym)
            else:
                dropped.append(sym)
        if dropped:
            print(f"WARNING: dropping universe symbols without chain/quote: {','.join(dropped)}")
        snapshot["universe"] = usable
        print(f"Universe: {','.join(usable) or '(empty)'}")

    if args.returns_cache:
        try:
            snapshot["returns_cache"] = load_json(args.returns_cache)
        except Exception:
            print(f"WARNING: could not read returns cache {args.returns_cache}; using zero-drift fallback")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"Snapshot written to {args.out}")
    print(json.dumps({k: len(v) if isinstance(v, list) else type(v).__name__ for k, v in snapshot.items()}, indent=2))


if __name__ == "__main__":
    main()
