#!/usr/bin/env python3
"""Analyst-signal discovery test suite.

Pure synthetic-data tests — the DB seam (analyst_signals._execute) and the
inbox write path (inbox.upsert_candidate) are monkeypatched, so the whole
suite runs under TRADE_AI_CI with no PostgreSQL.

    .venv/bin/python -m pytest tests/test_hermes_analyst_signals.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import analyst_signals as A  # noqa: E402


# ── synthetic per-symbol latest-vs-prior snapshot rows ───────────────────────

def _row(symbol, *, cur_rec=None, prev_rec=None, cur_tgt=None, prev_tgt=None,
         cur_n=8, prev_n=8, prev_date="2026-07-01"):
    return {"symbol": symbol, "cur_date": "2026-07-29", "prev_date": prev_date,
            "cur_rec": cur_rec, "prev_rec": prev_rec,
            "cur_tgt": cur_tgt, "prev_tgt": prev_tgt,
            "cur_px": 100.0, "cur_n": cur_n, "prev_n": prev_n}


def _compute(rows, **kw):
    kw.setdefault("rating_delta_min", 0.5)
    kw.setdefault("target_move_pct_min", 10.0)
    kw.setdefault("min_opinions", 3)
    kw.setdefault("new_coverage_enabled", True)
    return A.compute_signals(rows, **kw)


# ── detection gates ──────────────────────────────────────────────────────────

def test_rating_upgrade_detected_and_directional():
    # recommendation_mean 3.0 → 2.0 is a 1.0 drop = upgrade on the 1..5 scale
    sig = _compute([_row("AAA", cur_rec=2.0, prev_rec=3.0)])
    assert len(sig) == 1
    s = sig[0]
    assert s["direction"] == "bullish"
    assert any(e["type"] == "RATING_CHANGE" for e in s["events"])


def test_rating_downgrade_direction():
    sig = _compute([_row("AAA", cur_rec=3.2, prev_rec=2.0)])
    assert sig[0]["direction"] == "bearish"


def test_target_move_detected():
    sig = _compute([_row("BBB", cur_tgt=132.0, prev_tgt=100.0)])  # +32%
    assert len(sig) == 1
    assert any(e["type"] == "TARGET_MOVE" and e["pct"] == 32.0
               for e in sig[0]["events"])


def test_below_threshold_moves_skipped():
    skipped = {}
    # 0.3 rating drop (< 0.5) and +5% target (< 10%) → nothing material
    sig = _compute([_row("CCC", cur_rec=2.7, prev_rec=3.0,
                         cur_tgt=105.0, prev_tgt=100.0)], skipped=skipped)
    assert sig == []
    assert skipped.get("no_material_move") == 1


def test_low_coverage_skipped():
    skipped = {}
    sig = _compute([_row("DDD", cur_rec=2.0, prev_rec=3.0, cur_n=1)],
                   skipped=skipped)
    assert sig == []
    assert skipped.get("low_coverage") == 1


def test_new_coverage_toggle():
    row = _row("EEE", cur_rec=1.8, prev_date=None, prev_rec=None)
    on = _compute([row], new_coverage_enabled=True)
    assert on and on[0]["events"][0]["type"] == "NEW_COVERAGE"
    assert on[0]["direction"] == "bullish"
    skipped = {}
    off = _compute([row], new_coverage_enabled=False, skipped=skipped)
    assert off == []
    assert skipped.get("new_coverage_disabled") == 1


def test_momentum_signal_clamped():
    assert A.momentum_signal(0.0) == 0.0
    assert A.momentum_signal(99.0) == 1.0
    assert 0.0 < A.momentum_signal(1.5) < 1.0


# ── payload builders ─────────────────────────────────────────────────────────

def test_ticker_payload_stable_label_and_observe_only():
    sig = _compute([_row("AAA", cur_rec=2.0, prev_rec=3.0)])
    payloads = A.build_ticker_payloads(sig, sectors={"AAA": "Technology"}, limit=25)
    assert len(payloads) == 1
    p = payloads[0]
    assert p["candidate_type"] == "TICKER_CANDIDATE"
    assert p["label"] == "AAA"      # BARE symbol so inbox validate_ticker(label) passes
    assert p["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
    assert p["meta"]["lane"] == "analyst_signal"
    assert p["meta"]["sector"] == "Technology"


def test_sector_rollup_requires_min_symbols():
    # three Tech names all bullish → one sector TREND; two would not qualify
    rows = [_row(s, cur_rec=2.0, prev_rec=3.0) for s in ("AA", "BB", "CC")]
    sig = _compute(rows)
    sectors = {"AA": "Energy", "BB": "Energy", "CC": "Energy"}
    payloads = A.build_sector_payloads(sig, sectors=sectors, min_symbols=3,
                                       covered=set())
    assert len(payloads) == 1
    p = payloads[0]
    assert p["candidate_type"] == "TREND_CANDIDATE"
    assert "Energy" in p["label"] and "tailwind" in p["label"]
    assert p["meta"]["n_symbols"] == 3


def test_sector_rollup_skips_covered():
    from lib.hermes_discovery import dedupe
    rows = [_row(s, cur_rec=2.0, prev_rec=3.0) for s in ("AA", "BB", "CC")]
    sig = _compute(rows)
    sectors = {s: "Energy" for s in ("AA", "BB", "CC")}
    covered = {dedupe.normalize_key("Energy sector analyst tailwind")}
    skipped = {}
    payloads = A.build_sector_payloads(sig, sectors=sectors, min_symbols=3,
                                       covered=covered, skipped=skipped)
    assert payloads == []
    assert skipped.get("covered_by_directive") == 1


# ── run_discovery: shadow-first (writes nothing while disabled) ──────────────

def test_run_discovery_shadow_first_writes_nothing(monkeypatch, tmp_path):
    # Pin an explicitly-disabled config so the test is isolated from whatever the
    # live schedule flag happens to be set to.
    cfg = tmp_path / "sched.json"
    cfg.write_text('{"analyst_signal_enabled": false, "analyst_min_opinions": 3}')
    monkeypatch.setattr(A, "collect_analyst_snapshots",
                        lambda *a, **k: [_row("AAA", cur_rec=2.0, prev_rec=3.0)])
    monkeypatch.setattr(A, "sector_map", lambda *a, **k: {"AAA": "Technology"})
    monkeypatch.setattr(A.entity_spikes, "covered_keys", lambda *a, **k: set())

    def _boom(*a, **k):
        raise AssertionError("inbox.upsert_candidate must not run while disabled")
    monkeypatch.setattr(A.inbox, "upsert_candidate", _boom)

    rep = A.run_discovery(dry_run=False, config_path=cfg)
    assert rep["effective_dry_run"] is True
    assert rep["upserted"] == 0
    assert rep["would_upsert"] >= 1
    assert any("analyst_signal_enabled=false" in n for n in rep["notes"])


def test_run_discovery_writes_when_enabled(monkeypatch, tmp_path):
    cfg = tmp_path / "sched.json"
    cfg.write_text('{"analyst_signal_enabled": true, "analyst_min_opinions": 3}')
    monkeypatch.setattr(A, "collect_analyst_snapshots",
                        lambda *a, **k: [_row("AAA", cur_rec=2.0, prev_rec=3.0)])
    monkeypatch.setattr(A, "sector_map", lambda *a, **k: {"AAA": "Technology"})
    monkeypatch.setattr(A.entity_spikes, "covered_keys", lambda *a, **k: set())
    calls = []
    monkeypatch.setattr(A.inbox, "upsert_candidate",
                        lambda **p: calls.append(p) or {"id": 1, "status": "READY_FOR_REVIEW",
                                                        "seen_count": 1})
    rep = A.run_discovery(dry_run=False, config_path=cfg)
    assert rep["effective_dry_run"] is False
    assert rep["upserted"] == 1
    assert calls and calls[0]["actor"] == A.ACTOR
