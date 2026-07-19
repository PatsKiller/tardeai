#!/usr/bin/env python3
"""options_lifecycle_engine.py — Phases 2+3: strategy-aware policy + harvest engine.

For every open canonical strategy: fetch fresh per-leg quotes, persist an
immutable economics snapshot (marks carry source + timestamp + spread%), update
MFE/MAE/giveback from the position's own snapshot history, then run the
strategy-specific policy and record a decision with the exact rationale
sentence. Everything configurable lives in config/options_lifecycle_policy.json
(versioned); every decision row records the policy version that produced it.

Hard rules encoded here:
  - No recommendation fires solely because P&L is positive.
  - A recognized spread is decided as ONE structure; leg-out never recommended.
  - Protective puts are never harvested solely on profit — hedge need first.
  - Anything unquotable/unpriceable → DATA_BLOCKED, fail closed, reason shown.
Advisory only: this module never touches an order path.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_model import ensure_tables, open_strategies

POLICY_PATH = ROOT / "config" / "options_lifecycle_policy.json"
DECISION_ENGINE_VERSION = "1.1.0"   # bump on any semantic change to decide()/reduce_decision()
REDUCER_VERSION = "reducer-1.0"


def policy() -> dict:
    return json.loads(POLICY_PATH.read_text())


def _policy_hash() -> str:
    import hashlib
    return hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()[:16]


def _commit_sha() -> str:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "unknown"


# ── quotes ────────────────────────────────────────────────────────────────────

_CHAIN_CACHE: dict[tuple, dict] = {}   # (underlying, strike_count) → chain; per-run process cache


def _fetch_chain(und: str, count: int) -> dict:
    key = (und, count)
    if key not in _CHAIN_CACHE:
        import schwab_transport
        _CHAIN_CACHE[key] = schwab_transport.get_option_chain(und, strike_count=count) or {}
    return _CHAIN_CACHE[key]


def _find_contract(chain: dict, exp_key: str, want: float, side: str):
    saw_expiration = False
    for exp in chain.get("expirations") or []:
        if str(exp.get("exp") or "")[:10] != exp_key:
            continue
        saw_expiration = True
        for s in exp.get("strikes") or []:
            if s.get("side") == side and abs(float(s.get("strike") or 0) - want) <= 0.02:
                return s, True
    return None, saw_expiration


def quote_leg(leg: dict) -> dict:
    """v1.1 P3: CONTRACT-EXACT quote resolution. Parses exact identity, escalates
    the strike window until the exact contract is found, verifies the expiration
    exists when absent, and fails closed when exact identity cannot be proven —
    an actionable price NEVER comes from a neighboring strike. Full provenance:
    exact_match, attempts, received_at, source, spread."""
    und = leg["occ_symbol"][:6].strip()
    exp_key = str(leg["expiration"])[:10]
    want = float(leg["strike"])
    side = "put" if leg["option_type"] == "put" else "call"
    windows = policy()["quotes"].get("chain_strike_windows", [48, 120, 250])
    saw_exp_ever = False
    for count in windows:
        try:
            chain = _fetch_chain(und, count)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120], "source": "schwab_chain",
                    "exact_match": False}
        if chain.get("status") != "ok":
            return {"ok": False, "error": f"chain status {chain.get('status')}",
                    "source": "schwab_chain", "exact_match": False}
        s, saw_exp = _find_contract(chain, exp_key, want, side)
        saw_exp_ever = saw_exp_ever or saw_exp
        if s is None:
            if not saw_exp and count == windows[0]:
                # cheap pre-check: is this expiration listed at all?
                try:
                    import schwab_transport
                    exps = schwab_transport.get_option_expirations(und)
                    listed = [str(x.get("date") or "")[:10] for x in (exps.get("expirations") or [])]
                    if listed and exp_key not in listed:
                        return {"ok": False, "exact_match": False, "source": "schwab_chain",
                                "error": f"expiration {exp_key} not listed by broker — identity unverifiable"}
                except Exception:
                    pass
            continue
        bid, ask = s.get("bid"), s.get("ask")
        mid = ((bid + ask) / 2 if bid is not None and ask is not None else s.get("last"))
        if mid is None:
            return {"ok": False, "error": "exact contract found but no two-sided quote or last",
                    "source": "schwab_chain", "exact_match": True}
        spread_pct = (round((ask - bid) / mid * 100, 1) if bid and ask and mid else None)
        return {"ok": True, "bid": bid, "ask": ask, "mid": round(float(mid), 2),
                "spread_pct": spread_pct, "delta": s.get("delta"), "gamma": s.get("gamma"),
                "theta": s.get("theta"), "vega": s.get("vega"), "iv": s.get("iv"),
                "underlying_price": chain.get("underlying_price"), "source": "schwab_chain",
                "exact_match": True, "attempts_strike_window": count,
                "ts": datetime.now(timezone.utc).isoformat()}
    return {"ok": False, "exact_match": False, "source": "schwab_chain",
            "error": f"exact contract not found after {windows[-1]}-strike scan"
                     + ("" if saw_exp_ever else f" (expiration {exp_key} never appeared)")}


# ── economics ─────────────────────────────────────────────────────────────────

def _sgn(leg: dict) -> int:
    return 1 if leg["side"] == "long" else -1


def strategy_economics(s: dict, quotes: dict[int, dict]) -> dict:
    """All Phase 3 metrics for one strategy given per-leg quotes keyed by leg_id.
    None = UNKNOWN throughout; data_quality_flags lists every reason."""
    flags = []
    legs = [l for l in s["legs"] if l["status"] == "open"]
    if not legs:
        return {"flags": ["no_open_legs"]}
    today = date.today()
    dte_nearest = min((l["expiration"] - today).days for l in legs)
    und_px = None
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    net_ok = True
    mark_total = 0.0          # signed liquidation value of the structure ($)
    mark_ok = True
    entry_total = 0.0         # signed entry value ($); None-able
    entry_ok = True
    unrealized = 0.0
    max_spread = None
    extrinsic_total = 0.0
    legs_snapshot = []
    for l in legs:
        q = quotes.get(l["leg_id"]) or {}
        mult, n = int(l["multiplier"]), float(l["contracts"])
        if q.get("ok") and q.get("mid") is not None:
            mark = float(q["mid"])
            und_px = q.get("underlying_price") or und_px
            mark_total += _sgn(l) * mark * n * mult
            if q.get("spread_pct") is not None:
                max_spread = max(max_spread or 0, q["spread_pct"])
            for g in net:
                if q.get(g) is not None:
                    net[g] += _sgn(l) * float(q[g]) * n * mult
                else:
                    net_ok = False
            if und_px:
                intrinsic = max(0.0, (und_px - float(l["strike"])) if l["option_type"] == "call"
                                else (float(l["strike"]) - und_px))
                extrinsic_total += _sgn(l) * max(0.0, mark - intrinsic) * n * mult
        else:
            mark_ok = False
            flags.append(f"no_quote:{l['occ_symbol']}:{q.get('error', 'missing')}")
        if l["opening_price"] is not None:
            entry_total += _sgn(l) * float(l["opening_price"]) * n * mult
            if q.get("ok") and q.get("mid") is not None:
                unrealized += (float(q["mid"]) - float(l["opening_price"])) * _sgn(l) * n * mult
        else:
            entry_ok = False
            flags.append(f"unknown_basis:{l['occ_symbol']}")
        legs_snapshot.append({"leg_id": l["leg_id"], "occ": l["occ_symbol"], "side": l["side"],
                              "contracts": n, **{k: q.get(k) for k in
                              ("bid", "ask", "mid", "spread_pct", "delta", "theta", "iv", "ts", "source")}})
    if not mark_ok:
        flags.append("mark_incomplete")
    if not entry_ok:
        flags.append("basis_incomplete")

    # max-profit frame per structure (None = unbounded/undefined)
    stype = s["strategy_type"]
    max_profit = pct_captured = None
    if entry_ok:
        credit = -entry_total   # positive when the structure was opened for a credit
        if stype in ("covered_call", "cash_secured_put", "credit_spread") and credit > 0:
            max_profit = credit
            if mark_ok:
                pct_captured = round((credit - max(0.0, -mark_total) if mark_total <= 0
                                      else credit - (-mark_total)) / credit * 100, 1)
                # equivalent: captured = (credit + mark_total)/credit — mark_total is negative liability
                pct_captured = round((credit + mark_total) / credit * 100, 1)
        elif stype == "debit_spread" and credit < 0:
            strikes = sorted(float(l["strike"]) for l in legs)
            width = (strikes[-1] - strikes[0]) * float(legs[0]["contracts"]) * int(legs[0]["multiplier"])
            max_profit = width + credit  # width − debit
            if mark_ok and max_profit > 0:
                pct_captured = round((mark_total - (-credit)) / max_profit * 100, 1)

    # nearest short strike distance (assignment lens)
    short_legs = [l for l in legs if l["side"] == "short"]
    short_distance_pct = short_delta = None
    if short_legs and und_px:
        ns = min(short_legs, key=lambda l: abs(float(l["strike"]) - und_px))
        short_distance_pct = round((float(ns["strike"]) - und_px) / und_px * 100
                                   * (1 if ns["option_type"] == "call" else -1), 2)
        qd = (quotes.get(ns["leg_id"]) or {}).get("delta")
        short_delta = abs(float(qd)) if qd is not None else None

    return {"flags": flags, "dte_nearest": dte_nearest, "underlying_price": und_px,
            "legs_json": legs_snapshot, "strategy_mark": round(mark_total, 2) if mark_ok else None,
            "max_spread_pct": max_spread, "net": {k: round(v, 2) for k, v in net.items()} if net_ok else None,
            "unrealized_pnl": round(unrealized, 2) if (mark_ok and entry_ok) else None,
            "entry_value": round(entry_total, 2) if entry_ok else None,
            "max_profit_possible": round(max_profit, 2) if max_profit is not None else None,
            "pct_max_profit_captured": pct_captured,
            "extrinsic_value": round(extrinsic_total, 2) if mark_ok and und_px else None,
            "short_distance_pct": short_distance_pct, "short_delta": short_delta,
            "itm_short": (short_distance_pct is not None and short_distance_pct < 0)}


def persist_snapshot(cur, conn, s: dict, eco: dict) -> tuple[int, dict]:
    """Insert immutable snapshot; MFE/MAE/giveback derive from this position's
    own history (peak of unrealized), returned enriched."""
    spid = s["strategy_position_id"]
    cur.execute("""SELECT max(max_favorable_excursion), min(max_adverse_excursion)
                   FROM options_position_snapshots WHERE strategy_position_id=%s""", (spid,))
    prior = cur.fetchone() or (None, None)
    upl = eco.get("unrealized_pnl")
    # DB numerics arrive as Decimal — coerce before any float arithmetic downstream
    p0 = float(prior[0]) if prior[0] is not None else None
    p1 = float(prior[1]) if prior[1] is not None else None
    mfe = max([x for x in (p0, upl) if x is not None], default=None)
    mae = min([x for x in (p1, upl) if x is not None], default=None)
    giveback = (round(float(mfe) - upl, 2) if (mfe is not None and upl is not None and float(mfe) > 0)
                else None)
    assignment_flags = {"itm_short": eco.get("itm_short"),
                        "short_distance_pct": eco.get("short_distance_pct"),
                        "extrinsic_value": eco.get("extrinsic_value")}
    cur.execute("""INSERT INTO options_position_snapshots
        (strategy_position_id, underlying_price, legs_json, strategy_mark, mark_source,
         quote_timestamp, max_spread_pct, net_delta, net_gamma, net_theta, net_vega,
         dte_nearest, moneyness_pct, unrealized_pnl, realized_pnl, total_strategy_pnl,
         pct_max_profit_captured, max_profit_possible, max_favorable_excursion,
         max_adverse_excursion, giveback_from_peak, extrinsic_value, assignment_flags,
         data_quality_flags)
        VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING snapshot_id""",
        (spid, eco.get("underlying_price"), json.dumps(eco.get("legs_json") or []),
         eco.get("strategy_mark"), "schwab_chain", eco.get("max_spread_pct"),
         (eco.get("net") or {}).get("delta"), (eco.get("net") or {}).get("gamma"),
         (eco.get("net") or {}).get("theta"), (eco.get("net") or {}).get("vega"),
         eco.get("dte_nearest"), eco.get("short_distance_pct"), upl, None, upl,
         eco.get("pct_max_profit_captured"), eco.get("max_profit_possible"),
         mfe, mae, giveback, eco.get("extrinsic_value"),
         json.dumps(assignment_flags), json.dumps(eco.get("flags") or [])))
    snap_id = cur.fetchone()[0]
    # v1.2.1 P0-2: two-axis rule — PRICING quality (ok/stale/incomplete) may not
    # overwrite PROVENANCE quality. provisional_basis survives every monitoring
    # cycle; only confirm_operator_basis() or broker evidence promotes it.
    pricing = ("ok" if not eco.get("flags") else
               ("stale" if any("no_quote" in f for f in eco["flags"]) else "incomplete_basis"))
    cur.execute("""UPDATE options_strategy_positions SET latest_snapshot_id=%s,
                   data_quality_status=CASE
                     WHEN data_quality_status='provisional_basis' AND %s='ok'
                       THEN 'provisional_basis'
                     ELSE %s END,
                   updated_at=now() WHERE strategy_position_id=%s""",
                (snap_id, pricing, pricing, spid))
    conn.commit()
    return snap_id, {**eco, "mfe": mfe, "mae": mae, "giveback": giveback}


# ── policy decisions ──────────────────────────────────────────────────────────

def _days_held(s: dict) -> int | None:
    if not s.get("opened_at"):
        return None
    o = s["opened_at"]
    return max(0, (datetime.now(timezone.utc) - (o if o.tzinfo else o.replace(tzinfo=timezone.utc))).days)


def decide(s: dict, eco: dict, pol: dict, defense_posture: dict | None = None) -> dict:
    """One strategy + one snapshot → {recommendation, urgency, confidence,
    rationale, alternatives}. The rationale is the exact operator sentence."""
    stype, dte = s["strategy_type"], eco.get("dte_nearest")
    cap, upl = eco.get("pct_max_profit_captured"), eco.get("unrealized_pnl")
    held = _days_held(s)
    alt = []

    if eco.get("flags"):
        blocked = [f for f in eco["flags"] if f.startswith(("no_quote", "unknown_basis"))]
        if blocked:
            return {"recommendation": "DATA_BLOCKED", "urgency": "amber", "confidence": "high",
                    "rationale": "Cannot price the structure honestly: " + "; ".join(blocked[:3]) +
                                 ". No action until data is whole — fail closed.",
                    "alternatives": [{"action": "fix_data", "note": "resolve quotes/basis, then re-evaluate"}]}

    if stype == "covered_call":
        c = pol["covered_call"]
        remaining = (eco["max_profit_possible"] - (eco["max_profit_possible"] * cap / 100)
                     if (cap is not None and eco.get("max_profit_possible")) else None)
        if cap is not None and dte is not None:
            if cap >= c["let_mature_pct_captured"] and dte <= c["let_mature_dte"] and not eco.get("itm_short"):
                return {"recommendation": "LET_MATURE", "urgency": "green", "confidence": "medium",
                        "rationale": f"Covered call has captured {cap:.0f}% with only {dte} DTE and the strike "
                                     f"safely away ({eco.get('short_distance_pct', 0):+.1f}%). Friction of closing "
                                     "now exceeds the residual — let it decay, review daily.",
                        "alternatives": [{"action": "HARVEST_FULL", "note": "close early to free the shares"}]}
            fast = held is not None and held <= c["fast_capture_days"] and cap >= c["early_harvest_pct_if_fast"]
            if (cap >= c["harvest_full_pct_captured"] or fast) and held is not None and held >= 1:
                if remaining is not None and remaining < c["harvest_min_remaining_premium_dollars"] or fast:
                    return {"recommendation": "HARVEST_FULL", "urgency": "amber", "confidence": "high",
                            "rationale": f"Covered call has captured {cap:.0f}% of maximum premium in {held} days "
                                         f"with {dte} DTE remaining. Only ${remaining:,.0f} of premium remains while "
                                         "assignment and upside-cap risk continue. HARVEST FULL.",
                            "alternatives": [{"action": "ROLL", "note": "roll out/up if income should continue"},
                                             {"action": "HOLD", "note": "accept cap risk for the residual"}]}
        strike_breached = eco.get("itm_short") or (
            eco.get("short_distance_pct") is not None
            and eco["short_distance_pct"] <= c["defend_strike_breach_pct"] * -1)
        if strike_breached or (eco.get("short_delta") is not None
                               and eco["short_delta"] >= c["defend_delta"]):
            why = (f"spot is THROUGH the strike ({eco.get('short_distance_pct', 0):+.1f}%)"
                   if strike_breached else f"short call delta {eco['short_delta']:.2f}")
            return {"recommendation": "DEFEND", "urgency": "red", "confidence": "high",
                    "rationale": f"Covered call under assignment pressure — {why}; shares face being "
                                 "called away. Decide: roll up/out, or accept assignment (state intent).",
                    "alternatives": [{"action": "ROLL", "note": "roll up/out for duration + strike room"},
                                     {"action": "ACCEPT_ASSIGNMENT", "note": "if parting with shares is acceptable"}]}
        if dte is not None and dte <= c["roll_review_dte"] and cap is not None and cap < c["harvest_full_pct_captured"]:
            return {"recommendation": "ROLL", "urgency": "amber", "confidence": "medium",
                    "rationale": f"{dte} DTE with only {cap:.0f}% captured — decay has underdelivered. "
                                 "Review roll economics vs closing; do not drift into expiry week unmanaged.",
                    "alternatives": [{"action": "CLOSE", "note": "pay up and release the cap"},
                                     {"action": "LET_MATURE", "note": "only if strike distance is comfortable"}]}
        against = cap is not None and cap < 0
        return {"recommendation": "HOLD", "urgency": "amber" if against else "green",
                "confidence": "medium",
                "rationale": (f"Covered call moving against: mark above entry credit "
                              f"({cap:.0f}% captured), {dte} DTE, strike "
                              f"{eco.get('short_distance_pct', 0):+.1f}% away — watch the defend triggers."
                              if against else
                              f"Covered call on plan: {cap if cap is not None else '?'}% captured, {dte} DTE, "
                              f"strike {eco.get('short_distance_pct', 0):+.1f}% away. Premium is being earned."),
                "alternatives": []}

    if stype == "cash_secured_put":
        c = pol["cash_secured_put"]
        assignment_ok = (s.get("operator_objective") or "") == "assignment_ok"
        if eco.get("short_delta") is not None and eco["short_delta"] >= c["defend_delta"]:
            if assignment_ok:
                return {"recommendation": "ACCEPT_ASSIGNMENT", "urgency": "amber", "confidence": "medium",
                        "rationale": f"Short put delta {eco['short_delta']:.2f} and objective is assignment_ok — "
                                     "review the entry you'd be assigned at; taking the shares is the plan working.",
                        "alternatives": [{"action": "ROLL", "note": "roll down/out to improve entry"},
                                         {"action": "CLOSE", "note": "thesis broke — pay to exit"}]}
            return {"recommendation": "DEFEND", "urgency": "red", "confidence": "high",
                    "rationale": f"Short put delta {eco['short_delta']:.2f}, strike "
                                 f"{abs(eco.get('short_distance_pct') or 0):.1f}% from spot and closing. "
                                 "Assignment not desired — roll down/out or close.",
                    "alternatives": [{"action": "ROLL"}, {"action": "CLOSE"}]}
        if cap is not None and held is not None and cap >= c["harvest_full_pct_captured"] and held >= c["harvest_min_days_held"]:
            return {"recommendation": "HARVEST_FULL", "urgency": "amber", "confidence": "high",
                    "rationale": f"CSP has captured {cap:.0f}% of premium in {held} days with {dte} DTE left. "
                                 "Remaining premium no longer pays for the tail — buy it back, free the collateral.",
                    "alternatives": [{"action": "HOLD", "note": "squeeze the residual"},
                                     {"action": "ROLL", "note": "re-strike if income should continue"}]}
        return {"recommendation": "HOLD", "urgency": "green", "confidence": "medium",
                "rationale": f"CSP on plan: {cap if cap is not None else '?'}% captured, {dte} DTE, "
                             f"strike {abs(eco.get('short_distance_pct') or 0):.1f}% below spot.",
                "alternatives": []}

    if stype == "protective_put":
        c = pol["protective_put"]
        hedge_needed = True
        why_needed = "hedge objective stands (default: never drop protection without an explicit read)"
        if defense_posture:
            states = defense_posture.get("protected_sector_states") or []
            hedge_needed = any(st in c["hedge_still_needed_states"] for st in states) or not states
            why_needed = ("protected exposure still sits in " + "/".join(states)
                          if states else why_needed)
        protected = (eco.get("underlying_price") or 0) * float(s.get("linked_share_qty") or 0)
        if upl is not None and upl > 0 and hedge_needed:
            return {"recommendation": "HOLD", "urgency": "green", "confidence": "high",
                    "rationale": f"Protective put is up ${upl:,.0f}, but {why_needed} and the hedge still covers "
                                 f"${protected:,.0f} of exposure. HOLD HEDGE; do not sell protection solely "
                                 "because it is profitable.",
                    "alternatives": [{"action": "ROLL", "note": "roll down/out to monetize + keep protection"}]}
        if dte is not None and dte <= c["roll_forward_dte"] and hedge_needed:
            return {"recommendation": "ROLL", "urgency": "amber", "confidence": "high",
                    "rationale": f"Hedge has {dte} DTE and the book still needs it — roll forward before decay "
                                 "guts the convexity. Compare replacement cost now vs at 7 DTE.",
                    "alternatives": [{"action": "CLOSE", "note": "only if the hedge objective has ended"}]}
        if not hedge_needed:
            return {"recommendation": "CLOSE", "urgency": "amber", "confidence": "medium",
                    "rationale": "The protected exposure no longer reads deteriorating — the hedge objective has "
                                 "ended. Harvest whatever value remains; insurance without a risk is pure theta.",
                    "alternatives": [{"action": "HOLD", "note": "if the operator's risk read differs"}]}
        return {"recommendation": "HOLD", "urgency": "green", "confidence": "medium",
                "rationale": f"Hedge in place, {dte} DTE, covering ${protected:,.0f}. On plan.",
                "alternatives": []}

    if stype in ("long_call", "long_put", "straddle", "strangle"):
        c = pol["long_option"]
        gb, mfe = eco.get("giveback"), eco.get("mfe")
        if (gb is not None and mfe and mfe > 0 and upl is not None
                and (gb / mfe * 100) >= c["giveback_harvest_pct"]
                and (held or 0) >= c["min_days_held_before_harvest"]):
            return {"recommendation": "HARVEST_FULL", "urgency": "red", "confidence": "high",
                    "rationale": f"Position peaked at ${mfe:,.0f} and has given back ${gb:,.0f} "
                                 f"({gb / mfe * 100:.0f}% of the peak). Winners that round-trip are the desk's "
                                 "worst outcome — harvest what remains.",
                    "alternatives": [{"action": "HARVEST_PARTIAL", "note": "scale out half, run the rest"}]}
        if (mfe and upl is not None and upl > 0 and eco.get("entry_value")
                and mfe >= abs(eco["entry_value"]) * c["scale_out_mfe_multiple"]):
            return {"recommendation": "HARVEST_PARTIAL", "urgency": "amber", "confidence": "medium",
                    "rationale": f"Up ${upl:,.0f} — peak reached {c['scale_out_mfe_multiple']:.0f}× the debit. "
                                 "Scale out to recover cost; let the remainder run on house money.",
                    "alternatives": [{"action": "HOLD", "note": "full conviction, accept giveback risk"}]}
        if dte is not None and dte <= c["thesis_review_dte"]:
            return {"recommendation": "DEFEND", "urgency": "amber", "confidence": "medium",
                    "rationale": f"{dte} DTE — theta now outruns most theses. State the catalyst that resolves "
                                 "inside the window, or close/roll; drifting into the decay cliff is not a plan.",
                    "alternatives": [{"action": "ROLL", "note": "pay for more time"},
                                     {"action": "CLOSE", "note": "thesis stale — salvage extrinsic"}]}
        return {"recommendation": "HOLD", "urgency": "green", "confidence": "medium",
                "rationale": f"Long option holding: P&L ${upl:,.0f}, {dte} DTE. Thesis window open." if upl is not None
                             else f"Long option holding, {dte} DTE.",
                "alternatives": []}

    if stype in ("credit_spread", "debit_spread"):
        c = pol["spread"]
        if stype == "credit_spread":
            if (eco.get("short_delta") is not None and eco.get("short_distance_pct") is not None
                    and (eco["short_delta"] >= c["credit_defend_short_delta"]
                         or abs(eco["short_distance_pct"]) <= c["credit_defend_short_distance_pct"])):
                capn = f"{cap:.0f}%" if cap is not None else "an unknown share"
                return {"recommendation": "CLOSE", "urgency": "red", "confidence": "high",
                        "rationale": f"Credit spread has captured {capn} of maximum profit, but the short strike "
                                     f"is now only {abs(eco['short_distance_pct']):.1f}% from spot and delta has "
                                     f"risen to {eco['short_delta']:.2f}. CLOSE SPREAD — as one order, never legs.",
                        "alternatives": [{"action": "ROLL", "note": "roll the spread out/away as one package"},
                                         {"action": "DEFEND", "note": "only with a stated recovery trigger"}]}
            if cap is not None and cap >= c["credit_harvest_pct_captured"] and (held or 0) >= 2:
                return {"recommendation": "HARVEST_FULL", "urgency": "amber", "confidence": "high",
                        "rationale": f"Credit spread has captured {cap:.0f}% of max profit in {held} days with "
                                     f"{dte} DTE left. Remaining reward is thin against gap risk through the short "
                                     "strike — close the spread.",
                        "alternatives": [{"action": "LET_MATURE", "note": "only far OTM into expiry"}]}
        else:
            if cap is not None and cap >= c["debit_harvest_pct_of_max"]:
                return {"recommendation": "HARVEST_FULL", "urgency": "amber", "confidence": "high",
                        "rationale": f"Debit spread has {cap:.0f}% of its maximum value with {dte} DTE — the last "
                                     "slice needs pin-perfect expiry. Take the win as one order.",
                        "alternatives": [{"action": "HOLD", "note": "deep ITM both legs and patient"}]}
        if dte is not None and dte <= c["pin_risk_window_dte"]:
            return {"recommendation": "CLOSE", "urgency": "red", "confidence": "high",
                    "rationale": f"{dte} DTE with strikes near spot — pin/assignment window. Spreads are closed "
                                 "as spreads before expiry week decides for you.",
                    "alternatives": [{"action": "LET_MATURE", "note": "only if BOTH legs are far from spot"}]}
        return {"recommendation": "HOLD", "urgency": "green", "confidence": "medium",
                "rationale": f"Spread on plan: {cap if cap is not None else '?'}% of max captured, {dte} DTE, "
                             f"short strike {abs(eco.get('short_distance_pct') or 0):.1f}% away.",
                "alternatives": []}

    return {"recommendation": "DATA_BLOCKED", "urgency": "amber", "confidence": "high",
            "rationale": f"Structure type '{stype}' is not policy-covered — managed as unknown; no automated "
                         "recommendation. Operator review required.",
            "alternatives": []}


PRECEDENCE = ["DATA_BLOCKED", "EXPIRATION_CRITICAL", "ASSIGNMENT_CRITICAL", "DEFEND",
              "ROLL", "ACCEPT_ASSIGNMENT", "EXERCISE_REVIEW", "HARVEST_FULL",
              "HARVEST_PARTIAL", "LET_MATURE", "HOLD"]
_CRITICAL_URGENCY = {"DATA_BLOCKED": "amber", "EXPIRATION_CRITICAL": "red",
                     "ASSIGNMENT_CRITICAL": "red"}


def reduce_decision(d: dict, findings: list[dict], eco: dict) -> dict:
    """v1.1 P1: ONE primary recommendation per snapshot. Assignment/expiry
    findings compete with the policy decision under a fixed precedence; losers
    become SUPPORTING CONTEXT inside the same decision — never independent
    contradictory primaries (no simultaneous HARVEST_FULL and DEFEND)."""
    candidates = [(d["recommendation"], d["urgency"], d["rationale"])]
    for f in findings or []:
        if f["code"] == "expiry_day":
            candidates.append(("EXPIRATION_CRITICAL", "red", f["line"]))
        elif f["code"].startswith(("early_assignment", "under_covered")) or (
                f["code"].startswith("itm_short") and (eco.get("dte_nearest") or 99) <= 3):
            candidates.append(("ASSIGNMENT_CRITICAL", "red", f["line"]))
    ranked = sorted(candidates, key=lambda c: PRECEDENCE.index(c[0])
                    if c[0] in PRECEDENCE else len(PRECEDENCE))
    primary_rec, primary_urg, primary_line = ranked[0]
    subordinate = [{"recommendation": r, "line": ln} for r, _, ln in ranked[1:]]
    subordinate += [{"finding": f["code"], "line": f["line"]} for f in (findings or [])
                    if f["line"] not in [c[2] for c in candidates]]
    rationale = primary_line
    if primary_rec != d["recommendation"]:
        rationale = (f"{primary_line} Supporting economics: {d['rationale']}")
    elif subordinate:
        extra = "; ".join(s["line"] for s in subordinate[:2] if s.get("line"))
        if extra:
            rationale = f"{primary_line} Supporting context: {extra}"
    return {**d, "recommendation": primary_rec,
            "urgency": _CRITICAL_URGENCY.get(primary_rec, primary_urg),
            "rationale": rationale, "subordinate": subordinate,
            "precedence_rule": " > ".join(dict.fromkeys(c[0] for c in ranked))}


def record_decision(cur, conn, spid: int, snap_id: int, d: dict, pol: dict) -> int | None:
    """Append to the ledger only when (recommendation, urgency) changed vs the
    latest live decision — supersedes the prior row. Returns decision_id or None."""
    cur.execute("""SELECT decision_id, recommendation, urgency FROM options_lifecycle_decisions
                   WHERE strategy_position_id=%s AND superseded_by IS NULL
                   ORDER BY decision_id DESC LIMIT 1""", (spid,))
    prev = cur.fetchone()
    if prev and prev[1] == d["recommendation"] and prev[2] == d["urgency"]:
        return None
    transition = (f"{prev[1]}→{d['recommendation']}" if prev else "initial")
    cur.execute("""INSERT INTO options_lifecycle_decisions
        (strategy_position_id, snapshot_id, policy_version, recommendation, urgency,
         confidence, rationale, alternatives, subordinate, precedence_rule,
         prior_recommendation, transition_reason, decision_engine_version,
         code_commit_sha, policy_hash, reducer_version)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING decision_id""",
        (spid, snap_id, pol["policy_version"], d["recommendation"], d["urgency"],
         d.get("confidence"), d["rationale"], json.dumps(d.get("alternatives") or []),
         json.dumps(d.get("subordinate") or []), d.get("precedence_rule"),
         prev[1] if prev else None, transition, DECISION_ENGINE_VERSION,
         _commit_sha(), _policy_hash(), REDUCER_VERSION))
    did = cur.fetchone()[0]
    if prev:
        cur.execute("UPDATE options_lifecycle_decisions SET superseded_by=%s WHERE decision_id=%s",
                    (did, prev[0]))
    conn.commit()
    return did


def evaluate_strategy(cur, conn, s: dict, *, persist: bool = True) -> dict:
    """v1.2 P2: THE canonical decision-producing path. Everything that needs a
    decision comes through here — quotes → economics → assignment findings →
    decide → reduce → (persist snapshot + decision). No caller may combine
    decide() and record_decision() without the reducer and findings again."""
    from options_lifecycle_alerts import assignment_review
    pol = policy()
    quotes = {l["leg_id"]: quote_leg(l) for l in s["legs"] if l["status"] == "open"}
    eco = strategy_economics(s, quotes)
    snap_id = None
    if persist:
        snap_id, eco = persist_snapshot(cur, conn, s, eco)
    findings = assignment_review(s, eco, pol)
    d = reduce_decision(decide(s, eco, pol, defense_posture_for(s["underlying"])),
                        findings, eco)
    # v1.2.1 P0-2: basis-material recommendations stay explicitly QUALIFIED
    # while the basis is provisional (operator evidence, unconfirmed)
    if s.get("data_quality_status") == "provisional_basis" and \
            d["recommendation"].startswith(("HARVEST", "CLOSE", "ROLL")):
        d = {**d, "rationale": d["rationale"] +
             " [QUALIFIED: economics rest on PROVISIONAL operator-supplied basis — "
             "confirm or replace with broker evidence before acting on P&L grounds]",
             "subordinate": (d.get("subordinate") or []) +
             [{"finding": "provisional_basis", "line": "basis unconfirmed (operator evidence)"}]}
    did = record_decision(cur, conn, s["strategy_position_id"], snap_id, d, pol) if persist else None
    return {"eco": eco, "decision": d, "findings": findings,
            "snapshot_id": snap_id, "decision_id": did}


def defense_posture_for(underlying: str) -> dict:
    """Sector states of the underlying per the Defense snapshot — the hedge-need
    signal for protective puts. Absent data = empty (engine defaults to HOLD hedge)."""
    try:
        snap = json.loads((ROOT / "data" / "runtime" / "defense_recommendations_latest.json").read_text())
        data = snap.get("data", snap)
        states = []
        for st in data.get("stances", []):
            if st.get("symbol") == underlying and st.get("sector_state"):
                states.append(st["sector_state"])
        if not states:
            for sec in (data.get("sources", {}) or {}).get("sector_states", []) or []:
                states.append(sec)
        return {"protected_sector_states": states}
    except Exception:
        return {}


def run(dry: bool = False) -> dict:
    """v1.2.1 P0-1: DELEGATES to evaluate_strategy() — the ONLY decision path.
    (The prior implementation here bypassed the reducer + findings; CLI, cron,
    API, and dry-run now all return the identical reduced recommendation.)"""
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    ensure_tables(cur, conn)
    pol = policy()
    out = {"evaluated": 0, "decisions": [], "policy_version": pol["policy_version"]}
    for s in open_strategies(cur):
        ev = evaluate_strategy(cur, conn, s, persist=not dry)
        out["decisions"].append({"spid": s["strategy_position_id"],
                                 "snapshot_id": ev["snapshot_id"],
                                 "decision_id": ev["decision_id"],
                                 **({"dry": True} if dry else {}), **ev["decision"]})
        out["evaluated"] += 1
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(dry=a.dry_run), indent=1, default=str))
