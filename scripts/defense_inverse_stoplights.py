#!/usr/bin/env python3
"""defense_inverse_stoplights.py — inverse-ETF hedge stoplight state machine.

Four INDEPENDENT, LABELED lights per candidate (never an unlabeled dot):
  THESIS  — is a hedge justified? (desk deterioration triggers + book exposure)
  ENTRY   — is entry pricing favorable? (computed from the UNDERLYING index)
  MANAGE  — is an open hedge functioning?
  EXIT    — must the hedge be reduced/closed?

Central correction (validated 2026-07-19, pre-registration f2988645):
two positive days ARM a timing window; they never create the thesis. The
pre-registered backtest REJECTED the two-day rule as the actionable entry gate
(OOS signal-weighted: benchmark +0.73% five sessions after two-day entries vs
−0.54% baseline; efficiency/day −0.115 vs −0.041; MDD reduction −0.04pp vs
+0.26pp). The ACTIONABLE entry
gate therefore remains the baseline +0.75% bounce-day rule; the two-day
sequence is tracked and displayed as SHADOW telemetry ("day 1 of 2") so paper
evidence keeps accruing without gating anything.

Instrument lanes: SH/PSQ/DOG/RWM are the -1× actionable-research lane.
SQQQ/SARK/REW are RESEARCH-ONLY LOCKED (leveraged/thematic products never
inherit -1× approval). Every card carries the daily-reset/path-dependence
warning (FINRA 09-31; Avellaneda & Zhang 2009).

A GREEN ENTRY light authorizes ONLY the existing Stage action — orders still
travel staging → approval → 2FA → caps/whitelist/kill-file → audit.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CFG_PATH = ROOT / "config" / "defense_recommendations.json"
SNAP = ROOT / "data" / "runtime" / "inverse_stoplights_latest.json"
POLICY_VERSION = "stoplights-1.0"

LANE = [  # actionable-research lane: -1x broad index only
    {"inverse": "SH",  "bench": "SPY", "name": "ProShares Short S&P 500",
     "leverage": "-1x", "expense_pct": 0.88},
    {"inverse": "PSQ", "bench": "QQQ", "name": "ProShares Short QQQ",
     "leverage": "-1x", "expense_pct": 0.95},
    {"inverse": "DOG", "bench": "DIA", "name": "ProShares Short Dow30",
     "leverage": "-1x", "expense_pct": 0.95},
    {"inverse": "RWM", "bench": "IWM", "name": "ProShares Short Russell2000",
     "leverage": "-1x", "expense_pct": 0.95},
]
LOCKED = [  # research-only, never actionable from this desk
    {"inverse": "SQQQ", "bench": "QQQ", "leverage": "-3x",
     "lock_reason": "leveraged daily-reset — separate approval/validation lane required"},
    {"inverse": "SARK", "bench": "ARKK", "leverage": "-1x (thematic)",
     "lock_reason": "single-theme concentration — does not inherit broad-index approval"},
    {"inverse": "REW", "bench": "XLK(2x)", "leverage": "-2x",
     "lock_reason": "leveraged daily-reset — separate approval/validation lane required"},
]
PATH_WARNING = ("daily-reset product: targets -1x of ONE DAY's benchmark return; multi-day "
                "results are path-dependent (FINRA 09-31; Avellaneda-Zhang 2009) — governed "
                "max holding period applies, never passive holding")


REQUIRED_CFG_FIELDS = ("bounce_day_pct", "materiality_exposure_pct", "band_pct",
                       "max_hold_sessions", "anti_chase_atr", "tp1_inverse_pct",
                       "tp2_inverse_pct", "hedge_ratio_tolerance_pct", "staging",
                       "stale_calendar_days", "beta_book_source", "shadow_twoday")
KNOWN_CFG_KEYS = set(REQUIRED_CFG_FIELDS) | {"_comment"}


class StoplightConfigError(RuntimeError):
    pass


def validate_stoplight_config(c: dict) -> dict:
    """v3 P1-1: the committed config is AUTHORITATIVE — no hidden defaults.
    Any missing/malformed/invalid required field fails the evaluator CLOSED."""
    errs = []
    for f in REQUIRED_CFG_FIELDS:
        if f not in c:
            errs.append(f"missing required field: {f}")
    unknown = set(c) - KNOWN_CFG_KEYS
    if unknown:
        errs.append(f"unknown config keys (typo?): {sorted(unknown)}")
    def num(k, lo=None, hi=None):
        v = c.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            errs.append(f"{k} must be numeric (got {type(v).__name__})")
            return None
        if lo is not None and v < lo:
            errs.append(f"{k}={v} below sensible floor {lo}")
        if hi is not None and v > hi:
            errs.append(f"{k}={v} above sensible ceiling {hi}")
        return v
    if not errs:
        num("bounce_day_pct", 0.05, 5.0)
        num("materiality_exposure_pct", 0.5, 100.0)
        num("anti_chase_atr", 0.5, 5.0)
        mh = num("max_hold_sessions", 1, 60)
        sd = num("stale_calendar_days", 1, 14)
        t1 = num("tp1_inverse_pct", 1, 50)
        t2 = num("tp2_inverse_pct", 1, 80)
        num("hedge_ratio_tolerance_pct", 1, 100)
        if t1 is not None and t2 is not None and not (t2 > t1):
            errs.append(f"tp2_inverse_pct ({t2}) must exceed tp1_inverse_pct ({t1})")
        band = c.get("band_pct")
        if (not isinstance(band, list) or len(band) != 2
                or not all(isinstance(x, (int, float)) for x in band) or not band[0] < band[1]):
            errs.append(f"band_pct must be an ordered [lo, hi] pair (got {band})")
        st = c.get("staging")
        if not isinstance(st, list) or abs(sum(st) - 100) > 1e-9:
            errs.append(f"staging must total 100 (got {st})")
        tw = c.get("shadow_twoday")
        if not isinstance(tw, dict) or "min_daily_pct" not in tw or "min_cum_pct" not in tw:
            errs.append("shadow_twoday must contain min_daily_pct and min_cum_pct")
        if not isinstance(c.get("beta_book_source"), str):
            errs.append("beta_book_source must be a string provenance label")
    if errs:
        raise StoplightConfigError("; ".join(errs))
    return c


def _cfg() -> dict:
    c = json.loads(CFG_PATH.read_text())
    section = c.get("inverse_stoplights")
    if section is None:
        raise StoplightConfigError("inverse_stoplights section MISSING from config — fail closed")
    return validate_stoplight_config(section)


def ensure_stoplight_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS inverse_stoplight_transitions (
        transition_id serial PRIMARY KEY,
        instrument text NOT NULL,
        benchmark text NOT NULL,
        light text NOT NULL,                 -- THESIS|ENTRY|MANAGE|EXIT
        old_state text,
        new_state text NOT NULL,
        action_label text NOT NULL,
        factors jsonb NOT NULL,              -- exact values incl. the two-day close dates
        contributing_closes jsonb,
        policy_version text NOT NULL,
        code_commit text,
        data_timestamps jsonb,
        reason text NOT NULL,
        operator_action text,
        eventual_outcome text,
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_stoplight_state
        ON inverse_stoplight_transitions (instrument, light, new_state, (factors->>'as_of'))""")
    conn.commit()


_BARS_CACHE: dict[str, list] = {}


def _bars_fresh(bars: list[dict], stale_days: int | None = None) -> bool:
    """Fail-closed freshness from the VALIDATED config (v3: no second hardcoded
    threshold). Cached bars existing is NOT freshness."""
    if not bars:
        return False
    if stale_days is None:
        stale_days = _cfg()["stale_calendar_days"]
    from datetime import date, timedelta
    try:
        last = date.fromisoformat(bars[-1]["d"])
    except Exception:
        return False
    return (date.today() - last) <= timedelta(days=int(stale_days))


HOLDINGS_PATH = ROOT / "data" / "portfolios" / "state" / "holdings.json"


def ensure_cycle_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS inverse_position_cycles (
        position_cycle_id serial PRIMARY KEY,
        instrument text NOT NULL,
        benchmark text,
        accounts jsonb NOT NULL,
        account_components jsonb NOT NULL,     -- per-account qty/basis, preserved
        first_seen_at timestamptz NOT NULL DEFAULT now(),
        first_seen_session date,
        qty_at_first numeric,
        basis_at_first numeric,
        current_qty numeric,
        current_basis numeric,                 -- NULL when any component basis unknown
        last_seen_at timestamptz DEFAULT now(),
        last_seen_session date,
        status text NOT NULL DEFAULT 'OPEN',   -- OPEN|CLOSED|DATA_GAP|RECONCILED
        closed_at timestamptz,
        closed_session date,
        holdings_snapshot_hash text,
        policy_version text,
        code_commit text,
        superseded_by int,
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_one_open_cycle
        ON inverse_position_cycles (instrument) WHERE status = 'OPEN'""")
    conn.commit()


def _read_holdings() -> tuple[dict | None, str | None, bool]:
    """(snapshot, content_hash, fresh). Unreadable → (None, None, False)."""
    import hashlib as _h
    import json as _json
    try:
        raw = Path(HOLDINGS_PATH).read_bytes()
        h = _json.loads(raw)
        # freshness: any updated_at within stale window, else generated marker
        fresh = True
        ts = h.get("as_of") or h.get("generated_at")
        if ts:
            from datetime import date, timedelta
            try:
                fresh = (date.today() - date.fromisoformat(str(ts)[:10])) <=                         timedelta(days=int(_cfg()["stale_calendar_days"]))
            except Exception:
                pass
        return h, _h.sha256(raw).hexdigest()[:16], fresh
    except Exception:
        return None, None, False


def _held_sessions(bars: list[dict], first_session: str | None) -> tuple[int | None, list]:
    """v3 P0-2: held sessions = COMPLETED trading sessions from the cycle's
    first-seen session, counted from the benchmark's actual session list —
    holidays never count, weekdays are irrelevant."""
    if not first_session or not bars:
        return None, []
    dates = [b["d"] for b in bars if b["d"] >= str(first_session)]
    return len(dates), dates


def resolve_position_cycle(cur, conn, inverse: str, bench_bars: list[dict],
                           benchmark: str | None = None) -> dict | None:
    """THE cycle resolver: open/update/close/reopen with governed absence rules.
    Returns the position dict for MANAGE/EXIT, or None when flat."""
    ensure_cycle_tables(cur, conn)
    snap, snap_hash, snap_fresh = _read_holdings()
    cur.execute("""SELECT position_cycle_id, first_seen_session, current_qty
                   FROM inverse_position_cycles
                   WHERE instrument=%s AND status='OPEN' FOR UPDATE""", (inverse,))
    open_cycle = cur.fetchone()
    if snap is None:
        # holdings data unavailable — NEVER a close signal; keep cycle, flag gap
        if open_cycle:
            conn.commit()
            return {"cycle_id": open_cycle[0], "data_gap": True,
                    "qty": float(open_cycle[2] or 0), "basis": None, "price": None,
                    "inv_gain_pct": None, "held_sessions": None,
                    "accounts": [], "note": "holdings data unavailable — cycle held open (DATA_GAP)"}
        conn.commit()
        return None
    comps = {}
    for r in snap.get("holdings", []):
        if (r.get("symbol") or "").upper() == inverse and not r.get("is_cash")                 and float(r.get("shares") or 0) > 0:
            acct = r.get("account") or "unknown"
            if acct in comps:      # account duplication guard
                continue
            comps[acct] = {"qty": float(r["shares"]),
                           "basis": float(r["cost_basis"]) if r.get("cost_basis") is not None else None,
                           "price": float(r.get("price") or 0)}
    qty = sum(c["qty"] for c in comps.values())
    basis_known = comps and all(c["basis"] is not None for c in comps.values())
    basis = sum(c["basis"] for c in comps.values()) if basis_known else None
    px = next((c["price"] for c in comps.values() if c["price"]), None)
    last_session = bench_bars[-1]["d"] if bench_bars else None
    from options_lifecycle_engine import _commit_sha
    if qty > 0:
        if open_cycle:
            cur.execute("""UPDATE inverse_position_cycles SET current_qty=%s, current_basis=%s,
                           account_components=%s, accounts=%s, last_seen_at=now(),
                           last_seen_session=%s, holdings_snapshot_hash=%s
                           WHERE position_cycle_id=%s""",
                        (qty, basis, json.dumps(comps), json.dumps(sorted(comps)),
                         last_session, snap_hash, open_cycle[0]))
            cycle_id, first_session = open_cycle[0], open_cycle[1]
        else:
            cur.execute("""INSERT INTO inverse_position_cycles
                (instrument, benchmark, accounts, account_components, first_seen_session,
                 qty_at_first, basis_at_first, current_qty, current_basis,
                 last_seen_session, holdings_snapshot_hash, policy_version, code_commit)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (instrument) WHERE status='OPEN' DO NOTHING
                RETURNING position_cycle_id""",
                (inverse, benchmark, json.dumps(sorted(comps)), json.dumps(comps),
                 last_session, qty, basis, qty, basis, last_session, snap_hash,
                 POLICY_VERSION, _commit_sha()))
            row = cur.fetchone()
            if row is None:   # concurrent evaluator won the insert
                cur.execute("""SELECT position_cycle_id, first_seen_session FROM inverse_position_cycles
                               WHERE instrument=%s AND status='OPEN'""", (inverse,))
                row2 = cur.fetchone()
                cycle_id, first_session = row2[0], row2[1]
            else:
                cycle_id, first_session = row[0], last_session
        conn.commit()
        held, _sess = _held_sessions(bench_bars, first_session)
        gain = ((px * qty - basis) / basis * 100) if (basis and px) else None
        return {"cycle_id": cycle_id, "qty": qty,
                "basis": basis, "price": px,
                "inv_gain_pct": round(gain, 2) if gain is not None else None,
                "gain_note": None if gain is not None else
                "gain UNAVAILABLE — aggregate basis incomplete (never shown as zero)",
                "held_sessions": held, "first_seen_session": str(first_session) if first_session else None,
                "accounts": sorted(comps), "account_components": comps}
    # qty == 0 in THIS snapshot
    if open_cycle:
        if snap_fresh:
            cur.execute("""UPDATE inverse_position_cycles SET status='CLOSED', closed_at=now(),
                           closed_session=%s, holdings_snapshot_hash=%s, current_qty=0
                           WHERE position_cycle_id=%s""",
                        (last_session, snap_hash, open_cycle[0]))
            conn.commit()
            return None      # confirmed absent → cycle closed
        conn.commit()
        return {"cycle_id": open_cycle[0], "data_gap": True,
                "qty": float(open_cycle[2] or 0), "basis": None, "price": None,
                "inv_gain_pct": None, "held_sessions": None, "accounts": [],
                "note": "holdings snapshot STALE — absence NOT confirmed; cycle held open"}
    conn.commit()
    return None


def _open_position(cur, inverse: str, bench_bars: list[dict] | None = None,
                   benchmark: str | None = None) -> dict | None:
    """Compatibility wrapper → the cycle resolver (v3 P0-2)."""
    conn = cur.connection
    return resolve_position_cycle(cur, conn, inverse, bench_bars or [], benchmark)


def _bars(cur, sym: str, n: int = 80) -> list[dict]:
    """Completed daily sessions — Schwab history API (per-run cache) with the
    research cache as fallback. A holiday/absent close simply has no row:
    'two sessions' always means two consecutive COMPLETED trading sessions."""
    if sym in _BARS_CACHE:
        return _BARS_CACHE[sym][-n:]
    rows = []
    try:
        import schwab_transport as st
        from datetime import date, timedelta
        raw = st.get_price_history(sym, str(date.today() - timedelta(days=200)),
                                   str(date.today()))
        if isinstance(raw, list):
            rows = [{"d": b["datetime"][:10], "o": b["open"], "h": b["high"],
                     "l": b["low"], "c": b["close"]} for b in raw]
    except Exception:
        pass
    if not rows:
        try:
            cache = json.loads((ROOT / "data" / "research" / "inverse_hedge_history.json").read_text())
            rows = cache.get(sym, [])
        except Exception:
            rows = []
    _BARS_CACHE[sym] = rows
    return rows[-n:]


def _atr14(bars) -> float | None:
    if len(bars) < 15:
        return None
    trs = []
    for i in range(1, len(bars)):
        trs.append(max(bars[i]["h"] - bars[i]["l"],
                       abs(bars[i]["h"] - bars[i - 1]["c"]),
                       abs(bars[i]["l"] - bars[i - 1]["c"])))
    return sum(trs[-14:]) / 14


def _ma(bars, n):
    return (sum(b["c"] for b in bars[-n:]) / n) if len(bars) >= n else None


def thesis_light(cur, bench: str, book_exposure_pct: float | None,
                 trigger_active: bool | None, freshness_ok: bool) -> dict:
    c = _cfg()
    if trigger_active is False:
        return {"state": "RED", "label": "NO BEARISH THESIS",
                "reason": "deterioration trigger inactive/reversed — no inverse entry may be staged"}
    missing = []
    if trigger_active is None:
        missing.append("trigger state unknown")
    if book_exposure_pct is None:
        missing.append("book exposure unknown")
    if not freshness_ok:
        missing.append("data freshness failed")
    if missing:
        return {"state": "AMBER", "label": "DETERIORATING / NOT YET ELIGIBLE",
                "reason": "; ".join(missing)}
    if book_exposure_pct < c["materiality_exposure_pct"]:
        return {"state": "AMBER", "label": "DETERIORATING / NOT YET ELIGIBLE",
                "reason": f"exposure {book_exposure_pct:.1f}% below materiality "
                          f"{c['materiality_exposure_pct']}%"}
    return {"state": "GREEN", "label": "HEDGE ELIGIBLE",
            "reason": f"deterioration confirmed · mapped exposure {book_exposure_pct:.1f}% "
                      f"≥ {c['materiality_exposure_pct']}%"}


def entry_light(bars: list[dict], thesis: dict) -> dict:
    """Computed from the UNDERLYING benchmark. Actionable gate = baseline
    bounce-day (pre-registered study rejected two-day as the gate); the two-day
    sequence renders as SHADOW telemetry."""
    c = _cfg()
    if thesis["state"] != "GREEN":
        return {"state": "RED", "label": "DO NOT ENTER",
                "reason": f"THESIS is {thesis['state']} — entry evaluation requires GREEN thesis"}
    if len(bars) < 60:
        return {"state": "RED", "label": "DO NOT ENTER", "reason": "insufficient session history"}
    atr = _atr14(bars)
    c0, c1, c2 = bars[-3]["c"], bars[-2]["c"], bars[-1]["c"]
    r_prev = (c1 / c0 - 1) * 100
    r_last = (c2 / c1 - 1) * 100
    two_day = (c2 / c0 - 1) * 100
    atr_norm = ((c2 - c0) / atr) if atr else None
    ma20, ma50 = _ma(bars, 20), _ma(bars, 50)
    arithmetic = {
        "day1_ret_pct": round(r_prev, 2), "day2_ret_pct": round(r_last, 2),
        "two_day_cum_pct": round(two_day, 2),
        "atr_norm_bounce": round(atr_norm, 2) if atr_norm is not None else None,
        "dist_20dma_pct": round((c2 / ma20 - 1) * 100, 2) if ma20 else None,
        "dist_50dma_pct": round((c2 / ma50 - 1) * 100, 2) if ma50 else None,
        "closes": [bars[-3]["d"], bars[-2]["d"], bars[-1]["d"]],
        "shadow_twoday_sequence": ("DAY 2 COMPLETE" if (r_prev > 0 and r_last > 0)
                                   else ("DAY 1 OF 2 — WAIT" if r_last > 0 else "no positive day")),
    }
    if ma50 and c2 > ma50:
        return {"state": "RED", "label": "DO NOT ENTER", "arithmetic": arithmetic,
                "reason": f"benchmark above 50DMA ({arithmetic['dist_50dma_pct']:+.1f}%) — "
                          "recovery conditions veto the hedge entry"}
    if atr_norm is not None and atr_norm > c["anti_chase_atr"]:
        return {"state": "RED", "label": "DO NOT ENTER", "arithmetic": arithmetic,
                "reason": f"bounce {atr_norm:.1f} ATR exceeds anti-chase rail "
                          f"({c['anti_chase_atr']} ATR) — too extended"}
    if r_last >= c["bounce_day_pct"]:
        return {"state": "GREEN", "label": "ENTRY WINDOW OPEN", "arithmetic": arithmetic,
                "reason": f"bounce day {r_last:+.2f}% ≥ {c['bounce_day_pct']}% with THESIS GREEN — "
                          "stage T1 only (25%); window expires at next session close",
                "window_opened": bars[-1]["d"]}
    return {"state": "AMBER", "label": "ARMED, WAITING FOR BOUNCE", "arithmetic": arithmetic,
            "reason": (f"{arithmetic['shadow_twoday_sequence']} · last session {r_last:+.2f}% "
                       f"< bounce gate {c['bounce_day_pct']}% — do not chase after a down day")}


def manage_light(position: dict | None, thesis: dict, inv_gain_pct: float | None,
                 hedge_ratio_drift_pct: float | None, held_sessions: int | None) -> dict:
    c = _cfg()
    if not position:
        return {"state": "GREEN", "label": "NO POSITION", "reason": "nothing to manage"}
    if thesis["state"] == "RED":
        return {"state": "RED", "label": "RISK BREACH",
                "reason": "position open with NO thesis — EXIT engine governs"}
    ambers = []
    if inv_gain_pct is not None and inv_gain_pct >= c["tp1_inverse_pct"]:
        ambers.append(f"first objective reached ({inv_gain_pct:+.1f}% ≥ +{c['tp1_inverse_pct']}%): "
                      "reduce 50%")
    if hedge_ratio_drift_pct is not None and abs(hedge_ratio_drift_pct) > c["hedge_ratio_tolerance_pct"]:
        ambers.append(f"hedge ratio drifted {hedge_ratio_drift_pct:+.0f}% — rebalance")
    if held_sessions is not None and held_sessions >= c["max_hold_sessions"] - 3:
        ambers.append(f"held {held_sessions}/{c['max_hold_sessions']} sessions — "
                      "max holding period approaching")
    if thesis["state"] == "AMBER":
        ambers.append("thesis weakened (not reversed) — tighten the exit")
    if ambers:
        return {"state": "AMBER", "label": "REVIEW / PARTIAL ACTION", "reason": " · ".join(ambers)}
    return {"state": "GREEN", "label": "HEDGE FUNCTIONING",
            "reason": f"thesis GREEN · gain {inv_gain_pct:+.1f}% · ratio in tolerance"
                      if inv_gain_pct is not None else "thesis GREEN · position within tolerances"}


def exit_light(position: dict | None, thesis: dict, bars: list[dict],
               inv_gain_pct: float | None, held_sessions: int | None,
               exposure_reduced: bool = False) -> dict:
    c = _cfg()
    if not position:
        return {"state": "GREEN", "label": "NO EXIT CONDITION", "reason": "no position"}
    reds = []
    if thesis["state"] == "RED":
        reds.append("bearish trigger exited (2-close) — thesis exit closes the REMAINDER regardless of P&L")
    ma50 = _ma(bars, 50)
    if ma50 and len(bars) >= 2 and bars[-1]["c"] > ma50 and bars[-2]["c"] > _ma(bars[:-1], 50):
        reds.append("benchmark confirmed trend recovery (2 closes above 50DMA)")
    if held_sessions is not None and held_sessions >= c["max_hold_sessions"]:
        reds.append(f"max holding period {c['max_hold_sessions']} sessions expired (daily-reset product)")
    if exposure_reduced:
        reds.append("the exposure that required this hedge was materially reduced")
    if reds:
        return {"state": "RED", "label": "EXIT NOW / STAND DOWN", "reason": " · ".join(reds)}
    if inv_gain_pct is not None and inv_gain_pct >= c["tp2_inverse_pct"]:
        return {"state": "AMBER", "label": "TAKE PARTIAL / TIGHTEN",
                "reason": f"second objective {inv_gain_pct:+.1f}% ≥ +{c['tp2_inverse_pct']}% — "
                          "close remainder or trail on the underlying"}
    if inv_gain_pct is not None and inv_gain_pct >= c["tp1_inverse_pct"]:
        return {"state": "AMBER", "label": "TAKE PARTIAL / TIGHTEN",
                "reason": f"first objective {inv_gain_pct:+.1f}% ≥ +{c['tp1_inverse_pct']}% — sell 50%"}
    return {"state": "GREEN", "label": "NO EXIT CONDITION", "reason": "position remains justified"}


def beta_sizing(cur, bench: str, inverse: str, equity: float,
                exposure_value: float, desired_beta_reduction: float = 0.25) -> dict:
    """required_notional = desired_beta_reduction × (exposure × β_book→bench)
    ÷ |β_inverse→bench| — capped inside the 2–5% envelope (hard rail)."""
    c = _cfg()
    bb = _bars(cur, bench, 61)
    ib = _bars(cur, inverse, 61)
    if len(bb) < 40 or len(ib) < 40:
        return {"ok": False, "error": "insufficient history for rolling betas"}
    common = min(len(bb), len(ib))
    br = [(bb[i]["c"] / bb[i - 1]["c"] - 1) for i in range(len(bb) - common + 1, len(bb))]
    ir = [(ib[i]["c"] / ib[i - 1]["c"] - 1) for i in range(len(ib) - common + 1, len(ib))]
    n = min(len(br), len(ir))
    br, ir = br[-n:], ir[-n:]
    mb = sum(br) / n
    mi = sum(ir) / n
    var_b = sum((x - mb) ** 2 for x in br) / n
    cov = sum((br[i] - mb) * (ir[i] - mi) for i in range(n)) / n
    beta_inv = cov / var_b if var_b else -1.0
    beta_book = 1.0  # conservative default: exposed book ≈ benchmark beta 1 (documented)
    required = desired_beta_reduction * exposure_value * beta_book / max(0.2, abs(beta_inv))
    lo, hi = equity * c["band_pct"][0] / 100, equity * c["band_pct"][1] / 100
    capped = min(max(required, 0), hi)
    below_floor = capped < lo
    return {"ok": True, "beta_inverse_vs_bench": round(beta_inv, 3),
            "beta_book_assumed": beta_book,
            "desired_beta_reduction": desired_beta_reduction,
            "exposure_value": round(exposure_value),
            "required_notional": round(required),
            "band_floor": round(lo), "band_cap": round(hi),
            "executable_notional": 0 if below_floor else round(capped),
            "note": ("below materiality floor — DISPLAY ONLY, no ticket" if below_floor else
                     f"capped inside the {c['band_pct'][0]}–{c['band_pct'][1]}% hard envelope"),
            "formula": "reduction × exposure × β_book ÷ |β_inv|, clamped to band"}


def record_transition(cur, conn, instrument, benchmark, light, old, new, label,
                      factors: dict, reason: str, closes=None):
    from options_lifecycle_engine import _commit_sha
    factors = {**factors, "as_of": factors.get("as_of") or datetime.now(timezone.utc).date().isoformat()}
    cur.execute("""INSERT INTO inverse_stoplight_transitions
        (instrument, benchmark, light, old_state, new_state, action_label, factors,
         contributing_closes, policy_version, code_commit, data_timestamps, reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (instrument, light, new_state, (factors->>'as_of')) DO NOTHING""",
        (instrument, benchmark, light, old, new, label, json.dumps(factors, default=str),
         json.dumps(closes or []), POLICY_VERSION, _commit_sha(),
         json.dumps({"computed_at": datetime.now(timezone.utc).isoformat()}), reason))
    inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def evaluate_all(cur, conn, notify: bool = False) -> dict:
    """Nightly/refresh evaluation for the whole lane; persists transitions,
    dedupes alerts (only meaningful transitions fire)."""
    ensure_stoplight_tables(cur, conn)
    try:
        _cfg()
    except StoplightConfigError as ce:
        # v3 P1-1: invalid/missing config = visible CONFIG ERROR, everything
        # fails closed, ENTRY can never be GREEN, no hidden defaults
        err = {"state": "RED", "label": "CONFIGURATION ERROR — FAIL CLOSED", "reason": str(ce)[:300]}
        out = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "policy_version": POLICY_VERSION, "config_error": str(ce),
               "candidates": [{**inst, "lights": {"THESIS": err, "ENTRY": err,
                                                  "MANAGE": err, "EXIT": err}} for inst in LANE],
               "locked": LOCKED, "path_warning": PATH_WARNING}
        SNAP.write_text(json.dumps(out, default=str))
        return out
    # book context from the defense snapshot (labeled data with timestamps)
    # THESIS truth comes from the DESK's own hedge computation: a rendered
    # HEDGE card already encodes "deterioration trigger active + exposure over
    # materiality + benchmark mapping" through the field-guarded engine. The
    # stoplights never re-derive a competing thesis.
    exposure = {}
    trigger = {"SPY": False, "QQQ": False, "DIA": False, "IWM": False}
    try:
        snap = json.loads((ROOT / "data" / "runtime" / "defense_recommendations_latest.json").read_text())
        data = snap.get("data", snap)
        c = _cfg()
        import re as _re
        for h in (data.get("groups", {}).get("short_side") or []):
            t = h.get("title") or ""
            if not t.startswith("HEDGE"):
                continue  # short ADVISORIES are not hedge-thesis cards
            for inst in LANE:
                if _re.search(rf"\b{inst['inverse']}\b", t) or f"inverse {inst['bench']}" in t:
                    trigger[inst["bench"]] = True
                    exposure[inst["bench"]] = c["materiality_exposure_pct"]  # desk-card-derived: passes materiality by construction
    except Exception:
        trigger = {}   # snapshot unreadable → unknown, THESIS goes AMBER not RED
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "policy_version": POLICY_VERSION, "candidates": [], "locked": LOCKED,
           "path_warning": PATH_WARNING}
    from options_lifecycle_alerts import _telegram
    for inst in LANE:
        bench, inv = inst["bench"], inst["inverse"]
        bars = _bars(cur, bench, 80)
        fresh = _bars_fresh(bars)
        th = thesis_light(cur, bench, exposure.get(bench), trigger.get(bench), fresh)
        if not fresh:
            en = {"state": "RED", "label": "DO NOT ENTER",
                  "reason": f"session data STALE (latest close {bars[-1]['d'] if bars else 'none'}) "
                            "— fail closed, no entry evaluation on stale bars"}
        else:
            en = entry_light(bars, th)
        pos = _open_position(cur, inv, bench_bars=bars, benchmark=bench)
        if pos:
            record_transition(cur, conn, inv, bench, "MANAGE", None, "POSITION_SEEN",
                              "POSITION TRACKED",
                              {"qty": pos["qty"], "as_of": bars[-1]["d"] if bars else None},
                              f"live {inv} position detected ({pos['qty']:g} sh)")
        mg = manage_light(pos, th, pos.get("inv_gain_pct") if pos else None,
                          None if pos else None, pos.get("held_sessions") if pos else None)
        if pos:
            mg["note"] = "hedge-ratio drift not computable until sizing tickets persist a target (labeled, not hidden)"
        ex = exit_light(pos, th, bars, pos.get("inv_gain_pct") if pos else None,
                        pos.get("held_sessions") if pos else None)
        card = {**inst, "daily_objective": f"-1x of {bench}'s DAILY return",
                "path_dependence_warning": PATH_WARNING,
                "max_hold_sessions": _cfg()["max_hold_sessions"],
                "lane_status": "operator-stage eligible (existing rails)",
                "latest_close": bars[-1] if bars else None,
                "position": pos,
                "lights": {"THESIS": th, "ENTRY": en, "MANAGE": mg, "EXIT": ex}}
        out["candidates"].append(card)
        for light, st in (("THESIS", th), ("ENTRY", en), ("MANAGE", mg), ("EXIT", ex)):
            # P1 (validator): ENTRY transitions carry a SUBSTATE so DAY 1 OF 2
            # produces a real transition+alert even while the color stays AMBER
            sub = (st.get("arithmetic", {}) or {}).get("shadow_twoday_sequence", "")
            state_key = st["state"] + (f"|{sub}" if light == "ENTRY" and sub else "")
            cur.execute("""SELECT new_state FROM inverse_stoplight_transitions
                           WHERE instrument=%s AND light=%s AND new_state != 'POSITION_SEEN'
                           ORDER BY transition_id DESC LIMIT 1""",
                        (inv, light))
            prev = (cur.fetchone() or [None])[0]
            st = {**st, "state_key": state_key}
            if prev != state_key:
                fresh_insert = record_transition(
                    cur, conn, inv, bench, light, prev, st["state_key"], st["label"],
                    {**st.get("arithmetic", {}), "as_of": bars[-1]["d"] if bars else None},
                    st["reason"], closes=st.get("arithmetic", {}).get("closes"))
                if notify and fresh_insert and (
                        (light == "ENTRY" and st["state"] == "GREEN") or
                        (light == "EXIT" and st["state"] == "RED") or
                        (light == "ENTRY" and "DAY 1 OF 2" in state_key)):
                    _telegram(f"🚦 INVERSE HEDGE {inv}/{bench} — {light} {st['state']}: "
                              f"{st['label']}\n{st['reason'][:300]}")
    SNAP.write_text(json.dumps(out, default=str))
    return out


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    r = evaluate_all(cur, conn, notify=False)
    for c in r["candidates"]:
        L = c["lights"]
        print(f"{c['inverse']}/{c['bench']}: THESIS {L['THESIS']['state']} · ENTRY {L['ENTRY']['state']} "
              f"({L['ENTRY']['label']}) · MANAGE {L['MANAGE']['state']} · EXIT {L['EXIT']['state']}")
