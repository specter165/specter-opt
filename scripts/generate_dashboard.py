#!/usr/bin/env python3
"""Generate HTML dashboard from decision logs and risk state."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.config import AgentConfig
from specter_opt.dashboard import render_dashboard


def main():
    cfg = AgentConfig()
    html = render_dashboard(
        decision_log_path=cfg.execution.decision_log,
        state_file=cfg.execution.state_file,
        account=None,
        output_path="data/dashboard.html",
    )
    print("Dashboard written to data/dashboard.html")


if __name__ == "__main__":
    main()
