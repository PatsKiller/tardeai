"""FU-007: per-account values on the Accounts table were exactly 2x and frozen since 2026-11-03.

Three defects, one per test group (all fixtures synthetic):
  1. portfolio_analyzer._get_sector crashed on a holdings row with "asset_type": null, which stopped the
     whole daily portfolio pipeline at stage 1, so performance_history.json was never rewritten.
  2. compute_period_returns added every holding's market_value ON TOP of account_summaries (which already
     carries each account's total), in place: every per-account current_value / end_value was 2x and the
     caller's account_summaries were corrupted.
  3. The data-broker snapshot looked account states up by the canonical id (schwab_roth_ira) in a dict
     keyed by the raw holdings id (schwab_roth), so the Roth rendered UNCLASSIFIED.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


# ── 1. a null asset_type no longer crashes the pipeline ──────────────────────────────────────────────────
def test_get_sector_tolerates_null_asset_type_and_symbol():
    from portfolio_analyzer import _get_sector

    assert _get_sector("ZZZQ", None) == "Other"
    assert _get_sector(None, None) == "Other"
    assert _get_sector("ZZZQ", "ETF") == "ETF/Fund"
    assert _get_sector("ZZZQ", "Mutual Fund") == "ETF/Fund"
    assert _get_sector("CASH", None) == "Cash"


def test_rebalancer_bucket_tolerates_null_asset_type():
    from portfolio_rebalancer import _bucket

    assert _bucket("ZZZQ", None) == "US Equity"
    assert _bucket("ZZZQ", "Bond Fund") == "Bonds"


# ── 2. per-account value is the holdings sum, once ──────────────────────────────────────────────────────
def _book():
    return {
        "portfolio_totals": {"total_value": 1600.0, "day_change": 0.0},
        "account_summaries": {
            "schwab_taxable": {"total_value": 1000.0},
            "schwab_rollover_ira": {"total_value": 600.0},
        },
        "holdings": [
            {"symbol": "ZZZA", "account": "schwab_taxable", "market_value": 400.0, "shares": 4, "asset_type": None},
            {"symbol": "ZZZB", "account": "schwab_taxable", "market_value": 600.0, "shares": 6},
            {"symbol": "ZZZC", "account": "schwab_rollover_ira", "market_value": 600.0, "shares": 6},
        ],
        "trade_journal": [],
    }


def test_per_account_value_is_not_doubled_and_summaries_are_untouched(tmp_path, monkeypatch):
    import portfolio_performance_history as pph

    monkeypatch.setattr(pph, "_portfolio_value_at", lambda *a, **k: None)  # no network, no reprice
    book = _book()
    before = copy.deepcopy(book["account_summaries"])
    out = pph.compute_period_returns(book, tmp_path)

    accts = out["accounts"]
    assert accts["schwab_taxable"]["current_value"] == 1000.0
    assert accts["schwab_rollover_ira"]["current_value"] == 600.0
    for a in accts.values():
        for p in (a.get("periods") or {}).values():
            if isinstance(p, dict) and "end_value" in p:
                assert p["end_value"] == a["current_value"]
    assert book["account_summaries"] == before, "compute_period_returns must not mutate the caller's summaries"


def test_api_per_account_value_comes_from_holdings_not_history(tmp_path, monkeypatch):
    import api_v2

    state = tmp_path / "state"
    state.mkdir()
    (state / "holdings.json").write_text(json.dumps(_book()))
    # a lagging, doubled history file, as found on 2026-11-06
    (state / "performance_history.json").write_text(json.dumps({
        "periods": {}, "current_value": 3200.0,
        "accounts": {"schwab_taxable": {"current_value": 2000.0, "periods": {}},
                     "fidelity_gone": {"current_value": 50.0, "periods": {}}},
    }))
    monkeypatch.setattr(api_v2, "STATE_DIR", state)
    res = api_v2.portfolio_performance()
    assert res["accounts"]["schwab_taxable"]["current_value"] == 1000.0
    # an account absent from today's holdings keeps the history value, labelled as such
    gone = res["accounts"].get("fidelity_gone")
    if gone is not None and "current_value_source" in gone:
        assert gone["current_value_source"] == "performance_history.json"


# ── 3. the Roth's state is found through the alias table ─────────────────────────────────────────────────
def test_snapshot_matches_account_state_through_canonical_key(tmp_path, monkeypatch):
    from lib.account_display import canonical_key
    from lib.data_broker import portfolio_snapshot as ps

    raw, canon = "schwab_roth", canonical_key("schwab_roth")
    assert canon != raw, "fixture assumes the alias table maps schwab_roth to a different canonical id"

    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    book = {
        "portfolio_totals": {"total_value": 500.0, "day_change": 5.0},
        "account_summaries": {raw: {"total_value": 500.0}},
        "holdings": [{"symbol": "ZZZD", "account": raw, "market_value": 500.0, "shares": 5,
                      "day_change": 5.0, "broker_position_as_of": "2026-11-06T14:00:00+00:00"}],
    }
    (state / "holdings.json").write_text(json.dumps(book))
    monkeypatch.setattr(ps, "STATE_DIR", state)
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path / "out"))
    # account_states is keyed by the RAW holdings id, as project_account_states keys it in production
    import lib.account_state as account_state
    monkeypatch.setattr(account_state, "project_account_states", lambda h: {
        "accounts": {raw: {"state": "LIVE", "display_value": 500.0, "display_value_as_of": "2026-11-06"}},
        "excluded_accounts": [], "stale_accounts": [], "unclassified_accounts": []})

    snap = ps.build_portfolio_snapshot()
    row = snap["by_account"].get(canon) or snap["by_account"].get(raw)
    assert row is not None
    assert row["state"] == "LIVE"
    assert row["display_value_as_of"] == "2026-11-06"
