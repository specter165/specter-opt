#!/usr/bin/env python3
"""Build a historical daily log-returns cache from Moomoo K-lines.

Usage:
  python scripts/build_returns_cache.py --kline SPY=spy_kline.json --kline NVDA=nvda_kline.json --out data/returns_cache.json

Legacy flags --spy-kline / --qqq-kline still work.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.calendar import ny_now


def _today_str() -> str:
    return ny_now().date().isoformat()


def _year_ago_str(today: str) -> str:
    return (datetime.strptime(today, "%Y-%m-%d").date() - timedelta(days=365)).isoformat()


def _parse_kline(path: str) -> List[dict]:
    with open(path, "r") as f:
        return json.load(f)["data"]["kline_list"]


def _closes_to_log_returns(closes: List[float]) -> List[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]


def build_cache(kline_paths: Dict[str, str]) -> Dict[str, List[float]]:
    cache: Dict[str, List[float]] = {}
    for symbol, path in kline_paths.items():
        closes = [bar["close"] for bar in _parse_kline(path)]
        cache[symbol.upper()] = _closes_to_log_returns(closes)
    return cache


def main():
    parser = argparse.ArgumentParser(description="Build returns cache for one or more underlyings")
    parser.add_argument("--kline", action="append", default=[], metavar="SYM=PATH",
                        help="K-line JSON for SYM, repeatable")
    parser.add_argument("--spy-kline", help="(legacy) Path to SPY K-line JSON")
    parser.add_argument("--qqq-kline", help="(legacy) Path to QQQ K-line JSON")
    parser.add_argument("--out", default="data/returns_cache.json", help="Output JSON path")
    args = parser.parse_args()

    paths: Dict[str, str] = {}
    for item in args.kline:
        if "=" not in item:
            parser.error(f"--kline expects SYM=PATH, got {item!r}")
        sym, path = item.split("=", 1)
        paths[sym.upper()] = path
    if args.spy_kline:
        paths.setdefault("SPY", args.spy_kline)
    if args.qqq_kline:
        paths.setdefault("QQQ", args.qqq_kline)
    if not paths:
        parser.error("provide at least one --kline SYM=PATH (or legacy --spy-kline/--qqq-kline)")

    cache = build_cache(paths)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(cache, f, indent=2)

    print(json.dumps({k: len(v) for k, v in cache.items()}, indent=2))
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
