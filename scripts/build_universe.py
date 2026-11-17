#!/usr/bin/env python3
"""Build the daily trading universe from Moomoo option-screener JSON.

Usage:
  python scripts/build_universe.py --option-screen data/mcp_option_screen.json --out data/universe.json
  python scripts/build_universe.py --option-screen a.json --option-screen b.json --max-symbols 6

Prints a one-line summary and the JSON payload. Deterministic: same input,
same symbols.
"""

import argparse
import json
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.config import UniverseConfig
from specter_opt.universe import load_universe, select_universe, universe_is_fresh, universe_symbols


def main():
    parser = argparse.ArgumentParser(description="Select trading universe from option-screener output")
    parser.add_argument("--option-screen", action="append", default=[],
                        help="quote_option_screen JSON, repeatable")
    parser.add_argument("--out", default="data/universe.json", help="Output selection path")
    parser.add_argument("--max-symbols", type=int, default=None, help="Override max_symbols")
    parser.add_argument("--ttl-hours", type=float, default=None, help="Override cache TTL")
    parser.add_argument("--reuse-if-fresh", action="store_true",
                        help="Keep the existing --out file when it is still within TTL")
    parser.add_argument("--anchor", action="append", default=[],
                        help="Symbol to keep if it passes filters, repeatable")
    parser.add_argument("--exclude", action="append", default=[], help="Symbol to exclude")
    parser.add_argument("--as-of", default=None, help="Session date label (YYYY-MM-DD)")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON payload")
    args = parser.parse_args()

    cfg = UniverseConfig()
    if args.max_symbols is not None:
        cfg = replace(cfg, max_symbols=args.max_symbols)
    if args.ttl_hours is not None:
        cfg = replace(cfg, ttl_hours=args.ttl_hours)
    if args.anchor:
        cfg = replace(cfg, always_include=list(args.anchor))
    if args.exclude:
        cfg = replace(cfg, exclude=list(args.exclude))

    if args.reuse_if_fresh:
        existing = load_universe(args.out)
        if universe_is_fresh(existing, cfg.ttl_hours):
            print(f"REUSED {args.out}: {','.join(universe_symbols(existing))}")
            if args.json_only:
                print(json.dumps(existing, indent=2))
            return

    if not args.option_screen:
        parser.error("provide at least one --option-screen JSON")

    payloads = []
    for path in args.option_screen:
        with open(path, "r") as f:
            payloads.append(json.load(f))

    selection = select_universe(payloads, cfg, as_of=args.as_of)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(selection.to_dict(), f, indent=2)

    print(f"UNIVERSE {args.as_of or selection.as_of}: {','.join(selection.symbols) or '(none)'}")
    print(f"excluded={len(selection.excluded)} metrics={len(selection.metrics)} -> {args.out}")
    if args.json_only:
        print(json.dumps(selection.to_dict(), indent=2))


if __name__ == "__main__":
    main()
