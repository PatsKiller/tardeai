"""Wave 2 slice 47 — the census recomputes the scoreboard rather than echoing it.

The census exists so the scoreboard can be *checked*. These tests hold it to
that: read-only, fail-soft on every source, and never inventing a number when a
source is missing.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "cio_wave2_census", ROOT / "scripts" / "cio_wave2_census.py",
)
census_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(census_mod)


@pytest.fixture()
def book(tmp_path):
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(json.dumps({
        "as_of": "2026-08-29",
        "generated_at": "2026-08-29 09:00:00",
        "portfolio_totals": {"total_cash": 500.0},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 500.0, "account": "a"},
            {"symbol": "SCHD", "market_value": 1000.0},
            {"symbol": "SCHG", "market_value": 8.09},
            {"symbol": "12507E201", "market_value": 0.0},
        ],
    }), encoding="utf-8")
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "cio_plans.jsonl").write_text("", encoding="utf-8")
    (cio / "cio_plans_projection.json").write_text("{}", encoding="utf-8")
    (tmp_path / "BUILD_SHA").write_text("deadbeef" * 5, encoding="utf-8")
    return tmp_path


def test_census_recomputes_the_holdings_numbers(book, monkeypatch):
    monkeypatch.setattr(census_mod, "_http_status", lambda *a, **k: 200)
    monkeypatch.setattr(census_mod, "_http_json", lambda *a, **k: {})
    c = census_mod.census(book)
    h = c["holdings"]
    assert h["held_equity_ticker_n"] == 2            # SCHD + SCHG
    assert h["held_equity_ticker_nondust_n"] == 1    # SCHG is dust
    assert h["dust_tickers"] == ["SCHG"]
    assert h["instrument_id_n"] == 1
    assert h["instrument_ids"] == ["12507E201"]
    assert h["dust_threshold_usd"] == 50.0


def test_census_carries_the_pin_and_endpoint_codes(book, monkeypatch):
    monkeypatch.setattr(census_mod, "_http_status", lambda url, **k: 200)
    monkeypatch.setattr(census_mod, "_http_json", lambda *a, **k: {})
    c = census_mod.census(book)
    assert c["current_pin"] == "deadbeef" * 5
    assert c["endpoints"] == {"health": 200, "v3_cio": 200, "home": 200}


def test_a_down_endpoint_is_zero_not_a_crash(book, monkeypatch):
    monkeypatch.setattr(census_mod, "_http_status", lambda *a, **k: 0)
    monkeypatch.setattr(census_mod, "_http_json", lambda *a, **k: {})
    c = census_mod.census(book)
    assert c["endpoints"]["home"] == 0
    assert c["home"]["coverage"]["held_n"] is None     # absent, not fabricated


def test_census_reports_the_rails(book, monkeypatch):
    monkeypatch.setattr(census_mod, "_http_status", lambda *a, **k: 200)
    monkeypatch.setattr(census_mod, "_http_json", lambda *a, **k: {
        "telegram_sent": False,
        "authority": "READ_ONLY_ADVISORY",
        "watch_block_summary": {"count": 26, "ready_count": 0, "fires_s7": False},
        "coverage": {"held_n": 15, "with_plan": 11},
        "graph_impact": {"attached_n": 5, "skipped": []},
        "earnings": [1] * 10,
        "new_position_if": [{"symbol": "NKE"}],
    })
    c = census_mod.census(book)
    assert c["rails"]["authority"] == "READ_ONLY_ADVISORY"
    assert c["rails"]["memory_behavior_influence"] == 0
    assert c["rails"]["telegram_sent"] is False
    assert c["rails"]["fires_s7"] is False
    assert c["home"]["coverage"]["with_plan"] == 11
    assert c["home"]["earnings_n"] == 10


def test_census_is_read_only(book, monkeypatch):
    """No file under the root may change. The census only reads."""
    monkeypatch.setattr(census_mod, "_http_status", lambda *a, **k: 200)
    monkeypatch.setattr(census_mod, "_http_json", lambda *a, **k: {})

    def snapshot_tree():
        return {p: p.stat().st_mtime_ns for p in sorted(book.rglob("*")) if p.is_file()}

    before = snapshot_tree()
    census_mod.census(book)
    assert snapshot_tree() == before


def test_render_never_raises_on_a_sparse_census(book, monkeypatch):
    monkeypatch.setattr(census_mod, "_http_status", lambda *a, **k: 0)
    monkeypatch.setattr(census_mod, "_http_json", lambda *a, **k: {})
    text = census_mod.render(census_mod.census(book))
    assert "CIO Wave 2 census" in text
    assert "held (non-dust)" in text


def test_census_declares_its_authority(book, monkeypatch):
    monkeypatch.setattr(census_mod, "_http_status", lambda *a, **k: 200)
    monkeypatch.setattr(census_mod, "_http_json", lambda *a, **k: {})
    c = census_mod.census(book)
    assert c["authority"] == "READ_ONLY_ADVISORY"
    assert c["memory_behavior_influence"] == 0
    assert c["financial_action"] is False
