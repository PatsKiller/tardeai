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
        return res
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
                                           "fell_for_reason")},
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
