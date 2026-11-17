#!/usr/bin/env python3
"""Post a SPECTER-OPT daily summary to Slack via webhook.

Usage:
  SLACK_WEBHOOK_URL=... python scripts/post_to_slack.py "message text"
  python scripts/post_to_slack.py --env data/.slack_webhook.env --message "message text"
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


def load_webhook(env_path: str) -> str:
    """Load SLACK_WEBHOOK_URL from a dotenv-style file or environment."""
    if env_path and Path(env_path).exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SLACK_WEBHOOK_URL="):
                    return line.split("=", 1)[1].strip()
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        raise RuntimeError("SLACK_WEBHOOK_URL not found")
    return url


def post_message(webhook_url: str, text: str) -> dict:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return {"status": resp.status, "body": body}


def main():
    parser = argparse.ArgumentParser(description="Post message to Slack")
    parser.add_argument("--env", default="data/.slack_webhook.env", help="Path to env file with SLACK_WEBHOOK_URL")
    parser.add_argument("--message", required=True, help="Message text to post")
    args = parser.parse_args()

    try:
        url = load_webhook(args.env)
        result = post_message(url, args.message)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
