"""Performance and exposure dashboard renderer."""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def render_dashboard(
    decision_log_path: str,
    state_file: str,
    account: Optional[Dict] = None,
    output_path: Optional[str] = None,
) -> str:
    decisions = load_jsonl(decision_log_path)
    state: Dict[str, Any] = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
        except Exception:
            pass

    enter_count = sum(1 for d in decisions if d.get("decision") in ("ENTER_INTENT", "ORDER_SUBMITTED"))
    hold_count = sum(1 for d in decisions if d.get("decision") in ("HOLD", "NO_TRADE", "SHADOW_HOLD"))
    halt_count = sum(1 for d in decisions if d.get("decision") == "HALT")
    last_decisions = decisions[-10:]

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>SPECTER-OPT Dashboard</title>
<style>
body {{ font-family: monospace; margin: 20px; background: #f8f9fa; color: #212529; }}
h1, h2 {{ color: #343a40; }}
table {{ border-collapse: collapse; margin: 10px 0; width: 100%; }}
th, td {{ border: 1px solid #dee2e6; padding: 6px; text-align: left; }}
th {{ background: #e9ecef; }}
.halt {{ color: #dc3545; font-weight: bold; }}
.enter {{ color: #198754; }}
.hold {{ color: #6c757d; }}
</style>
</head>
<body>
<h1>SPECTER-OPT Dashboard</h1>
<p>Generated: {datetime.now(timezone.utc).isoformat()} UTC</p>
<h2>State</h2>
<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Halted</td><td>{state.get('halted', False)} {('<span class="halt">HALTED</span>' if state.get('halted') else '')}</td></tr>
<tr><td>Halt reason</td><td>{state.get('halt_reason', '')}</td></tr>
<tr><td>Day-start equity</td><td>{state.get('day_start_equity', 0):,.2f}</td></tr>
<tr><td>Peak equity</td><td>{state.get('peak_equity', 0):,.2f}</td></tr>
<tr><td>Last equity</td><td>{state.get('last_equity', 0):,.2f}</td></tr>
<tr><td>Orders today</td><td>{state.get('orders_submitted_today', 0)}</td></tr>
<tr><td>Reserved premium</td><td>{sum(state.get('reservations', {}).values()):,.2f}</td></tr>
</table>
<h2>Account</h2>
<pre>{json.dumps(account or {}, indent=2, default=str)}</pre>
<h2>Decision Summary</h2>
<table>
<tr><th>Metric</th><th>Count</th></tr>
<tr><td>Enter / Submitted</td><td>{enter_count}</td></tr>
<tr><td>Hold / No Trade</td><td>{hold_count}</td></tr>
<tr><td>Halt</td><td>{halt_count}</td></tr>
<tr><td>Total decisions</td><td>{len(decisions)}</td></tr>
</table>
<h2>Recent Decisions</h2>
<table>
<tr><th>Time</th><th>Decision</th><th>Rationale</th></tr>
"""
    for d in last_decisions:
        cls = ""
        dec = d.get("decision", "")
        if dec in ("ENTER_INTENT", "ORDER_SUBMITTED"):
            cls = "enter"
        elif dec in ("HOLD", "NO_TRADE", "SHADOW_HOLD"):
            cls = "hold"
        elif dec == "HALT":
            cls = "halt"
        html += f"<tr><td>{d.get('timestamp_utc', '')}</td><td class='{cls}'>{dec}</td><td>{d.get('rationale', '')}</td></tr>\n"
    html += """</table>
</body>
</html>"""

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(html)
    return html
