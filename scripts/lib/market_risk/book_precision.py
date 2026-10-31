"""Live-only precision for the operator's book: look-through exposure, per-position CIO stances, protection playbooks,
book clusters and the heat-map exposure column (precision PR).

Runs only in the live evaluator (``portfolio`` context present), never in backtests or fixtures. Reads the existing
read-only position, stop and profile readers (``exposure.load_inputs``), the ``etf_holdings_snapshot`` store when it
exists, and the latest inverse-hedge stoplight state. Writes nothing. Real symbols live only in the snapshot (the
persistent-state runtime file), never in the repo. Account labels are reduced to an account TYPE (ira / taxable) in
memory for the wash-sale note and dropped.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import lookthrough as lt
from scripts.lib.market_risk import position_stances as ps
from scripts.lib.market_risk import protection_playbook as pp
from scripts.lib.market_risk import sectors as sec


def _account_type(label: Any) -> str:
    s = str(label or "").lower()
    return "ira" if ("ira" in s or "roth" in s or "rollover" in s or "401" in s) else "taxable"


def _reader_bars(reader: Any, sym: str, n: int, end: datetime) -> list[dict[str, Any]]:
    try:
        return list(reader.daily_bars([sym], sessions=n, end=end) or [])
    except Exception:  # noqa: BLE001 — missing bars are an honest unknown in the playbook
        return []


def _sma_above(reader: Any, sym: str, n: int, end: datetime) -> bool | None:
    rows = [r for r in _reader_bars(reader, sym, n + 5, end) if r.get("close") is not None]
    if len(rows) < n:
        return None
    closes = [float(r["close"]) for r in rows]
    return closes[-1] >= sum(closes[-n:]) / n


def read_only(conn_factory: Any) -> Any:
    """A connection made read-only before its first statement (M4). Same rule as ``PgReader._cur``: psycopg2
    ``set_session(readonly=True)`` or psycopg 3 ``read_only``; a connection exposing neither is refused."""
    conn = conn_factory()
    if hasattr(conn, "set_session"):
        conn.set_session(readonly=True)
    elif hasattr(conn, "read_only"):
        conn.read_only = True
    else:
        conn.close()
        raise RuntimeError("market_risk book precision: connection cannot be made read-only; refusing to use it")
    return conn


def _hedge_state(conn_factory: Any, instrument: str) -> dict[str, Any] | None:
    try:
        conn = read_only(conn_factory)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT light, new_state, created_at FROM inverse_stoplight_transitions WHERE instrument=%s "
                "ORDER BY created_at DESC LIMIT 1",
                (instrument,),
            )
            r = cur.fetchone()
        conn.close()
        return None if not r else {"symbol": instrument, "light": r[0], "state": r[1], "as_of": str(r[2])}
    except Exception as exc:  # noqa: BLE001
        return {"symbol": instrument, "state": "UNKNOWN", "reason": type(exc).__name__}


def _iso_date(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _last_completed_session(now: datetime) -> date:
    from scripts.lib.market_risk import sessions as ss

    local = now.astimezone(ss.ET)
    d = local.date()
    if not (ss.is_trading_day(d) and local.time() >= ss.close_time(d)):
        d -= timedelta(days=1)
        while not ss.is_trading_day(d):
            d -= timedelta(days=1)
    return d


def _sessions_between(a: date, b: date) -> int:
    """Trading sessions after ``a`` up to and including ``b`` (0 when a >= b)."""
    from scripts.lib.market_risk import sessions as ss

    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        n += ss.is_trading_day(d)
    return n


def book_staleness(book: dict[str, Any], now: datetime, policy: dict[str, Any]) -> str | None:
    """Reason the holdings are too old to stance on, or None (M1). STATED RULE: the holdings' ``data_as_of`` may lag
    the last completed session by at most ``positions.holdings_max_sessions_behind`` sessions (default 1: the
    holdings publish after the close, so the evening run may still read the previous session's book)."""
    limit = int((policy.get("positions") or {}).get("holdings_max_sessions_behind", 1))
    d = _iso_date(book.get("data_as_of"))
    if d is None:
        return "holdings data_as_of missing: stances unknown until the book is republished"
    behind = _sessions_between(d, _last_completed_session(now))
    if behind > limit:
        return (
            f"holdings stale: data as of {d.isoformat()}, {behind} sessions behind the last close "
            f"(limit {limit}); stances unknown until the book is republished"
        )
    return None


def _earnings_dates(conn_factory: Any, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """{SYMBOL: {next_earnings_date, last_earnings_date}} from ``symbol_profiles`` (read-only; M2). The profile loader in
    ``exposure.load_inputs`` reads an ``earnings_date`` column that ``symbol_profiles`` does not have."""
    if not symbols or conn_factory is None:
        return {}
    conn = read_only(conn_factory)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ON (upper(symbol)) upper(symbol), next_earnings_date, last_earnings_date "
                "FROM symbol_profiles WHERE upper(symbol) = ANY(%s) ORDER BY upper(symbol), updated_at DESC NULLS LAST",
                (sorted({s.upper() for s in symbols}),),
            )
            return {str(r[0]).upper(): {"next_earnings_date": r[1], "last_earnings_date": r[2]} for r in cur.fetchall()}
    finally:
        conn.close()


def reporting_soon(earnings: Any, now: datetime, window_sessions: int) -> set[str]:
    """Symbols whose next earnings fall within ``window_sessions`` trading sessions of ``now``. Accepts the dict shape
    ``load_inputs`` returns ({SYMBOL: date}) and the profile shape ({SYMBOL: {next_earnings_date, ...}}) (M2)."""
    out: set[str] = set()
    if not isinstance(earnings, dict):
        return out
    today = now.date()
    for sym, v in earnings.items():
        d = _iso_date(v.get("next_earnings_date") if isinstance(v, dict) else v)
        if d is not None and d >= today and _sessions_between(today, d) <= window_sessions:
            out.add(str(sym).upper())
    return out


def _parse_ts(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def after_hours_moves(reader: Any, symbols: list[str], now: datetime) -> dict[str, float]:
    """B2: extended-session move per symbol, knowable at ``now``: the latest quote stamped after the last regular close
    and at or before ``now`` (``as_of <= now``), against that session's regular close from the daily bars. Empty
    during the regular session (there is no after-hours move to read) and when nothing printed after the close."""
    from scripts.lib.market_risk import sessions as ss

    if not symbols or not hasattr(reader, "quotes"):
        return {}
    local = now.astimezone(ss.ET)
    today = local.date()
    if ss.is_trading_day(today) and (9, 30) <= (local.hour, local.minute) and local.time() < ss.close_time(today):
        return {}
    d = _last_completed_session(now)
    close_at = datetime.combine(d, ss.close_time(d), ss.ET)
    try:
        rows = reader.quotes(symbols, start=close_at, end=now) or []
        bars = reader.daily_bars(symbols, sessions=1, end=now) or []
    except Exception:  # noqa: BLE001 — no extended quotes is an honest unknown, never a crash
        return {}
    closes = {
        str(b["symbol"]).upper(): float(b["close"]) for b in bars if b.get("close") and b.get("date") == d.isoformat()
    }
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        ts = _parse_ts(r.get("as_of"))
        sess = str(r.get("session") or "").lower()
        if ts is None or ts <= close_at or ts > now or sess == "regular" or r.get("price") is None:
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym not in latest or ts > _parse_ts(latest[sym]["as_of"]):
            latest[sym] = r
    return {s: round((float(r["price"]) / closes[s] - 1.0) * 100.0, 4) for s, r in latest.items() if closes.get(s)}


SESSION_HISTORY_MAX = 20


def compact_sectors(block: dict[str, Any] | None) -> dict[str, Any]:
    """The part of a sectors block the multi-session conditions read: group key/label/state (B3)."""
    groups = [
        {"key": g.get("key"), "label": g.get("label"), "state": g.get("state")}
        for g in (block or {}).get("groups") or []
        if isinstance(g, dict)
    ]
    return {"groups": groups}


def session_history(prior: dict | None, *, now: datetime, tier: Any, sectors_block: dict | None) -> list[dict]:
    """B3: per-session ``{session, tier, sectors}`` history, newest last, carried in the assessment (``prior`` is the
    previous assessment). A session is recorded only once its close has passed (``sessions.completed_session``): an
    evaluation after the close upserts that session (the latest post-close evaluation wins); pre-market, intraday,
    weekend and holiday evaluations add nothing, so "N sessions" counts N recovered CLOSES."""
    from scripts.lib.market_risk import sessions as ss

    hist = [h for h in ((prior or {}).get("session_history") or []) if isinstance(h, dict) and h.get("session")]
    done = ss.completed_session(now)
    if done:
        entry = {"session": done, "tier": str(tier), "sectors": compact_sectors(sectors_block)}
        hist = [h for h in hist if h["session"] != entry["session"]] + [entry]
        hist.sort(key=lambda h: h["session"])
    return hist[-SESSION_HISTORY_MAX:]


HOLDINGS_STORE_ID = "portfolio.holdings.current"  # data/portfolios/state/holdings.json — the file Home reads


def current_book(policy: dict[str, Any], *, doc: dict | None = None, path: Any = None) -> dict[str, Any]:
    """The CURRENT holdings (canonical store ``portfolio.holdings.current``, the same holdings.json Home reads), split
    into material positions and residuals, with closed_today excluded. Freshness is ``data_as_of`` /
    ``aggregate_published_at`` — the top-level ``as_of`` of that file is a stale legacy field and is never used."""
    src = None
    if doc is None:
        from scripts.lib import canonical_store_registry as reg

        res = reg.resolve_store(HOLDINGS_STORE_ID)
        src = str(res.get("path"))
        import json as _json

        doc = _json.loads(open(res["path"], encoding="utf-8").read())
    cfg = (policy.get("positions") or {}).get("materiality") or {}
    min_shares = float(cfg.get("min_shares", 1.0))
    min_mv = float(cfg.get("min_market_value", 1000.0))
    min_w = float(cfg.get("min_book_weight", 0.001))
    holdings = [
        h for h in doc.get("holdings") or [] if isinstance(h, dict) and h.get("symbol") and not h.get("is_cash")
    ]
    total = sum(float(h.get("market_value") or 0) for h in holdings) or 0.0
    closed = {
        (str(acct), str(r.get("symbol")).upper())
        for acct, rows in (doc.get("closed_today") or {}).items()
        for r in (rows or [])
        if isinstance(r, dict)
    }
    material, residuals, excluded_closed = [], [], []
    for h in holdings:
        sym = str(h["symbol"]).upper()
        sh = float(h.get("shares") or h.get("quantity") or 0)
        mv = float(h.get("market_value") or 0)
        if (str(h.get("account")), sym) in closed and sh < min_shares:
            excluded_closed.append(sym)
            continue
        if sh < min_shares or mv < min_mv or (total and mv / total < min_w):
            residuals.append(sym)
            continue
        material.append(
            {
                "symbol": sym,
                "account_type": _account_type(h.get("account")),
                "shares": sh,
                # canonical_mark (reconciled) or price; never the legacy current_price (stale on 22/27 holdings,
                # 2026-10-05 price-truth incident)
                "mark": float(h.get("canonical_mark") or h.get("price") or 0) or None,
            }
        )
    return {
        "source": src or "injected",
        "data_as_of": doc.get("data_as_of"),
        "published_at": doc.get("aggregate_published_at"),
        "material": material,
        "residuals": sorted(set(residuals)),
        "closed_today_excluded": sorted(set(excluded_closed)),
    }


def _ro_profiles_loader(conn_factory: Any) -> Any:
    """``exposure.load_inputs`` profile loader over a read-only connection (M4); same columns as the default."""

    def load(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], Any]:
        conn = read_only(conn_factory)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT ON (upper(symbol)) upper(symbol), sector, description_1s FROM symbol_profiles "
                    "WHERE upper(symbol) = ANY(%s) ORDER BY upper(symbol), updated_at DESC NULLS LAST",
                    (symbols,),
                )
                profiles = {r[0]: {"sector": r[1], "description": r[2]} for r in cur.fetchall()}
        finally:
            conn.close()
        return profiles, None

    return load


def _unknown_stances(syms: list[str], reason: str, as_of: Any) -> dict[str, dict[str, Any]]:
    out = {}
    for s in syms:
        rec = {
            "symbol": s,
            "stance": "UNKNOWN",
            "label": "unknown",
            "reasons": [reason],
            "since": as_of,
            "exposure_to_stressed": None,
            "re_enter_if": [],
            "flagged_groups": [],
            "reentered_tier": None,
            "as_of": as_of,
        }
        c.assert_no_behavior_fields(rec)
        out[s] = rec
    return out


def attach(
    a: Any,
    *,
    now: datetime,
    reader: Any,
    policy: dict[str, Any],
    prior: dict | None,
    loaders: dict | None = None,
    conn_factory: Any = None,
) -> dict[str, Any]:
    from scripts.lib.market_risk import exposure

    loaders = dict(loaders or {})
    book_doc = loaders.pop("book_doc", None)
    earnings_loader = loaders.pop("earnings_loader", None)
    if conn_factory is not None and "profiles_loader" not in loaders:
        loaders["profiles_loader"] = _ro_profiles_loader(conn_factory)
    doc = a.to_dict()
    block = doc.get("sectors") or {}
    hist = getattr(a, "session_history", None) or session_history(
        prior, now=now, tier=doc.get("tier"), sectors_block=block
    )
    a.session_history = hist
    inp = exposure.load_inputs(now=now, **loaders)
    if not inp.get("available"):
        a.positions = {"_note": f"book unavailable: {inp.get('note')}"}
        return {"available": False}
    book = current_book(policy, doc=book_doc)
    syms = sorted({p["symbol"] for p in book["material"]})
    book_meta = {
        "source": book["source"],
        "data_as_of": book["data_as_of"],
        "published_at": book["published_at"],
        "residuals_ignored": len(book["residuals"]),
        "closed_today_excluded": book["closed_today_excluded"],
    }
    stale = book_staleness(book, now, policy)
    if stale:
        a.positions = {**_unknown_stances(syms, stale, doc.get("as_of")), "_book": {**book_meta, "stale": stale}}
        c.assert_no_behavior_fields(a.positions)
        return {"available": False, "stale": stale}
    material = set(syms)
    pos = [p for p in inp["positions"] if not p.get("is_cash") and p["symbol"] in material]
    marks = {p["symbol"]: p.get("mark") for p in book["material"]}
    types: dict[str, set[str]] = {}
    for p in book["material"]:
        types.setdefault(p["symbol"], set()).add(p["account_type"])
    for p in pos:
        if not marks.get(p["symbol"]):
            marks[p["symbol"]] = p.get("mark")
    stops = {str(s.get("symbol")).upper(): s.get("level") for s in inp.get("stops") or [] if s.get("level")}
    dist = {s: (marks[s] / float(stops[s]) - 1.0) * 100.0 for s in syms if s in stops and marks.get(s)}
    holdings: dict[str, list[dict[str, Any]]] = {}
    if hasattr(reader, "etf_holdings"):
        try:
            for r in reader.etf_holdings(syms, end=now) or []:
                holdings.setdefault(str(r["etf"]).upper(), []).append(r)
        except Exception:  # noqa: BLE001
            holdings = {}
    held_through = sorted({str(h.get("holding") or "").upper() for hs in holdings.values() for h in hs} - {""})
    basket = list((policy.get("ai_concentration") or {}).get("basket") or [])
    cfg = policy.get("positions") or {}
    try:
        earn = (earnings_loader or (lambda s: _earnings_dates(conn_factory, s)))(sorted(set(syms) | set(held_through)))
    except Exception:  # noqa: BLE001 — an unreadable calendar is no reporting flag, never a crash
        earn = {}
    if isinstance(inp.get("earnings"), dict):
        earn = {**{k: v for k, v in inp["earnings"].items()}, **earn}
    report = reporting_soon(earn, now, int(cfg.get("reporting_window_sessions", 5)))
    expo = {
        s: lt.exposure_for(
            s,
            ai_basket=basket,
            holdings=holdings,
            profiles=inp.get("profiles") or {},
            reporting_soon=report,
            themes=cfg.get("theme_overrides") or {},
        )
        for s in syms
    }
    prior_pos = {k: v for k, v in ((prior or {}).get("positions") or {}).items() if isinstance(v, dict)}
    reentry = ps.reentry_conditions(
        flagged_groups=sorted({g for p in prior_pos.values() for g in p.get("flagged_groups") or []}),
        sectors_block=block,
        history=hist,
        index_above_50d=_sma_above(reader, str(cfg.get("reclaim_symbol") or "QQQ"), 50, now),
        vix_below_20d=(None if (v := _sma_above(reader, "^VIX", 20, now)) is None else not v),
        engine_tier=str(doc.get("tier")),
        cfg=cfg,
    )
    # B2: the evening exit review is live — after-hours moves knowable at `now` give each position's implied open
    # (the playbook's own formula), and that implied open feeds the stance.
    ah_moves = after_hours_moves(reader, sorted(set(syms) | set(held_through)), now)
    evening: dict[str, dict[str, Any]] = {}
    for s in syms:
        imp = pp.implied_open(holdings.get(s) or [{"holding": s, "weight": 1.0}], ah_moves)
        if imp.get("known") and s in dist:
            imp["room_to_stop_pct"] = round(abs(dist[s]) + float(imp["implied_open_pct"]), 2)
            evening[s] = imp
    stances = ps.stances(
        positions=syms,
        exposures=expo,
        tier=str(doc.get("tier")),
        shock=doc.get("shock_type") or {},
        sectors_block=block,
        prior=prior_pos,
        reentry=reentry,
        stop_distance_pct=dist,
        policy=policy,
        as_of=doc.get("as_of"),
        evening_risk=evening,
    )
    rets = {}
    for s in syms:
        b = [float(r["close"]) for r in _reader_bars(reader, s, 70, now) if r.get("close")]
        rets[s] = [b[i] / b[i - 1] - 1 for i in range(1, len(b)) if b[i - 1]]
    fg = {s: stances[s]["flagged_groups"] for s in syms}
    mcorr = float((cfg.get("playbook") or {}).get("min_cluster_corr", 0.8))
    clusters = pp.book_clusters(rets, fg, mcorr)
    hedge = _hedge_state(conn_factory, "PSQ") if conn_factory else None
    flagged = [s for s in syms if stances[s]["stance"] not in ("HOLD",)]
    playbooks = {}
    for s in flagged:
        cl = [s, *pp.moves_with(s, {k: v for k, v in rets.items() if k in flagged}, {k: fg[k] for k in flagged}, mcorr)]
        try:
            playbooks[s] = pp.build(
                symbol=s,
                tier=str(doc.get("tier")),
                stance=stances[s],
                stop_distance_pct=dist.get(s),
                bars=_reader_bars(reader, s, 520, now),
                holdings=holdings.get(s),
                after_hours_moves=ah_moves,
                account_types=sorted(types.get(s, set())),
                hedge=hedge,
                cluster=cl,
                policy=policy,
                as_of=doc.get("as_of"),
            )
        except Exception as exc:  # noqa: BLE001 — a playbook failure is reported, never blocks the tier
            playbooks[s] = {"symbol": s, "error": f"{type(exc).__name__}: {exc}"}
    for s, rec in stances.items():
        rec["look_through"] = {k: expo[s].get(k) for k in ("groups", "ai_share", "reporting", "basis", "note")}
        if s in playbooks:
            rec["playbook"] = playbooks[s]
    a.positions = {**stances, "_book": book_meta}
    a.heatmap = sec.heatmap(block, lt.book_group_exposure(list(expo.values())))
    c.assert_no_behavior_fields(a.positions)
    return {"available": True, "flagged": flagged, "clusters": clusters, "hedge": hedge, "evening": sorted(evening)}


def reentry_watch_block(
    a: Any, *, now: datetime, reader: Any, policy: dict[str, Any], prior: dict | None, conn_factory: Any
) -> dict[str, Any]:
    """RE-ENTRY WATCH for every symbol exited in the last ``lookback_days`` (trade_closed, read-only), held or not."""
    from datetime import date as _date

    from scripts.lib.market_risk import reentry_watch as rw

    cfg = policy.get("reentry_watch") or {}
    doc = a.to_dict()
    exits: dict[str, dict[str, Any]] = {}
    conn = read_only(conn_factory)  # M4: read-only from the first statement
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, account, close_date, (pnl < 0) FROM trade_closed "
                "WHERE close_date >= %s::date - %s AND close_date <= %s::date ORDER BY close_date",
                (now.date(), int(cfg.get("lookback_days", 30)), now.date()),
            )
            for sym, acct, d, loss in cur.fetchall():
                e = exits.setdefault(str(sym).upper(), {"exit_date": str(d), "taxable_loss_date": None})
                e["exit_date"] = max(e["exit_date"], str(d))
                # B4: the wash-sale clock runs from the latest LOSS sale in a TAXABLE account only — a taxable gain
                # plus an IRA loss is no wash sale
                if loss and _account_type(acct) == "taxable":
                    e["taxable_loss_date"] = max(e["taxable_loss_date"] or str(d), str(d))
            syms = sorted(exits)
            earn: dict[str, Any] = {}
            profiles: dict[str, dict[str, Any]] = {}
            if syms:
                cur.execute(
                    "SELECT symbol, next_earnings_date, last_earnings_date, sector FROM symbol_profiles "
                    "WHERE symbol = ANY(%s)",
                    (syms,),
                )
                for r in cur.fetchall():
                    earn[str(r[0]).upper()] = (r[1], r[2])
                    profiles[str(r[0]).upper()] = {"sector": r[3] if len(r) > 3 else None}
    finally:
        conn.close()
    block = doc.get("sectors") or {}
    # B3: the per-session history carried in the assessment (newest last, includes this session)
    sh = getattr(a, "session_history", None) or session_history(
        prior, now=now, tier=doc.get("tier"), sectors_block=block
    )
    a.session_history = sh
    hist = [h.get("sectors") or {} for h in sh]
    label_of = {r.get("key"): r.get("label") for r in block.get("groups") or []}
    basket = list((policy.get("ai_concentration") or {}).get("basket") or [])
    themes = (policy.get("positions") or {}).get("theme_overrides") or {}
    flow = next((o for o in doc.get("observations") or [] if o.get("category") == "options_flow"), {})
    cards = {}
    for sym, e in exits.items():
        bars = [r for r in (reader.daily_bars([sym], sessions=400, end=now) or []) if r.get("close") is not None]
        closes = [float(r["close"]) for r in bars]
        dates = [str(r["date"])[:10] for r in bars]
        pre = None
        if e["exit_date"] in dates:
            k = dates.index(e["exit_date"])
            pre = closes[k - 1] if k > 0 else None
        elif dates:
            before = [cl for d, cl in zip(dates, closes) if d < e["exit_date"]]
            pre = before[-1] if before else None
        ex = lt.exposure_for(sym, ai_basket=basket, themes=themes, profiles=profiles)
        groups = ex.get("groups") or {}
        main = max(groups.items(), key=lambda kv: kv[1])[0] if groups else None
        gh = [next((g.get("state") for g in (h.get("groups") or []) if g.get("key") == main), "UNKNOWN") for h in hist]
        nxt, lst = earn.get(sym) or (None, None)
        to_e = since_e = None
        ed = None
        if nxt and (_date.fromisoformat(str(nxt)[:10]) - now.date()).days >= 0:
            ed = str(nxt)[:10]
            to_e = int((_date.fromisoformat(ed) - now.date()).days * 5 / 7)
        if lst:
            since_e = int((now.date() - _date.fromisoformat(str(lst)[:10])).days * 5 / 7)

        try:
            cards[sym] = rw.card(
                symbol=sym,
                exit_date=e["exit_date"],
                breakdown_close=pre,
                closes=closes,
                last_date=dates[-1] if dates else None,
                group_label=label_of.get(main) or main,
                group_history=gh,
                earnings_next=ed,
                earnings_last=str(lst)[:10] if lst else None,
                sessions_since_earnings=since_e,
                sessions_to_earnings=to_e,
                market_tier=str(doc.get("market_tier")),
                options_flow_state=str(flow.get("state") or "UNKNOWN"),
                taxable_loss_days_ago=(
                    (now.date() - _date.fromisoformat(e["taxable_loss_date"])).days if e["taxable_loss_date"] else None
                ),
                policy=policy,
            )
        except Exception as exc:  # noqa: BLE001 — one symbol failing is reported, the rest still render
            cards[sym] = {"symbol": sym, "error": f"{type(exc).__name__}: {exc}"}
    a.reentry_watch = cards
    return cards
