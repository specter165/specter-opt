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
DEFAULT_ENV_ID = "env_00vril0nfsgzldpyxwfm"
DEFAULT_DEPLOYMENT_NAME = "SPECTER-OPT Trading Cycle"
DEFAULT_CRON = "*/30 10-15 * * 1-5"
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


def find_deployment() -> Optional[str]:
    page = ""
    while True:
        url = "/deployments?limit=50"
        if page:
            url += f"&page={page}"
        data = call("GET", url)
        for dep in data.get("data", []):
            if dep.get("name") == DEFAULT_DEPLOYMENT_NAME:
                return dep["id"]
        if not data.get("has_more"):
            break
        page = data.get("next_page", "")
    return None


def create() -> None:
    existing = find_deployment()
    if existing:
        print(f"Deployment already exists: {existing}")
        print("Run `python scripts/deploy_coordinator.py status` to view it.")
        return

    body = {
        "name": DEFAULT_DEPLOYMENT_NAME,
        "agent": DEFAULT_COORDINATOR_ID,
        "environment_id": DEFAULT_ENV_ID,
        "schedule": {
            "type": "cron",
            "expression": DEFAULT_CRON,
            "timezone": DEFAULT_TZ,
        },
        "initial_events": [
            {
                "type": "user.message",
                "content": [{"type": "text", "text": "Run the next trading cycle."}],
            }
        ],
    }
    dep = call("POST", "/deployments", body)
    print(f"Created deployment: {dep['id']}")
    print(f"Status: {dep['status']}")
    print(f"Next runs: {dep.get('schedule', {}).get('upcoming_runs_at', [])}")


def status(dep_id: Optional[str] = None) -> None:
    if dep_id is None:
        dep_id = find_deployment()
    if not dep_id:
        print("No deployment found. Run `create` first.")
        return
    dep = call("GET", f"/deployments/{dep_id}")
    print(json.dumps(dep, indent=2))


def run_now(dep_id: Optional[str] = None) -> None:
    if dep_id is None:
        dep_id = find_deployment()
    if not dep_id:
        print("No deployment found. Run `create` first.")
        return
    result = call("POST", f"/deployments/{dep_id}/run")
    print(f"Triggered run: {result.get('id', result)}")


def pause(dep_id: Optional[str] = None) -> None:
    if dep_id is None:
        dep_id = find_deployment()
    if not dep_id:
        print("No deployment found.")
        return
    call("POST", f"/deployments/{dep_id}/pause")
    print(f"Paused {dep_id}")


def unpause(dep_id: Optional[str] = None) -> None:
    if dep_id is None:
        dep_id = find_deployment()
    if not dep_id:
        print("No deployment found.")
        return
    call("POST", f"/deployments/{dep_id}/unpause")
    print(f"Unpaused {dep_id}")


def main():
    parser = argparse.ArgumentParser(description="Manage SPECTER-OPT Coordinator deployment")
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
