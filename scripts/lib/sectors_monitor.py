"""Watch Sectors read-only handler. One multi-horizon signal, no provider calls."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lib.sector_signals import number
from lib.cio_sector_opportunity import canonical_sector

SECTOR_ETFS = {'Technology': 'XLK', 'Financials': 'XLF', 'Energy': 'XLE', 'Healthcare': 'XLV', 'Consumer Cyclical': 'XLY', 'Industrials': 'XLI', 'Consumer Defensive': 'XLP', 'Utilities': 'XLU', 'Real Estate': 'XLRE', 'Basic Materials': 'XLB', 'Communication Services': 'XLC'}


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _json_clean(value):
    if isinstance(value, dict):
        return {k: _json_clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(v) for v in value]
    if isinstance(value, Decimal):
        return number(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def monitor(db_query, state_dir, *, sector_map=None, query=None, now=None):
    """Exact multi-horizon RS plus stored quote context and portfolio overlay.

    Missing horizons remain explicit gaps. Watched sectors sort first. Labels
    come entirely from the shared projection; this endpoint never acts on them.
    """
    import json as _j
    _SECTOR_ETF_MAP = sector_map or SECTOR_ETFS
    _db_query = db_query

    # One Source of Truth Phase 4 (2026-09-13): quotes come from the market_quote projection in ONE
    # batch (skip_live — a bulk page never blocks on the provider waterfall) and the RS history from
    # the sector_momentum projection. This hub no longer SELECTs market_quotes / sector_rs_daily itself;
    # the response carries the read envelope (as_of, age_hours, source, stale) for both feeds.
    from lib.data_broker.envelope import envelope as _brk_envelope, newest as _brk_newest
    from lib.data_broker.market_quote import get_price_batch as _brk_prices
    from lib.data_broker.sector_momentum import get_sector_signals

    _etfs = list(dict.fromkeys(["SPY"] + list(_SECTOR_ETF_MAP.values())))
    _quotes = _brk_prices(_db_query, _etfs, max_age_hours=168, skip_live=True)
    spy_chg = number((_quotes.get("SPY") or {}).get("chg_pct"))
    watched = {}
    for d in _db_query("SELECT id, label, spec FROM watch_directives WHERE kind='sector' AND status='active'") or []:
        spec = d["spec"] if isinstance(d["spec"], dict) else _j.loads(d["spec"])
        key = spec.get("finviz_sector") or spec.get("gics_sector") or ""
        if key:
            # A4: normalize 'Financial' vs 'Financials' so the watching chip
            # matches regardless of which variant the directive stored
            watched[key.strip().lower().rstrip("s")] = {"id": d["id"], "label": d["label"]}
    signals = get_sector_signals(_db_query)
    _rs_hist_env = _brk_envelope("sector_momentum", signals.get("as_of"), now=now,
                                 stale_after_hours=96, source={"table": "ticker_prices", "file": None, "provider": "internal:ticker_prices", "writer": "scripts/lib/writers/ticker_prices_writer.py"})

    def _rs_block(etf):
        signal = {k: v for k, v in (signals["sectors"].get(etf) or {}).items() if k != "sector"}
        return {**signal, "rs_5d_pct": signal.get("rs5"), "rs_20d_pct": signal.get("rs20"),
                "rs_60d_pct": signal.get("rs60"), "rs_series": [], "rs_n": None,
                "rs_trend": signal.get("momentum", "missing")}

    # v4 (E2): book overlay — actual sector weights from canonical holdings.json
    # resolved_sectors (the pipeline's fund LOOK-THROUGH decomposition, so SCHG/tech
    # concentration shows honestly). Read-only. Names aliased to the monitor's keys.
    _book: dict = {}
    _book_dollars: dict = {}
    try:
        _h = _load_json(Path(state_dir) / "holdings.json") or {}
        _rs = _h.get("resolved_sectors") or []
        for r in _rs:
            name = canonical_sector(r.get("sector"))
            pct, dollars = number(r.get("pct")), number(r.get("value"))
            if name:
                if pct is not None:
                    _book[name] = _book.get(name, 0.0) + pct
                if dollars is not None:
                    _book_dollars[name] = _book_dollars.get(name, 0.0) + dollars
    except Exception:
        _book = {}

    out = []
    for sec, etf in _SECTOR_ETF_MAP.items():
        q = _quotes.get(etf) or {}
        etf_chg = q.get("chg_pct")
        rel = round(float(etf_chg) - spy_chg, 2) if etf_chg is not None and spy_chg is not None else None
        cons = (
            _db_query("SELECT count(DISTINCT symbol) AS n FROM incubator_universe WHERE sector=%s", (sec,), fetch="one")
            or {}
        )
        # Reconcile each per-sector momentum candidate against the CIO verdict + analyst coverage so a
        # score-ranked "setup" the CIO says AVOID (or with thin coverage) is flagged, not surfaced as a buy.
        candidate_rows = (
            _db_query(
                """SELECT DISTINCT wi.symbol, wi.rsi, wi.trend, wi.score, wi.origin_system,
                                wi.setup_advisory, wi.watch_score_kind,
                                an.nop AS analyst_opinions
                             FROM watchlist_items wi
                             LEFT JOIN LATERAL (SELECT number_of_analyst_opinions nop FROM yahoo_analyst_targets_history y
                                                WHERE upper(y.symbol)=upper(wi.symbol) ORDER BY created_at DESC LIMIT 1) an ON true
                             WHERE wi.status IN ('active','researched') AND wi.score IS NOT NULL
                               AND wi.symbol IN (SELECT DISTINCT symbol FROM incubator_universe WHERE sector=%s)
                             ORDER BY wi.score DESC NULLS LAST LIMIT 12""",
                (sec,),
            )
        )
        cands = candidate_rows or []
        candidate_gap = "Screened names unavailable" if candidate_rows is None else None
        for _c in cands:
            _c["cio_view"] = None
            _c["cio_avoid"] = False
            _nop = _c.get("analyst_opinions")
            _c["thin_coverage"] = _nop is None or int(_nop) < 3
        cands = [c for c in cands if not c["cio_avoid"]][:8]
        _rsb = _rs_block(etf)
        _bw = _book.get(canonical_sector(sec))
        out.append(
            {
                "sector": sec,
                "etf": etf,
                "etf_change_pct": _json_clean(etf_chg),
                "quote_as_of": q.get("as_of"),
                "spy_change_pct": spy_chg,
                "rel_strength": rel,
                "momentum": _rsb.get("momentum", "missing"),
                "constituent_count": cons.get("n"),
                "setup_count": None if candidate_gap else len(cands),
                "candidate_gap": candidate_gap,
                "candidates": [{k: _json_clean(v) for k, v in c.items()} for c in cands],
                "is_watched": sec.strip().lower().rstrip("s") in watched,
                "directive": watched.get(sec.strip().lower().rstrip("s")),
                **_rsb,
                "book_weight_pct": _bw,
                "book_dollars": _book_dollars.get(canonical_sector(sec)),
                "leaders": [],
                "leaders_gap": "Sector leaders not measured",
                # E2: one-glance answer to "am I overweight what's lagging?" — deterministic copy
                "book_flag": (
                    "overweight_lagging" if (_bw or 0) >= 10 and _rsb.get("momentum") in ("lagging", "weakening") else None
                ),
            }
        )
    # W1 is the sole CIO stance resolver. Do not fall back to the old watch
    # synthesis as competing authority while the W1 dependency is unavailable.
    names = sorted({c["symbol"] for row in out for c in row["candidates"]})
    try:
        from lib.cio_truth import stances_for_symbols
        stances = stances_for_symbols(names, db_query=_db_query, now=now)
    except Exception:
        stances = {}
    for row in out:
        for candidate in row["candidates"]:
            stance = stances.get(candidate["symbol"]) or {}
            candidate["cio_view"] = stance.get("stance")
            candidate["cio_gap"] = stance.get("gap") or (None if stance.get("stance") else {"reason": "CIO view unavailable"})
            candidate["cio_avoid"] = str(stance.get("stance") or "").upper() in ("AVOID", "IGNORE", "REBALANCE_TRIM")
        row["candidates"] = [c for c in row["candidates"] if not c["cio_avoid"]]
        row["setup_count"] = None if row["candidate_gap"] else len(row["candidates"])

    # Leaders are explicitly limited to this sector's screened names, ranked by
    # the same exact 20-session return difference. No analyst score becomes a
    # price leader or a CIO recommendation.
    names = sorted({c["symbol"] for row in out for c in row["candidates"]})
    leader_signals = get_sector_signals(_db_query, symbols=names)["sectors"] if names else {}
    for row in out:
        measured = [{"symbol": c["symbol"], "rs20": leader_signals.get(c["symbol"], {}).get("rs20")}
                    for c in row["candidates"]]
        measured = {r["symbol"]: r for r in measured if r["rs20"] is not None}
        row["leaders"] = sorted(measured.values(), key=lambda r: (-r["rs20"], r["symbol"]))[:3]
        row["leaders_basis"] = "screened names · 20 sessions vs SPY"
        row["leaders_gap"] = None if row["leaders"] else row["candidate_gap"] or ("Screened leaders not measured — price history unavailable" if row["candidates"] else "No screened names with measured leaders")

    out.sort(key=lambda s: (not s["is_watched"], {"leading": 0, "neutral": 1, "lagging": 2}.get(s["momentum"], 3)))
    # Stale quarantine + field truth ledger. Additive: every pre-existing key is left
    # exactly as the frontend already reads it. A stale sector keeps its row and its
    # numbers — nothing is deleted — but loses recommendation eligibility, so a
    # four-day-old observation can no longer originate a new add.
    quality_block = {}
    try:
        from datetime import date as _date
        from defense_data_quality import (
            Quality,
            field_ledger,
            quarantine_stale_rows,
        )

        _today = now.date() if now else _date.today()
        _rows = [{"symbol": s.get("etf"), "sector": s.get("sector"), "as_of": s.get("as_of")} for s in out]
        _q = quarantine_stale_rows(_rows, as_of=_today, max_age_days=4)
        _stale = {r.get("sector") for r in _q["quarantined"]}
        for s in out:
            is_stale = s.get("sector") in _stale or s.get("as_of") is None
            s["stale"] = is_stale
            s["source_age_days"] = next(
                (r.get("age_days") for r in (_q["quarantined"] + _q["current"]) if r.get("sector") == s.get("sector")),
                None,
            )
            s["stale_sla_days"] = 4
            s["quarantine_reason"] = "source_older_than_sla" if is_stale else None
            # Legacy recommendations remain authoritative; this flag is advisory input
            # to the shadow lane and to the UI, and does not itself remove a live card.
            s["recommendation_eligible"] = not is_stale and not s.get("gap")
            if is_stale:
                s["freshness_gap"] = "Sector prices are older than the freshness limit"
        quality_block = {
            "sectors_total": len(out),
            "sectors_stale": len(_stale),
            "stale_sla_days": 4,
            "ledger": field_ledger(
                source="ticker_prices",
                provider="sector_momentum projection",
                source_as_of=max((s.get("as_of") or "" for s in out), default=None) or None,
                cadence="daily_close",
                value=[s.get("sector") for s in out],
                coverage_n=sum(not r.get("gap") and not r.get("stale") for r in out),
                coverage_total=len(out),
                quality=Quality("ok") if not _stale else Quality("partial_stale", (f"stale_sectors={len(_stale)}",)),
            ),
        }
    except Exception as _e:
        quality_block = {"error": f"quality block unavailable: {str(_e)[:120]}"}
    # quote_price has two registry windows: 0.25h in RTH, 72h when the market is closed
    # (weekend/holiday/after-hours). Ask the session calendar which one applies.
    try:
        from market_session import is_market_open as _brk_mkt_open

        _mkt_closed = not _brk_mkt_open()
    except Exception:
        _mkt_closed = None
    _q_env = _brk_envelope(
        "quote_price", _brk_newest([v.get("as_of") for v in _quotes.values()]), market_closed=_mkt_closed, now=now
    )
    _rs_env = {
        k: _rs_hist_env.get(k)
        for k in ("as_of", "age_hours", "source", "stale", "stale_after_hours", "gap")
        if k in _rs_hist_env
    }
    return {
        **_q_env,
        "feeds": {"market_quotes": {k: v for k, v in _q_env.items() if k != "schema"}, "sector_rs_daily": _rs_env, "sector_prices": _rs_env},
        "posture_basis": "20d_60d_vs_spy",
        "rs_as_of": signals.get("as_of"),
        "gap": "Sector prices unavailable" if not signals.get("as_of") else None,
        "spy_change_pct": spy_chg,
        "sectors": out,
        "data_quality": quality_block,
        # A4 legend: on-page semantics instead of implied meaning
        "legend": (
            "setups/N: setups = score-ranked screened names after the canonical CIO avoid filter; "
            "coverage gaps remain visible; N = tracked constituents in incubator_universe for the "
            "sector. 'n/a · quote missing' = sector ETF has no quote row (not a calc failure). "
            "'watching' chip = an active sector directive exists for this sector."
        ),
    }
