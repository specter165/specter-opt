#!/usr/bin/env python3
"""Check remaining compute credits and alert Slack when below threshold.

Reads CREDITS_REMAINING from data/.credits.env (or the file path passed via --env).
Posts to Slack only when credits fall below the threshold.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from post_to_slack import load_webhook, post_message

DEFAULT_CREDITS_ENV = "data/.credits.env"
DEFAULT_THRESHOLD = 100


def load_credits(path: str) -> float:
    p = Path(path)
    if not p.exists():
        # Sandboxes have no persistent .credits.env; allow a supplied secret.
        env_val = os.environ.get("CREDITS_REMAINING")
        if env_val is not None and env_val.strip() != "":
            return float(env_val.strip())
        raise FileNotFoundError(f"Credits env file not found: {path}")
    with open(p, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("CREDITS_REMAINING="):
                return float(line.split("=", 1)[1].strip())
    raise ValueError(f"CREDITS_REMAINING not found in {path}")


def main():
    parser = argparse.ArgumentParser(description="Check compute credits and alert Slack")
    parser.add_argument("--credits-env", default=DEFAULT_CREDITS_ENV, help="Path to env file with CREDITS_REMAINING")
    parser.add_argument("--slack-env", default="data/.slack_webhook.env", help="Path to Slack webhook env file")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Alert threshold")
    parser.add_argument("--dry-run", action="store_true", help="Print instead of posting")
    args = parser.parse_args()

    try:
        credits = load_credits(args.credits_env)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    output = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "credits_remaining": credits,
        "threshold": args.threshold,
        "alert": credits < args.threshold,
    }
    print(json.dumps(output, indent=2))

    if not output["alert"]:
        return

    msg = (
        f"*SPECTER-OPT Credit Warning — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n"
        f"Remaining credits: `{credits}`\n"
        f"Threshold: `{args.threshold}`\n"
        f"_Please top up or pause schedules to avoid interruption._"
    )

    if args.dry_run:
        print(msg)
        return

    try:
        url = load_webhook(args.slack_env)
        result = post_message(url, msg)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Slack post failed: {e}")


if __name__ == "__main__":
    main()
