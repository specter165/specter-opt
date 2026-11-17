#!/usr/bin/env python3
"""Build a historical daily log-returns cache for SPY/QQQ from Moomoo K-lines.

Usage:
  python scripts/build_returns_cache.py --out data/returns_cache.json
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


def build_cache(spy_kline_path: str, qqq_kline_path: str) -> Dict[str, List[float]]:
    spy_closes = [bar["close"] for bar in _parse_kline(spy_kline_path)]
    qqq_closes = [bar["close"] for bar in _parse_kline(qqq_kline_path)]
    return {
        "SPY": _closes_to_log_returns(spy_closes),
        "QQQ": _closes_to_log_returns(qqq_closes),
    }


def main():
    parser = argparse.ArgumentParser(description="Build SPY/QQQ returns cache")
    parser.add_argument("--spy-kline", help="Path to SPY K-line JSON from MCP")
    parser.add_argument("--qqq-kline", help="Path to QQQ K-line JSON from MCP")
    parser.add_argument("--out", default="data/returns_cache.json", help="Output JSON path")
    args = parser.parse_args()

    if not args.spy_kline or not args.qqq_kline:
        print("ERROR: --spy-kline and --qqq-kline are required", file=sys.stderr)
        sys.exit(1)

    cache = build_cache(args.spy_kline, args.qqq_kline)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(cache, f, indent=2)

    print(json.dumps({k: len(v) for k, v in cache.items()}, indent=2))
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
