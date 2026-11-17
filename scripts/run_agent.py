#!/usr/bin/env python3
"""Run a specific SPECTER-OPT agent or the full multi-agent pipeline.

Usage:
  python scripts/run_agent.py --agent research
  python scripts/run_agent.py --pipeline
  python scripts/run_agent.py --pipeline --agents research strategy risk
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.agents import AgentContext, Orchestrator


def main():
    parser = argparse.ArgumentParser(description="Run SPECTER-OPT agents")
    parser.add_argument("--agent", help="Run a single agent by name")
    parser.add_argument("--pipeline", action="store_true", help="Run the default pipeline")
    parser.add_argument(
        "--agents",
        nargs="+",
        help="Run a custom sequence of agents (requires --pipeline)",
    )
    parser.add_argument("--out", default="data/agent_summary.json", help="Summary output path")
    parser.add_argument("--snapshot", default="data/snapshot_fresh.json", help="Snapshot path")
    parser.add_argument("--mode", default="paper", help="Trading mode")
    args = parser.parse_args()

    context = AgentContext(
        snapshot_path=args.snapshot,
        mode=args.mode,
    )
    orchestrator = Orchestrator(context)

    if args.agent:
        results = [orchestrator.run_agent(args.agent)]
    elif args.pipeline or args.agents:
        results = orchestrator.run_pipeline(args.agents)
    else:
        parser.error("Specify --agent, --pipeline, or --agents")

    summary = orchestrator.summary(results)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
