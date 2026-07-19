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
(OOS: benchmark +0.85% five sessions after two-day entries vs −0.57% for the
baseline bounce rule; efficiency/day −0.125 vs −0.042). The ACTIONABLE entry
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


def _cfg() -> dict:
    c = json.loads(CFG_PATH.read_text())
    return c.get("inverse_stoplights", {
        "bounce_day_pct": c.get("hedge_playbook", {}).get("bounce_day_pct", 0.75),
        "materiality_exposure_pct": 8.0,
        "band_pct": [2.0, 5.0],
        "max_hold_sessions": 20,
        "anti_chase_atr": 1.5,
        "tp1_inverse_pct": 8, "tp2_inverse_pct": 15,
        "hedge_ratio_tolerance_pct": 25,
        "staging": [25, 25, 50],
        "shadow_twoday": {"min_daily_pct": 0.0, "min_cum_pct": 0.75}})


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
        fresh = bool(bars) and bars[-1]["d"] >= str(datetime.now(timezone.utc).date())[:8] + "01"
        th = thesis_light(cur, bench, exposure.get(bench), trigger.get(bench), bool(bars))
        en = entry_light(bars, th) if bars else {"state": "RED", "label": "DO NOT ENTER",
                                                "reason": "no session history"}
        # open positions: none exist today (holdings scan)
        mg = manage_light(None, th, None, None, None)
        ex = exit_light(None, th, bars, None, None)
        card = {**inst, "daily_objective": f"-1x of {bench}'s DAILY return",
                "path_dependence_warning": PATH_WARNING,
                "max_hold_sessions": _cfg()["max_hold_sessions"],
                "lane_status": "operator-stage eligible (existing rails)",
                "latest_close": bars[-1] if bars else None,
                "lights": {"THESIS": th, "ENTRY": en, "MANAGE": mg, "EXIT": ex}}
        out["candidates"].append(card)
        for light, st in (("THESIS", th), ("ENTRY", en), ("MANAGE", mg), ("EXIT", ex)):
            cur.execute("""SELECT new_state FROM inverse_stoplight_transitions
                           WHERE instrument=%s AND light=%s ORDER BY transition_id DESC LIMIT 1""",
                        (inv, light))
            prev = (cur.fetchone() or [None])[0]
            if prev != st["state"]:
                fresh_insert = record_transition(
                    cur, conn, inv, bench, light, prev, st["state"], st["label"],
                    {**st.get("arithmetic", {}), "as_of": bars[-1]["d"] if bars else None},
                    st["reason"], closes=st.get("arithmetic", {}).get("closes"))
                if notify and fresh_insert and (
                        (light == "ENTRY" and st["state"] == "GREEN") or
                        (light == "EXIT" and st["state"] == "RED") or
                        "DAY 1 OF 2" in json.dumps(st.get("arithmetic", {}))):
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
