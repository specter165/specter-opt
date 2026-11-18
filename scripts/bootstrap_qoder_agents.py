#!/usr/bin/env python3
"""Bootstrap SPECTER-OPT multi-agent roster in Qoder Cloud.

Requires QODER_PAT environment variable. Creates six child Agents and one
coordinator, all with the built-in toolset (Bash/Read/Write/Edit/Glob/Grep).
The coordinator should also be given the Moomoo MCP server in the Qoder
console after creation, because the script cannot know your MCP endpoint.

Usage:
  export QODER_PAT=pt-...
  python scripts/bootstrap_qoder_agents.py
"""

import json
import os
import sys
from typing import Any, Dict

import urllib.request

API = "https://api.qoder.com/api/v1/cloud/agents"

CHILD_TOOLS = [
    {
        "type": "agent_toolset_20260401",
        "enabled_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    }
]

COORDINATOR_TOOLS = [
    {
        "type": "agent_toolset_20260401",
        "enabled_tools": [
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            # Add MCP toolset in console after attaching the Moomoo MCP server.
        ],
    }
]

WORK_DIR = "/data/specter-opt"
CONTEXT_FILE = "data/agent_context.json"
SUMMARY_FILE = "data/agent_summary.json"

CHILD_PROMPT_TEMPLATE = """You are the SPECTER-OPT {name} Agent.

When the coordinator invokes you, your only job is to run the corresponding
local agent module and report back what happened.

1. Make sure the repo is present at {work_dir} (git clone or git pull if needed).
2. Run exactly this Bash command:
   cd {work_dir} && python scripts/run_agent.py --agent {key} --context {context_file} --out {summary_file}
3. Read {summary_file}.
4. Reply with a concise summary: success/failure, key numbers, and any errors.

Do not trade, do not modify code, and do not run any other commands unless
the agent script above fails and you need to diagnose why."""

CHILDREN = [
    {
        "key": "research",
        "name": "Research",
        "description": "Gather account state, positions, and open orders",
    },
    {
        "key": "strategy",
        "name": "Strategy",
        "description": "Price universe and emit order intents",
    },
    {
        "key": "risk",
        "name": "Risk",
        "description": "Check risk halt conditions and limits",
    },
    {
        "key": "execution",
        "name": "Execution",
        "description": "Archive pending intents for submission",
    },
    {
        "key": "reporting",
        "name": "Reporting",
        "description": "Post daily summary to Slack",
    },
]

COORDINATOR_SYSTEM = """You are the SPECTER-OPT Coordinator. You run the paper-trading options pipeline by delegating to child Agents in sequence.

Child roster:
- research: refresh account state, positions, open orders
- strategy: price the universe and emit order intents
- risk: confirm no halt / limit breach
- execution: archive pending intents so they can be submitted
- reporting: post Slack summary

Trading cycle:
1. Send research a message: "Run the research agent and report equity, positions, and open orders."
2. If no halt and the book has room, send strategy: "Run the strategy agent and report the top candidate and any pending intents."
3. Send risk: "Run the risk agent and confirm whether trading is allowed."
4. If pending intents exist and risk is green, send execution: "Run the execution agent to archive pending intents."
5. Read data/pending_paper_orders_history.jsonl. For each archived intent, submit it with the Moomoo MCP sim_trade_input_order tool (paper account 5830137, market 100, side 1 for BUY, limit order at the intent price).
6. Send reporting: "Run the reporting agent and confirm Slack post status."

Always read data/agent_summary.json after a child reports back. Never skip the risk agent before execution. If any child returns an error, stop and report it."""


def api_call(method: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    pat = os.environ.get("QODER_PAT")
    if not pat:
        print("ERROR: set QODER_PAT environment variable", file=sys.stderr)
        sys.exit(1)

    url = f"{API}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    # The API returns the object directly for agent create/get; list wraps in data.
    return payload.get("data", payload)


def create_child(agent_def: Dict[str, str]) -> str:
    body = {
        "name": f"SPECTER-OPT {agent_def['name']} Agent",
        "description": agent_def["description"],
        "model": "ultimate",
        "system": CHILD_PROMPT_TEMPLATE.format(
            name=agent_def["name"],
            key=agent_def["key"],
            work_dir=WORK_DIR,
            context_file=CONTEXT_FILE,
            summary_file=SUMMARY_FILE,
        ),
        "tools": CHILD_TOOLS,
    }
    result = api_call("POST", "", body)
    agent_id = result["id"]
    print(f"Created {agent_def['name']} Agent: {agent_id}")
    return agent_id


def create_coordinator(children: Dict[str, str]) -> str:
    roster = [
        {"type": "agent", "id": agent_id, "version": "latest"}
        for agent_id in children.values()
    ]
    body = {
        "name": "SPECTER-OPT Coordinator",
        "description": "Orchestrates the SPECTER-OPT paper-trading pipeline",
        "model": "ultimate",
        "system": COORDINATOR_SYSTEM,
        "tools": COORDINATOR_TOOLS,
        "multiagent": {
            "type": "coordinator",
            "agents": roster,
        },
    }
    result = api_call("POST", "", body)
    agent_id = result["id"]
    print(f"Created Coordinator: {agent_id}")
    return agent_id


def main():
    print("Creating SPECTER-OPT child agents...")
    children = {}
    for child_def in CHILDREN:
        children[child_def["key"]] = create_child(child_def)

    print("\nCreating coordinator...")
    coordinator_id = create_coordinator(children)

    print("\nDone.")
    print("\nNEXT STEPS:")
    print("1. Open the Qoder console and attach the Moomoo MCP server to the Coordinator.")
    print("2. Bind the same environment used by this sandbox (so /data/specter-opt is present).")
    print("3. Create a Session with the Coordinator and send: 'Run the next trading cycle.'")
    print("\nIDs:")
    print(f"  coordinator: {coordinator_id}")
    for key, agent_id in children.items():
        print(f"  {key}: {agent_id}")


if __name__ == "__main__":
    main()
