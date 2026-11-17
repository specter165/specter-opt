"""Risk state must outlive a repo re-clone."""

import os
import sys

import pytest

from specter_opt.config import AgentConfig
from specter_opt.risk import RiskGuard


def test_state_lives_in_external_dir_when_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("SPECTER_RISK_STATE", raising=False)
    monkeypatch.setenv("SPECTER_STATE_DIR", str(tmp_path))
    guard = RiskGuard(AgentConfig())
    assert guard.state_file == os.path.join(str(tmp_path), "risk_state.json")


def test_external_state_survives_new_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("SPECTER_RISK_STATE", raising=False)
    monkeypatch.setenv("SPECTER_STATE_DIR", str(tmp_path))
    first = RiskGuard(AgentConfig())
    first.manual_halt("drawdown")
    assert first.state.halted is True

    # Simulate a re-clone: a brand-new guard must load the same file.
    second = RiskGuard(AgentConfig())
    assert second.state.halted is True
    assert second.state.halt_reason == "drawdown"


def test_credits_fall_back_to_env_when_file_absent(tmp_path, monkeypatch):
    scripts = os.path.join(os.path.dirname(__file__), "..", "scripts")
    sys.path.insert(0, os.path.abspath(scripts))
    import check_credits

    monkeypatch.setenv("CREDITS_REMAINING", "42")
    assert check_credits.load_credits(str(tmp_path / "missing.env")) == 42.0
