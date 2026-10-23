"""Watch position facts — held / formerly held / never held, the last round trip and the re-entry advice, per symbol,
plus the filters and sorts over them (operator 2026-10-23). Read-only. Zero provider calls. No new store.

Operator 2026-10-23 09:25 (verbatim): "NAVN is saying add. When I actually sold that yesterday, it should be tracked
that formerly held, that it should be letting me know if it's an opportunity to get back in. It should also know if I
made money with it or not. And you need to make it tighter." and "we should be able to filter on this information."

Where each fact comes from — no new silo:

* **held** — the one Watch held reader, ``watch_domains.held_positions(surface="watch")`` (positions_store reader
  batch #1: positions_current when fresh, else the holdings file with an explicit fallback_reason).
* **formerly held** — not held now, and a sell fill in ``trade_transactions`` (the broker ledger the curator already
  reads for "recently sold") inside ``FORMER_DAYS``.
* **last round trip and re-entry advice** — the CIO prospect lifecycle, computed by the same code the CIO prospect
  build uses (``cio_prospect_builder.load_lifecycle_inputs`` + ``lifecycle_for`` → ``cio_prospect_lifecycle``:
  fills, observed stop path, exit cause, P/L, R, post-exit review; ``reentry_rules.derive_intel_state`` — the Re-Entry
  Decision Desk's classifier — for READY / NEAR / WAIT). The CIO prospect store is not live, so this projection runs
  those pure functions over the same read-only inputs and says so (``source``); when the store is live the record's
  own ``position_lifecycle`` / ``reentry_advice`` replace it.

``MBI_BEHAVIOR = 0``: levels are references for a person, never orders; the observed stop is ``stop_price_observed``.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

SCHEMA = "WatchPositionFacts@v1"
FORMER_DAYS = 365
BREAKEVEN_PCT = 0.25  # |P/L %| below this is breakeven
CACHE_S = 300.0
SOURCE_LABEL = (
    "CIO prospect lifecycle (cio_prospect_builder.lifecycle_for over schwab_round_trips, "
    "trade_transactions, stop_lifecycle, ticker_prices; the prospect store is not live)"
)

EXIT_CAUSE = {  # cio_prospect_lifecycle.classify_exit class → filter key, label
    "stop_out": ("stop", "Stop hit"),
    "trailing_ratchet": ("trailing", "Trailing stop"),
    "target": ("target", "Target"),
    "manual_sell": ("manual", "Manual sell"),
    "time_exit": ("time", "Time exit"),
    "unknown_no_stop_history": ("unknown", "Unknown (no stop history)"),
}
READINESS = {"READY TO REVIEW": "ready", "NEAR ENTRY": "near"}

# Filter / sort vocabulary — shared by watch-universe, watch-curation and watch-prospects. ``server`` is the exact
# server-side rule (the page shows it as the tooltip).
FILTERS: dict[str, dict[str, Any]] = {
    "position": {
        "label": "Position status",
        "kind": "multi",
        "options": ["held", "formerly_held", "never_held"],
        "server": "keeps rows whose position_state is one of the chosen values: held = in the Watch held "
        "reader (positions_current when fresh, else the holdings file); formerly_held = not held "
        f"and a sell fill in trade_transactions within {FORMER_DAYS} days; never_held = neither",
    },
    "result": {
        "label": "Last trade result",
        "kind": "multi",
        "options": ["won", "lost", "breakeven"],
        "server": f"keeps formerly held rows whose last closed round trip P/L % is > +{BREAKEVEN_PCT}% (won), "
        f"< -{BREAKEVEN_PCT}% (lost) or within ±{BREAKEVEN_PCT}% (breakeven); rows without a "
        "round trip are dropped",
    },
    "pnl_usd_min": {
        "label": "P/L $ ≥",
        "kind": "number",
        "server": "keeps rows whose last round trip net P/L in dollars is ≥ this; rows without one drop",
    },
    "pnl_usd_max": {
        "label": "P/L $ ≤",
        "kind": "number",
        "server": "keeps rows whose last round trip net P/L in dollars is ≤ this; rows without one drop",
    },
    "pnl_pct_min": {
        "label": "P/L % ≥",
        "kind": "number",
        "server": "keeps rows whose last round trip P/L % (exit vs entry fill) is ≥ this",
    },
    "pnl_pct_max": {
        "label": "P/L % ≤",
        "kind": "number",
        "server": "keeps rows whose last round trip P/L % (exit vs entry fill) is ≤ this",
    },
    "exit_cause": {
        "label": "Exit cause",
        "kind": "multi",
        "options": ["stop", "trailing", "target", "manual", "time", "unknown"],
        "server": "keeps rows whose last exit was classified (cio_prospect_lifecycle.classify_exit) as: "
        "stop = exit at an observed stop never raised; trailing = exit at an observed stop "
        "that was raised at least once; target = at/above the linked plan target; manual = "
        "matches no stop and no target; time = a time exit (no classifier produces it yet, so "
        "it matches nothing today); unknown = no stop history",
    },
    "exited_within": {
        "label": "Exit date",
        "kind": "single",
        "options": ["1d", "1w", "1m", "older"],
        "server": "keeps rows whose last sell is within 1 day / 7 days / 30 days of now, or older than 30 days",
    },
    "reentry": {
        "label": "Re-entry readiness",
        "kind": "multi",
        "options": ["ready", "near", "waiting", "invalidated"],
        "server": "keeps formerly held rows by the Re-Entry Desk classifier (reentry_rules): ready = READY "
        "TO REVIEW (in zone, RSI 40–70); near = NEAR ENTRY (within 3% of the zone); invalidated = "
        "the thesis is invalidated/retired; waiting = any other state (WAIT, wash block, "
        "overbought, stale, missing data)",
    },
    "reentry_dist_min": {
        "label": "Distance to trigger % ≥",
        "kind": "number",
        "server": "keeps rows whose distance from price to the re-entry zone (desk distance_pct; "
        "0 = inside, + above, − below) is ≥ this",
    },
    "reentry_dist_max": {
        "label": "Distance to trigger % ≤",
        "kind": "number",
        "server": "keeps rows whose distance from price to the re-entry zone is ≤ this",
    },
    "r_min": {
        "label": "R ≥",
        "kind": "number",
        "server": "keeps rows whose last round trip R multiple (linked plan stop, else the initial observed "
        "stop) is ≥ this",
    },
    "r_max": {"label": "R ≤", "kind": "number", "server": "keeps rows whose last round trip R multiple is ≤ this"},
}
FILTER_KEYS = tuple(FILTERS)
SORTS: dict[str, str] = {
    "exit_date": "most recent sell first (rows without a sell last)",
    "pnl_pct": "last round trip P/L % high → low",
    "pnl_usd": "last round trip P/L $ high → low",
    "r": "last round trip R high → low",
    "reentry_distance": "closest to the re-entry zone first (absolute distance %)",
    "formerly_held_first": "formerly held first (most recent sell first), then by conviction",
}


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        try:
            t = datetime.fromisoformat(str(v)[:10])
        except ValueError:
            return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _iso(v: Any) -> Optional[str]:
    t = _ts(v)
    return t.isoformat() if t else None


# ── facts (pure) ─────────────────────────────────────────────────────────────


def round_trip_view(life: Optional[dict[str, Any]], review: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The last closed round trip, flattened for a row: entry, exit, P/L $ and %, R, exit cause, noise vs trend."""
    if not life or life.get("status") != "closed":
        return None
    pnl = life.get("pnl") or {}
    cause = life.get("exit_cause") or {}
    key, label = EXIT_CAUSE.get(str(cause.get("class") or ""), ("unknown", str(cause.get("class") or "unknown")))
    r = _f(pnl.get("r_multiple"))
    r_basis = "linked plan stop"
    if r is None:
        r = _f(pnl.get("r_on_initial_observed_stop"))
        r_basis = "initial observed stop"
    if r is None:
        r = _f(pnl.get("r_on_plan_invalidation_at_entry"))
        r_basis = "plan invalidation at entry"
    pct = _f(pnl.get("pnl_pct"))
    stops = life.get("observed_stops") or {}
    nvt = (review or {}).get("noise_vs_trend") or {}
    return {
        "entry_at": (life.get("entry_fill") or {}).get("at"),
        "entry_price": _f((life.get("entry_fill") or {}).get("price")),
        "exit_at": (life.get("exit_fill") or {}).get("at"),
        "exit_price": _f((life.get("exit_fill") or {}).get("price")),
        "pnl_usd": _f(pnl.get("net_pnl_usd")),
        "pnl_pct": pct,
        "result": None
        if pct is None
        else ("breakeven" if abs(pct) < BREAKEVEN_PCT else ("won" if pct > 0 else "lost")),
        "r": None if r is None else round(r, 2),
        "r_basis": r_basis if r is not None else None,
        "exit_cause": key,
        "exit_cause_label": label,
        "exit_cause_evidence": cause.get("evidence"),
        "in_profit": cause.get("in_profit"),
        "stop_raised": stops.get("ratchets_up"),
        "stop_initial": stops.get("initial"),
        "stop_last": stops.get("last"),
        "hold_days": life.get("hold_days"),
        "round_trip_key": life.get("round_trip_key"),
        "noise_vs_trend": nvt.get("verdict"),
        "noise_vs_trend_basis": nvt.get("basis"),
    }


def advice_view(advice: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not advice:
        return None
    state = str(advice.get("state") or "")
    conds = advice.get("conditions") or []
    thesis_bad = any(c.get("id") == "thesis_valid" and c.get("met") is False for c in conds)
    readiness = "invalidated" if thesis_bad else READINESS.get(state, "waiting")
    lv = advice.get("levels") or {}
    zone = lv.get("entry_zone") or [None, None]
    return {
        "state": state,
        "readiness": readiness,
        "action": advice.get("action"),
        "reason": advice.get("reason"),
        "distance_pct": None if _f(advice.get("distance_pct")) is None else round(_f(advice.get("distance_pct")), 2),
        "entry_zone": zone,
        "reclaim": lv.get("reclaim"),
        "alert_levels": [
            {"reference": a.get("reference"), "level": a.get("level"), "means": a.get("means")}
            for a in advice.get("alert_levels") or []
        ],
        "conditions": [{"id": c.get("id"), "text": c.get("text"), "met": c.get("met")} for c in conds],
        "classifier": advice.get("classifier"),
    }


def facts_for(
    symbol: str, *, held: set[str], last_sell: dict[str, Any], lifecycle: dict[str, dict[str, Any]], now: datetime
) -> dict[str, Any]:
    s = symbol.upper()
    sold = _ts(last_sell.get(s))
    lc = lifecycle.get(s) or {}
    if s in held:
        state = "held"
    elif sold is not None and now - sold <= timedelta(days=FORMER_DAYS):
        state = "formerly_held"
    elif round_trip_view(lc.get("life"), lc.get("review")):
        state = "formerly_held"
    else:
        state = "never_held"
    rt = round_trip_view(lc.get("life"), lc.get("review")) if state == "formerly_held" else None
    if rt and rt.get("exit_at") and (sold is None or (_ts(rt["exit_at"]) or sold) > sold):
        sold = _ts(rt["exit_at"])
    return {
        "position_state": state,
        "position_label": {"held": "held", "formerly_held": "formerly held", "never_held": "never held"}[state],
        "last_sell_at": sold.isoformat() if (sold and state == "formerly_held") else None,
        "last_round_trip": rt,
        "reentry": advice_view(lc.get("advice")) if state == "formerly_held" else None,
    }


# ── filters and sorts (pure) ─────────────────────────────────────────────────


def _multi(q: dict[str, Any], key: str) -> set[str]:
    return {x.strip().lower() for x in str(q.get(key) or "").split(",") if x.strip()}


def active_filters(q: dict[str, Any]) -> dict[str, Any]:
    return {k: q[k] for k in FILTER_KEYS if str(q.get(k) or "").strip()}


def passes(pf: dict[str, Any], q: dict[str, Any], *, now: datetime) -> bool:
    """True when the position facts ``pf`` (facts_for output) pass every position filter in ``q`` (see FILTERS)."""
    pos = _multi(q, "position")
    if pos and pf.get("position_state") not in pos:
        return False
    rt = pf.get("last_round_trip") or {}
    adv = pf.get("reentry") or {}
    res = _multi(q, "result")
    if res and rt.get("result") not in res:
        return False
    for key, val, cmp in (
        ("pnl_usd_min", rt.get("pnl_usd"), "ge"),
        ("pnl_usd_max", rt.get("pnl_usd"), "le"),
        ("pnl_pct_min", rt.get("pnl_pct"), "ge"),
        ("pnl_pct_max", rt.get("pnl_pct"), "le"),
        ("r_min", rt.get("r"), "ge"),
        ("r_max", rt.get("r"), "le"),
        ("reentry_dist_min", adv.get("distance_pct"), "ge"),
        ("reentry_dist_max", adv.get("distance_pct"), "le"),
    ):
        lim = _f(q.get(key))
        if lim is None:
            continue
        if val is None or (cmp == "ge" and val < lim) or (cmp == "le" and val > lim):
            return False
    ec = _multi(q, "exit_cause")
    if ec and rt.get("exit_cause") not in ec:
        return False
    rd = _multi(q, "reentry")
    if rd and adv.get("readiness") not in rd:
        return False
    within = str(q.get("exited_within") or "").strip().lower()
    if within:
        sold = _ts(pf.get("last_sell_at"))
        if sold is None:
            return False
        age = now - sold
        lim = {"1d": timedelta(days=1), "1w": timedelta(days=7), "1m": timedelta(days=30)}.get(within)
        if within == "older":
            if age <= timedelta(days=30):
                return False
        elif lim is not None and age > lim:
            return False
    return True


def facet_counts(facts: list[dict[str, Any]], *, now: datetime) -> dict[str, dict[str, int]]:
    """Count chips: how many rows carry each option (over the rows the other filters left)."""
    out: dict[str, dict[str, int]] = {
        "position": {},
        "result": {},
        "exit_cause": {},
        "exited_within": {},
        "reentry": {},
    }
    for pf in facts:

        def inc(k: str, v: Any) -> None:
            if v:
                out[k][v] = out[k].get(v, 0) + 1

        inc("position", pf.get("position_state"))
        rt = pf.get("last_round_trip") or {}
        inc("result", rt.get("result"))
        inc("exit_cause", rt.get("exit_cause"))
        inc("reentry", (pf.get("reentry") or {}).get("readiness"))
        sold = _ts(pf.get("last_sell_at"))
        if sold:
            age = now - sold
            for k, d in (("1d", 1), ("1w", 7), ("1m", 30)):
                if age <= timedelta(days=d):
                    inc("exited_within", k)
            if age > timedelta(days=30):
                inc("exited_within", "older")
    return out


def sort_key(sort: str, pf: dict[str, Any], conviction: Optional[float]) -> tuple:
    rt = pf.get("last_round_trip") or {}
    adv = pf.get("reentry") or {}
    conv = -(conviction or 0.0)
    if sort == "exit_date":
        t = _ts(pf.get("last_sell_at"))
        return (t is None, -(t.timestamp() if t else 0), conv)
    if sort in ("pnl_pct", "pnl_usd", "r"):
        v = rt.get({"pnl_pct": "pnl_pct", "pnl_usd": "pnl_usd", "r": "r"}[sort])
        return (v is None, -(v or 0), conv)
    if sort == "reentry_distance":
        d = adv.get("distance_pct")
        return (d is None, abs(d or 0), conv)
    if sort == "formerly_held_first":
        t = _ts(pf.get("last_sell_at"))
        fh = pf.get("position_state") == "formerly_held"
        return (not fh, -(t.timestamp() if (fh and t) else 0), conv)
    return (0, conv)


# ── gather (I/O) ─────────────────────────────────────────────────────────────

_CACHE: dict[str, Any] = {"at": 0.0, "val": None}


def _db() -> Optional[Callable[..., Any]]:
    try:
        from db_adapter import _execute
    except Exception:  # noqa: BLE001
        return None
    return lambda sql, params=None: _execute(sql, params, fetch="all")


def last_sells(db_query: Callable[..., Any]) -> dict[str, Any]:
    rows = (
        db_query(
            """SELECT upper(symbol) AS s, max(coalesce(trade_time, trade_date::timestamptz)) AS at FROM trade_transactions
            WHERE lower(action) LIKE 'sell%%' AND trade_date > now() - (%s || ' days')::interval GROUP BY 1""",
            (str(FORMER_DAYS),),
        )
        or []
    )
    return {str(r["s"]).upper(): r.get("at") for r in rows if r.get("s")}


def lifecycles(
    db_query: Callable[..., Any], *, held: set[str], opps: dict[str, dict[str, Any]], rsi: dict[str, Any], now: datetime
) -> tuple[dict[str, dict[str, Any]], str]:
    """{SYM: lifecycle_for(...)} for every not-held symbol with a closed round trip in the lifecycle window."""
    try:
        try:
            from scripts.lib import cio_prospect_builder as pb
        except ImportError:  # pragma: no cover
            from lib import cio_prospect_builder as pb  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {}, f"error:{type(e).__name__}"
    inputs = pb.load_lifecycle_inputs(db_query)
    # stop_lifecycle is rewritten newest-first on every scan, so its id runs backwards in time for one position
    # (NAVN 2026-10-23: ids 3717493..3717502 hold 26.02 .. 24.59). Broker order ids are monotonic: order by them.
    for srows in ((inputs.get("stop_history") or {}).get("rows") or {}).values():
        for r in srows:
            oid = str(r.get("order_id") or "")
            if oid.isdigit():
                r["seq"] = int(oid)
    syms = sorted(s for s in ((inputs.get("round_trips") or {}).get("rows") or {}) if s not in held)
    bars: dict[str, list] = {}
    for s in syms:
        try:
            bars[s] = list(db_query(pb.BARS_SQL, (s,)) or [])
        except Exception:  # noqa: BLE001
            bars[s] = []
    inputs["bars"] = {"rows": bars, "status": "ok"}
    inputs["indicators"] = {"rows": {s: {"rsi": rsi.get(s)} for s in syms if rsi.get(s) is not None}, "status": "ok"}
    out: dict[str, dict[str, Any]] = {}
    for s in syms:
        try:
            ident = {"security_guid": f"symbol:{s}"}
            lc = pb.lifecycle_for(
                s, inputs, is_held=False, held={}, identity=ident, opp=opps.get(s), thesis=None, decision=None, now=now
            )
        except Exception:  # noqa: BLE001 — one symbol never blanks the rest
            continue
        if lc:
            out[s] = lc
    statuses = {k: (v or {}).get("status") for k, v in inputs.items() if isinstance(v, dict)}
    return out, "ok" if all(str(x).startswith("ok") for x in statuses.values() if x) else f"partial:{statuses}"


def load(
    *,
    held: set[str],
    opps: dict[str, dict[str, Any]],
    rsi: Optional[dict[str, Any]] = None,
    db_query: Optional[Callable[..., Any]] = None,
    now: Optional[datetime] = None,
    fresh: bool = False,
) -> dict[str, Any]:
    """{facts_for: fn(sym), source, status, as_of} — cached CACHE_S (the lifecycle reads are a few hundred rows)."""
    now = now or datetime.now(timezone.utc)
    if not fresh and db_query is None and _CACHE["val"] is not None and time.monotonic() - _CACHE["at"] < CACHE_S:
        cached = _CACHE["val"]
        return {
            **cached,
            "facts_for": lambda s: facts_for(
                s, held=held, last_sell=cached["_sells"], lifecycle=cached["_life"], now=now
            ),
        }
    q = db_query or _db()
    sells: dict[str, Any] = {}
    life: dict[str, dict[str, Any]] = {}
    status = "ok"
    if q is None:
        status = "unavailable:no_db"
    else:
        try:
            sells = last_sells(q)
        except Exception as e:  # noqa: BLE001
            status = f"sells_error:{type(e).__name__}"
        life, lstat = lifecycles(q, held=held, opps=opps, rsi=rsi or {}, now=now)
        if lstat != "ok":
            status = lstat if status == "ok" else f"{status};{lstat}"
    val = {
        "_sells": sells,
        "_life": life,
        "source": SOURCE_LABEL,
        "status": status,
        "as_of": now.isoformat(),
        "round_trips": len(life),
        "former_window_days": FORMER_DAYS,
    }
    if db_query is None:
        _CACHE.update(at=time.monotonic(), val=val)
    return {**val, "facts_for": lambda s: facts_for(s, held=held, last_sell=sells, lifecycle=life, now=now)}


def public(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in meta.items() if not k.startswith("_") and k != "facts_for"}
