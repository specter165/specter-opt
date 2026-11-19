"""Keep tests hermetic: never read or write the production risk state."""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_risk_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTER_RISK_STATE", str(tmp_path / "risk_state.json"))
    # Tests that build an AgentConfig must not append fake HOLD/NO_TRADE rows
    # to the real decision log, which is otherwise indistinguishable from a
    # live trading cycle.
    monkeypatch.setenv("SPECTER_DECISION_LOG", str(tmp_path / "decisions.jsonl"))
