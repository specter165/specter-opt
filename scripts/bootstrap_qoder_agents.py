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

1. Ensure the repo at {work_dir} is current:
   - If the directory is missing, clone it:
     git clone https://github.com/specter165/specter-opt.git {work_dir}
   - Otherwise sync it:
     cd {work_dir} && bash scripts/sync_repo.sh
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
        "key": "supervision",
        "name": "Supervision",
        "description": "Monitor open positions for stop-loss and expiry exits",
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
- supervision: monitor open positions for 30% stop-loss or expiry within 1 day
- strategy: price the universe and emit order intents
- risk: confirm no halt / limit breach
- execution: archive pending intents and exit intents so they can be submitted
- reporting: post Slack summary

Trading cycle:
Paper account rules:
- Paper trading on account 5830137, market 100, is pre-authorized. This cycle
  runs unattended on a schedule: never ask for confirmation, never wait for
  user input, and never end the turn with a question. Proceed automatically.
- Only use the `sim_trade_*` MCP tools. Do NOT call `account_authorized_trd_accs`
  or any non-sim live-account tool — they return Forbidden. If such a call
  fails, ignore it and continue with the sim tools.
1. You must complete the ENTIRE market-data refresh yourself. Child agents have
   NO Moomoo MCP access, so never delegate a data-collection step to them.
   Do not stop halfway: a partial refresh means no snapshot and no trade.
   a. `cd {work_dir} && bash scripts/sync_repo.sh` (clones or hard-resets to origin/main).
      If the directory does not exist yet, clone it first:
      `git clone --depth 1 https://github.com/specter165/specter-opt.git {work_dir}`
      then run `cd {work_dir} && bash scripts/sync_repo.sh`.
   b. `mkdir -p data/chains data/quotes data/kline`
   c. Save account state with the Moomoo MCP tools (these return small JSON —
      write it directly with the Write tool):
      - sim_trade_position_list → data/mcp_positions.json
      - sim_trade_history_order_list → data/mcp_orders.json
      - sim_trade_cash_info → data/mcp_cash.json
      - sim_trade_account_list → data/mcp_accounts.json
   d. Universe: if data/universe.json is missing or older than 8 hours, call
      quote_option_screen (US stock options, DTE 7-45, delta 0.25-0.75) and
      save the raw JSON to data/mcp_option_screen.json, then run
      `python scripts/build_universe.py --input data/mcp_option_screen.json --out data/universe.json`.
   e. For every symbol in data/universe.json:
      - call quote_option_chain (7..21 DTE) → data/chains/SYM.json
      - call quote_stock_quote for US.SYM → data/quotes/SYM_underlying.json
      - call quote_cur_kline (day K, num 60) → data/kline/SYM.json
      Large MCP results are persisted to /tmp/tool-outputs/...; copy the
      referenced file to the destination path with Bash `cp` in that case.
   f. `python scripts/build_returns_cache.py --kline SYM=data/kline/SYM.json ... --out data/returns_cache.json`
      (repeat --kline for every symbol in the universe).
   g. Collect every contract code returned by the chains and call
      quote_market_snapshot in batches of at most 400 codes, saving each batch
      to data/quotes/options_batch_1.json, options_batch_2.json, ...
   h. Build the snapshot, passing one --chain, --quote and --option-snapshot
      flag per file you actually produced (paths are SYM=path, e.g.
      `--chain NVDA=data/chains/NVDA.json`):
      `python scripts/build_snapshot.py --account data/mcp_cash.json \
       --account-meta data/mcp_accounts.json --positions data/mcp_positions.json \
       --orders data/mcp_orders.json --universe data/universe.json \
       --chain SYM=data/chains/SYM.json ... --quote SYM=data/quotes/SYM_underlying.json ... \
       --option-snapshot data/quotes/options_batch_1.json ... \
       --returns-cache data/returns_cache.json --out data/snapshot_live.json`
      If this exits non-zero (e.g. DATA_STALE), STOP the cycle and report the
      error. Do not run the strategy agent on an empty or stale snapshot.
Only after data/snapshot_live.json exists may you spawn any child agent.
2. Send research: "Run the research agent and report equity, positions, and open orders."
3. Send supervision: "Run the supervision agent and report any exit intents."
4. If no halt and the book has room, send strategy: "Run the strategy agent and report the top candidate and any pending intents."
5. Send risk: "Run the risk agent and confirm whether trading is allowed."
6. If pending intents or exit intents exist and risk is green, send execution: "Run the execution agent to archive pending intents and exits."
7. Read data/pending_paper_orders_history.jsonl. For each archived intent, submit it with the Moomoo MCP sim_trade_input_order tool (paper account 5830137, market 100). Use side=1 for BUY (new positions) and side=2 for SELL (exits). Use limit order at the intent price, order_type=1.
8. Send reporting: "Run the reporting agent and confirm Slack post status."

EOD report only:
1. Fetch fresh account state as above.
2. Send research.
3. Send reporting.

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
        "system": COORDINATOR_SYSTEM.format(work_dir=WORK_DIR),
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
