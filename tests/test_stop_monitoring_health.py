#!/usr/bin/env python3
"""Stop monitoring health module tests."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "stop_monitoring_health",
        ROOT / "scripts" / "lib" / "stop_monitoring_health.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_active_stop_keys_working_only():
    mod = _load()
    scan = {"stops": [
        {"account": "fidelity_rollover_ira", "symbol": "ANET", "lifecycle": "working"},
        {"account": "schwab_taxable", "symbol": "GONE", "lifecycle": "cancelled"},
    ]}
    keys = mod._active_stop_keys(scan)
    assert keys == {("fidelity_rollover_ira", "ANET")}


def test_is_stop_eligible_excludes_401k_and_funds():
    mod = _load()
    assert not mod._is_stop_eligible("FCNTX", "fidelity_rollover_ira")
    assert mod._is_stop_eligible("ANET", "fidelity_rollover_ira")
    assert not mod._is_stop_eligible("V", "fidelity_401k")


def test_diagnose_returns_scan_summary():
    mod = _load()
    diag = mod.diagnose(persist_scan=False)
    assert diag.get("ok") is True
    assert "scan_summary" in diag
    assert "issues" in diag