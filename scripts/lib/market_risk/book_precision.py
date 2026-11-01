"""Live-only precision for the operator's book: look-through exposure, per-position CIO stances, protection playbooks,
book clusters and the heat-map exposure column (precision PR).

Runs only in the live evaluator (``portfolio`` context present), never in backtests or fixtures. Reads the existing
read-only position, stop and profile readers (``exposure.load_inputs``), the ``etf_holdings_snapshot`` store when it
exists, and the latest inverse-hedge stoplight state. Writes nothing. Real symbols live only in the snapshot (the
persistent-state runtime file), never in the repo. Account labels are reduced to an account TYPE (ira / taxable) in
memory for the wash-sale note and dropped.
"""

from __future__ import annotations

import re

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


_HEDGE_FACTOR_RE = re.compile(r"\(([0-9]+(?:\.[0-9]+)?)x median\)")


def hedging_factor(observations: list[dict] | None) -> float | None:
    """The largest index put/call-vs-trailing-median factor in the options-flow observation (e.g. "QQQ P/C OI 3.97
    (3.85x median)" -> 3.85), recorded per session so the re-entry Stage 1 can tell hedging easing from its peak."""
    obs = next((o for o in observations or [] if isinstance(o, dict) and o.get("category") == "options_flow"), None)
    vals = []
    for ev in (obs or {}).get("evidence") or []:
        m = _HEDGE_FACTOR_RE.search(str((ev or {}).get("detail") or ""))
        if m:
            vals.append(float(m.group(1)))
    return max(vals) if vals else None


def session_history(
    prior: dict | None, *, now: datetime, tier: Any, sectors_block: dict | None, hedging: float | None = None
) -> list[dict]:
    """B3: per-session ``{session, tier, sectors}`` history, newest last, carried in the assessment (``prior`` is the
    previous assessment). A session is recorded only once its close has passed (``sessions.completed_session``): an
    evaluation after the close upserts that session (the latest post-close evaluation wins); pre-market, intraday,
    weekend and holiday evaluations add nothing, so "N sessions" counts N recovered CLOSES."""
    from scripts.lib.market_risk import sessions as ss

    hist = [h for h in ((prior or {}).get("session_history") or []) if isinstance(h, dict) and h.get("session")]
    done = ss.completed_session(now)
    if done:
        entry = {"session": done, "tier": str(tier), "sectors": compact_sectors(sectors_block), "hedging_factor": hedging}
        hist = [h for h in hist if h["session"] != entry["session"]] + [entry]
        hist.sort(key=lambda h: h["session"])
    return hist[-SESSION_HISTORY_MAX:]


HOLDINGS_STORE_ID = "portfolio.holdings.current"  # the position store Home reads (lib/portfolio_positions.STORE_REL)


def current_book(policy: dict[str, Any], *, doc: dict | None = None, path: Any = None) -> dict[str, Any]:
    """The CURRENT holdings (canonical store ``portfolio.holdings.current``, the same position store Home reads), split
    into material positions and residuals, with closed_today excluded. Freshness is ``data_as_of`` /
    ``aggregate_published_at`` — the top-level ``as_of`` of that file is a stale legacy field and is never used."""
    src = None
    if doc is None:
        from pathlib import Path as _Path

        from scripts.lib import canonical_store_registry as reg
        from scripts.lib import portfolio_positions as pp

        res = reg.resolve_store(HOLDINGS_STORE_ID)
        src = str(res.get("path"))
        # Read through the sanctioned position-store reader (tests/test_portfolio_price_truth_20261005.py ratchet).
        # load_store() returns {} for a missing or unreadable store; fail closed here as the direct read did,
        # rather than report an empty book.
        doc = pp.load_store(_Path(res["path"]))
        if not doc:
            raise FileNotFoundError(f"position store missing or unreadable: {src}")
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
        prior, now=now, tier=doc.get("tier"), sectors_block=block, hedging=hedging_factor(doc.get("observations"))
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
            as_of=now,
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
    # design home/v005: residual lots get a look-through too (the Home card counts their dollars; no stance, no
    # playbook — materiality still hides those), and the book shares are VALUE-weighted, never equal per position
    residual_lt = {}
    for s in book["residuals"]:
        if s in expo:
            continue
        e = lt.exposure_for(s, ai_basket=basket, holdings=holdings, profiles=inp.get("profiles") or {},
                            themes=cfg.get("theme_overrides") or {}, as_of=now)
        residual_lt[s] = {k: e.get(k) for k in ("groups", "ai_share", "basis", "note")}
    book_meta["residual_look_through"] = residual_lt
    a.positions = {**stances, "_book": book_meta}
    a.heatmap = sec.heatmap(block, book_shares(expo, book["material"]))
    c.assert_no_behavior_fields(a.positions)
    return {"available": True, "flagged": flagged, "clusters": clusters, "hedge": hedge, "evening": sorted(evening)}


def book_shares(expo: dict[str, dict[str, Any]], material: list[dict[str, Any]]) -> dict[str, float]:
    """Book share per group, VALUE-weighted by each material position's shares x mark (design home/v005; the
    equal-per-position average let a residual count as much as the largest holding). Shares only, no amount out."""
    values: dict[str, float] = {}
    for p in material:
        if p.get("mark") and p.get("shares"):
            values[p["symbol"]] = values.get(p["symbol"], 0.0) + float(p["shares"]) * float(p["mark"])
    return lt.book_group_exposure(list(expo.values()), weights=values)


def _acct_key(raw: Any) -> str:
    """Canonical account key (``schwab_roth`` and ``schwab_roth_ira`` are one account; config/account_display_names)."""
    try:
        from scripts.lib import account_display as ad
    except ImportError:  # pragma: no cover
        from lib import account_display as ad  # type: ignore
    return ad.canonical_key(raw) or str(raw or "")


def _held_accounts(policy: dict[str, Any], doc: dict | None = None) -> set[tuple[str, str]]:
    """(canonical account, SYMBOL) pairs the holdings store holds now, at or above the materiality share floor."""
    try:
        if doc is None:
            from pathlib import Path as _Path

            from scripts.lib import canonical_store_registry as reg
            from scripts.lib import portfolio_positions as pp_

            doc = pp_.load_store(_Path(reg.resolve_store(HOLDINGS_STORE_ID)["path"]))
    except Exception:  # noqa: BLE001 — unreadable store: nothing is known held, exits stand as the ledger says
        return set()
    floor = float((((policy.get("positions") or {}).get("materiality") or {}).get("min_shares", 1.0)))
    return {
        (_acct_key(h.get("account")), str(h.get("symbol")).upper())
        for h in (doc or {}).get("holdings") or []
        if isinstance(h, dict) and not h.get("is_cash") and float(h.get("shares") or h.get("quantity") or 0) >= floor
    }


def _after(buy_date: str, buy_time: Any, sell_date: str, sell_time: Any, held_now: bool = False) -> bool:
    """A Buy is a RE-buy only when it came after the sale: a later date, or the same date at a later time. A same-day
    Buy without times on both sides counts only when the account holds the symbol now (then the buy must have come
    after the sale); otherwise it is not counted (a buy-then-sell day trade must stay an exit). Review of #2447."""
    if buy_date != sell_date:
        return buy_date > sell_date
    if buy_time is not None and sell_time is not None:
        return buy_time > sell_time
    return held_now


def per_account_exits(
    closes_rows: list[tuple],
    buys: list[tuple],
    *,
    held: set[tuple[str, str]],
    wash_days: int,
    sells: list[tuple] | None = None,
) -> dict[str, dict[str, Any]]:
    """Exits per symbol, decided per ACCOUNT (design home/v005 SPEC section 2). Pure.

    ``closes_rows``: (symbol, account, close_date, is_loss, sell_price) from trade_closed. ``buys``: (SYMBOL,
    canonical account, trade_date, price[, trade_time]) and ``sells``: (SYMBOL, canonical account, trade_date,
    trade_time) from trade_transactions (the times order a same-day sell and buy). An account is EXITED when it does not hold the
    symbol now and no Buy in that account is dated on or after its latest sale. A symbol with no exited account is
    held, not an exit, and is left out. Wash sale per taxable loss sale: ``occurred`` when the same account re-bought
    within ``wash_days``, else ``window_open`` until the loss date + ``wash_days``."""
    from datetime import date as _date, timedelta as _td

    last: dict[tuple[str, str], dict[str, Any]] = {}
    for row in closes_rows:
        sym, acct, d, loss = row[:4]
        px = row[4] if len(row) > 4 else None
        k = (str(sym).upper(), _acct_key(acct))
        d = str(d)[:10]
        r = last.setdefault(k, {"date": d, "price": None, "loss_date": None})
        if d >= r["date"]:
            r["date"], r["price"] = d, (float(px) if px is not None else r["price"])
        if loss and _account_type(acct) == "taxable":
            r["loss_date"] = max(r["loss_date"] or d, d)

    def sell_time(sym: str, acct: str, d: str) -> Any:
        return max((t for ss, sa, sd, t in (sells or []) if ss == sym and sa == acct and sd == d and t is not None),
                   default=None)

    def rebuys(sym: str, acct: str, d: str, held_now: bool) -> list[tuple[str, Any]]:
        st = sell_time(sym, acct, d)
        return sorted(
            (b[2], b[3]) for b in buys
            if b[0] == sym and b[1] == acct and _after(b[2], b[4] if len(b) > 4 else None, d, st, held_now)
        )

    by_sym: dict[str, dict[str, Any]] = {}
    for (sym, acct), r in last.items():
        held_now = (acct, sym) in held
        rebuy = rebuys(sym, acct, r["date"], held_now)
        e = by_sym.setdefault(sym, {"accounts": [], "wash": None})
        exited = not held_now and not rebuy
        e["accounts"].append({"account": acct, "date": r["date"], "price": r["price"], "exited": exited})
        if r["loss_date"]:
            ld = _date.fromisoformat(r["loss_date"])
            # the wash-sale test runs from the LOSS sale, not the latest sale (a later gain sale must not hide it)
            rb = [(bd, bp) for bd, bp in rebuys(sym, acct, r["loss_date"], held_now)
                  if _date.fromisoformat(bd) <= ld + _td(days=wash_days)]
            w = (
                {"state": "occurred", "account_scope": _opaque(acct), "loss_sale_date": r["loss_date"],
                 "rebuy_date": rb[0][0], "rebuy_price": float(rb[0][1]) if rb[0][1] is not None else None}
                if rb
                else {"state": "window_open", "account_scope": _opaque(acct), "loss_sale_date": r["loss_date"],
                      "until": (ld + _td(days=wash_days)).isoformat()}
            )
            if e["wash"] is None or w["loss_sale_date"] >= e["wash"]["loss_sale_date"]:
                e["wash"] = w
    out: dict[str, dict[str, Any]] = {}
    for sym, e in by_sym.items():
        ex = [x for x in e["accounts"] if x["exited"]]
        if not ex:
            continue
        top = max(ex, key=lambda x: x["date"])
        taxable_loss = e["wash"]["loss_sale_date"] if e["wash"] and e["wash"]["state"] == "window_open" else None
        out[sym] = {
            "exit_date": top["date"],
            "exit_price": top["price"],
            "exit_account_scope": _opaque(top["account"]),
            "exit_account_type": _account_type(top["account"]),
            "held_elsewhere": sorted(_opaque(a) for a, s in held if s == sym),
            "taxable_loss_date": taxable_loss,
            "wash_sale": e["wash"],
        }
    return out


def _opaque(acct: Any) -> str:
    from scripts.lib.market_risk.exposure import opaque_account

    return opaque_account(acct)


def reentry_watch_block(
    a: Any,
    *,
    now: datetime,
    reader: Any,
    policy: dict[str, Any],
    prior: dict | None,
    conn_factory: Any,
    held_accounts: set[tuple[str, str]] | None = None,
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
            lookback = int(cfg.get("lookback_days", 30))
            cur.execute(
                "SELECT symbol, account, close_date, (pnl < 0), sell_price FROM trade_closed "
                "WHERE close_date >= %s::date - %s AND close_date <= %s::date ORDER BY close_date",
                (now.date(), lookback, now.date()),
            )
            closes_rows = cur.fetchall()
            # design home/v005: a symbol re-bought in the SAME account after the sale is held there, not exited
            # (operator 2026-11-01, from a broker screenshot: a same-day sale and re-buy)
            cur.execute(
                "SELECT symbol, account, trade_date, price, trade_time, lower(action) FROM trade_transactions "
                "WHERE (lower(action) LIKE 'buy%%' OR lower(action) LIKE 'sell%%') "
                "AND trade_date >= %s::date - %s AND trade_date <= %s::date",
                (now.date(), lookback, now.date()),
            )
            tx = [r for r in cur.fetchall() if len(r) >= 6]
            buys = [
                (str(r[0]).upper(), _acct_key(r[1]), str(r[2])[:10], r[3], r[4]) for r in tx if str(r[5]).startswith("buy")
            ]
            sells = [
                (str(r[0]).upper(), _acct_key(r[1]), str(r[2])[:10], r[4]) for r in tx if str(r[5]).startswith("sell")
            ]
            exits = per_account_exits(
                closes_rows, buys, held=held_accounts or set(), wash_days=int(cfg.get("wash_sale_days", 30)), sells=sells
            )
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
    from scripts.lib.market_risk import reentry_stages as rs_stages

    sector_symbols = {
        r.get("key"): list(r.get("symbols") or []) for r in block.get("groups") or [] if r.get("kind") == "sector"
    }
    bench_sym = str((block.get("benchmark") or {}).get("symbol") or "SPY")
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
        ex = lt.exposure_for(sym, ai_basket=basket, themes=themes, profiles=profiles, as_of=now)
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

        weights = {g: w for g, w in groups.items() if g in sector_symbols and w}
        gcl = {}
        for g in weights:
            gb = [r for r in (reader.daily_bars(sector_symbols[g][:1], sessions=40, end=now) or []) if r.get("close") is not None]
            gcl[g] = [float(r["close"]) for r in gb]
        bench = [float(r["close"]) for r in (reader.daily_bars([bench_sym], sessions=40, end=now) or []) if r.get("close") is not None]
        try:
            st = rs_stages.evaluate(
                symbol=sym,
                exit_date=e["exit_date"],
                exit_price=e.get("exit_price"),
                bars=bars,
                group_ratio=rs_stages.weighted_group_ratio(gcl, weights, bench),
                hedging_series=[h.get("hedging_factor") for h in sh],
                market_tier=str(doc.get("market_tier")),
                policy=policy,
            )
        except Exception as exc:  # noqa: BLE001 — the stages are additive; the legacy card still renders
            st = {"error": f"{type(exc).__name__}: {exc}"}
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
                    (now.date() - _date.fromisoformat(e["taxable_loss_date"])).days
                    if e["taxable_loss_date"] and (e.get("wash_sale") or {}).get("state") != "occurred"
                    else None
                ),
                policy=policy,
            )
            cards[sym].update(
                exit_price=e.get("exit_price"),
                exit_account_scope=e.get("exit_account_scope"),
                exit_account_type=e.get("exit_account_type"),
                held_elsewhere=e.get("held_elsewhere") or [],
                wash_sale=e.get("wash_sale"),
                look_through={"groups": groups, "basis": ex.get("basis"), "note": ex.get("note")},
                stages=st,
            )
            c.assert_no_behavior_fields(cards[sym])
        except Exception as exc:  # noqa: BLE001 — one symbol failing is reported, the rest still render
            cards[sym] = {"symbol": sym, "error": f"{type(exc).__name__}: {exc}"}
    a.reentry_watch = cards
    return cards
