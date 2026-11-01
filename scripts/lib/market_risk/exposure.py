"""Portfolio-exposure-aware severity (DSN-20261031-market-risk-engine §5.9).

``build_portfolio_context`` turns normalized positions, profiles, look-through, stops, earnings and recent entries
into a ``contract.PortfolioContext``: a 0-100 ``vulnerability`` with per-component points, the risk-budget breaches
(``risk_budget``), and the positions that drive it. ``proposed_uplift`` applies the config rule (market tier +
vulnerability or a budget at the uplift ratio -> at most one tier up; BLUE/NONE/GREEN never lift).

Outputs carry symbol, reason and stop distance % only — never a size, quantity, dollar amount, weight
recommendation or stop price (MBI_BEHAVIOR = 0; ``assert_no_behavior_fields`` at the boundary). Unknown is not
zero: unreadable positions give ``vulnerability=None`` with a note.

``load_inputs`` reads production through the existing readers only: ``lib.portfolio_positions.load_store``
(the position store accessor), ``symbol_profiles`` (sector/name/earnings), ``lib.last_known_stops.load_last_known``
(no broker call). Accounts are reduced to opaque keys before anything leaves this module.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable

from scripts.lib.market_risk import risk_budget as rb
from scripts.lib.market_risk.contract import PortfolioContext, assert_no_behavior_fields

TIER_ORDER = ("NONE", "BLUE", "YELLOW", "ORANGE", "RED")
NEVER_UPLIFT = {"GREEN", "NONE", "BLUE"}


def opaque_account(label: Any) -> str:
    """Stable opaque key for an account label (labels never leave this module)."""
    return "acct-" + hashlib.sha256(str(label or "").encode("utf-8")).hexdigest()[:8]


def _scale(value: float | None, full_at: float, max_points: float, starts_at: float = 0.0) -> float:
    if value is None or full_at <= starts_at:
        return 0.0
    frac = (value - starts_at) / (full_at - starts_at)
    return round(max(0.0, min(1.0, frac)) * max_points, 2)


def stop_distances(positions: list[dict[str, Any]], stops: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Per held symbol, the nearest resting stop's distance below the mark in % (input may carry raw stop
    levels; the output carries the distance only)."""
    if stops is None:
        return []
    marks = {str(p.get("symbol") or "").upper(): p.get("mark") for p in positions}
    best: dict[str, float] = {}
    for s in stops:
        sym = str(s.get("symbol") or "").upper()
        d = s.get("distance_pct")
        if d is None:
            lvl, mk = s.get("level"), marks.get(sym)
            if lvl and mk:
                d = (float(mk) - float(lvl)) / float(mk) * 100.0
        if d is None:
            continue
        best[sym] = min(best.get(sym, float("inf")), float(d))
    return [{"symbol": k, "stop_distance_pct": round(v, 2)} for k, v in sorted(best.items())]


def build_portfolio_context(
    positions: list[dict[str, Any]],
    *,
    profiles: dict[str, dict[str, Any]],
    etf_lookthrough: dict[str, dict[str, float]] | None,
    stops: list[dict[str, Any]] | None,
    earnings: dict[str, Any] | None,
    now: datetime,
    policy: dict[str, Any],
    entries: list[dict[str, Any]] | None = None,
    event_symbols: Iterable[str] | None = None,
    as_of: str | None = None,
) -> PortfolioContext:
    """``policy`` is the portfolio risk budget document (``risk_budget.load_budget``)."""
    today = now.date() if isinstance(now, datetime) else now
    total = sum(float(p.get("market_value") or 0) for p in positions)
    if not positions or total <= 0:
        return PortfolioContext(vulnerability=None, as_of=as_of, note="positions unavailable: vulnerability unknown")
    comp = (policy.get("vulnerability") or {}).get("components") or {}
    kw = dict(
        profiles=profiles,
        etf_lookthrough=etf_lookthrough,
        stops=stops,
        earnings=earnings,
        entries=entries,
        event_symbols=event_symbols,
        today=today,
        budget=policy,
    )
    book = rb.measure(positions, **kw)
    breaches = rb.breaches(book, rb.limits_for(policy, None), policy, scope="book")
    for acct in sorted({str(p.get("account_key") or "") for p in positions} - {""}):
        scoped = [p for p in positions if p.get("account_key") == acct]
        share = sum(float(p.get("market_value") or 0) for p in scoped) / total
        for b in rb.breaches(rb.measure(scoped, **kw), rb.limits_for(policy, acct), policy, scope=acct):
            # an account's breach matters to the book in proportion to the account's share of it (review #2383, N1)
            breaches.append({**b, "book_share": round(share, 4)})

    # --- components -------------------------------------------------------------------------------------------
    points: dict[str, float] = {}
    lim = rb.limits_for(policy, None)
    ratios = [
        (book["actual"].get(m) or 0) / lim[k]
        for m, k in (
            ("single_sector_pct", "max_single_sector_pct"),
            ("growth_style_pct", "max_growth_style_pct"),
            ("ai_basket_pct", "max_ai_basket_pct"),
        )
        if lim.get(k)
    ]
    c = comp.get("concentration") or {}
    points["concentration"] = _scale(
        max(ratios or [0.0]),
        float(c.get("full_at_ratio", 2.0)),
        float(c.get("max_points", 25)),
        float(c.get("starts_at_ratio", 0.5)),
    )
    c = comp.get("earnings") or {}
    earn_pct = None
    if earnings is not None:
        earn_pct = rb.measure(positions, **{**kw, "sessions_48h": int(c.get("sessions", 5))})["actual"].get(
            "earnings_exposure_48h_pct"
        )
    points["earnings"] = _scale(earn_pct, float(c.get("full_at_pct", 25)), float(c.get("max_points", 20)))
    c = comp.get("stop_proximity") or {}
    dists = stop_distances(positions, stops)
    near = {d["symbol"] for d in dists if d["stop_distance_pct"] <= float(c.get("near_pct", 6.0))}
    near_pct = (
        (
            100.0
            * sum(float(p.get("market_value") or 0) for p in positions if str(p.get("symbol") or "").upper() in near)
            / total
        )
        if stops is not None
        else None
    )
    points["stop_proximity"] = _scale(near_pct, float(c.get("full_at_pct", 50)), float(c.get("max_points", 20)))
    c = comp.get("unprotected") or {}
    points["unprotected"] = _scale(
        book["actual"].get("unprotected_pct"), float(c.get("full_at_pct", 20)), float(c.get("max_points", 15))
    )
    c = comp.get("recent_event_entry") or {}
    points["recent_event_entry"] = _scale(
        book["actual"].get("recent_entry_in_event_window_pct"),
        float(c.get("full_at_pct", 10)),
        float(c.get("max_points", 20)),
    )
    vulnerability = round(min(100.0, sum(points.values())), 1)

    # --- drivers: symbol + reason + stop distance only -------------------------------------------------------
    dist_by = {d["symbol"]: d["stop_distance_pct"] for d in dists}
    reasons: dict[str, list[str]] = {}
    for m, syms in book["drivers"].items():
        if (book["actual"].get(m) or 0) <= 0 or m in ("single_sector_pct", "single_theme_pct"):
            continue
        for s in syms:
            reasons.setdefault(s, []).append(m.replace("_pct", "").replace("_", " "))
    for s in near:
        reasons.setdefault(s, []).append("stop near")
    drivers = tuple(
        {
            "symbol": s,
            "reason": ", ".join(sorted(set(r))),
            **({"stop_distance_pct": dist_by[s]} if s in dist_by else {}),
        }
        for s, r in sorted(reasons.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )[:8]
    notes = ["components: " + ", ".join(f"{k} {v:g}" for k, v in points.items())]
    if etf_lookthrough is None:
        notes.append("ETF look-through UNKNOWN (etf_holdings_snapshot not built)")
    if stops is None:
        notes.append("stops unknown")
    if earnings is None:
        notes.append("earnings calendar unknown")
    ctx = PortfolioContext(
        vulnerability=vulnerability,
        budget_breaches=tuple(breaches),
        drivers=drivers,
        as_of=as_of or now.isoformat(),
        note="; ".join(notes),
    )
    assert_no_behavior_fields({"budget_breaches": list(ctx.budget_breaches), "drivers": list(ctx.drivers)})
    return ctx


def proposed_uplift(market_tier: str, ctx: PortfolioContext | None, policy: dict[str, Any]) -> dict[str, Any] | None:
    """At most one tier up. Rule 1: config ``uplift.rules`` (market tier + vulnerability). Rule 2: any budget at
    the uplift ratio. BLUE/NONE/GREEN never lift; unknown vulnerability never lifts by rule 1."""
    if ctx is None or market_tier in NEVER_UPLIFT or market_tier not in TIER_ORDER:
        return None
    if market_tier == "RED":
        return None
    nxt = TIER_ORDER[TIER_ORDER.index(market_tier) + 1]
    for r in (policy.get("uplift") or {}).get("rules") or []:
        if (
            r.get("market_tier") == market_tier
            and ctx.vulnerability is not None
            and ctx.vulnerability >= float(r.get("min_vulnerability", 101))
        ):
            return {
                "from": market_tier,
                "to": r.get("to", nxt),
                "reason": "vulnerability",
                "vulnerability": ctx.vulnerability,
                "rule_min": float(r["min_vulnerability"]),
            }
    hits = [b for b in ctx.budget_breaches if b.get("level") == "UPLIFT"]
    if hits:
        return {
            "from": market_tier,
            "to": nxt,
            "reason": "budget",
            "budgets": [f"{b['budget']} {b['actual']}% vs {b['limit']}%" for b in hits[:3]],
        }
    return None


# --- production readers (no broker call, no new store) ------------------------------------------------------


def _default_store_loader() -> dict[str, Any]:
    from lib import portfolio_positions as pp  # type: ignore

    return pp.load_store()


def _default_stops_loader(now: datetime) -> list[dict[str, Any]]:
    from lib import last_known_stops as lks  # type: ignore

    rows = lks.load_last_known(brokers=("schwab",), now=now)
    return [{"symbol": r.get("symbol"), "level": r.get("stop_price"), "account": r.get("account")} for r in rows]


def _default_profiles_loader(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    from db_adapter import _get_conn  # type: ignore

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'symbol_profiles'")
    have = {r[0] for r in cur.fetchall()}
    cols = [c for c in ("sector", "description_1s", "earnings_date", "instrument_type") if c in have]
    cur.execute(
        f"SELECT DISTINCT ON (upper(symbol)) upper(symbol), {', '.join(cols)} FROM symbol_profiles "
        "WHERE upper(symbol) = ANY(%s) ORDER BY upper(symbol), updated_at DESC NULLS LAST",
        (symbols,),
    )
    profiles, earnings = {}, {}
    for row in cur.fetchall():
        rec = dict(zip(cols, row[1:]))
        profiles[row[0]] = {"sector": rec.get("sector"), "description": rec.get("description_1s")}
        if rec.get("earnings_date"):
            earnings[row[0]] = rec["earnings_date"]
    return profiles, (earnings if "earnings_date" in have else None)


def load_inputs(
    *,
    now: datetime | None = None,
    store_loader: Callable[[], dict[str, Any]] | None = None,
    stops_loader: Callable[[datetime], list[dict[str, Any]]] | None = None,
    profiles_loader: Callable[[list[str]], tuple[dict, Any]] | None = None,
) -> dict[str, Any]:
    """Normalized inputs for ``build_portfolio_context``. Each failed reader becomes ``None`` plus a note
    (unknown, not zero); a failed position read makes ``available`` False."""
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []
    try:
        doc = (store_loader or _default_store_loader)() or {}
    except Exception as exc:  # noqa: BLE001 — reader failure is reported as unknown, never raised into scoring
        doc = {}
        notes.append(f"position store unreadable: {type(exc).__name__}")
    holdings = [h for h in doc.get("holdings") or [] if isinstance(h, dict) and h.get("symbol")]
    if not holdings:
        notes.append("position store empty or unreadable")
        return {"available": False, "note": "; ".join(notes), "as_of": doc.get("as_of")}
    positions = []
    for h in holdings:
        mv = h.get("market_value")
        try:
            mv = float(mv)
        except (TypeError, ValueError):
            continue
        sh = h.get("shares") or h.get("quantity")
        mark = h.get("canonical_mark") or h.get("price")
        positions.append(
            {
                "symbol": str(h["symbol"]).upper(),
                "account_key": opaque_account(h.get("account")),
                "market_value": mv,
                "is_cash": bool(h.get("is_cash")),
                "mark": float(mark) if mark else (mv / float(sh) if sh else None),
            }
        )
    syms = sorted({p["symbol"] for p in positions})
    profiles, earnings = {}, None
    try:
        profiles, earnings = (profiles_loader or _default_profiles_loader)(syms)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"symbol_profiles unreadable: {type(exc).__name__}")
    stops = None
    try:
        raw = (stops_loader or _default_stops_loader)(now)
        stops = [{"symbol": s.get("symbol"), "level": s.get("level")} for s in raw]
    except Exception as exc:  # noqa: BLE001
        notes.append(f"last-known stops unreadable: {type(exc).__name__}")
    return {
        "available": True,
        "positions": positions,
        "profiles": profiles,
        "earnings": earnings,
        "stops": stops,
        "etf_lookthrough": None,
        "entries": None,
        "note": "; ".join(notes),
        "as_of": doc.get("as_of") or doc.get("updated_at"),
    }


def context_from_production(
    *,
    now: datetime | None = None,
    budget: dict[str, Any] | None = None,
    event_symbols: Iterable[str] | None = None,
    **loaders: Any,
) -> PortfolioContext:
    now = now or datetime.now(timezone.utc)
    inp = load_inputs(now=now, **loaders)
    if not inp.get("available"):
        return PortfolioContext(
            vulnerability=None, as_of=inp.get("as_of"), note=f"vulnerability unknown: {inp.get('note')}"
        )
    ctx = build_portfolio_context(
        inp["positions"],
        profiles=inp["profiles"],
        etf_lookthrough=inp["etf_lookthrough"],
        stops=inp["stops"],
        earnings=inp["earnings"],
        now=now,
        policy=budget or rb.load_budget(),
        entries=inp["entries"],
        event_symbols=event_symbols,
        as_of=str(inp.get("as_of") or now.isoformat()),
    )
    if inp.get("note"):
        return PortfolioContext(
            vulnerability=ctx.vulnerability,
            budget_breaches=ctx.budget_breaches,
            drivers=ctx.drivers,
            as_of=ctx.as_of,
            note=f"{ctx.note}; {inp['note']}",
        )
    return ctx
