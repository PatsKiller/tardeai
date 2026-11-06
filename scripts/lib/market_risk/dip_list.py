"""Dip list with valuation: members of the stressed groups, ranked by drawdown from their 20-session high
(PKG-SELLOFF-INTEL-20261106 E).

Package text: "members of stressed groups ranked by drawdown from 20-day high, with forward P/E now vs pre-selloff ONLY
if snapshot history covers it (measure depth first; report the number of days), plus conviction score and earnings
date. Quality filter stated, not hidden."

Inputs (all read by the caller; this module is pure):

* the market-risk snapshot's ``sectors`` block: which groups are STRESS or WEAK right now;
* the CIO opportunity projection: each name's sector, industry and conviction (``rotation_advice.group_of`` maps a name
  to its groups, so membership means exactly what it means for the rotation card);
* the daily closes (``PgReader.daily_bars``: market bars, then quote closes, then ticker prices): the price, the
  20-session high and its session, the drawdown and the one-session falls;
* the Yahoo analyst history (``yahoo_analyst_targets_history``): consensus target and rating, analyst count, and in
  ``data.extended`` the EPS trend, EPS revisions and earnings dates. Its own ``current_price`` (captured about 06:10
  ET) is NOT used as a price series: it is sparse per symbol (measured 2026-11-06: some names have two records in six
  weeks), which would wrongly drop most names for too few sessions.

The Yahoo record that matches the high is the capture on the weekday after the high's session (it carries that close).

Forward P/E = price / consensus next-fiscal-year EPS (``eps_trend`` index ``+1y``). "Before the selloff" is the session
of the 20-session high. Its EPS comes, in order of preference, from (1) the symbol's own record captured for that
session (or within ``own_record_days`` before it), or (2) today's record's lookback column (7/30/60/90 days ago) nearest
the high's age, when one is within ``lookback_tolerance_days``. Otherwise there is no pre-selloff P/E and the row says
why. The history depth (days of snapshots, days with an EPS trend) is measured and reported, never assumed.

Advisory only (``MBI_BEHAVIOR = 0``): a ranked screen with its reasons. No size, weight, price level, order or stop;
``assert_no_behavior_fields`` runs on the payload and the shared sizing-text guard on the rendered text.
"""

from __future__ import annotations

import statistics as st
from datetime import date, timedelta
from typing import Any, Iterable, Optional

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk.rotation_advice import group_of

SCHEMA = "MarketRiskDipList@v1"
STRESSED_STATES = ("STRESS", "WEAK")
EPS_KEY = "+1y"
LOOKBACK_COLUMNS = {7: "7daysAgo", 30: "30daysAgo", 60: "60daysAgo", 90: "90daysAgo"}

# The quality filter. Every value is printed with the list; a name that fails it is counted under its reason.
DEFAULT_FILTER: dict[str, Any] = {
    "min_price": 5.0,  # sub-$5 names: spreads and moves too wide for a valuation read
    "min_analysts": 8,  # fewer analysts: the consensus EPS and target are one or two opinions
    "min_sessions": 10,  # price sessions in the window: fewer cannot locate a 20-session high
    "high_sessions": 20,  # the drawdown window
    "max_drawdown_pct": -5.0,  # the list starts at a 5% drawdown; shallower names are counted, not listed
    "series_break_ratio": 2.5,  # a one-session close step this large is an unadjusted split, not a move (as in F)
    "own_record_days": 4,  # an own record up to this many days before the pre-selloff session still counts
    "lookback_tolerance_days": 10,  # a lookback column (7/30/60/90d) must be this close to the high's age
}
# The narrower screen (report 75 section 3). Also stated; a screen, not a recommendation.
DEFAULT_SCREEN: dict[str, Any] = {
    "max_drawdown_pct": -12.0,
    "min_analysts": 10,
    "max_rating": 2.0,  # Yahoo recommendation mean: 1 Strong Buy ... 5 Sell; 2.0 = Buy or better
    "eps_not_cut_tolerance": 0.005,  # next-year EPS estimate not lowered by more than 0.5% over 30 days
    "earnings_clear_days": 7,  # no earnings report within 7 calendar days (about 5 sessions)
}
# A name that fell far more than its own group on one session probably had its own news.
EVENT = {"day_pct": -12.0, "vs_group_pts": -10.0, "min_group": 5}


# -- parsing ----------------------------------------------------------------------------------------------------------


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None  # NaN -> None


def _d(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def parse_record(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """One ``yahoo_analyst_targets_history`` row -> the fields this module reads. A row without a date is dropped."""
    snap = _d(row.get("snapshot_date"))
    if snap is None:
        return None
    ext = ((row.get("data") or {}).get("extended") or {}) if isinstance(row.get("data"), dict) else {}
    trend = {e.get("index"): e for e in ext.get("eps_trend") or [] if isinstance(e, dict) and e.get("index")}
    revs = {e.get("index"): e for e in ext.get("eps_revisions") or [] if isinstance(e, dict) and e.get("index")}
    upcoming = sorted(
        str(e.get("index"))[:10]
        for e in ext.get("earnings_dates") or []
        if isinstance(e, dict) and e.get("index") and e.get("Reported EPS") is None
    )
    return {
        "snapshot": snap,
        "price": _f(row.get("current_price")),
        "target": _f(row.get("target_mean_price")),
        "rating": _f(row.get("recommendation_mean")),
        "rating_key": row.get("recommendation_key"),
        "analysts": int(_f(row.get("number_of_analyst_opinions")) or 0),
        "eps_trend": trend,
        "eps_revisions": revs,
        "earnings_upcoming": upcoming,
    }


# -- measures ---------------------------------------------------------------------------------------------------------


def _eps(rec: dict[str, Any], col: str = "current") -> Optional[float]:
    return _f((rec.get("eps_trend") or {}).get(EPS_KEY, {}).get(col))


def _pe(price: Optional[float], eps: Optional[float]) -> Optional[float]:
    return round(price / eps, 1) if price and eps and eps > 0 else None


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return round(100.0 * (a / b - 1.0), 2) if a is not None and b else None


def eps_before(
    records: list[dict[str, Any]], pre_snapshot: date, now: dict[str, Any], cfg: dict[str, Any]
) -> tuple[Optional[float], str]:
    """Next-FY EPS as it stood when the high printed, and how it was found (or why it was not)."""
    own = [
        r
        for r in records
        if r["snapshot"] <= pre_snapshot
        and (pre_snapshot - r["snapshot"]).days <= int(cfg["own_record_days"])
        and _eps(r) is not None
    ]
    if own:
        r = max(own, key=lambda r: r["snapshot"])
        return _eps(r), f"own record {r['snapshot'].isoformat()}"
    age = (now["snapshot"] - pre_snapshot).days
    tol = int(cfg["lookback_tolerance_days"])
    best = min(LOOKBACK_COLUMNS, key=lambda n: (abs(n - age), n))
    if abs(best - age) <= tol:
        eps = _eps(now, LOOKBACK_COLUMNS[best])
        if eps is not None:
            return eps, f"today's record, estimate {best} days ago (high was {age} days ago)"
    return None, f"no estimate within {tol} days of the high ({age} days ago); EPS history does not reach it"


def price_break(closes: list[float], ratio: float) -> bool:
    return any(a > 0 and b > 0 and max(b / a, a / b) >= ratio for a, b in zip(closes, closes[1:]))


def stressed_groups(sectors_block: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sector and theme groups the snapshot calls STRESS or WEAK."""
    return [
        {k: g.get(k) for k in ("key", "label", "kind", "state", "r5", "rs5")}
        for g in (sectors_block or {}).get("groups") or []
        if isinstance(g, dict) and g.get("state") in STRESSED_STATES and g.get("kind") in ("sector", "theme")
    ]


def membership(candidate: dict[str, Any], groups: dict[str, Any], stressed: set[str]) -> list[str]:
    """Stressed groups a name belongs to: ``rotation_advice.group_of``, plus semis for a semiconductor industry."""
    keys = group_of(candidate, groups)
    if "semis" in groups and "semiconductor" in str(candidate.get("industry") or "").lower() and "semis" not in keys:
        keys.append("semis")
    return [k for k in keys if k in stressed]


def history_depth(records_by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """How far back the analyst history reaches: measured from the rows, never assumed."""
    snaps = sorted({r["snapshot"] for rs in records_by_symbol.values() for r in rs})
    eps = sorted({r["snapshot"] for rs in records_by_symbol.values() for r in rs if _eps(r) is not None})
    return {
        "snapshot_days": len(snaps),
        "first_snapshot": snaps[0].isoformat() if snaps else None,
        "last_snapshot": snaps[-1].isoformat() if snaps else None,
        "eps_trend_days": len(eps),
        "eps_trend_first": eps[0].isoformat() if eps else None,
        "symbols": len(records_by_symbol),
    }


# -- the list ---------------------------------------------------------------------------------------------------------


def _closes(bars: list[Any]) -> list[tuple[date, float]]:
    """(session, close), oldest first, one close per session (the first one given wins, as the reader ranks them)."""
    out: dict[date, float] = {}
    for b in bars or []:
        d, px = (_d(b.get("date")), _f(b.get("close"))) if isinstance(b, dict) else (_d(b[0]), _f(b[1]))
        if d is not None and px is not None and px > 0:
            out.setdefault(d, px)
    return sorted(out.items())


def next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d


def _row(
    sym: str,
    closes: list[tuple[date, float]],
    recs: list[dict[str, Any]],
    cand: dict[str, Any],
    groups: list[str],
    today: date,
    cfg: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    window = closes[-int(cfg["high_sessions"]) :]
    if not window:
        return None, "no daily closes"
    if not recs:
        return None, "not in the analyst history"
    recs = sorted(recs, key=lambda r: r["snapshot"])
    now = recs[-1]
    px_s, px = window[-1]
    if px < float(cfg["min_price"]):
        return None, f"price under ${cfg['min_price']:.0f}"
    if now.get("analysts", 0) < int(cfg["min_analysts"]):
        return None, f"fewer than {cfg['min_analysts']} analysts"
    if len(window) < int(cfg["min_sessions"]):
        return None, f"fewer than {cfg['min_sessions']} daily closes"
    if price_break([p for _, p in window], float(cfg["series_break_ratio"])):
        return None, "price history break (a one-session step of 2.5x or more: likely an unadjusted split)"
    hi_s, hi_px = max(window, key=lambda t: (t[1], t[0]))
    dd = _pct(px, hi_px)
    if dd is None or dd > float(cfg["max_drawdown_pct"]):
        return None, f"drawdown shallower than {cfg['max_drawdown_pct']:.0f}%"
    # the Yahoo capture that carries the high's close is the next weekday's (captured ~06:10 ET)
    cap = next_weekday(hi_s)
    near = [r for r in recs if r["snapshot"] <= cap and (cap - r["snapshot"]).days <= int(cfg["own_record_days"])]
    at_high = near[-1] if near else None
    eps_now = _eps(now)
    eps_pre, basis = eps_before(recs, cap, now, cfg)
    fpe_now, fpe_pre = _pe(px, eps_now), _pe(hi_px, eps_pre)
    eps30 = _eps(now, "30daysAgo")
    rev = (now.get("eps_revisions") or {}).get(EPS_KEY) or {}
    upcoming = [d for d in now.get("earnings_upcoming") or [] if d >= today.isoformat()]
    rets = [(window[i][0], _pct(window[i][1], window[i - 1][1]), window[i - 1][0]) for i in range(1, len(window))]
    if eps_pre is None:
        pre_missing = basis
    elif fpe_pre is None:
        pre_missing = "EPS estimate not positive"
    else:
        pre_missing = None
    return {
        "symbol": sym,
        "groups": groups,
        "sector": cand.get("sector"),
        "industry": cand.get("industry"),
        "conviction": _f(cand.get("conviction")),
        "price": px,
        "price_session": px_s.isoformat(),
        "high_20": hi_px,
        "high_session": hi_s.isoformat(),
        "drawdown_pct": dd,
        "sessions": len(window),
        "analyst_record": now["snapshot"].isoformat(),
        "fpe_now": fpe_now,
        "fpe_now_missing": None
        if fpe_now is not None
        else ("no EPS trend in the analyst record" if eps_now is None else "EPS estimate not positive"),
        "fpe_pre": fpe_pre,
        "fpe_pre_basis": basis if eps_pre is not None else None,
        "fpe_pre_missing": pre_missing,
        "fpe_change_pct": _pct(fpe_now, fpe_pre),
        "eps_next_fy": eps_now,
        "eps_next_fy_30d_change_pct": _pct(eps_now, eps30),
        "revisions_30d": {"up": _f(rev.get("upLast30days")), "down": _f(rev.get("downLast30days"))} if rev else None,
        "consensus_target": now.get("target"),
        "consensus_target_at_high": at_high.get("target") if at_high else None,
        "target_change_pct": _pct(now.get("target"), at_high.get("target")) if at_high else None,
        "upside_to_target_pct": _pct(now.get("target"), px),
        "rating": now.get("rating"),
        "rating_at_high": at_high.get("rating") if at_high else None,
        "rating_key": now.get("rating_key"),
        "analysts": now.get("analysts"),
        "next_earnings": upcoming[0] if upcoming else None,
        "_rets": rets,
    }, None


def _event_flags(rows: list[dict[str, Any]]) -> None:
    """A fall of 12%+ in one session that is 10+ points worse than the group median that session: own news, likely.

    The session calendar is the union of every listed name's close dates. A return whose previous close is more than
    one session back (a gap in that name's closes) spans several sessions: it is not a one-session fall, so it neither
    enters a group median nor raises the flag."""
    days = sorted({s for r in rows for s, _, _ in r["_rets"]} | {p for r in rows for _, _, p in r["_rets"]})
    idx = {d: i for i, d in enumerate(days)}
    one = {
        r["symbol"]: [(s, x) for s, x, prev in r["_rets"] if x is not None and idx[s] - idx[prev] == 1] for r in rows
    }
    med: dict[tuple[str, str], float] = {}
    for g in {g for r in rows for g in r["groups"]}:
        by_day: dict[str, list[float]] = {}
        for r in rows:
            if g in r["groups"]:
                for s, x in one[r["symbol"]]:
                    by_day.setdefault(s.isoformat(), []).append(x)
        for day, xs in by_day.items():
            if len(xs) >= EVENT["min_group"]:
                med[(g, day)] = st.median(xs)
    for r in rows:
        r["own_news_day"] = None
        worst = min(one[r["symbol"]], key=lambda t: t[1], default=None)
        if not worst or worst[1] > EVENT["day_pct"]:
            continue
        for g in r["groups"]:
            m = med.get((g, worst[0].isoformat()))
            if m is not None and worst[1] - m <= EVENT["vs_group_pts"]:
                r["own_news_day"] = {
                    "session": worst[0].isoformat(),
                    "pct": worst[1],
                    "group": g,
                    "group_median_pct": round(m, 2),
                }
                break


def _screen(r: dict[str, Any], scr: dict[str, Any], today: date) -> Optional[str]:
    """None when the row passes the narrower screen, else the first reason it does not."""
    if r["drawdown_pct"] > float(scr["max_drawdown_pct"]):
        return f"drawdown shallower than {scr['max_drawdown_pct']:.0f}%"
    if (r["analysts"] or 0) < int(scr["min_analysts"]):
        return f"fewer than {scr['min_analysts']} analysts"
    if r["rating"] is None or r["rating"] > float(scr["max_rating"]):
        return f"consensus rating weaker than {scr['max_rating']:.1f}"
    ch = r["eps_next_fy_30d_change_pct"]
    if ch is None:
        return "no next-year EPS trend in the analyst record"
    if ch < -100.0 * float(scr["eps_not_cut_tolerance"]):
        return "next-year EPS estimate lowered in 30 days"
    rv = r["revisions_30d"] or {}
    if (rv.get("up") or 0) < (rv.get("down") or 0):
        return "more EPS revisions down than up in 30 days"
    if r["fpe_now"] is None:
        return "no forward P/E"
    if (
        r["next_earnings"]
        and r["next_earnings"] <= (today + timedelta(days=int(scr["earnings_clear_days"]))).isoformat()
    ):
        return f"earnings within {scr['earnings_clear_days']} days"
    if r["own_news_day"]:
        return "fell far more than its group on one session (own news, likely)"
    return None


def build(
    *,
    sectors_block: Optional[dict[str, Any]],
    policy_groups: Iterable[dict[str, Any]],
    candidates: Iterable[dict[str, Any]],
    analyst_rows: Iterable[dict[str, Any]],
    bars: dict[str, list[Any]],
    today: date,
    earnings: Optional[dict[str, str]] = None,
    cfg: Optional[dict[str, Any]] = None,
    screen: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The dip list payload.

    ``bars`` is symbol -> daily closes, oldest first (``{"date", "close"}`` dicts or ``(date, close)`` pairs, as
    ``PgReader.daily_bars`` returns): price, the 20-session high, the drawdown and the one-session falls come from it.
    The Yahoo analyst rows supply only the valuation fields (EPS trend, target, rating, analysts, revisions, earnings);
    their own price is a sparse 06:10 ET capture and is not used. ``earnings`` (symbol -> ISO date) fills a missing
    earnings date only."""
    cfg = {**DEFAULT_FILTER, **(cfg or {})}
    scr = {**DEFAULT_SCREEN, **(screen or {})}
    groups = {g["key"]: g for g in policy_groups if isinstance(g, dict) and g.get("key")}
    stressed = stressed_groups(sectors_block)
    keys = {g["key"] for g in stressed}
    recs: dict[str, list[dict[str, Any]]] = {}
    for row in analyst_rows:
        rec = parse_record(row)
        if rec is not None and row.get("symbol"):
            recs.setdefault(str(row["symbol"]).upper(), []).append(rec)
    depth = history_depth(recs)
    excluded: dict[str, list[str]] = {}
    rows: list[dict[str, Any]] = []
    members = 0
    for cand in candidates:
        sym = str(cand.get("symbol") or "").upper()
        if not sym or cand.get("type") in ("etf", "ETF"):
            continue
        gs = membership(cand, groups, keys)
        if not gs:
            continue
        members += 1
        row, why = _row(sym, _closes((bars or {}).get(sym) or []), recs.get(sym, []), cand, gs, today, cfg)
        if row is None:
            excluded.setdefault(str(why), []).append(sym)
            continue
        if not row["next_earnings"] and (earnings or {}).get(sym):
            row["next_earnings"] = earnings[sym]
        rows.append(row)
    _event_flags(rows)
    latest = max((r["price_session"] for r in rows), default=None)
    for r in rows:
        r.pop("_rets", None)
    rows.sort(key=lambda r: (r["drawdown_pct"], r["symbol"]))
    shortlist, held_back = [], {}
    for r in rows:
        why = _screen(r, scr, today)
        if why is None:
            shortlist.append(r["symbol"])
        else:
            held_back.setdefault(why, []).append(r["symbol"])
    by_sym = {r["symbol"]: r for r in rows}
    shortlist.sort(key=lambda s: (-(by_sym[s]["upside_to_target_pct"] or -1e9), s))
    payload = {
        "schema": SCHEMA,
        "as_of": today.isoformat(),
        "price_basis": f"daily closes (market bars, quotes, ticker prices) through {latest or 'n/a'}; analyst fields"
        " from the Yahoo capture about 06:10 ET, which carries the prior session's close",
        "stressed_groups": stressed,
        "history": depth,
        "filter": cfg,
        "screen": scr,
        "members": members,
        "rows": rows,
        "excluded": {k: sorted(v) for k, v in sorted(excluded.items())},
        "shortlist": shortlist,
        "screen_held_back": {k: sorted(v) for k, v in sorted(held_back.items())},
        "summary": summary(rows),
    }
    c.assert_no_behavior_fields(payload)
    return payload


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Is it earnings or the multiple? Counted over the listed names, each figure with its n."""
    eps = [r["eps_next_fy_30d_change_pct"] for r in rows if r["eps_next_fy_30d_change_pct"] is not None]
    tgt = [r["target_change_pct"] for r in rows if r["target_change_pct"] is not None]
    fpe = [r["fpe_change_pct"] for r in rows if r["fpe_change_pct"] is not None and (r["fpe_pre"] or 0) < 200]
    rv = [r["revisions_30d"] for r in rows if r["revisions_30d"]]
    return {
        "listed": len(rows),
        "eps_estimate_raised": sum(1 for x in eps if x > 0.5),
        "eps_estimate_cut": sum(1 for x in eps if x < -0.5),
        "eps_estimate_n": len(eps),
        "targets_raised": sum(1 for x in tgt if x > 0.5),
        "targets_cut": sum(1 for x in tgt if x < -0.5),
        "targets_n": len(tgt),
        "revisions_up": int(sum(r.get("up") or 0 for r in rv)),
        "revisions_down": int(sum(r.get("down") or 0 for r in rv)),
        "median_fpe_change_pct": round(st.median(fpe), 1) if fpe else None,
        "fpe_pairs_n": len(fpe),
    }


# -- text -------------------------------------------------------------------------------------------------------------


def _p(x: Optional[float], nd: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{0.0:.{nd}f}%" if round(x, nd) == 0 else f"{x:+.{nd}f}%"


def _n(x: Optional[float], nd: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def line(r: dict[str, Any]) -> str:
    fpe = (
        f"fwd P/E {_n(r['fpe_pre'])} at the high -> {_n(r['fpe_now'])} now"
        if r["fpe_pre"] is not None and r["fpe_now"] is not None
        else f"fwd P/E n/a now ({r['fpe_now_missing']})"
        if r["fpe_now"] is None
        else f"fwd P/E {_n(r['fpe_now'])} now; at the high: n/a ({r['fpe_pre_missing']})"
    )
    parts = [
        f"**{r['symbol']}** {_p(r['drawdown_pct'])} from its 20-session high ({r['high_session']}), ${_n(r['price'], 2)}",
        fpe,
    ]
    if r["eps_next_fy_30d_change_pct"] is not None:
        parts.append(f"next-year EPS estimate {_p(r['eps_next_fy_30d_change_pct'])} in 30 days")
    if r["revisions_30d"]:
        parts.append(
            f"revisions 30d up {int(r['revisions_30d']['up'] or 0)} / down {int(r['revisions_30d']['down'] or 0)}"
        )
    if r["consensus_target"]:
        was = (
            f", was ${_n(r['consensus_target_at_high'], 0)} at the high"
            if r["target_change_pct"] is not None and abs(r["target_change_pct"]) >= 0.5
            else ", unchanged since the high"
            if r["target_change_pct"] is not None
            else ""
        )
        parts.append(f"target ${_n(r['consensus_target'], 0)} ({_p(r['upside_to_target_pct'], 0)} away{was})")
    if r["rating"] is not None:
        parts.append(
            f"rating {_n(r['rating'], 2)} {r['rating_key'] or ''} ({r['analysts']} analysts)".replace("  ", " ")
        )
    parts.append(f"conviction {_n(r['conviction'], 0)}")
    parts.append(f"earnings {r['next_earnings'] or 'unknown'}")
    out = "- " + "; ".join(parts)
    ev = r.get("own_news_day")
    if ev:
        out += (
            f". Fell {_p(ev['pct'], 0)} on {ev['session']} vs a {ev['group']} median of {_p(ev['group_median_pct'], 0)}:"
            " far worse than its group, likely its own news; check before reading it as a sector dip"
        )
    return out


def render(p: dict[str, Any], *, limit: int = 30) -> str:
    h, f, s = p["history"], p["filter"], p["summary"]
    L: list[str] = []
    A = L.append
    groups = ", ".join(f"{g['label']} ({g['state']})" for g in p["stressed_groups"]) or "none"
    A(f"# Dip list, {p['as_of']}")
    A("")
    A("Advisory screen, not a recommendation: no orders, sizes or stop levels.")
    A(f"Stressed groups in the market-risk snapshot: {groups}.")
    A(f"Prices: {p['price_basis']}.")
    A(
        f"Analyst history measured: {h['snapshot_days']} snapshot days ({h['first_snapshot']} to {h['last_snapshot']},"
        f" {h['symbols']} symbols); EPS-trend history {h['eps_trend_days']} days since {h['eps_trend_first'] or 'n/a'}."
        " A P/E at the high is shown only where that history reaches the high's date; otherwise the row says why."
    )
    A(
        f"Quality filter: price at least ${f['min_price']:.0f}; at least {f['min_analysts']} analysts; at least"
        f" {f['min_sessions']} daily closes in the window; no one-session step of {f['series_break_ratio']}x (split); drawdown"
        f" {f['max_drawdown_pct']:.0f}% or deeper from the {f['high_sessions']}-session high."
    )
    A("")
    if not p["stressed_groups"]:
        A("No group is STRESS or WEAK, so there is no dip list today.")
        return "\n".join(L)
    A(f"## Summary ({s['listed']} of {p['members']} group members listed)")
    A(
        f"- Next-year EPS estimates over 30 days: raised in {s['eps_estimate_raised']}, cut in {s['eps_estimate_cut']}"
        f" (n={s['eps_estimate_n']}). EPS revisions 30d: up {s['revisions_up']}, down {s['revisions_down']}."
    )
    A(
        f"- Consensus targets since each name's high: raised in {s['targets_raised']}, cut in {s['targets_cut']}"
        f" (n={s['targets_n']}). Median forward P/E change, high to now: {_p(s['median_fpe_change_pct'], 0)}"
        f" (n={s['fpe_pairs_n']})."
    )
    A("")
    A(f"## Ranked by drawdown from the 20-session high (deepest first; {min(limit, len(p['rows']))} shown)")
    for r in p["rows"][:limit]:
        A(line(r))
    A("")
    scr = p["screen"]
    A("## Narrower screen (stated; ranked by distance to the consensus target)")
    A(
        f"Down {scr['max_drawdown_pct']:.0f}% or more; at least {scr['min_analysts']} analysts; rating {scr['max_rating']:.1f}"
        " or better (1 = Strong Buy); next-year EPS estimate not lowered in 30 days; revisions up at least down;"
        f" forward P/E known; no earnings within {scr['earnings_clear_days']} days; no single-session own-news fall."
    )
    by = {r["symbol"]: r for r in p["rows"]}
    for sym in p["shortlist"][:15]:
        A(line(by[sym]))
    if not p["shortlist"]:
        A("- None pass.")
    for why, syms in p["screen_held_back"].items():
        A(f"- Held back, {why}: {', '.join(syms)}")
    A("")
    A("## Left out by the quality filter (counted, with the reason)")
    for why, syms in p["excluded"].items():
        A(f"- {why} ({len(syms)}): {', '.join(syms[:25])}{' ...' if len(syms) > 25 else ''}")
    if not p["excluded"]:
        A("- None.")
    text = "\n".join(L)
    from scripts.lib.buy_ready_cio_review import _SIZING_TEXT  # the shared sizing-text guard, used as-is

    if _SIZING_TEXT.search(text):
        raise ValueError("sizing text in the dip list")
    return text
