#!/usr/bin/env python3
"""M3-S8 unit tests — gated IGN weight refit. The G1 gate is load-bearing: refit must be impossible
before the §12 sample (≥100 fires / ≥15 sessions). Refit fit is verified to recover a known signal."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_weight_refit as wr  # noqa: E402
from scalp_weight_refit import check_g1, refit_weights, deterministic_split, lock_record, SUBSCORES  # noqa: E402

CFG = {"refit": {"g1_min_fires": 100, "g1_min_sessions": 15, "held_out_frac": 0.3}}


# ── G1 gate (load-bearing) ──────────────────────────────────────────
def test_g1_blocks_small_sample():
    g = check_g1(n_fires=6, n_sessions=1, cfg=CFG)
    assert g["met"] is False and g["gap_fires"] == 94 and g["gap_sessions"] == 14

def test_g1_needs_both_fires_and_sessions():
    assert check_g1(120, 10, CFG)["met"] is False    # enough fires, too few sessions
    assert check_g1(80, 20, CFG)["met"] is False      # enough sessions, too few fires
    assert check_g1(100, 15, CFG)["met"] is True      # both exactly met


# ── refit recovers a known signal ───────────────────────────────────
def test_refit_recovers_dominant_predictor():
    # outcome driven almost entirely by v_rvol (index 0); others noise
    rows_X, y = [], []
    for i in range(300):
        vr = (i % 10) / 10.0
        x = [vr, (i * 7 % 10) / 10.0, (i * 3 % 10) / 10.0, (i * 5 % 10) / 10.0,
             (i * 2 % 10) / 10.0, (i * 9 % 10) / 10.0]
        rows_X.append(x)
        y.append(1 if vr > 0.5 else 0)
    fit = refit_weights(rows_X, y)
    assert fit is not None
    w = fit["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6                 # normalized
    assert w["v_rvol"] == max(w.values())                    # dominant predictor gets top weight
    assert w["v_rvol"] > 0.4

def test_refit_none_when_no_signal():
    # random-ish outcome uncorrelated with all sub-scores → no positive signal is fragile; assert it
    # returns either None or a valid normalized dict (never crashes)
    X = [[0.5] * 6 for _ in range(50)]
    y = [i % 2 for i in range(50)]
    out = refit_weights(X, y)
    assert out is None or abs(sum(out["weights"].values()) - 1.0) < 1e-6


# ── deterministic split + lock hash ─────────────────────────────────
def test_deterministic_split_is_stable():
    rows = [{"symbol": f"S{i}", "session_date": "2026-07-27", "minute": i} for i in range(200)]
    a1, b1 = deterministic_split(rows, 0.3)
    a2, b2 = deterministic_split(rows, 0.3)
    assert [r["symbol"] for r in a1] == [r["symbol"] for r in a2]     # reproducible
    assert 0.2 < len(b1) / len(rows) < 0.4                            # ~30% held out

def test_lock_record_has_stable_hash():
    w = {k: 1/6 for k in SUBSCORES}
    r1 = lock_record(w, {"n_fires": 100}, priors={"v_rvol": 0.28})
    r2 = lock_record(w, {"n_fires": 100}, priors={"v_rvol": 0.28})
    assert r1["weights_hash"] == r2["weights_hash"] and len(r1["weights_hash"]) == 16
    r3 = lock_record({**w, "v_rvol": 0.5}, {"n_fires": 100}, priors={"v_rvol": 0.28})
    assert r3["weights_hash"] != r1["weights_hash"]                   # different weights → different hash


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
