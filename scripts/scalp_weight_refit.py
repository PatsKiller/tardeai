#!/usr/bin/env python3
"""M3-S8 — one-time IGN weight refit, GATED on the §12 sample (G1).

The v1 IGN weights are PRIORS. §12: refit them ONCE, only after G1 (≥100 TRIGGER fires across ≥15
sessions), on a held-out split, then LOCK them (committed with a hash) and RESTART the sample. No
continuous tuning — that is overfitting with extra steps.

This is the load-bearing gate: `refit` REFUSES (raises WeightRefitBlocked) unless G1 is satisfied.
On the current sample (6 fires / 1 session) it refuses. Read-only over scalp_ignition_events; no
order/proposal path. `--apply` is required to write the lock; nothing mutates without it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_CONFIG = _REPO / "config" / "scalp_signal_engine.yaml"
SUBSCORES = ["v_rvol", "v_burst", "v_cat", "v_disp", "v_liq", "v_rs"]


class WeightRefitBlocked(Exception):
    """Raised when a refit is attempted before the §12 sample gate (G1) is satisfied."""


def _cfg() -> dict:
    return yaml.safe_load(_CONFIG.read_text())


def check_g1(n_fires: int, n_sessions: int, cfg: dict) -> dict:
    r = cfg.get("refit", {})
    need_f = int(r.get("g1_min_fires", 100))
    need_s = int(r.get("g1_min_sessions", 15))
    met = n_fires >= need_f and n_sessions >= need_s
    return {"met": met, "n_fires": n_fires, "n_sessions": n_sessions,
            "required_fires": need_f, "required_sessions": need_s,
            "gap_fires": max(0, need_f - n_fires), "gap_sessions": max(0, need_s - n_sessions)}


# ── pure refit (numpy logistic, positive-part normalized) ──
def refit_weights(X: list[list[float]], y: list[int], l2: float = 1.0,
                  iters: int = 800, lr: float = 0.3) -> dict | None:
    """Fit six sub-score weights that best discriminate the outcome (hit_1r_first). Logistic
    regression via gradient descent; positive coefficients normalized to sum 1 (keeps IGN∈[0,100]).
    Returns {weights, coef, n} or None if no positive signal. Pure/deterministic."""
    import numpy as np
    if not X or len(X) != len(y):
        return None
    Xa = np.asarray(X, float)
    ya = np.asarray(y, float)
    Xb = np.column_stack([np.ones(len(Xa)), Xa])
    b = np.zeros(Xb.shape[1])
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Xb @ b, -30, 30)))
        reg = np.r_[0.0, b[1:]] * (l2 / len(ya))
        b -= lr * (Xb.T @ (p - ya) / len(ya) + reg)
    coef = b[1:]
    pos = np.maximum(coef, 0.0)
    if pos.sum() <= 0:
        return None
    w = pos / pos.sum()
    return {"weights": {k: round(float(w[i]), 4) for i, k in enumerate(SUBSCORES)},
            "coef": {k: round(float(coef[i]), 4) for i, k in enumerate(SUBSCORES)}, "n": len(ya)}


def deterministic_split(rows: list[dict], held_out_frac: float) -> tuple[list, list]:
    """Deterministic train/test split by a stable hash of (symbol, session_date, minute) — no RNG,
    reproducible. `held_out_frac` of rows go to test."""
    test, train = [], []
    for r in rows:
        key = f"{r.get('symbol')}|{r.get('session_date')}|{r.get('minute')}"
        h = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 1000
        (test if h < held_out_frac * 1000 else train).append(r)
    return train, test


def p_at_1r_deciles(rows: list[dict], weights: dict, band: int = 10) -> list[dict]:
    buckets: dict = {}
    for r in rows:
        ign = 100.0 * sum(weights[k] * (r["subscores"].get(k, 0.0)) for k in weights)
        b = min(9, int(ign // band))
        buckets.setdefault(b, []).append(bool(r["hit_1r_first"]))
    return [{"band": f"{b*band}-{b*band+band}", "n": len(v), "p_at_1r": round(sum(v)/len(v), 3)}
            for b, v in sorted(buckets.items())]


def lock_record(weights: dict, sample_meta: dict, priors: dict) -> dict:
    payload = {"weights": weights, "sample": sample_meta, "priors": priors,
               "engine": "m3-s8", "policy": "refit-once-locked-v1"}
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    payload["weights_hash"] = h
    return payload


# ── I/O ──
def _conn():
    try:
        from db_adapter import get_connection
    except ModuleNotFoundError:
        from scripts.db_adapter import get_connection
    return get_connection()


def load_sample(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT symbol, session_date, minute_of_session, subscores, hit_1r_first
                       FROM scalp_ignition_events
                       WHERE lane='TRIGGER' AND hit_1r_first IS NOT NULL AND subscores IS NOT NULL""")
        rows = []
        for sym, sd, mn, ss, hit in cur.fetchall():
            ss = ss if isinstance(ss, dict) else json.loads(ss)
            rows.append({"symbol": sym, "session_date": str(sd), "minute": mn,
                         "subscores": ss, "hit_1r_first": bool(hit)})
    return rows


def run(args) -> int:
    cfg = _cfg()
    conn = _conn()
    rows = load_sample(conn)
    n_fires = len(rows)
    n_sessions = len({r["session_date"] for r in rows})
    g1 = check_g1(n_fires, n_sessions, cfg)
    print(f"G1 gate (§12): fires={g1['n_fires']}/{g1['required_fires']}  "
          f"sessions={g1['n_sessions']}/{g1['required_sessions']}  MET={g1['met']}")
    if not g1["met"]:
        print(f"  → REFIT BLOCKED: need {g1['gap_fires']} more fires, {g1['gap_sessions']} more sessions. "
              "Weights stay at v1 priors (refitting now = overfitting).")
        if args.refit:
            raise WeightRefitBlocked(json.dumps(g1))
        return 0
    if not args.refit:
        print("  G1 met — run with --refit --apply to fit + lock (ONE TIME).")
        return 0
    # G1 met + --refit
    frac = float(cfg.get("refit", {}).get("held_out_frac", 0.3))
    train, test = deterministic_split(rows, frac)
    X = [[r["subscores"].get(k, 0.0) for k in SUBSCORES] for r in train]
    y = [1 if r["hit_1r_first"] else 0 for r in train]
    fit = refit_weights(X, y)
    if not fit:
        print("  refit produced no positive signal — weights unchanged."); return 0
    deciles = p_at_1r_deciles(test, fit["weights"])
    mono = all(deciles[i]["p_at_1r"] <= deciles[i+1]["p_at_1r"] for i in range(len(deciles)-1))
    priors = cfg["ignition"]["weights"]
    meta = {"n_fires": n_fires, "n_sessions": n_sessions, "n_train": len(train), "n_test": len(test),
            "held_out_monotonic_g3": mono, "held_out_deciles": deciles,
            "refit_at": datetime.now(timezone.utc).isoformat()}
    rec = lock_record(fit["weights"], meta, priors)
    print(f"  refit weights: {fit['weights']}")
    print(f"  held-out G3 monotonic: {mono}  hash: {rec['weights_hash']}")
    if args.apply:
        lock_path = _REPO / cfg["refit"].get("lock_file", "config/scalp_ignition_weights_locked.json")
        lock_path.write_text(json.dumps(rec, indent=2))
        # The lock record preserves the v1 priors + hash + sample fingerprint. Applying to the live
        # scorer = update config ignition.weights to rec['weights'] and commit both (operator step).
        print(f"  LOCKED → {lock_path.name} (hash {rec['weights_hash']}). "
              "Update config ignition.weights to these + commit the lock record. Sample RESTARTS now.")
    else:
        print("  (dry: pass --apply to write the lock record + weights)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M3-S8 IGN weight refit (gated on §12 G1)")
    ap.add_argument("--refit", action="store_true", help="attempt the one-time refit (requires G1)")
    ap.add_argument("--apply", action="store_true", help="write the lock record (with --refit)")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
