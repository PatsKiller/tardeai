"""Hermetic: file phantoms PASS when Attribution already filters them."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "scripts" / "check_command_center_data_consistency.py"


def _load():
    spec = importlib.util.spec_from_file_location("census_consistency_20260920", MOD_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_file_phantoms_pass_when_api_filters(monkeypatch, tmp_path):
    M = _load()
    holdings = {
        "account_summaries": {
            "live": {"total_value": 1_000_000},
            "fidelity_rollover_ira": {"total_value": 0},
            "moomoo_taxable_live": {"total_value": 0},
        },
        "holdings": [],
        "portfolio_totals": {"total_value": 1_000_000},
    }
    state = tmp_path / "state"
    state.mkdir()
    (state / "holdings.json").write_text(__import__("json").dumps(holdings), encoding="utf-8")
    monkeypatch.setattr(M, "STATE_DIR", state)
    M.results.clear()

    def fake_api(path):
        assert path == "/api/v2/attribution"
        return {"data": {"accounts": {"live": {"total_value": 1_000_000}}}}

    monkeypatch.setattr(M, "api_get", fake_api)
    M.check_phantom_accounts()
    by_name = {n: (s, d) for s, n, d in M.results}
    assert by_name["Phantom accounts (file)"][0] == "PASS"
    assert "filtered by Attribution API" in by_name["Phantom accounts (file)"][1]
    assert by_name["Attribution API phantoms"][0] == "PASS"


def test_file_phantoms_warn_when_api_unreachable(monkeypatch, tmp_path):
    M = _load()
    holdings = {
        "account_summaries": {"ghost": {"total_value": 0}},
        "holdings": [],
        "portfolio_totals": {"total_value": 1},
    }
    state = tmp_path / "state"
    state.mkdir()
    (state / "holdings.json").write_text(__import__("json").dumps(holdings), encoding="utf-8")
    monkeypatch.setattr(M, "STATE_DIR", state)
    M.results.clear()
    monkeypatch.setattr(M, "api_get", lambda path: {"error": "down"})
    M.check_phantom_accounts()
    by_name = {n: (s, d) for s, n, d in M.results}
    assert by_name["Phantom accounts (file)"][0] == "WARN"
    assert "unreachable" in by_name["Phantom accounts (file)"][1]
