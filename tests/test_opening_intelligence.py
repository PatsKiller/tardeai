#!/usr/bin/env python3
"""Opening-intelligence tests. Deterministic fixtures — no network, no broker."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import opening_intelligence as oi  # noqa: E402

ET = ZoneInfo("America/New_York")


def q(canon, chg, *, vendor="X=F", stale=False, err="", age=60.0, delayed=True):
    return oi.Quote(canonical=canon, vendor_symbol=vendor, price=100.0,
                    previous_close=100.0 - chg, change_pct=chg,
                    quote_ts=datetime.now(timezone.utc).isoformat(),
                    age_sec=age, delayed=delayed, source="fixture",
                    stale=stale, error=err)


class FakeProvider(oi.OpeningMarketProvider):
    def __init__(self, futures=None, etfs=None, cross=None, state=oi.TRUE_FUTURES_DELAYED):
        self._f, self._e, self._c, self._s = futures or {}, etfs or {}, cross or {}, state

    def get_index_futures(self): return self._f
    def get_premarket_etfs(self): return self._e
    def get_cross_asset_context(self): return self._c
    def health(self): return {"ok": self._s != oi.SOURCE_UNAVAILABLE, "state": self._s}


@pytest.fixture(autouse=True)
def _cap(monkeypatch):
    monkeypatch.setattr(oi, "capability", lambda: oi.TRUE_FUTURES_DELAYED)


# ── session classification (§11) ──────────────────────────────────────────
@pytest.mark.parametrize("hhmm,day,want", [
    ((2, 0), 20, "overnight"), ((6, 0), 20, "premarket"), ((9, 29), 20, "premarket"),
    ((10, 0), 20, "regular"), ((15, 59), 20, "regular"), ((17, 0), 20, "afterhours"),
    ((21, 0), 20, "overnight"), ((12, 0), 18, "weekend"), ((12, 0), 19, "weekend"),
])
def test_session_classification(hhmm, day, want):
    n = datetime(2026, 7, day, hhmm[0], hhmm[1], tzinfo=ET)
    assert oi.market_session(n) == want


# ── bias buckets (§14) ────────────────────────────────────────────────────
@pytest.mark.parametrize("changes,want", [
    ([0.8, 0.9], oi.STRONG_HIGHER), ([0.3, 0.25], oi.HIGHER),
    ([0.05, -0.05], oi.MIXED), ([-0.3, -0.25], oi.LOWER),
    ([-0.9, -0.8], oi.STRONG_LOWER), ([], oi.DATA_INSUFFICIENT),
])
def test_bias_buckets(changes, want):
    assert oi._bias_from(changes) == want


# ── no source: never present prior close as an overnight move (§10) ───────
def test_no_source_is_data_insufficient():
    s = oi.build_snapshot(FakeProvider(), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert s["opening_bias"] == oi.DATA_INSUFFICIENT
    assert s["source_kind"] == "NONE"
    assert any("prior close is NOT presented" in l for l in s["limitations"])


def test_all_stale_is_data_insufficient():
    f = {"SP500_FUT": q("SP500_FUT", 0.5, stale=True)}
    s = oi.build_snapshot(FakeProvider(futures=f), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert s["opening_bias"] == oi.DATA_INSUFFICIENT
    assert s["stale_fields"]


def test_provider_error_is_recorded_not_swallowed():
    f = {"SP500_FUT": q("SP500_FUT", 0.0, err="Timeout: boom")}
    s = oi.build_snapshot(FakeProvider(futures=f), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert any("Timeout" in x for x in s["stale_fields"])


# ── true futures path ─────────────────────────────────────────────────────
def test_true_futures_drive_bias_and_are_labelled_delayed():
    f = {"SP500_FUT": q("SP500_FUT", 0.7), "NASDAQ100_FUT": q("NASDAQ100_FUT", 0.9)}
    s = oi.build_snapshot(FakeProvider(futures=f), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert s["source_kind"] == "TRUE_FUTURES"
    assert s["opening_bias"] == oi.STRONG_HIGHER
    assert any("delayed" in e for e in s["evidence"])
    assert any("DELAYED" in l for l in s["limitations"])


def test_etf_proxy_only_is_labelled_and_low_coverage():
    e = {"SP500_FUT_PROXY": q("SP500_FUT_PROXY", 0.4, vendor="SPY")}
    s = oi.build_snapshot(FakeProvider(etfs=e), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert s["source_kind"] == "ETF_PREMARKET_PROXY"
    assert any("NOT FUTURES" in l for l in s["limitations"])
    assert s["confidence_state"] == oi.LOW_COVERAGE


# ── conflict detection (§15) ──────────────────────────────────────────────
def test_futures_vs_proxy_conflict_downgrades_confidence():
    f = {"SP500_FUT": q("SP500_FUT", 0.5)}
    e = {"SP500_FUT_PROXY": q("SP500_FUT_PROXY", -0.4, vendor="SPY")}
    s = oi.build_snapshot(FakeProvider(futures=f, etfs=e),
                          now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert s["conflicts"], "opposite-sign future vs proxy must be a conflict"
    assert s["confidence_state"] == oi.CONFLICTED


def test_vix_up_with_higher_bias_is_a_conflict():
    f = {"SP500_FUT": q("SP500_FUT", 0.5), "DOW_FUT": q("DOW_FUT", 0.4)}
    c = {"VIX": q("VIX", 3.0, vendor="^VIX")}
    s = oi.build_snapshot(FakeProvider(futures=f, cross=c),
                          now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert any("VIX" in x for x in s["conflicts"])
    assert s["confidence_state"] == oi.CONFLICTED


# ── safety: advisory only ─────────────────────────────────────────────────
def test_snapshot_declares_no_execution_authority():
    f = {"SP500_FUT": q("SP500_FUT", 0.5)}
    s = oi.build_snapshot(FakeProvider(futures=f), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert s["execution_authority"] is False
    assert any("Advisory context only" in l for l in s["limitations"])


def test_render_never_predicts():
    f = {"SP500_FUT": q("SP500_FUT", 0.7)}
    s = oi.build_snapshot(FakeProvider(futures=f), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    txt = oi.render_opening_read(s)
    low = txt.lower()
    for banned in ("will open", "guaranteed", "certain to"):
        assert banned not in low, f"predictive language leaked: {banned}"
    assert "not a prediction" in low
    assert "revalidate" in low


def test_render_surfaces_data_insufficient():
    s = oi.build_snapshot(FakeProvider(), now=datetime(2026, 7, 20, 8, 0, tzinfo=ET))
    assert "DATA INSUFFICIENT" in oi.render_opening_read(s)


def test_module_has_no_execution_calls():
    """Static guard: this module must never place or approve anything."""
    src = (ROOT / "scripts" / "opening_intelligence.py").read_text()
    for banned in ("place_order", "submit_order", "options_approval_queue",
                   "resolve_approval", "execution_eligible = True"):
        assert banned not in src, f"execution surface referenced: {banned}"


# ── the snapshot lives in persistent state, never in the release tree (LQ-20261107-113) ────
# The old code bound SNAPSHOT_DIR = ROOT/"data/runtime"/... at import; every release wrote the day's
# jsonl into its own tree and the next promote orphaned it (audit 2026-11-07:
# portfolio-server/3fadf59fb-.../data/runtime/opening_intelligence/2026-11-02.jsonl).

def _snap(market_date="2026-08-03"):
    return {"market_date": market_date, "captured_at": "2026-08-03T13:15:00+00:00",
            "opening_bias": oi.MIXED, "source_kind": "TRUE_FUTURES", "evidence": []}


def test_snapshot_dir_is_resolved_not_a_release_relative_constant():
    assert not hasattr(oi, "SNAPSHOT_DIR"), (
        "a module-level SNAPSHOT_DIR is bound to Path(__file__) at import: whatever release the code "
        "runs from owns the output and the next promote orphans it")


def test_snapshot_dir_follows_tradeai_state_root(tmp_path, monkeypatch):
    state = tmp_path / "persistent-state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    assert oi.snapshot_dir() == state / "data" / "runtime" / "opening_intelligence"


def test_snapshot_dir_falls_back_to_the_durable_root(tmp_path, monkeypatch):
    state = tmp_path / "persistent-state"
    (state / "data" / "runtime" / "opening_intelligence").mkdir(parents=True)
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(state))
    assert oi.snapshot_dir() == state / "data" / "runtime" / "opening_intelligence"


def test_persist_writes_only_under_the_state_root(tmp_path, monkeypatch):
    state = tmp_path / "persistent-state"
    release = tmp_path / "release"  # a fake release checkout the code happens to run from
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(oi, "ROOT", release)

    day = oi.persist(_snap())

    assert day == state / "data" / "runtime" / "opening_intelligence" / "2026-08-03.jsonl"
    assert day.read_text().strip(), "the day's jsonl line must be written"
    latest = state / "data" / "runtime" / "opening_intelligence" / "latest.json"
    assert json.loads(latest.read_text())["market_date"] == "2026-08-03"
    assert not release.exists(), "nothing may be written into the release tree"


def test_persist_appends_to_the_same_day_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    oi.persist(_snap("2026-08-03"))
    oi.persist(_snap("2026-08-03"))
    day = tmp_path / "state" / "data" / "runtime" / "opening_intelligence" / "2026-08-03.jsonl"
    assert len(day.read_text().splitlines()) == 2
