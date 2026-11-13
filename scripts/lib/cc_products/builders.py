"""Build functions for the Home/route products (DSN-20261112-PRECOMPUTE-CACHE, operator 13 Nov 2026).

Each ``build_*(ctx)`` runs ONLY inside the child ``product_builder.build_in_child`` forks (read-only DB session,
RLIMIT_AS, deadline). Each returns ``{"data", "as_of", "source_watermarks", "status", "reason"}`` where ``as_of`` is
the SOURCE clock (never the build time, unless the source is a live DB read made by this build).

The logic is the server's request-time code moved out of the request path, line for line, so the stored body has
the legacy route's shape:

* ``build_market_risk``   = api_v2 ``_market_risk_latest_projection`` + ``_home_cio_card`` (+ ``_fresh_price_batch``)
* ``build_risk``          = api_v2 ``_risk_payload_cached`` (``cio_truth.risk_payload``)
* ``build_analyst_links`` = api_v2 ``_reports_analyst_links`` over the full map (the route filters per request)
* ``build_home``          = api_v2 ``_home_since_close`` / ``_home_incidents`` / approvals summary /
  ``_home_priorities_live`` / ``_home_status`` / ``_home_gates`` as slices

This module must never import ``api_v2``. No broker call, no LLM call, no write.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cc_products.product_builder import ET, parse_ts

FRESH_PRICE_MAX_AGE_HOURS = 0.5  # api_v2.FRESH_PRICE_MAX_AGE_HOURS (operator price rule 2026-11-07)


def _scripts_on_path(ctx) -> None:
    p = str(Path(ctx.code_root) / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_json(path: Path):
    """api_v2 ``_load_json``: a 0-byte, missing or unparseable file is None."""
    try:
        if path.exists() and path.stat().st_size == 0:
            return None
        return json.loads(path.read_text()) if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


def _iso(dt) -> str | None:
    t = parse_ts(dt)
    return t.astimezone(timezone.utc).isoformat() if t else None


def _oldest(marks: dict, *, exclude=()) -> tuple[str | None, str | None]:
    best = None
    name = None
    for k, m in marks.items():
        if k in exclude or not isinstance(m, dict):
            continue
        t = parse_ts(m.get("as_of"))
        if t is not None and (best is None or t < best):
            best, name = t, k
    return (best.astimezone(timezone.utc).isoformat() if best else None), name


# ------------------------------------------------------------------------------------------ market_risk.latest


def _iso_quote_time(value):
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S ET").replace(tzinfo=ET).isoformat()
    except ValueError:
        return s


def fresh_price_batch(db_query, symbols) -> dict:
    """api_v2 ``_fresh_price_batch(symbols, live=False)``: Finviz cache, then a market_quotes row, 30-minute rule,
    no yfinance, no non-finite price. A symbol with no current quote is absent."""
    syms = [str(s or "").upper().strip() for s in symbols or [] if str(s or "").strip()]
    if not syms:
        return {}
    try:
        from lib.data_broker.market_quote import get_price_batch

        batch = get_price_batch(db_query, syms, max_age_hours=FRESH_PRICE_MAX_AGE_HOURS, skip_live=True) or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for sym, q in batch.items():
        if not isinstance(q, dict) or q.get("price") is None:
            continue
        if "yfinance" in str(q.get("source") or "").lower():
            continue
        try:
            price = float(q["price"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        src = str(q.get("source") or "unknown")
        out[str(sym).upper()] = {"price": price,
                                 "chg_pct": None if "finviz_quote_cache" in src.lower() else q.get("chg_pct"),
                                 "as_of": _iso_quote_time(q.get("as_of")), "source": src}
    return out


def market_risk_projection(ctx) -> dict:
    """api_v2 ``_market_risk_latest_projection`` with PROJECT_ROOT = ctx.code_root."""
    _scripts_on_path(ctx)
    from lib.market_risk import escalation as _mr_esc
    from lib.market_risk_projection import build as _mr_build, load_snapshot as _mr_load

    root = Path(ctx.state_root)  # SNAPSHOT_REL is "data/runtime/..."; state_root/data/runtime == PROJECT_ROOT/data/runtime
    snap = _mr_load(lambda rel: _load_json(root / rel), lambda rel: (root / rel).exists())
    radar = _load_json(ctx.runtime_dir / "hedging_radar_latest.json")
    ep_err = None
    try:
        ep = _mr_esc.open_episode(_mr_esc.load())
    except Exception as e:  # noqa: BLE001
        ep, ep_err = None, f"episode ledger unreadable: {type(e).__name__}"
    proj = _mr_build(snap, radar, episode=ep)
    if ep_err:
        proj["episode_error"] = ep_err
    try:
        from lib.market_risk_book_join import join as _mr_join

        proj = _mr_join(proj)
    except Exception as e:  # noqa: BLE001
        proj["book_exposure_error"] = f"{type(e).__name__}: {e}"
    return proj


def home_cio_card(ctx, mr: dict) -> tuple[dict, dict]:
    """api_v2 ``_home_cio_card`` minus its 30 s cache. Returns (card, source watermarks)."""
    _scripts_on_path(ctx)
    from zoneinfo import ZoneInfo

    from lib import home_cio_card as _hcc
    from lib import since_close_card as _sc

    marks: dict[str, Any] = {}
    db_query = ctx.db_query
    snap = _sc.load_json(ctx.portfolio_state_dir / "since_close_latest.json")
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if snap:
        snap = _sc.served_since_close(snap, _sc.fetch_stops_for_snapshot(db_query, snap), now=now_et)
        snap = {**snap, "freshness": _sc.freshness(snap, now=now_et)}
        marks["since_close"] = {"as_of": _iso(snap.get("generated_at")), "source": "since_close_latest.json"}
    defense = _load_json(ctx.runtime_dir / "defense_recommendations_latest.json") or None
    momentum = _load_json(ctx.runtime_dir / "sector_momentum_latest.json") or None
    for name, doc in (("defense", defense), ("sector_momentum", momentum)):
        if isinstance(doc, dict):
            marks[name] = {"as_of": _iso(doc.get("as_of") or doc.get("generated_at"))}
    syms = set(_hcc.rotation_symbols(mr))
    for g in (((defense or {}).get("groups") or {}).get("get_into") or []):
        for ins in (g or {}).get("instruments") or []:
            if str(ins.get("kind") or "") == "sector ETF" and ins.get("symbol"):
                syms.add(str(ins["symbol"]).upper())
    quotes = fresh_price_batch(db_query, sorted(syms)) if syms else {}
    if quotes:
        qt = [parse_ts(q.get("as_of")) for q in quotes.values()]
        qt = [t for t in qt if t is not None]
        marks["quotes"] = {"as_of": _iso(min(qt)) if qt else None, "count": len(quotes)}
    bars, bars_meta = [], {"present": False}
    if syms:
        since = date.today() - timedelta(days=45)
        rows = db_query(
            "SELECT symbol, bar_time::date AS session, close FROM market_ohlcv_bars WHERE timeframe = 'daily' "
            "AND symbol = ANY(%s) AND close IS NOT NULL AND bar_time >= %s ORDER BY symbol, bar_time",
            (sorted(syms), since),
        )
        if rows:
            bars = [{"symbol": r.get("symbol"), "session": str(r.get("session")), "close": r.get("close")} for r in rows]
            bars_meta = {"present": True, "source_id": "market_ohlcv_bars:daily", "symbols": sorted(syms),
                         "as_of": max(b["session"] for b in bars)}
            marks["daily_bars"] = {"as_of": _iso(bars_meta["as_of"])}
        else:
            bars_meta = {"present": False, "reason": "no daily bars read (DB unavailable or empty)"}
    try:
        from lib import portfolio_positions as _pp

        holdings = (_pp.load_store() or {}).get("holdings") or []
    except Exception:  # noqa: BLE001
        holdings = []
    stocks = {}
    stock_groups = tuple(_hcc.DEFENSIVE_KEYS)
    try:
        from lib import rotation_stocks as _rst
        from lib.holdings_document import load_document as _holdings_doc

        stock_groups = _rst.defaults()["groups"]
        doc = _holdings_doc(db_query=db_query)
        held = [{"symbol": h.get("symbol"), "sector": h.get("sector"), "market_value": h.get("market_value"),
                 "is_cash": h.get("is_cash")} for h in (doc.get("holdings") or []) if isinstance(h, dict)]
        stocks = _rst.read(db_query, held=held, exclude=syms)
    except Exception as e:  # noqa: BLE001
        stocks = {g: {"rows": [], "as_of": None, "gap": f"constituent read failed: {type(e).__name__}"}
                  for g in stock_groups}
    card = _hcc.build(mr, snap, defense=defense, momentum=momentum, bars=bars, bars_meta=bars_meta, quotes=quotes,
                      holdings=holdings, stocks=stocks, now=datetime.now(timezone.utc))
    return card, marks


def build_market_risk(ctx) -> dict:
    """One body for /api/v2/market-risk/latest (``projection``) and /api/v2/home/cio-card (``home_cio_card``).

    ``as_of`` = the Market Risk snapshot's own clock (the 5-minute hard expiry is about that record). The card's
    other inputs (since-close brief, quotes, bars, defense, momentum) keep their own clocks in the watermarks and the
    route exposes the oldest of them. No snapshot clock → as_of = the read time with status DEGRADED and a reason."""
    read_at = datetime.now(timezone.utc)
    reason = None
    status = "OK"
    try:
        mr = market_risk_projection(ctx)
    except Exception as e:  # noqa: BLE001 - the card renders "market risk unavailable" (legacy behaviour)
        mr = {"state": "not_evaluated", "reason": f"market risk projection failed: {type(e).__name__}"}
    card, marks = home_cio_card(ctx, mr)
    mr_clock = _iso(mr.get("as_of"))
    marks["market_risk_snapshot"] = {"as_of": mr_clock, "state": mr.get("state")}
    radar = (mr.get("hedging_radar") or {}) if isinstance(mr.get("hedging_radar"), dict) else {}
    if radar.get("as_of"):
        marks["hedging_radar"] = {"as_of": _iso(radar.get("as_of"))}
    as_of = mr_clock
    if as_of is None:
        as_of, status = read_at.isoformat(), "DEGRADED"
        reason = "market risk snapshot has no clock; product clock is the read time"
    oldest, oldest_name = _oldest(marks)
    marks["_product"] = {"oldest_section_as_of": oldest, "oldest_section": oldest_name,
                         "sources_read_at": read_at.isoformat(), "clock_rule": "market_risk_snapshot.as_of"}
    return {"data": {"projection": mr, "home_cio_card": card}, "as_of": as_of, "source_watermarks": marks,
            "status": status, "reason": reason}


# ------------------------------------------------------------------------------------------------------- risk


def build_risk(ctx) -> dict:
    """/api/v2/risk body (``cio_truth.risk_payload``). ``as_of`` = the holdings truth clock it reports."""
    _scripts_on_path(ctx)
    from scripts.lib import cio_truth

    read_at = datetime.now(timezone.utc)
    payload = cio_truth.risk_payload(db_query=ctx.db_query)
    truth = payload.get("truth") or {}
    clock = _iso(truth.get("as_of")) or _iso(payload.get("positions_as_of"))
    marks = {"holdings_truth": {"as_of": clock, "source": truth.get("source"), "stale": truth.get("stale"),
                                "gap": truth.get("gap")}}
    status, reason = "OK", None
    if clock is None:
        clock, status, reason = read_at.isoformat(), "DEGRADED", "holdings truth has no clock; product clock is the read time"
    marks["_product"] = {"oldest_section_as_of": clock, "oldest_section": "holdings_truth",
                         "sources_read_at": read_at.isoformat(), "clock_rule": "cio_truth.truth.as_of"}
    return {"data": payload, "as_of": clock, "source_watermarks": marks, "status": status, "reason": reason}


# --------------------------------------------------------------------------------------- reports.analyst_links


def build_analyst_links(ctx) -> dict:
    """The full verified-links map (limit 0 = no limit). The route applies ``symbol`` and ``limit`` per request on
    the stored map, which gives the legacy answer: the legacy map is filtered first, then sorted and truncated.
    ``as_of`` = when this build verified the files on disk (that check IS the source read)."""
    _scripts_on_path(ctx)
    import reporting_engine as _re

    read_at = datetime.now(timezone.utc)
    out = _re.report_links_map(symbols=None, limit=0)
    marks = {"report_registry": {"as_of": _iso(out.get("updated_at"))},
             "files_verified": {"as_of": read_at.isoformat(), "count": out.get("count")}}
    marks["_product"] = {"sources_read_at": read_at.isoformat(), "clock_rule": "files verified at build"}
    return {"data": out, "as_of": read_at.isoformat(), "source_watermarks": marks, "status": "OK", "reason": None}


# ------------------------------------------------------------------------------------------------------- home

#: Per-slice staleness the read side applies with the slice's OWN clock (a fresh build never refreshes it).
HOME_SLICE_STALE_S = {"since_close": 3 * 3600, "incidents": 180, "approvals_summary": 180, "priorities_live": 180,
                      "status": 180, "gates": 180}


def build_home(ctx) -> dict:
    """Both Home sections' server reads as slices. Each slice keeps its legacy route body; a slice that failed is
    ``{"error": ...}`` and the product is DEGRADED. Product ``as_of`` = the oldest clock among the live slices; the
    overnight since-close brief keeps its own clock in its slice (and in ``_product.oldest_section``) so it is never
    shown fresher than it is, but it does not expire the live slices."""
    _scripts_on_path(ctx)
    from zoneinfo import ZoneInfo

    read_at = datetime.now(timezone.utc)
    slices: dict[str, Any] = {}
    marks: dict[str, Any] = {}
    failed: list[str] = []

    def _slice(name, fn, clock_fn):
        try:
            body = fn()
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            slices[name] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
            marks[name] = {"as_of": None, "error": type(e).__name__}
            return None
        slices[name] = body
        marks[name] = {"as_of": clock_fn(body)}
        return body

    from lib import since_close_card as _sc

    def _since_close():
        snap = _sc.load_json(ctx.portfolio_state_dir / "since_close_latest.json")
        now = datetime.now(ZoneInfo("America/New_York"))
        win = _sc.window(now)
        if not snap:
            return {"status": "no_snapshot", "window": win, "as_of_now": now.isoformat()}
        snap = _sc.served_since_close(snap, _sc.fetch_stops_for_snapshot(ctx.db_query, snap), now=now)
        return {"status": "ok", **snap, "window_now": win, "freshness": _sc.freshness(snap, now=now),
                "as_of_now": now.isoformat()}

    sc = _slice("since_close", _since_close, lambda b: _iso(b.get("generated_at")))

    from lib import home_incidents as _hi

    inc = _slice("incidents", lambda: _hi.build(ctx.db_query_raising),
                 lambda b: _iso(((b.get("snapshot") or {}).get("computed_at"))) or read_at.isoformat())

    # Approvals are an AUTH-SCOPED read (home_approvals_api refuses a caller that is not the signed-in operator or
    # the service token). A builder has no principal, and a global product must not carry one principal's data to
    # every reader, so the slice is not built into scope "global" (operator contract: authorized account scope).
    # priorities_live then names approvals in its ``unread`` list (PARTIAL), exactly as when the read fails.
    slices["approvals_summary"] = {"state": "UNKNOWN", "scope_excluded": True,
                                   "reason": "auth-scoped read; not built into the global Home product"}
    marks["approvals_summary"] = {"as_of": None, "scope_excluded": True}
    appr = None

    from lib import home_priorities_live as _hp

    _slice("priorities_live",
           lambda: _hp.build(lambda: inc, lambda: sc, lambda: appr),
           lambda b: read_at.isoformat())

    from lib import home_status_live as _hsl

    _slice("status", lambda: _hsl.serve(ctx.get_conn, snapshot_query=ctx.db_query, use_cache=False),
           lambda b: _iso(((b.get("trade_ready") or {}).get("computed_at"))) or read_at.isoformat())

    from lib import home_v010_api as _h

    _slice("gates", lambda: _h.home_gates(ctx.db_query, use_cache=False), lambda b: read_at.isoformat())

    live = [parse_ts(m.get("as_of")) for k, m in marks.items() if k != "since_close" and isinstance(m, dict)]
    live = [t for t in live if t is not None]
    as_of = min(live).astimezone(timezone.utc).isoformat() if live else None
    oldest, oldest_name = _oldest(marks)
    marks["_product"] = {"oldest_section_as_of": oldest, "oldest_section": oldest_name,
                         "sources_read_at": read_at.isoformat(), "clock_rule": "oldest live slice"}
    status = "DEGRADED" if failed else "OK"
    reason = ("slices failed: " + ", ".join(failed)) if failed else None
    return {"data": {"slices": slices, "slice_clocks": {k: v for k, v in marks.items() if k != "_product"},
                     "slice_stale_after_s": HOME_SLICE_STALE_S},
            "as_of": as_of, "source_watermarks": marks, "status": status, "reason": reason}
