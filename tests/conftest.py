"""Keep tests hermetic: never read or write the production risk state."""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_risk_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTER_RISK_STATE", str(tmp_path / "risk_state.json"))
