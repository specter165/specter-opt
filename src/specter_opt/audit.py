"""Decision audit trail."""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import pytz


class DecisionLog:
    """Append-only JSONL decision log."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(
        self,
        decision: str,
        rationale: str,
        data: Dict[str, Any],
        model_version: str = "1.0.0",
        config_version: str = "1.0.0",
    ) -> None:
        record = {
            "timestamp_utc": datetime.now(pytz.UTC).isoformat(),
            "decision": decision,
            "rationale": rationale,
            "model_version": model_version,
            "config_version": config_version,
            "data": data,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
