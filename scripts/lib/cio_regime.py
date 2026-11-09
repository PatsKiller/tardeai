"""cio_regime — the deterministic "Regime" block of the CIO brief (LQ-20261107-1317).

Operator, 2026-11-08 20:23 ET: *"we need a little bit more: is the market right, is the sector right, we also
have the CPI, plus we're coming through the weekend of a crash. I would expect this updated around 6 a.m. with the
futures and around 8 a.m. with pre-market. I shouldn't have to tell you — this should be native to the system."*

The brief could say the risk tier and the holdings; it could not say the four things that question asks, and it
read neither futures nor pre-market at all. This module assembles one block of six sections, each from a store that
already exists on this host:

* ``market``    - the Market Risk Engine's tier and score, plus its breadth category (``market_risk/latest.json``).
* ``sector``    - which sectors the selloff is in, and the leaders / laggards by 20-day relative strength
                  (the same snapshot's ``sectors`` block; never recomputed here).
* ``macro``     - the buy gate from ``lib.cio_buys_gate`` (LQ-1311): CPI/PPI/FOMC inside the horizon, and what it
                  means for new buys. Reused, not re-derived.
* ``event``     - the open market-event episode: when the selloff started, its baseline close, the sectors it named,
                  and which session this is relative to it (``market_event_episodes``).
* ``futures``   - /ES, /NQ, /RTY as a percent against a dated settle, with the print's own as-of time
                  (``market_quotes_extended``, feed ``schwab``).
* ``premarket`` - how the held names are moving outside the regular session (``market_quotes_extended``).

**Every field carries its own ``as_of`` and ``source_ids``, and a missing input is stated as missing.** There is no
fallback that fills a gap with a plausible number: a futures print with no dated settle reports its level and says
the percent was not measured; a sector block with no ``sectors`` payload says so rather than showing an empty list;
a held name the off-hours lane never quoted is NAMED in ``missing``. The same law as ``lib.market_brief_inputs``.

Deterministic only: no model writes any of it, nothing is scored, nothing is ordered, sized or placed. Advisory
context for an operator surface — MBI_BEHAVIOR = 0.

Hermetic: the module reads nothing by itself. The caller passes the market-risk snapshot it already loaded and a
``db_query(sql, params) -> rows | None`` reader (``None`` = the read failed; ``[]`` = read fine, no rows). No
network, no scheduler, no DB handle of its own.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from lib.cio_buys_gate import buys_block

SCHEMA = "CioRegime@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
ET = ZoneInfo("America/New_York")

DbQuery = Callable[..., Any]

#: The futures the operator named. The store also carries /YM; it is not asked for here, so it is not shown.
FUTURES_ROOTS: tuple[str, ...] = ("/ES", "/NQ", "/RTY")
DEFAULT_FEED = "schwab"
#: How far back a stored print may be and still describe "now". Wide enough for a Monday pre-open read of the
#: Sunday-night session, narrow enough that last week's print is never presented as this morning's.
FUTURES_LOOKBACK_DAYS = 5
PREMARKET_LOOKBACK_HOURS = 60
#: Extended sessions that are a pre-open read. ``futures_open`` is futures only and never a held-name mover.
PREMARKET_SESSIONS = ("premarket", "overnight", "afterhours")
#: Leaders / laggards shown per side.
SECTOR_SIDE = 3
#: The lane's own ticker test (config/market_risk_offhours_quotes.yaml): a settlement id or a fund code stored in the
#: holdings document is not a ticker and must not appear as "a held name never quoted".
TICKER_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def reader(conn: Any) -> DbQuery:
    """A ``db_query`` over an already-open connection. SELECT only; the caller owns the transaction.

    Kept here rather than in the lane so the one shape every section reads through is defined once, and so a lane
    can hand in a stub instead (every test does).
    """
    def _query(sql: str, params: Any = None) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    return _query


def _rows(db_query: Optional[DbQuery], sql: str, params: Any = None) -> Optional[list[dict[str, Any]]]:
    """``None`` = the read failed; ``[]`` = read fine, nothing there. The two are never conflated."""
    if db_query is None:
        return None
    # nosemgrep: tq-py-broad-except-returns-default -- None is the explicit unknown here, never a default
    try:
        got = db_query(sql, params)
    except Exception:  # noqa: BLE001 — a failed read is "missing", never an empty section
        return None
    if got is None:
        return None
    return [dict(x) for x in got]


def _block(*, as_of: Any, state: str, source_ids: Sequence[str], missing: Optional[Sequence[str]] = None,
           line: Optional[str] = None, **fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema": f"{SCHEMA}#section",
        "state": state,
        "as_of": _iso(as_of),
        "line": line,
        "source_ids": [s for s in source_ids if s],
        "missing": list(missing or []),
    }
    out.update(fields)
    return out


# ── market ────────────────────────────────────────────────────────────────────────────────────────


def market_block(market_risk: Optional[Mapping[str, Any]], as_of: datetime) -> dict[str, Any]:
    """The risk tier, its score and the breadth category — nothing inferred from them."""
    mr = market_risk or {}
    tier = str(mr.get("tier") or mr.get("market_tier") or "").upper() or None
    score = _num(mr.get("score"))
    breadth = mr.get("breadth") if isinstance(mr.get("breadth"), Mapping) else {}
    breadth_state = str(breadth.get("state") or "").upper() or None
    breadth_detail = breadth.get("detail")
    confirming = mr.get("confirming")
    if isinstance(confirming, Mapping):
        conf_n, conf_of = _num(confirming.get("n")), _num(confirming.get("of"))
    elif _num(confirming) is not None:
        conf_n, conf_of = _num(confirming), None
    else:
        conf_n, conf_of = None, None

    missing: list[str] = []
    if not mr:
        missing.append("no market-risk read on file")
    if mr and not tier:
        missing.append("market-risk read has no tier")
    if not breadth_state:
        missing.append("breadth not measured")

    bits: list[str] = []
    if tier:
        bits.append(f"{tier}" + (f" (score {score:.1f})" if score is not None else ""))
    else:
        bits.append("risk tier not measured")
    bits.append(f"breadth {breadth_state.lower()}" if breadth_state else "breadth not measured")
    if conf_n is not None:
        bits.append(f"{int(conf_n)}" + (f"/{int(conf_of)}" if conf_of else "") + " categories confirming")
    if str(mr.get("mode") or "") == "shadow":
        bits.append("SHADOW, not alerting")
    if mr.get("carried_only"):
        bits.append("carried over the closure, not alerting")

    return _block(
        as_of=mr.get("as_of") or as_of,
        state="missing" if not tier else "ok",
        source_ids=[f"market_risk:{mr.get('as_of')}" if mr.get("as_of") else "market_risk",
                    "market_risk:breadth"],
        missing=missing,
        line=" · ".join(bits),
        tier=tier,
        score=score,
        breadth={"state": breadth_state, "detail": breadth_detail, "as_of": _iso(breadth.get("as_of"))},
        confirming=(None if conf_n is None else {"n": int(conf_n), "of": None if conf_of is None else int(conf_of)}),
        mode=mr.get("mode"),
        carried_only=bool(mr.get("carried_only")),
    )


# ── sector ────────────────────────────────────────────────────────────────────────────────────────


def _side(groups: Iterable[Mapping[str, Any]], *, positive: bool) -> list[dict[str, Any]]:
    """Sector groups by 20-day relative strength. A group with no rs20 is not ranked at all.

    The SIDE is also a sign test: a sector whose rs20 is +0.2 is outperforming, so it is never a "laggard" —
    naming it one would be a wrong statement about the tape. Leaders must be up over 20 days, laggards down.
    """
    scored = [g for g in groups if _num(g.get("rs20")) is not None]
    scored = [g for g in scored if (_num(g.get("rs20")) > 0 if positive else _num(g.get("rs20")) < 0)]
    scored.sort(key=lambda g: (_num(g.get("rs20")), str(g.get("label") or "")), reverse=positive)
    return [
        {"group": g.get("key"), "label": g.get("label"), "rs20": _num(g.get("rs20")), "state": g.get("state")}
        for g in scored[:SECTOR_SIDE]
    ]


def sector_block(market_risk: Optional[Mapping[str, Any]], as_of: datetime) -> dict[str, Any]:
    """Which sectors are selling off, and the leaders / laggards by rs20 — read from the snapshot, never recomputed."""
    mr = market_risk or {}
    sec = mr.get("sectors") if isinstance(mr.get("sectors"), Mapping) else None
    shock = mr.get("shock") if isinstance(mr.get("shock"), Mapping) else {}
    if not sec:
        return _block(as_of=None, state="missing", source_ids=["market_risk:sectors"],
                      missing=["no sector block in the market-risk snapshot"],
                      line="sector read missing", selloff=[], leaders=[], laggards=[])

    groups = [g for g in (sec.get("groups") or []) if isinstance(g, Mapping)]
    sectors = [g for g in groups if str(g.get("kind") or "sector") == "sector"]
    stressed = [str(s) for s in (sec.get("stressed") or [])]
    resilient = [str(s) for s in (sec.get("resilient") or [])]
    leaders = _side(sectors, positive=True)
    laggards = _side(sectors, positive=False)

    missing: list[str] = []
    if not stressed:
        missing.append("no stressed sector named")
    if not any(_num(g.get("rs20")) is not None for g in sectors):
        missing.append("no sector rs20 on file")
    else:
        if not leaders:
            missing.append("no sector outperforming on rs20")
        if not laggards:
            missing.append("no sector underperforming on rs20")
    bits = []
    if stressed:
        bits.append("selloff in " + ", ".join(stressed))
    else:
        bits.append("no stressed sector named")
    if leaders:
        bits.append("leadership " + ", ".join(f"{x['label']} {x['rs20']:+.1f}" for x in leaders if x["label"]))
    if laggards:
        bits.append("laggards " + ", ".join(f"{x['label']} {x['rs20']:+.1f}" for x in laggards if x["label"]))
    if resilient:
        bits.append(f"{len(resilient)} of {sec.get('sectors_measured') or len(sectors)} sectors holding")

    return _block(
        as_of=sec.get("as_of") or as_of,
        state="ok" if sectors else "missing",
        source_ids=[f"market_risk:sectors:{sec.get('as_of')}" if sec.get("as_of") else "market_risk:sectors"],
        missing=missing,
        line=" · ".join(bits),
        selloff=stressed,
        leaders=leaders,
        laggards=laggards,
        resilient=resilient,
        shock={"class": shock.get("class"), "label": shock.get("label"), "headline": shock.get("headline")},
        sectors_down=sec.get("sectors_down"),
        sectors_measured=sec.get("sectors_measured"),
    )


# ── macro gate ───────────────────────────────────────────────────────────────────────────────────


def macro_block(market_risk: Optional[Mapping[str, Any]], macro: Optional[Sequence[Mapping[str, Any]]],
                as_of: datetime) -> dict[str, Any]:
    """The LQ-1311 buy gate, reused verbatim: the tier decides the posture, the calendar names the release."""
    mr = market_risk or {}
    tier = str(mr.get("tier") or mr.get("market_tier") or "").upper() or None
    events = list(macro or [])
    gate = buys_block(tier, events, as_of.astimezone(ET))
    missing = [] if events else ["no macro events in the calendar window"]
    return _block(
        as_of=as_of,
        state="ok" if events else "missing",
        source_ids=list(gate.get("source_ids") or []),
        missing=missing,
        line=gate.get("line"),
        gate=gate.get("gate"),
        until=gate.get("until"),
        until_short=gate.get("until_short"),
        events=len(events),
    )


# ── event context ───────────────────────────────────────────────────────────────────────────────


def prior_session(day: date, service: Any = None) -> date:
    """The most recent NYSE trading day strictly before ``day``."""
    if service is None:
        from lib.cio_market_session import get_session_service

        service = get_session_service()
    out = day - timedelta(days=1)
    for _ in range(14):
        if service.is_trading_day(out):
            return out
        out -= timedelta(days=1)
    return out


def sessions_between(older: date, newer: date, service: Any = None) -> int:
    """Completed trading sessions AFTER ``older`` and before ``newer``.

    The baseline is a CLOSE, so the day it closed on is not itself a completed session since it: 11-04 → 11-09 is
    11-05 and 11-06, two sessions, not three.
    """
    if service is None:
        from lib.cio_market_session import get_session_service

        service = get_session_service()
    n, day = 0, older + timedelta(days=1)
    while day < newer:
        if service.is_trading_day(day):
            n += 1
        day += timedelta(days=1)
    return n


OPEN_EPISODE_SQL = (
    "SELECT episode_id, kind, scope, state, opened_at, baseline_date, affected_sectors, last_eval, updated_at "
    "FROM market_event_episodes WHERE state <> 'CLOSED'"
)


def event_block(db_query: Optional[DbQuery], as_of: datetime, service: Any = None) -> dict[str, Any]:
    """The open market-event episode: when the selloff began and which session this is, relative to it.

    A read failure, an absent episode and an episode with no baseline date are three different statements, and the
    block says which one it is making.
    """
    got = _rows(db_query, OPEN_EPISODE_SQL)
    if got is None:
        return _block(as_of=None, state="missing", source_ids=["market_event_episodes"],
                      missing=["market_event_episodes unreadable (table missing or no reader)"],
                      line="market-event context missing", short=None)
    if not got:
        return _block(as_of=None, state="empty", source_ids=["market_event_episodes"],
                      missing=["no open market-event episode"],
                      line="no open market-event episode", short=None)
    ep = max(got, key=lambda e: str(e.get("opened_at") or e.get("updated_at") or ""))
    baseline = ep.get("baseline_date")
    try:
        base_date = date.fromisoformat(str(baseline)[:10])
    except (TypeError, ValueError):
        base_date = None
    affected = [str(s) for s in (ep.get("affected_sectors") or [])]
    last = ep.get("last_eval") if isinstance(ep.get("last_eval"), Mapping) else {}
    last_session = str(last.get("session") or "") or None

    since = sessions_between(base_date, as_of.astimezone(ET).date(), service) if base_date else None
    short = f"after the {base_date:%m-%d} selloff" if base_date else None
    bits = [f"{str(ep.get('kind') or 'selloff').replace('_', ' ')} {ep.get('state') or ''}".strip()]
    if base_date:
        bits.append(f"baseline close {base_date:%a %m-%d}")
    if since is not None:
        bits.append(f"{since} completed session(s) since")
    if last_session:
        bits.append(f"last evaluated {last_session}")
    if affected:
        bits.append("named: " + ", ".join(affected))
    missing = [] if base_date else ["episode has no baseline_date"]

    return _block(
        as_of=ep.get("updated_at") or ep.get("opened_at"),
        state="ok" if base_date else "missing",
        source_ids=[f"market_event_episodes:{ep.get('episode_id')}"],
        missing=missing,
        line=" · ".join(b for b in bits if b),
        episode_id=ep.get("episode_id"),
        kind=ep.get("kind"),
        scope=ep.get("scope"),
        state_of_episode=ep.get("state"),
        opened_at=_iso(ep.get("opened_at")),
        baseline_date=_iso(base_date),
        affected_sectors=affected,
        last_session=last_session,
        sessions_since_baseline=since,
        short=short,
    )


# ── futures ──────────────────────────────────────────────────────────────────────────────────────


FUTURES_SQL = (
    "SELECT DISTINCT ON (symbol) symbol, session, bar_end, price, reference_close, reference_date, change_pct, "
    "reference_basis FROM market_quotes_extended "
    "WHERE feed = %s AND symbol = ANY(%s) AND bar_end >= %s ORDER BY symbol, bar_end DESC"
)
#: The newest print that carried a dated settle, per symbol. Used ONLY when the newest print has none, and every
#: figure derived from it is labelled with that settle's own date.
FUTURES_REF_SQL = (
    "SELECT DISTINCT ON (symbol) symbol, reference_close, reference_date FROM market_quotes_extended "
    "WHERE feed = %s AND symbol = ANY(%s) AND reference_close IS NOT NULL AND bar_end >= %s "
    "ORDER BY symbol, bar_end DESC"
)


def futures_block(db_query: Optional[DbQuery], as_of: datetime, *, feed: str = DEFAULT_FEED,
                  service: Any = None) -> dict[str, Any]:
    """ES/NQ/RTY against a dated settle, with the print's own as-of. A percent with no settle is not measured."""
    now = as_of.astimezone(timezone.utc)
    since = (now - timedelta(days=FUTURES_LOOKBACK_DAYS)).isoformat()
    got = _rows(db_query, FUTURES_SQL, [feed, list(FUTURES_ROOTS), since])
    source = f"market_quotes_extended:{feed}"
    if got is None:
        return _block(as_of=None, state="missing", source_ids=[source],
                      missing=[f"{source} unreadable"], line="futures read missing", rows=[])
    by = {str(r.get("symbol") or "").upper(): r for r in got}
    prior = prior_session(as_of.astimezone(ET).date(), service)
    refs = {str(r.get("symbol") or "").upper(): r for r in
            (_rows(db_query, FUTURES_REF_SQL, [feed, list(FUTURES_ROOTS), since]) or [])}

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for sym in FUTURES_ROOTS:
        r = by.get(sym)
        if not r:
            missing.append(sym)
            continue
        price = _num(r.get("price"))
        bar_end = _dt(r.get("bar_end"))
        measured = _num(r.get("change_pct"))
        ref_date = _dt(r.get("reference_date"))
        ref_close = _num(r.get("reference_close"))
        stale_ref = None
        # The print's own percent counts only when its reference is the session this print moves from.
        if measured is not None and ref_date is not None and ref_date.date() >= prior:
            pass  # measured against the right settle
        elif price is not None:
            fallback = refs.get(sym) or {}
            f_close = _num(fallback.get("reference_close"))
            f_date = _dt(fallback.get("reference_date"))
            if f_close:
                measured = round((price / f_close - 1.0) * 100.0, 2)
                ref_close, ref_date, stale_ref = f_close, f_date, True
            else:
                measured = None
        else:
            measured = None
        if measured is None:
            missing.append(f"{sym} percent (no dated settle in the feed)")
        rows.append({
            "symbol": sym,
            "price": price,
            "change_pct": measured,
            "change_label": ("vs prior settle" if measured is not None and not stale_ref
                             else (f"vs the {ref_date:%m-%d} settle" if measured is not None else "not measured")),
            "reference_close": ref_close,
            "reference_date": ref_date.date().isoformat() if ref_date else None,
            "reference_stale": bool(stale_ref),
            "session": r.get("session"),
            "reference_basis": r.get("reference_basis"),
            "as_of": _iso(bar_end),
            "age_hours": round((now - bar_end.astimezone(timezone.utc)).total_seconds() / 3600.0, 1) if bar_end else None,
        })

    def _bit(row: Mapping[str, Any]) -> str:
        pct = row.get("change_pct")
        level = row.get("price")
        head = f"{row['symbol']} {level:,.2f}" if level is not None else f"{row['symbol']} not quoted"
        if pct is None:
            return f"{head} (percent not measured)"
        if row.get("reference_stale"):
            return f"{head} {pct:+.2f}% vs the {str(row.get('reference_date'))[:10]} settle (stale)"
        return f"{head} {pct:+.2f}%"

    newest = max((r["as_of"] for r in rows if r.get("as_of")), default=None)
    fresh = [r for r in rows if r.get("change_pct") is not None and not r.get("reference_stale")]
    fut_short = None
    if fresh:
        avg = sum(float(r["change_pct"]) for r in fresh) / len(fresh)
        fut_short = f"futures {'/'.join(str(r['symbol']).lstrip('/') for r in fresh)} {avg:+.2f}%"
    return _block(
        as_of=newest,
        state="ok" if rows else "empty",
        source_ids=[f"{source}:{newest}" if newest else source],
        missing=missing,
        line=" · ".join(_bit(r) for r in rows) if rows else "no futures print on file",
        rows=rows,
        prior_session=_iso(prior),
        short=fut_short,
    )


# ── pre-market held-name movers ─────────────────────────────────────────────────────────────────


PREMARKET_SQL = (
    "SELECT DISTINCT ON (symbol) symbol, session, session_date, bar_end, price, reference_close, reference_date, "
    "change_pct, reference_basis FROM market_quotes_extended "
    "WHERE feed = %s AND symbol = ANY(%s) AND session = ANY(%s) AND bar_end >= %s "
    "ORDER BY symbol, bar_end DESC"
)


def premarket_block(db_query: Optional[DbQuery], held_symbols: Iterable[str], as_of: datetime, *,
                    feed: str = DEFAULT_FEED) -> dict[str, Any]:
    """How the held names are moving outside the regular session, biggest absolute move first."""
    raw = {str(s).strip().upper() for s in held_symbols or () if str(s).strip()}
    syms = sorted(s for s in raw if TICKER_RE.match(s))
    # Named, not silently dropped: how many held rows were not ticker-shaped at all.
    not_ticker = len(raw) - len(syms)
    source = f"market_quotes_extended:{feed}"
    if not syms:
        return _block(as_of=None, state="empty", source_ids=[source], missing=["no held names to read"],
                      line="no held names", rows=[], held=0, not_ticker=not_ticker)
    since = (as_of.astimezone(timezone.utc) - timedelta(hours=PREMARKET_LOOKBACK_HOURS)).isoformat()
    got = _rows(db_query, PREMARKET_SQL, [feed, syms, list(PREMARKET_SESSIONS), since])
    if got is None:
        return _block(as_of=None, state="missing", source_ids=[source], missing=[f"{source} unreadable"],
                      line="pre-market read missing", rows=[])
    rows = []
    for r in got:
        end = _dt(r.get("bar_end"))
        rows.append({
            "symbol": str(r.get("symbol") or "").upper(),
            "price": _num(r.get("price")),
            "change_pct": _num(r.get("change_pct")),
            "session": r.get("session"),
            "reference_date": _iso(r.get("reference_date")),
            "reference_basis": r.get("reference_basis"),
            "as_of": _iso(end),
            "age_hours": round((as_of - end).total_seconds() / 3600.0, 1) if end else None,
        })
    rows.sort(key=lambda x: (-(abs(x["change_pct"]) if x["change_pct"] is not None else -1.0), x["symbol"]))
    seen = {r["symbol"] for r in rows}
    missing = [s for s in syms if s not in seen]
    moved = [r for r in rows if r["change_pct"] is not None]
    if moved:
        top = moved[0]
        line = f"{len(moved)} of {len(syms)} held names moved {top['session']}; largest {top['symbol']} {top['change_pct']:+.2f}%"
    elif rows:
        line = f"{len(rows)} of {len(syms)} held names quoted outside the session; no measured move"
    else:
        line = "no held name quoted outside the session"
    newest = max((r["as_of"] for r in rows if r.get("as_of")), default=None)
    return _block(
        as_of=newest,
        state="ok" if rows else "empty",
        source_ids=[f"{source}:{newest}" if newest else source],
        missing=missing,
        line=line,
        rows=rows,
        held=len(syms),
        not_ticker=not_ticker,
    )


# ── assembly ───────────────────────────────────────────────────────────────────────────────────


def build(*, as_of: datetime, market_risk: Optional[Mapping[str, Any]] = None,
          macro: Optional[Sequence[Mapping[str, Any]]] = None, held_symbols: Iterable[str] = (),
          db_query: Optional[DbQuery] = None, feed: str = DEFAULT_FEED, service: Any = None) -> dict[str, Any]:
    """All six sections. One failed or missing input never hides another: each section states its own state."""
    market = market_block(market_risk, as_of)
    sector = sector_block(market_risk, as_of)
    macro_gate = macro_block(market_risk, macro, as_of)
    event = event_block(db_query, as_of, service)
    futures = futures_block(db_query, as_of, feed=feed, service=service)
    premarket = premarket_block(db_query, held_symbols, as_of, feed=feed)

    source_ids: list[str] = []
    for sec in (market, sector, macro_gate, event, futures, premarket):
        for sid in sec.get("source_ids") or []:
            if sid not in source_ids:
                source_ids.append(sid)

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": as_of.isoformat(),
        "market": market,
        "sector": sector,
        "macro": macro_gate,
        "event": event,
        "futures": futures,
        "premarket": premarket,
        # The one-line posture fragment the bottom line cites (criterion 3): the event's own date, then the
        # futures percent ONLY when it was measured against a settle the block can name.
        "short": short_line(event, futures),
        "source_ids": source_ids,
        "missing": [f"{name}: {m}" for name, sec in
                    (("market", market), ("sector", sector), ("macro", macro_gate), ("event", event),
                     ("futures", futures), ("premarket", premarket))
                    for m in sec.get("missing") or []],
    }


def short_line(event: Mapping[str, Any], futures: Mapping[str, Any]) -> Optional[str]:
    """``"after the 11-04 selloff; futures +0.30%"`` — only what the sections prove. ``None`` when neither does."""
    bits: list[str] = []
    if event.get("short"):
        bits.append(str(event["short"]))
    if futures.get("short"):
        bits.append(str(futures["short"]))
    return "; ".join(bits) if bits else None
