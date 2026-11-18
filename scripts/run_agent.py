#!/usr/bin/env python3
"""Run a specific SPECTER-OPT agent or the full multi-agent pipeline.

Usage:
  python scripts/run_agent.py --agent research
  python scripts/run_agent.py --pipeline
  python scripts/run_agent.py --pipeline --agents research strategy risk

Multi-agent file-based handoff:
  python scripts/run_agent.py --agent research --context data/agent_context.json --out data/agent_context.json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.agents import AgentContext, Orchestrator


def load_context(path: str) -> AgentContext:
    if not os.path.exists(path):
        return AgentContext()
    with open(path, "r") as f:
        return AgentContext.from_dict(json.load(f))


def save_context(context: AgentContext, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(context.to_dict(), f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(description="Run SPECTER-OPT agents")
    parser.add_argument("--agent", help="Run a single agent by name")
    parser.add_argument("--pipeline", action="store_true", help="Run the default pipeline")
    parser.add_argument(
        "--agents",
        nargs="+",
        help="Run a custom sequence of agents (requires --pipeline)",
    )
    parser.add_argument("--context", default="data/agent_context.json", help="Path to read/write AgentContext JSON")
    parser.add_argument("--out", default="data/agent_summary.json", help="Summary output path")
    parser.add_argument("--snapshot", default=None, help="Snapshot path (overrides context)")
    parser.add_argument("--mode", default=None, help="Trading mode (overrides context)")
    args = parser.parse_args()

    context = load_context(args.context)
    if args.snapshot:
        context.snapshot_path = args.snapshot
    if args.mode:
        context.mode = args.mode

    orchestrator = Orchestrator(context)

    if args.agent:
        results = [orchestrator.run_agent(args.agent)]
    elif args.pipeline or args.agents:
        results = orchestrator.run_pipeline(args.agents)
    else:
        parser.error("Specify --agent, --pipeline, or --agents")

    summary = orchestrator.summary(results)
    save_context(context, args.context)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
