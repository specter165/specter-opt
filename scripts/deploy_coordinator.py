#!/usr/bin/env python3
"""Manage the SPECTER-OPT Coordinator deployment.

A deployment runs the Coordinator on a cron schedule (or manually). Each run
creates a fresh Cloud Agent Session and sends the trigger message.

Usage:
  export QODER_PAT=pt-...
  python scripts/deploy_coordinator.py create
  python scripts/deploy_coordinator.py status
  python scripts/deploy_coordinator.py run      # trigger one manual run
  python scripts/deploy_coordinator.py pause
  python scripts/deploy_coordinator.py unpause
"""

import argparse
import json
import os
import sys
import urllib.request
from typing import Any, Dict, Optional

API = "https://api.qoder.com/api/v1/cloud"

# Hard-coded after first creation. Change these if you recreate.
DEFAULT_COORDINATOR_ID = "agent_00vtx968cg001u7ae5oi"
DEFAULT_COORDINATOR_VERSION = 7
DEFAULT_ENV_ID = "env_00vril0nfsgzldpyxwfm"

TRADING_DEPLOYMENT_NAME = "SPECTER-OPT Trading Cycle"
TRADING_CRON = "*/30 10-15 * * 1-5"
TRADING_MESSAGE = "Run the trading cycle without reporting."

EOD_DEPLOYMENT_NAME = "SPECTER-OPT EOD Report"
EOD_CRON = "15 16 * * 1-5"
EOD_MESSAGE = "Run the EOD report only."

DEFAULT_TZ = "America/New_York"


def pat() -> str:
    token = os.environ.get("QODER_PAT")
    if not token:
        print("ERROR: set QODER_PAT environment variable", file=sys.stderr)
        sys.exit(1)
    return token


def call(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{API}{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {pat()}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def find_deployment(name: str) -> Optional[str]:
    page = ""
    while True:
        url = "/deployments?limit=50"
        if page:
            url += f"&page={page}"
        data = call("GET", url)
        for dep in data.get("data", []):
            if dep.get("name") == name and dep.get("archived_at") is None:
                return dep["id"]
        if not data.get("has_more"):
            break
        page = data.get("next_page", "")
    return None


def create_one(name: str, cron: str, message: str) -> Optional[str]:
    existing = find_deployment(name)
    if existing:
        print(f"Deployment already exists: {existing} ({name})")
        return existing

    body = {
        "name": name,
        "agent": {"id": DEFAULT_COORDINATOR_ID, "type": "agent", "version": DEFAULT_COORDINATOR_VERSION},
        "environment_id": DEFAULT_ENV_ID,
        "schedule": {
            "type": "cron",
            "expression": cron,
            "timezone": DEFAULT_TZ,
        },
        "initial_events": [
            {
                "type": "user.message",
                "content": [{"type": "text", "text": message}],
            }
        ],
    }
    dep = call("POST", "/deployments", body)
    print(f"Created deployment: {dep['id']} ({name})")
    print(f"Status: {dep['status']}")
    print(f"Next runs: {dep.get('schedule', {}).get('upcoming_runs_at', [])}")
    return dep["id"]


def create() -> None:
    create_one(TRADING_DEPLOYMENT_NAME, TRADING_CRON, TRADING_MESSAGE)
    create_one(EOD_DEPLOYMENT_NAME, EOD_CRON, EOD_MESSAGE)


def status(dep_id: Optional[str] = None) -> None:
    if dep_id:
        deps = [call("GET", f"/deployments/{dep_id}")]
    else:
        deps = []
        for name in (TRADING_DEPLOYMENT_NAME, EOD_DEPLOYMENT_NAME):
            dep_id = find_deployment(name)
            if dep_id:
                deps.append(call("GET", f"/deployments/{dep_id}"))
            else:
                print(f"No deployment found for {name}")
    for dep in deps:
        print(json.dumps(dep, indent=2))


def run_now(dep_id: Optional[str] = None) -> None:
    if dep_id:
        result = call("POST", f"/deployments/{dep_id}/run")
        print(f"Triggered run: {result.get('id', result)}")
        return
    for name in (TRADING_DEPLOYMENT_NAME, EOD_DEPLOYMENT_NAME):
        dep_id = find_deployment(name)
        if dep_id:
            result = call("POST", f"/deployments/{dep_id}/run")
            print(f"Triggered run for {name}: {result.get('id', result)}")
        else:
            print(f"No deployment found for {name}")


def _apply_all(op: str) -> None:
    for name in (TRADING_DEPLOYMENT_NAME, EOD_DEPLOYMENT_NAME):
        dep_id = find_deployment(name)
        if dep_id:
            call("POST", f"/deployments/{dep_id}/{op}")
            print(f"{op.capitalize()}d {dep_id} ({name})")
        else:
            print(f"No deployment found for {name}")


def pause(dep_id: Optional[str] = None) -> None:
    if dep_id:
        call("POST", f"/deployments/{dep_id}/pause")
        print(f"Paused {dep_id}")
        return
    _apply_all("pause")


def unpause(dep_id: Optional[str] = None) -> None:
    if dep_id:
        call("POST", f"/deployments/{dep_id}/unpause")
        print(f"Unpaused {dep_id}")
        return
    _apply_all("unpause")


def main():
    parser = argparse.ArgumentParser(description="Manage SPECTER-OPT Coordinator deployments")
    parser.add_argument("command", choices=["create", "status", "run", "pause", "unpause"])
    parser.add_argument("--deployment-id", help="Override deployment ID")
    args = parser.parse_args()

    if args.command == "create":
        create()
    elif args.command == "status":
        status(args.deployment_id)
    elif args.command == "run":
        run_now(args.deployment_id)
    elif args.command == "pause":
        pause(args.deployment_id)
    elif args.command == "unpause":
        unpause(args.deployment_id)


if __name__ == "__main__":
    main()
