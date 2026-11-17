#!/usr/bin/env python3
"""Bootstrap the SPECTER-OPT repo in a schedule sandbox.

Schedules may run in fresh sandboxes where /data/specter-opt is not mounted.
This script searches common locations, pulls the latest code from GitHub if a
remote is configured, or falls back to a minimal in-memory operation mode.

Usage:
  python scripts/bootstrap_sandbox.py [--remote https://github.com/user/repo.git]

Exit codes:
  0 - repo found or cloned successfully
  1 - repo not found and no remote configured
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_NAME = "specter-opt"
DEFAULT_REMOTE = "https://github.com/specter165/specter-opt.git"
SEARCH_PATHS = [
    "/data/specter-opt",
    "/mnt/specter-opt",
    f"{os.path.expanduser('~')}/specter-opt",
    os.path.join(os.path.dirname(__file__), ".."),
    os.path.join(os.path.dirname(__file__), "..", "..", "specter-opt"),
    os.path.join(os.getcwd(), "specter-opt"),
    os.getcwd(),
]


def find_repo() -> Path | None:
    for p in SEARCH_PATHS:
        path = Path(p).resolve()
        if (path / "scripts" / "run_agent.py").exists():
            return path
    return None


def clone_repo(remote: str, target: Path) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", remote, str(target)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except Exception:
        return False


def pull_latest(repo_path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Bootstrap SPECTER-OPT repo")
    parser.add_argument(
        "--remote",
        default=os.getenv("SPECTER_GIT_REMOTE") or DEFAULT_REMOTE,
        help="GitHub remote URL",
    )
    parser.add_argument("--target", default="/data/specter-opt", help="Target clone path")
    parser.add_argument("--output", default="data/bootstrap_state.json", help="State output path")
    args = parser.parse_args()

    repo = find_repo()
    state = {
        "repo_path": str(repo) if repo else None,
        "cloned": False,
        "pulled": False,
        "fallback": False,
        "error": None,
    }

    if repo:
        state["pulled"] = pull_latest(repo)
    elif args.remote:
        target = Path(args.target)
        if clone_repo(args.remote, target):
            repo = target
            state["repo_path"] = str(repo)
            state["cloned"] = True
        else:
            state["error"] = f"Failed to clone from {args.remote}"
    else:
        state["error"] = "Repo not found and no SPECTER_GIT_REMOTE configured"
        state["fallback"] = True

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(state, f, indent=2)

    print(json.dumps(state, indent=2))

    if repo:
        print(f"\nREPO_PATH={repo}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
