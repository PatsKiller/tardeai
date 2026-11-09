"""market_event_plan — WP3 of the market-event re-entry spec (SPEC_MARKET_EVENT_REENTRY_20261107 §4.3).

Deterministic, advisory-only re-entry plan for a market event:

* ``market_gate(snapshot, policy)``: is the market itself healing? It reads the Market Risk snapshot
  (``data/runtime/market_risk_latest.json``, MarketRiskSnapshot@v1). The primary condition is the
  tier stepping down, or the score falling for N consecutive evaluations. The confirmations are the
  options-flow (put/call) state, the breadth state and the extended-hours (futures proxy) state.
* ``name_gate(bars, policy)``: has this name stopped falling? Signals: no new low for K sessions,
  RSI turning up from below ``rsi_low``, OBV/CMF accumulation, and the SMA20 reclaim (used only by
  the last tranche).
* ``evaluate_candidate(...)``: the state machine. WATCH -> STABILIZING -> READY (t1, then t2 once
  the market gate confirms, then t3 once the name reclaims SMA20). INVALIDATED when the low breaks
  the invalidation price a previous evaluation recorded. ENTERED is never set here: only an operator
  record can say a position was entered, so a stored ENTERED is carried, never inferred.
* ``plan_accounts(...)``: per-account advisory sizing.
  - deployable = settled cash - reserve_pct x account value;
  - allocation by score, capped per name and per sector;
  - tranche dollars at 30/30/40;
  - a risk check that (entry - invalidation) x shares stays within the per-name risk budget;
  - wash-sale and account-type annotations.
  Nothing is ever dropped silently: every candidate that gets no dollars carries the reason.

Rail (AGENTS.md §0 rule 1, §2): MBI_BEHAVIOR = 0. This module is advisory output for the operator,
the same class as ``redeploy_capital_book`` (advisory_only). It has no order, stop, broker or
DB-write path. It imports nothing that can reach a broker or a quote provider. The CIO stays the
single verdict owner; nothing here is a decision.

Pure: no I/O except ``load_policy`` (``config/market_event_policy.json``, owned by WP1). No LLM.
Inputs from the WP1/WP2 tables use the spec §4.2 field names.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

SCHEMA = "MarketEventPlan@v1"
ADVISORY_NOTE = (
    "Advisory only. Not an order, not a stop, not a decision. The operator decides, "
    "and the CIO is the verdict owner."
)

STATES = ("WATCH", "STABILIZING", "READY", "ENTERED", "INVALIDATED")
TIERS = ("GREEN", "NONE", "BLUE", "YELLOW", "ORANGE", "RED")  # scripts/lib/market_risk/contract.py

DEFAULT_POLICY: dict[str, Any] = {
    "cash_reserve_pct": 5.0,
    "tranche_pcts": [30, 30, 40],
    "per_name_cap_pct_of_deployable": 10.0,
    "per_sector_cap_pct_of_deployable": 30.0,
    "risk_budget_pct_of_account": 1.0,
    "min_tranche_usd": 250,
    "max_candidates": 25,
    "entry_zone_below_pct": 2.0,
    "entry_zone_above_pct": 1.0,
    "market_gate": {
        "score_falling_evaluations": 2,
        "min_confirming": 2,
        "options_flow_ok_states": ["CALM", "WARN"],
        "breadth_ok_states": ["CALM", "WARN"],
        "futures_ok_states": ["CALM", "WARN"],
    },
    "name_gate": {
        "no_new_low_sessions": 3,
        "rsi_period": 14,
        "rsi_low": 35,
        "rsi_lookback_sessions": 5,
        "cmf_period": 20,
        "obv_slope_sessions": 5,
        "sma_period": 20,
        "invalidation_buffer_pct": 1.0,
        "low_lookback_sessions": 20,
        "min_bars": 30,
    },
    #: LQ-20261107-1656/1674 — the stages after ENTERED. Operator-approved defaults (2026-11-09 14:50 ET):
    #: trim 25 %, rs_loss 5 %, 3 sessions, and "YELLOW+" means YELLOW **or better** (tier rank <= YELLOW).
    "lifecycle": {
        "enabled": True,
        "positions_max_age_minutes": 30,
        "snapshot_max_age_minutes": 60,
        "tranche_held_fraction": 0.8,
        "trim_gain_pct": 25.0,
        "trim_rsi": 75.0,
        "rs_loss_pct": 5.0,
        "rs_loss_sessions": 3,
        "t3_max_tier": "YELLOW",
        "exit_min_tier": "RED",
        "gain_guardian_states": ["GIVEBACK_BREACH"],  # holdings_gain_guardian.py:337 (the vocabulary its classifier emits)
        "settle_min": 15,
        "event_kinds": ["CPI", "FOMC", "NFP", "PCE"],
        "tier_order": ["GREEN", "NONE", "BLUE", "YELLOW", "ORANGE", "RED"],
    },
}

#: account types that never receive a plan (registry ``type`` values, lower case)
EXCLUDED_ACCOUNT_TYPES = frozenset({"paper"})
#: account types where no wash-sale loss can be realized (scripts/lib/wash_sale.py)
TAX_ADVANTAGED_TYPES = frozenset({"rollover_ira", "roth_ira", "ira", "traditional_ira", "sep_ira", "hsa"})


# --------------------------------------------------------------------------- policy


def _merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_policy(path: Optional[Path] = None) -> dict[str, Any]:
    """The ``plan`` block of config/market_event_policy.json over the defaults.

    The result carries ``policy_source``: "file" when the block was read, "defaults" when the file
    or block is absent, and "defaults (unreadable: ...)" when the file is on disk but cannot be
    parsed. An unreadable file is reported, never treated as an empty policy.
    """
    p = path or Path(__file__).resolve().parents[2] / "config" / "market_event_policy.json"
    pol = _merge(DEFAULT_POLICY, {})
    source = "defaults"
    version = None
    if p.exists():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            block = doc.get("plan") if isinstance(doc, dict) else None
            version = doc.get("policy_version") if isinstance(doc, dict) else None
            if isinstance(block, Mapping):
                pol = _merge(DEFAULT_POLICY, block)
                source = "file"
        except (OSError, ValueError) as exc:
            source = f"defaults (unreadable: {type(exc).__name__}: {exc})"
    pol["policy_source"] = source
    pol["policy_version"] = version
    return pol


# --------------------------------------------------------------------------- helpers


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v: Optional[float], nd: int = 2) -> Optional[float]:
    return None if v is None else round(v, nd)


def rsi_series(closes: Sequence[float], period: int = 14) -> list[Optional[float]]:
    """Wilder RSI. Entries before ``period`` closes are None."""
    out: list[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period

    def _v(g: float, lo: float) -> float:
        if lo == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / lo)

    out[period] = _v(ag, al)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
        out[i] = _v(ag, al)
    return out


def obv_series(closes: Sequence[float], volumes: Sequence[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        step = volumes[i] if closes[i] > closes[i - 1] else (-volumes[i] if closes[i] < closes[i - 1] else 0.0)
        out.append(out[-1] + step)
    return out


def cmf(bars: Sequence[Mapping[str, float]], period: int = 20) -> Optional[float]:
    """Chaikin money flow over the last ``period`` bars."""
    win = list(bars)[-period:]
    if len(win) < period:
        return None
    mfv = vol = 0.0
    for b in win:
        h, lo, c, v = b["high"], b["low"], b["close"], b["volume"]
        rng = h - lo
        mult = 0.0 if rng <= 0 else ((c - lo) - (h - c)) / rng
        mfv += mult * v
        vol += v
    return None if vol <= 0 else mfv / vol


def clean_bars(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Daily bars ascending by date with numeric OHLCV. Rows with a missing field are dropped
    (and counted by the caller via the length difference)."""
    out = []
    for r in rows or []:
        vals = {k: _f(r.get(k)) for k in ("open", "high", "low", "close", "volume")}
        if any(vals[k] is None for k in ("high", "low", "close")):
            continue
        vals["volume"] = vals["volume"] or 0.0
        vals["date"] = str(r.get("date") or r.get("bar_time") or "")[:10]
        out.append(vals)
    out.sort(key=lambda b: b["date"])
    return out


# --------------------------------------------------------------------------- market gate


def _tier_rank(t: Any) -> Optional[int]:
    t = str(t or "").upper()
    return TIERS.index(t) if t in TIERS else None


def market_gate(snapshot: Optional[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    """Market gate from the Market Risk snapshot.

    passed = primary AND confirmations >= min_confirming.
    * primary: the tier stepped down within the last N evaluations, or the score fell at each of the
      last N evaluations. Identical consecutive evaluations (e.g. a weekend) are not a fall.
    * confirmations: options_flow (put/call), breadth and extended_hours (futures proxy) category
      states in their "ok" sets. UNKNOWN or missing counts as not confirming and is listed as such.
    """
    mg = policy.get("market_gate") or {}
    n = int(mg.get("score_falling_evaluations", 2))
    need = int(mg.get("min_confirming", 2))
    out: dict[str, Any] = {"passed": False, "primary": None, "confirmations": [], "reasons": [],
                           "tier": None, "score": None, "as_of": None, "mode": None}
    if not isinstance(snapshot, Mapping) or snapshot.get("schema") != "MarketRiskSnapshot@v1":
        out["reasons"].append("market-risk snapshot missing or unreadable: market gate NOT evaluated")
        out["evaluated"] = False
        return out
    out.update(tier=snapshot.get("tier"), score=_f(snapshot.get("score")), as_of=snapshot.get("as_of"),
               mode=snapshot.get("mode"), evaluated=True)
    hist = [h for h in (snapshot.get("history") or []) if isinstance(h, Mapping)]
    scores = [_f(h.get("score")) for h in hist][-(n + 1):]
    tiers = [_tier_rank(h.get("tier")) for h in hist][-(n + 1):]
    falling = len(scores) == n + 1 and all(
        a is not None and b is not None and b < a for a, b in zip(scores, scores[1:])
    )
    stepped = (len(tiers) == n + 1 and tiers[-1] is not None
               and any(t is not None and tiers[-1] < t for t in tiers[:-1]))
    out["primary"] = {"score_falling": falling, "tier_stepped_down": stepped,
                      "window": [{"as_of": h.get("as_of"), "score": h.get("score"), "tier": h.get("tier")}
                                 for h in hist[-(n + 1):]]}
    cats = {str(c.get("category")): c for c in (snapshot.get("categories") or []) if isinstance(c, Mapping)}
    conf_n = 0
    for key, label, ok_key in (("options_flow", "put/call normalizing", "options_flow_ok_states"),
                               ("breadth", "breadth improving", "breadth_ok_states"),
                               ("extended_hours", "futures direction", "futures_ok_states")):
        c = cats.get(key) or {}
        state = str(c.get("state") or "UNKNOWN").upper()
        ok = state in {str(s).upper() for s in mg.get(ok_key) or []}
        conf_n += ok
        out["confirmations"].append({"name": label, "category": key, "state": state, "confirms": ok,
                                     "detail": c.get("detail"), "as_of": c.get("as_of")})
    out["confirming"] = {"n": conf_n, "need": need}
    primary_ok = falling or stepped
    if not primary_ok:
        out["reasons"].append(
            f"tier has not stepped down and the score has not fallen at each of the last {n} evaluations")
    if conf_n < need:
        out["reasons"].append(f"{conf_n} of 3 confirmations (need {need})")
    out["passed"] = bool(primary_ok and conf_n >= need)
    return out


# --------------------------------------------------------------------------- name gate


def name_gate(bars_in: Iterable[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    """Name-level signals from daily bars (ascending). Never raises; short history -> evaluated False."""
    ng = policy.get("name_gate") or {}
    bars = clean_bars(bars_in)
    k = int(ng.get("no_new_low_sessions", 3))
    min_bars = int(ng.get("min_bars", 30))
    out: dict[str, Any] = {"evaluated": False, "bars": len(bars), "signals": {}, "reasons": []}
    if len(bars) < min_bars:
        out["reasons"].append(f"{len(bars)} daily bars (need {min_bars}): name gate NOT evaluated")
        return out
    closes = [b["close"] for b in bars]
    lows = [b["low"] for b in bars]
    vols = [b["volume"] for b in bars]
    lb = int(ng.get("low_lookback_sessions", 20))
    window = lows[-lb:]
    low = min(window)
    low_idx = len(lows) - len(window) + window.index(low)
    # the most recent bar that printed the window low (ties -> latest)
    for i in range(len(lows) - 1, len(lows) - len(window) - 1, -1):
        if lows[i] == low:
            low_idx = i
            break
    sessions_since_low = len(lows) - 1 - low_idx
    no_new_low = sessions_since_low >= k

    period = int(ng.get("rsi_period", 14))
    rsi = rsi_series(closes, period)
    rsi_low = float(ng.get("rsi_low", 35))
    look = int(ng.get("rsi_lookback_sessions", 5))
    recent = [x for x in rsi[-(look + 1):] if x is not None]
    rsi_now = rsi[-1]
    rsi_prev = rsi[-2] if len(rsi) > 1 else None
    rsi_turn = bool(recent and rsi_now is not None and rsi_prev is not None
                    and min(recent) < rsi_low and rsi_now > rsi_prev and rsi_now > min(recent))

    obv = obv_series(closes, vols)
    s = int(ng.get("obv_slope_sessions", 5))
    obv_up = len(obv) > s and obv[-1] > obv[-1 - s]
    cmf_v = cmf(bars, int(ng.get("cmf_period", 20)))
    accumulation = bool(obv_up or (cmf_v is not None and cmf_v > 0))

    sp = int(ng.get("sma_period", 20))
    sma = sum(closes[-sp:]) / sp if len(closes) >= sp else None
    reclaim = sma is not None and closes[-1] > sma

    buf = float(ng.get("invalidation_buffer_pct", 1.0)) / 100.0
    out.update(
        evaluated=True,
        as_of=bars[-1]["date"],
        last_close=_r(closes[-1], 4),
        window_low=_r(low, 4),
        window_low_date=bars[low_idx]["date"],
        sessions_since_low=sessions_since_low,
        invalidation=_r(low * (1.0 - buf), 4),
        sma20=_r(sma, 4),
        rsi=_r(rsi_now, 1),
        cmf=_r(cmf_v, 3),
        signals={"no_new_low": no_new_low, "rsi_turning_up": rsi_turn,
                 "accumulation": accumulation, "sma20_reclaim": bool(reclaim)},
    )
    if not no_new_low:
        out["reasons"].append(f"new {lb}-session low {sessions_since_low} session(s) ago (need {k} without one)")
    if not rsi_turn:
        out["reasons"].append(f"RSI {out['rsi']} not turning up from below {rsi_low:g}")
    if not accumulation:
        out["reasons"].append("no accumulation (OBV not rising, CMF <= 0)")
    if not reclaim:
        out["reasons"].append("below SMA20 (third tranche waits for the reclaim)")
    return out


# --------------------------------------------------------------------------- state machine


def evaluate_candidate(candidate: Mapping[str, Any], bars: Iterable[Mapping[str, Any]],
                       mgate: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    """State + tranches ready for one candidate.

    ``candidate`` is a market_event_candidates row (spec §4.2). Its stored ``state`` and
    ``plan.invalidation`` are the memory: a candidate that was STABILIZING/READY and whose low broke
    the stored invalidation becomes INVALIDATED and stays so for the episode. ENTERED is carried
    from the row and never inferred.
    """
    prev = str(candidate.get("state") or "WATCH").upper()
    prev_plan = candidate.get("plan") if isinstance(candidate.get("plan"), Mapping) else {}
    g = name_gate(bars, policy)
    res: dict[str, Any] = {"symbol": str(candidate.get("symbol") or "").upper(), "previous_state": prev,
                           "name_gate": g, "tranches_ready": 0, "reasons": list(g.get("reasons") or [])}
    if prev == "INVALIDATED":
        res.update(state="INVALIDATED", reasons=["invalidated earlier in this episode (sticky)"])
        return res
    prev_inv = _f((prev_plan or {}).get("invalidation"))
    if g.get("evaluated") and prev in ("STABILIZING", "READY", "ENTERED") and prev_inv is not None:
        last_low = _f(clean_bars(bars)[-1]["low"]) if g["bars"] else None
        if last_low is not None and last_low < prev_inv:
            res.update(state="INVALIDATED",
                       reasons=[f"low {last_low:g} broke the recorded invalidation {prev_inv:g}"])
            return res
    if prev == "ENTERED":
        res["state"] = "ENTERED"
        res["reasons"] = ["entered per operator record; plan shown for the remaining tranches"]
    elif not g.get("evaluated"):
        res["state"] = prev if prev in STATES else "WATCH"
        return _hold_fell_for_reason(candidate, res)
    sig = g.get("signals") or {}
    if not g.get("evaluated"):
        return res
    if res.get("state") != "ENTERED":
        if not sig.get("no_new_low"):
            res["state"] = "WATCH"
        elif not (sig.get("rsi_turning_up") and sig.get("accumulation")):
            res["state"] = "STABILIZING"
        else:
            res["state"] = "READY"
    if res["state"] in ("READY", "ENTERED") and sig.get("no_new_low"):
        t = 1
        if mgate.get("passed"):
            t = 2
            if sig.get("sma20_reclaim"):
                t = 3
        res["tranches_ready"] = t
        if t < 2:
            res["reasons"].append("second tranche waits for the market gate")
    return _hold_fell_for_reason(candidate, res)


def _operator_starred(candidate: Mapping[str, Any]) -> bool:
    ev = candidate.get("reason_evidence") if isinstance(candidate.get("reason_evidence"), Mapping) else {}
    return candidate.get("operator_star") is True or (ev or {}).get("operator_star") is True


def _hold_fell_for_reason(candidate: Mapping[str, Any], res: dict[str, Any]) -> dict[str, Any]:
    """Spec §4.3: a name that fell for its own reason is never READY without an operator star.

    It is held at STABILIZING with no tranche ready. ENTERED (the operator's own record) and
    INVALIDATED are left as they are. Only an explicit ``operator_star is True`` releases the hold.
    """
    res["fell_for_reason"] = bool(candidate.get("fell_for_reason"))
    if not res["fell_for_reason"] or _operator_starred(candidate):
        return res
    if res.get("state") == "READY":
        res["state"] = "STABILIZING"
        res["tranches_ready"] = 0
        res["held_for_star"] = True
        res["reasons"].append("fell for its own reason: held below READY until the operator stars it")
    return res


# --------------------------------------------------------------------------- sizing


def _score(c: Mapping[str, Any]) -> float:
    q, d = _f(c.get("quality_score")), _f(c.get("discount_score"))
    if q is None and d is None:
        return 1.0
    return max(0.0, (q or 0.0) + (d or 0.0))


def account_tax_class(account_type: Any) -> str:
    t = str(account_type or "unknown").lower()
    if t == "taxable":
        return "taxable"
    if t in TAX_ADVANTAGED_TYPES:
        return "tax_advantaged"
    return "unknown"


def plan_accounts(accounts: Sequence[Mapping[str, Any]], evaluated: Sequence[Mapping[str, Any]],
                  policy: Mapping[str, Any], *, wash: Optional[Mapping[str, Mapping[str, Any]]] = None
                  ) -> list[dict[str, Any]]:
    """Per-account advisory sizing.

    ``accounts``: [{account_label, account_type, cash_usd, account_value_usd}] (an internal key may be
    present; it is never copied to the output).
    ``evaluated``: candidates merged with ``evaluate_candidate`` output; each needs symbol, sector,
    last_price, state, tranches_ready, name_gate, quality_score and discount_score.
    ``wash``: {SYMBOL: wash_sale.classify(...) result}, the most restrictive across taxable accounts.
    The statutory gate applies to buys in every account (wash_sale.py).
    """
    wash = wash or {}
    tr = [float(x) for x in policy.get("tranche_pcts") or [30, 30, 40]]
    tr_sum = sum(tr) or 1.0
    reserve_pct = float(policy.get("cash_reserve_pct", 5.0)) / 100.0
    name_cap = float(policy.get("per_name_cap_pct_of_deployable", 10.0)) / 100.0
    sector_cap = float(policy.get("per_sector_cap_pct_of_deployable", 30.0)) / 100.0
    risk_pct = float(policy.get("risk_budget_pct_of_account", 1.0)) / 100.0
    min_tr = float(policy.get("min_tranche_usd", 0) or 0)
    below = float(policy.get("entry_zone_below_pct", 2.0)) / 100.0
    above = float(policy.get("entry_zone_above_pct", 1.0)) / 100.0

    live = [c for c in evaluated if c.get("state") not in ("INVALIDATED",)]
    out = []
    for a in accounts:
        label = str(a.get("account_label") or "Unlabelled account")
        atype = str(a.get("account_type") or "unknown").lower()
        cash = _f(a.get("cash_usd")) or 0.0
        value = _f(a.get("account_value_usd")) or 0.0
        reserve = reserve_pct * value
        deployable = max(0.0, cash - reserve)
        acct: dict[str, Any] = {
            "account_label": label, "account_type": atype, "tax_class": account_tax_class(atype),
            "cash_usd": _r(cash), "account_value_usd": _r(value), "reserve_usd": _r(reserve),
            "deployable_usd": _r(deployable), "cash_as_of": a.get("cash_as_of"),
            "risk_budget_per_name_usd": _r(risk_pct * value), "names": [], "notes": [],
        }
        if atype in EXCLUDED_ACCOUNT_TYPES:
            acct["deployable_usd"] = 0.0
            acct["notes"].append(f"{atype} account: no plan")
            out.append(acct)
            continue
        if deployable <= 0:
            acct["notes"].append("cash is at or under the reserve: nothing deployable")
        total_w = sum(_score(c) for c in live) or 0.0
        alloc: dict[str, float] = {}
        for c in live:
            sym = str(c.get("symbol") or "").upper()
            raw = deployable * (_score(c) / total_w) if total_w else 0.0
            alloc[sym] = min(raw, name_cap * deployable)
        by_sector: dict[str, float] = {}
        for c in live:
            sec = str(c.get("sector") or "Unknown")
            by_sector[sec] = by_sector.get(sec, 0.0) + alloc[str(c.get("symbol") or "").upper()]
        scale = {sec: (min(1.0, sector_cap * deployable / tot) if tot > 0 else 1.0)
                 for sec, tot in by_sector.items()}
        used = 0.0
        for c in sorted(evaluated, key=lambda x: (x.get("rank") is None, x.get("rank") or 0,
                                                  str(x.get("symbol")))):
            sym = str(c.get("symbol") or "").upper()
            sec = str(c.get("sector") or "Unknown")
            g = c.get("name_gate") or {}
            row: dict[str, Any] = {"symbol": sym, "sector": sec, "state": c.get("state"),
                                   "tranches_ready": c.get("tranches_ready", 0), "annotations": []}
            if c.get("state") == "INVALIDATED":
                row["annotations"].append("invalidated: no plan")
                acct["names"].append(row)
                continue
            target = alloc.get(sym, 0.0) * scale.get(sec, 1.0)
            if scale.get(sec, 1.0) < 1.0:
                row["annotations"].append(f"sector cap: {sec} scaled to {scale[sec]:.0%}")
            if alloc.get(sym, 0.0) >= name_cap * deployable - 0.005 and deployable > 0:
                row["annotations"].append("per-name cap applied")
            entry = _f(c.get("last_price")) or _f(g.get("last_close"))
            inv = _f(g.get("invalidation"))
            if entry is None or entry <= 0:
                row["annotations"].append("no price: no sizing")
                acct["names"].append(row)
                continue
            risk_per_share = (entry - inv) if inv is not None and inv < entry else None
            budget = risk_pct * value
            if risk_per_share is None:
                row["annotations"].append("no invalidation below the price: risk check not possible, no sizing")
                target = 0.0
            elif budget > 0 and target / entry * risk_per_share > budget:
                capped = budget / risk_per_share * entry
                row["annotations"].append(
                    f"risk budget: position cut from ${target:,.0f} to ${capped:,.0f} "
                    f"(loss at invalidation <= ${budget:,.0f})")
                target = capped
            sma = _f(g.get("sma20"))
            tranches = []
            for i, pct in enumerate(tr, start=1):
                usd = target * pct / tr_sum
                px = sma if (i == len(tr) and sma) else entry
                shares = int(usd // px) if px else 0
                t: dict[str, Any] = {
                    "tranche": i, "pct": pct, "usd": _r(usd), "shares": shares,
                    "entry_zone": ([_r(sma, 2), _r(sma * (1 + above), 2)] if (i == len(tr) and sma)
                                   else [_r(max(entry * (1 - below), (inv or 0) * 1.001), 2),
                                         _r(entry * (1 + above), 2)]),
                    "trigger": ("name gate (no new low, RSI turn, accumulation)" if i == 1
                                else "market gate confirms" if i == 2 else "reclaims SMA20"),
                    "ready": i <= int(c.get("tranches_ready") or 0),
                }
                if usd < min_tr:
                    t["note"] = f"under the ${min_tr:,.0f} minimum tranche"
                    t["shares"] = 0
                elif shares == 0:
                    t["note"] = "under one share"
                tranches.append(t)
            row.update(target_usd=_r(target), entry_ref=_r(entry, 4), invalidation=_r(inv, 4),
                       loss_at_invalidation_usd=_r(sum(t["shares"] for t in tranches) * risk_per_share)
                       if risk_per_share else None, tranches=tranches)
            used += sum((t["usd"] or 0) for t in tranches if t["shares"])
            w = wash.get(sym) or {}
            kind = str(w.get("kind") or "NONE")
            if kind in ("WASH_SALE_RISK_LOSS", "UNVERIFIED"):
                row["annotations"].append(
                    f"wash sale: {kind} until {w.get('hold_until')} ({w.get('label') or 'see wash_sale'})"
                    + ("; an IRA buy inside the window disallows the loss permanently"
                       if acct["tax_class"] == "tax_advantaged" else ""))
                row["wash_sale"] = {"kind": kind, "hold_until": w.get("hold_until")}
            elif kind == "HOUSE_HOLD_NO_LOSS":
                row["annotations"].append(f"house re-entry hold until {w.get('hold_until')} (gain; not a wash sale)")
                row["wash_sale"] = {"kind": kind, "hold_until": w.get("hold_until")}
            if acct["tax_class"] == "unknown":
                row["annotations"].append("account type unknown: treated as taxable for wash sale")
            acct["names"].append(row)
        acct["planned_usd"] = _r(used)
        acct["unallocated_usd"] = _r(max(0.0, deployable - used))
        out.append(acct)
    return out


def build(*, episode: Optional[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]],
          bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]], snapshot: Optional[Mapping[str, Any]],
          accounts: Sequence[Mapping[str, Any]], policy: Mapping[str, Any],
          wash: Optional[Mapping[str, Mapping[str, Any]]] = None) -> dict[str, Any]:
    """Whole plan: market gate, each candidate's state, and per-account sizing (top max_candidates by rank)."""
    mg = market_gate(snapshot, policy)
    top = sorted(candidates, key=lambda c: (c.get("rank") is None, c.get("rank") or 0,
                                            str(c.get("symbol"))))[: int(policy.get("max_candidates", 25))]
    evaluated = []
    for c in top:
        sym = str(c.get("symbol") or "").upper()
        ev = evaluate_candidate(c, bars_by_symbol.get(sym) or [], mg, policy)
        merged = {**{k: c.get(k) for k in ("symbol", "sector", "rank", "source", "baseline_price", "last_price",
                                           "drawdown_pct", "quality_score", "discount_score",
                                           "fell_for_reason", "reason_evidence")},
                  **ev, "stored_state": c.get("state")}
        merged["symbol"] = sym
        evaluated.append(merged)
    return {
        "schema": SCHEMA, "advisory_only": True, "note": ADVISORY_NOTE,
        "episode": dict(episode) if episode else None,
        "market_gate": mg,
        "candidates": evaluated,
        "accounts": plan_accounts(accounts, evaluated, policy, wash=wash),
        "policy": {"source": policy.get("policy_source"), "version": policy.get("policy_version"),
                   "cash_reserve_pct": policy.get("cash_reserve_pct"), "tranche_pcts": policy.get("tranche_pcts")},
    }


# --------------------------------------------------------------------------- lifecycle (LQ-20261107-1656/1674)
#
# The WP3 state machine stops at ENTERED: ``evaluate_candidate`` carries a stored ENTERED and never moves it, so once
# a name is bought the engine goes silent. ``evaluate_position`` is the other half — it runs for a row that is already
# entered and answers "what does the operator do next about the position that exists".
#
# Operator decision 2026-11-09 14:50 ET: ENTERED_OBSERVED may be set from ``positions_current`` (qty > 0 in the
# episode) and is labelled with the source, so it is never confused with an operator-confirmed ENTERED. This module
# stays pure: the caller supplies the position, the snapshot and the calendar events; nothing here reads a broker,
# a credential, a DB or a quote provider. Rail: MBI_BEHAVIOR = 0 (AGENTS.md §0 rule 1, §2).

POSITION_STAGES = (
    "ENTERED_OBSERVED",  # qty > 0 but not yet at the first tranche's planned size
    "ENTERED_T1",
    "ADD_T2_READY",
    "HELD_T2",
    "ADD_T3_READY",
    "FULL",
    "TRIM_READY",
    "EXIT_READY",
    "INVALIDATED",
    "STOPPED_OUT",
)
TERMINAL_STAGES = ("INVALIDATED", "STOPPED_OUT")
#: stages that always alert (Fi text); the others go to the brief/digest only (design step 6)
FI_TEXT_STAGES = ("ADD_T2_READY", "ADD_T3_READY", "EXIT_READY", "STOPPED_OUT")


def _parse_at(v: Any) -> Optional[datetime]:
    """An ISO timestamp or datetime as tz-aware UTC, or None. Naive input is taken as UTC (ISO compare memory)."""
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str) and v.strip():
        try:
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _minutes_since(v: Any, now: datetime) -> Optional[float]:
    dt = _parse_at(v)
    return None if dt is None else (now - dt).total_seconds() / 60.0


def _tier_index(tier: Any, order: Sequence[str]) -> Optional[int]:
    """Rank in the MRE tier order (GREEN, NONE, BLUE, YELLOW, ORANGE, RED): larger is worse."""
    t = str(tier or "").upper()
    try:
        return list(order).index(t)
    except ValueError:
        return None


def _tranches_held(qty: Optional[float], plan: Mapping[str, Any], frac: float) -> tuple[Optional[int], str]:
    """How many planned tranches the observed size covers, and why when it cannot be measured.

    ``plan["tranche_qty"]`` (per-tranche share counts) is the direct form; ``plan["planned_shares"]`` with
    ``tranche_pcts`` is the derived one. A tranche counts as held when qty >= its cumulative planned qty x frac —
    a partial fill below that is ENTERED_OBSERVED, not a held tranche.
    """
    if qty is None:
        return None, "holding_qty_unknown"
    base = plan.get("tranche_qty")
    if not isinstance(base, (list, tuple)) or not base:
        shares = _f(plan.get("planned_shares"))
        pcts = plan.get("tranche_pcts")
        if shares is None or not isinstance(pcts, (list, tuple)) or not pcts:
            return None, "tranche_plan_qty_unknown"
        total = float(sum(float(x) for x in pcts)) or 100.0
        base = [shares * float(p) / total for p in pcts]
    held, cum = 0, 0.0
    for n in base:
        cum += float(n)
        if qty >= cum * frac:
            held += 1
        else:
            break
    return held, ""


def evaluate_position(candidate: Mapping[str, Any], holding: Mapping[str, Any],
                      events: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any],
                      policy: Mapping[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The stage of an entered position, with every gate re-evaluated on every call.

    ``candidate``: the market_event_candidates row — ``episode_id``, ``symbol``, ``sector``, ``state``, ``plan``
    (``tranche_percents``/``tranche_qty``, ``invalidation``, ``entry_price``), ``entry_tier``, ``fell_for_reason`` and
    ``reason_evidence``. ``holding``: ``qty``, ``avg_cost`` (may be None — ``positions_current`` has no cost column,
    see the note below), ``stop_price``/``stop_state``, ``price``, ``sleeve_pct``. ``events``: the calendar rows this
    episode cares about, ``{"kind", "at", "released_at"}``. ``snapshot``: ``as_of``, ``tier``, ``last_close``,
    ``low``, ``sma20``, ``rsi14``, ``rs5_loss_sessions``, ``gain_guardian_state``, ``sleeve`` (``pct``, ``target``).

    A missing input is UNAVAILABLE and never PASS — the ``reentry_rotation_alerts`` rule. A stale positions or
    snapshot input makes the row UNVERIFIABLE and **no stage advances**.
    """
    lc = policy.get("lifecycle") if isinstance(policy.get("lifecycle"), Mapping) else {}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    sym = str(candidate.get("symbol") or "").upper()
    label = str(holding.get("account_label") or candidate.get("account_label") or "unlabelled")
    prev = str(candidate.get("stage") or candidate.get("state") or "ENTERED").upper()
    plan = candidate.get("plan") if isinstance(candidate.get("plan"), Mapping) else {}
    reasons: list[str] = []
    gates: dict[str, Any] = {}

    res: dict[str, Any] = {
        "schema": "MarketEventPosition@v1",
        "episode_id": candidate.get("episode_id"),
        "symbol": sym,
        "account_label": label,
        "previous_stage": prev,
        "stage": prev,
        "verdict": "OK",
        "gates": gates,
        "reasons": reasons,
        "alert": None,
        "handoff": None,
        "advisory_only": True,
        "note": ADVISORY_NOTE,
    }

    # --- freshness. The positions snapshot is the thing this lane must not move without.
    pos_age = _minutes_since(holding.get("as_of"), now)
    snap_age = _minutes_since(snapshot.get("as_of"), now)
    max_pos = float(lc.get("positions_max_age_minutes", 30.0))
    max_snap = float(lc.get("snapshot_max_age_minutes", 60.0))
    stale: list[str] = []
    if pos_age is None:
        stale.append(f"positions_as_of {holding.get('as_of')!r} unreadable")
    elif pos_age > max_pos:
        stale.append(f"positions {pos_age:.0f} min old (limit {max_pos:g})")
    if snap_age is None:
        stale.append(f"snapshot_as_of {snapshot.get('as_of')!r} unreadable")
    elif snap_age > max_snap:
        stale.append(f"snapshot {snap_age:.0f} min old (limit {max_snap:g})")
    if stale:
        res["verdict"] = "UNVERIFIABLE"
        reasons.extend(stale)
        reasons.append("no stage advances on a stale input")
        gates["fresh"] = {"ok": False, "reasons": stale}
        return res
    gates["fresh"] = {"ok": True}

    if prev in TERMINAL_STAGES:
        # INVALIDATED / STOPPED_OUT are terminal for the episode (design PROCESS 2). Recovery owns any re-entry.
        res["verdict"] = "OK"
        reasons.append(f"{prev} is terminal for this episode: no stage advances, recovery owns re-entry")
        gates["terminal"] = {"ok": True, "stage": prev}
        return res

    qty = _f(holding.get("qty"))
    price = _f(snapshot.get("last_close")) or _f(holding.get("price"))
    entry = _f(plan.get("entry_price")) or _f(candidate.get("entry_price"))
    inval = _f(plan.get("invalidation"))
    tier_order = lc.get("tier_order") or ["GREEN", "NONE", "BLUE", "YELLOW", "ORANGE", "RED"]
    tier = str(snapshot.get("tier") or "").upper() or None
    tier_rank = _tier_index(tier, tier_order)
    entry_rank = _tier_index(candidate.get("entry_tier"), tier_order)
    low = _f(snapshot.get("low"))
    stop_state = str(holding.get("stop_state") or "").upper()

    # --- terminal: stopped out hands the name to recovery_state; this lane never re-enters it.
    if stop_state == "FILLED" or (qty is not None and qty == 0 and holding.get("had_working_stop") is True):
        res.update(stage="STOPPED_OUT", verdict="OK",
                   handoff={"to": "recovery_state", "kind": "stop_out", "episode_id": candidate.get("episode_id"),
                            "symbol": sym, "account_label": label, "stop_state": stop_state or "missing"})
        reasons.append("stop filled or the position went to zero with a working stop gone: recovery owns re-entry")
        gates["stopped_out"] = {"ok": True}
        return _with_alert(res, candidate, lc)

    # --- exit gates. Any one is enough; each records its own verdict so the alert can say which.
    # The close-below-invalidation leg is not repeated here: it is INVALIDATED, decided below, because the design's
    # proof 5 makes it terminal for the episode rather than a recoverable EXIT_READY.
    exits: list[str] = []
    rs_loss = snapshot.get("rs5_loss_sessions")
    rs_need = int(lc.get("rs_loss_sessions", 3))
    if isinstance(rs_loss, (int, float)):
        if float(rs_loss) >= rs_need:
            exits.append(f"rs5 at or below -{float(lc.get('rs_loss_pct', 5.0)):g}% for "
                         f"{int(rs_loss)} sessions (need {rs_need})")
    else:
        reasons.append("rs5_loss_sessions not measured: the RS-loss exit cannot be evaluated")
    exit_rank = _tier_index(lc.get("exit_min_tier", "RED"), tier_order)
    if (tier_rank is not None and exit_rank is not None and entry_rank is not None
            and tier_rank >= exit_rank and price is not None and entry is not None and price < entry):
        exits.append(f"tier escalated to {tier} after entry with the close {price:g} under the entry basis {entry:g}")
    ev = candidate.get("reason_evidence") if isinstance(candidate.get("reason_evidence"), Mapping) else {}
    neg = ev.get("negative_catalyst_types") or []
    if candidate.get("fell_for_reason") and neg:
        exits.append("thesis-invalidating catalyst: " + ", ".join(str(x) for x in neg))
    gates["exit"] = {"ok": not exits, "reasons": exits}

    # --- trim gates
    trims: list[str] = []
    sleeve = snapshot.get("sleeve") if isinstance(snapshot.get("sleeve"), Mapping) else {}
    sp = _f(sleeve.get("pct"))
    st = _f(sleeve.get("target"))
    if sp is not None and st is not None and sp > st:
        lo = _f(sleeve.get("band_low_frac"))
        hi = _f(sleeve.get("band_high_frac"))
        band = "" if lo is None or hi is None else f"; suggested trim {lo * 100:.0f}-{hi * 100:.0f}% of the position"
        trims.append(f"sleeve {sp:g}% is over its {st:g}% target{band}")
    gain = _f(holding.get("avg_cost"))
    gain_pct = (price / gain - 1.0) * 100.0 if price is not None and gain else None
    rsi14 = _f(snapshot.get("rsi14"))
    trim_gain = float(lc.get("trim_gain_pct", 25.0))
    trim_rsi = float(lc.get("trim_rsi", 75.0))
    if gain_pct is None:
        reasons.append("no cost basis: the gain leg of the trim gate is unmeasured")
    elif gain_pct >= trim_gain and rsi14 is not None and rsi14 >= trim_rsi:
        trims.append(f"gain {gain_pct:.1f}% with RSI {rsi14:.1f} >= {trim_rsi:g}")
    gg = str(snapshot.get("gain_guardian_state") or "").upper()
    gg_states = [str(x).upper() for x in (lc.get("gain_guardian_states") or [])]
    if gg and gg in gg_states:
        trims.append(f"gain guardian giveback state {gg}")
    gates["trim"] = {"ok": not trims, "reasons": trims,
                     "unmeasured": ["gain_pct"] if gain_pct is None else []}

    # --- progression gates
    frac = float(lc.get("tranche_held_fraction", 0.8))
    held, held_why = _tranches_held(qty, plan, frac)
    if held is None:
        reasons.append(held_why)
    gates["held"] = {"ok": held is not None, "tranches": held, "reason": held_why or None, "qty": qty}
    n_tr = max(1, len(plan.get("tranche_percents") or plan.get("tranche_pcts") or [30, 30, 40]))

    # t2: the calendar gate. Explicit policy entry wins; otherwise the first configured event at/after entry.
    t2_reasons: list[str] = []
    gate = lc.get("event_gate") if isinstance(lc.get("event_gate"), Mapping) else {}
    gkind = str(gate.get("kind") or "").upper()
    settle = int(gate.get("settle_min") or lc.get("settle_min", 15))
    released = None
    for e in events or []:
        if not isinstance(e, Mapping):
            continue
        if gkind and str(e.get("kind") or "").upper() != gkind:
            continue
        if not gkind and str(e.get("kind") or "").upper() not in [str(k).upper() for k in lc.get("event_kinds") or []]:
            continue
        released = e
        break
    t2_open = False
    if released is None:
        t2_reasons.append("event_gate: no calendar event in scope" if not gkind else f"event_gate:{gkind} not scheduled")
    else:
        kind = str(released.get("kind") or gkind or "event").upper()
        rel_at = _parse_at(released.get("released_at"))
        if rel_at is None:
            t2_reasons.append(f"event_gate:{kind} not released")
        elif (now - rel_at).total_seconds() / 60.0 < settle:
            t2_reasons.append(f"event_gate:{kind} settling (<{settle} min)")
        elif tier_rank is not None and entry_rank is not None and tier_rank > entry_rank:
            t2_reasons.append(f"event_gate:{kind} withheld: tier {tier} worse than at entry "
                              f"{candidate.get('entry_tier')}")
        elif low is not None and inval is not None and low < inval:
            t2_reasons.append(f"event_gate:{kind} withheld: low {low:g} under invalidation {inval:g}")
        else:
            t2_open = True
    gates["t2"] = {"ok": t2_open, "reasons": t2_reasons}

    # t3: tier YELLOW or better AND the SMA20 reclaim (the existing name_gate rule).
    t3_reasons: list[str] = []
    t3_max = _tier_index(lc.get("t3_max_tier", "YELLOW"), tier_order)
    sma = _f(snapshot.get("sma20"))
    reclaim = price is not None and sma is not None and price > sma
    if tier_rank is None:
        t3_reasons.append("tier not measured")
    elif t3_max is not None and tier_rank > t3_max:
        t3_reasons.append(f"tier {tier} is worse than {lc.get('t3_max_tier', 'YELLOW')}")
    if sma is None or price is None:
        t3_reasons.append("SMA20 reclaim not measured")
    elif not reclaim:
        t3_reasons.append(f"close {price:g} below SMA20 {sma:g}")
    gates["t3"] = {"ok": not t3_reasons, "reasons": t3_reasons}

    # --- stage: terminal/override first, then progression from how many tranches are actually held.
    if exits:
        stage = "EXIT_READY"
        reasons.extend(exits)
    elif trims:
        stage = "TRIM_READY"
        reasons.extend(trims)
    elif held is None:
        stage = prev if prev in POSITION_STAGES else "ENTERED_OBSERVED"
    elif held >= n_tr:
        stage = "FULL"
    elif held >= 2:
        stage = "ADD_T3_READY" if gates["t3"]["ok"] else "HELD_T2"
        reasons.extend(gates["t3"]["reasons"] if not gates["t3"]["ok"] else [])
    elif held >= 1:
        stage = "ADD_T2_READY" if t2_open else "ENTERED_T1"
        if not t2_open:
            reasons.extend(t2_reasons)
    else:
        stage = "ENTERED_OBSERVED"
        reasons.append(f"observed size is below the first tranche's plan x {frac:g}")

    # The one irreversible-looking one: an entered position whose close broke the recorded invalidation.
    if inval is not None and price is not None and price < inval:
        stage = "INVALIDATED"
        reasons.insert(0, f"close {price:g} broke the recorded invalidation {inval:g}")
        gates["invalidated"] = {"ok": False, "reason": reasons[0]}

    res["stage"] = stage
    if gain_pct is None or snapshot.get("rs5_loss_sessions") is None or sma is None:
        res["verdict"] = "DEGRADED"
    res["gates"] = gates
    return _with_alert(res, candidate, lc)


def _with_alert(res: dict[str, Any], candidate: Mapping[str, Any], lc: Mapping[str, Any]) -> dict[str, Any]:
    """Attach the alert identity, once per (episode, symbol, label, to_stage). An unchanged stage gets none."""
    if res["stage"] == res["previous_stage"]:
        return res
    eid = f"{candidate.get('episode_id')}:{res['symbol']}:{res['account_label']}:{res['stage']}"
    res["alert"] = {
        "event_id": eid,
        "stage": res["stage"],
        "from_stage": res["previous_stage"],
        "symbol": res["symbol"],
        "account_label": res["account_label"],
        "class": "fi_text" if res["stage"] in FI_TEXT_STAGES else "digest",
    }
    return res
