#!/usr/bin/env python3
"""Build per-symbol quote_option_screen strategies for the Coordinator.

The Moomoo option screener can return a full quote (bid/ask/OI/volume/IV/delta
plus underlying price and IV) for every contract of one underlying when it is
filtered by underlying stock_id. That replaces quote_option_chain +
quote_market_snapshot for the whole universe.

Usage:
  python scripts/plan_screen_calls.py \
      --universe data/universe.json \
      --basicinfo data/mcp_basicinfo.json \
      --out data/screen_plan.json
"""

import argparse
import json
import sys
from typing import Dict, List

MIN_DTE = 6
MAX_DTE = 22
MIN_DELTA = 35000   # screener delta is x1e5
MAX_DELTA = 70000


def load(path: str):
    with open(path, "r") as f:
        return json.load(f)


def universe_symbols(universe: dict) -> List[str]:
    syms = universe.get("symbols")
    if isinstance(syms, list):
        return [s for s in syms if isinstance(s, str)]
    return []


def stock_ids(basicinfo: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in basicinfo.get("data", {}).get("basic_list", []):
        code = row.get("code", "")
        sid = row.get("stock_id")
        if code.startswith("US.") and sid:
            out[code.split(".", 1)[1]] = int(sid)
    return out


def strategy_for(stock_id: int) -> dict:
    return {
        "market_category_list": [0],
        "filter_group_list": [
            {
                "underlying_list": [
                    {"indicator_type": 101, "indicator_value": {"value_list": [stock_id]}}
                ]
            },
            {
                "option_list": [
                    {
                        "indicator_type": 1002,
                        "indicator_value": {
                            "value_interval": {"min_value": MIN_DTE, "max_value": MAX_DTE}
                        },
                    }
                ]
            },
            {
                "option_list": [
                    {
                        "indicator_type": 3004,
                        "indicator_value": {
                            "value_interval": {"min_value": MIN_DELTA, "max_value": MAX_DELTA}
                        },
                    }
                ]
            },
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True)
    ap.add_argument("--basicinfo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    syms = universe_symbols(load(args.universe))
    ids = stock_ids(load(args.basicinfo))

    plan = {}
    missing = []
    for sym in syms:
        sid = ids.get(sym)
        if sid is None:
            missing.append(sym)
            continue
        plan[sym] = {
            "stock_id": sid,
            "strategy": strategy_for(sid),
            "field_filter": {
                "code": "x",
                "delta": 1,
                "volume": 1,
                "ask_price": 1,
                "bid_price": 1,
                "strike_price": 1,
                "open_interest": 1,
                "implied_volatility": 1,
                "underlying_info": {"iv": 1, "price": 1},
            },
        }

    with open(args.out, "w") as f:
        json.dump(plan, f, indent=2)

    print(f"screen plan: {len(plan)} symbols -> {args.out}")
    if missing:
        print(f"WARNING: no stock_id for {','.join(missing)}", file=sys.stderr)
    return 0 if plan else 2


if __name__ == "__main__":
    sys.exit(main())
