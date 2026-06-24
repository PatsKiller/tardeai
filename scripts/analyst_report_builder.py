#!/usr/bin/env python3
"""analyst_report_builder.py — analyst-grade report composition for Command Center v3.

Builds structured JSON reports from existing data sources (enrichment, agents, Layer 4,
Hermes, proposals, health agent, journal). Consumed by report_export.py and /api/v2/reports/analyst/*.

Extending templates
-------------------
1. Add a section id to SECTION_IDS and compose it in build_symbol_report() (or a dedicated builder).
2. Register new report types in REPORT_TYPES and branch in build_report() / api preview+export.
3. For new visuals: append dicts to report["visuals"] with "type" and optional "chart_path" (PNG).
   report_export.py embeds chart_path images in DOCX automatically.
4. Sector/theme reports: extend build_sector_theme_report() peer queries and theme directives.
5. Scheduled digests: generate_analyst_daily_digest.py or reporting_engine.generate_scheduled().
6. Batch prospectus + registry: reporting_engine.py (see docs/reporting/REPORTING_ENGINE.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
REPORT_OUT = PROJECT_ROOT / "data" / "portfolios" / "reports" / "analyst"

SECTION_IDS = (
    "header_context",
    "executive_summary",
    "personal_performance",
    "report_continuity",
    "news_catalysts",
    "technical_analysis",
    "fundamental_valuation",
    "intelligence_view",
    "risk_assessment",
    "action_plan",
    "peer_comparison",
    "options_strategy",
    # legacy aliases (still accepted in section filters)
    "agent_synthesis",
    "agent_performance_note",
    "ensemble_validation",
    "investment_thesis",
    "fundamental_news",
    "valuation_targets",
    "recommendation",
    "key_risks",
    "health_context",
)

REPORT_TYPES = {
    "symbol_watchlist": {"label": "Watchlist Item Report", "context": "watchlist"},
    "symbol_holding": {"label": "Portfolio Holding Report", "context": "holding"},
    "symbol_custom": {"label": "Custom Instrument Report", "context": "custom"},
    "sector_theme": {"label": "Sector & Theme Report", "context": "sector"},
    "daily_digest": {"label": "Daily Intelligence Digest", "context": "portfolio"},
    "weekly_review": {"label": "Weekly Portfolio Review", "context": "portfolio"},
    "intelligence_deep": {"label": "Intelligence Deep Dive", "context": "intelligence"},
    "event_driven": {"label": "Event-Driven Alert Report", "context": "alerts"},
}

EVENT_FILTERS = ("all", "stop_hit", "thesis_invalidation", "large_move")


def _load(path: Path) -> dict | list:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _db_query(sql: str, params=None, fetch="all"):
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _execute
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return [] if fetch == "all" else None


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{_f(v):+.2f}%"


def _confidence_label(score: float | None) -> str:
    if score is None:
        return "Low"
    s = _f(score)
    if s >= 75:
        return "High"
    if s >= 50:
        return "Medium"
    return "Low"


_ENRICH_CACHE: dict | None = None


def _enrichment_cache() -> dict:
    global _ENRICH_CACHE
    if _ENRICH_CACHE is None:
        ec = _load(STATE_DIR / "ticker_enrichment_cache.json")
        _ENRICH_CACHE = ec if isinstance(ec, dict) else {}
    return _ENRICH_CACHE


def _enrichment(symbol: str, *, cache: dict | None = None) -> dict:
    ec = cache if cache is not None else _enrichment_cache()
    row = ec.get(symbol.upper(), {}) if isinstance(ec, dict) else {}
    return row if isinstance(row, dict) else {}


def _normalize_confidence(val: Any) -> float | None:
    """Map DB confidence to 0-100 display scale."""
    if val is None:
        return None
    c = _f(val)
    if c <= 1.0:
        c *= 100.0
    return round(c, 1)


def _normalize_score_10(val: Any) -> float | None:
    """Map ensemble / lane scores to 0-10 display scale."""
    if val is None:
        return None
    s = _f(val)
    if 0 < s <= 1.0:
        s *= 10.0
    return round(s, 2)


def _normalize_ensemble_row(row: dict | None) -> dict | None:
    """Normalize ensemble DB row for UI (scores 0–10, confidence 0–1)."""
    if not row:
        return None
    out = dict(row)
    out["final_score"] = _normalize_score_10(out.get("final_score"))
    fc = out.get("final_confidence")
    if fc is not None:
        c = _f(fc)
        out["final_confidence"] = c if c <= 1.0 else round(c / 100.0, 3)
    votes = out.get("votes")
    if isinstance(votes, str):
        try:
            votes = json.loads(votes)
        except Exception:
            votes = []
    if isinstance(votes, list):
        norm_votes = []
        for v in votes:
            if not isinstance(v, dict):
                continue
            nv = dict(v)
            if nv.get("score") is not None:
                nv["score"] = _normalize_score_10(nv.get("score"))
            norm_votes.append(nv)
        out["votes"] = norm_votes
    return out


def _resolve_price(symbol: str, enrich: dict, holding: dict | None, *, allow_yahoo: bool = True) -> float:
    """Best available live price — enrichment often lacks price field."""
    for src in (
        enrich.get("price"),
        enrich.get("latest_price"),
        (holding or {}).get("current_price"),
        (holding or {}).get("price"),
    ):
        p = _f(src)
        if p > 0:
            return p
    if not allow_yahoo:
        return 0.0
    try:
        from portfolio_technical_charts import _fetch_yahoo_history
        hist = _fetch_yahoo_history(symbol.upper(), 30)
        if hist and hist.get("prices"):
            return _f(hist["prices"][-1])
    except Exception:
        pass
    return 0.0


def _enriched(
    symbol: str,
    holding: dict | None = None,
    *,
    fast: bool = False,
    enrich_cache: dict | None = None,
) -> dict:
    """Enrichment row merged with resolved price and holding day change."""
    row = dict(_enrichment(symbol, cache=enrich_cache))
    holding = holding if holding is not None else (None if fast else _holding_for_symbol(symbol))
    price = _resolve_price(symbol, row, holding, allow_yahoo=not fast)
    if price > 0:
        row["price"] = price
        row["latest_price"] = price
    if holding:
        if holding.get("day_change_pct") is not None:
            row["day_change_pct"] = holding.get("day_change_pct")
        if holding.get("unrealized_pnl_pct") is not None:
            row["unrealized_pnl_pct"] = holding.get("unrealized_pnl_pct")
    return row


def _holding_rows_raw() -> list[dict]:
    return [x for x in (_load(STATE_DIR / "holdings.json").get("holdings") or []) if not x.get("is_cash")]


def _holding_for_symbol(symbol: str) -> dict | None:
    sym = symbol.upper()
    for row in _holding_rows_raw():
        if str(row.get("symbol", "")).upper() == sym:
            return row
    return None


def _watchlist_row(symbol: str) -> dict | None:
    rows = _db_query(
        """SELECT wi.symbol, wi.trend, wi.score, wi.source, wi.bucket, wi.status,
                  wi.trade_plan, wi.holdings_llm_action, wi.holdings_llm_confidence,
                  wi.holdings_llm_health, wi.updated_at, sp.sector
           FROM watchlist_items wi
           LEFT JOIN symbol_profiles sp ON sp.symbol = wi.symbol
           WHERE wi.symbol = %s
           ORDER BY wi.updated_at DESC LIMIT 1""",
        (symbol.upper(),),
        fetch="one",
    )
    return dict(rows) if rows else None


def _synthesis(symbol: str) -> dict | None:
    rows = _db_query(
        """SELECT symbol, recommendation, confidence, action, decision_safety, safety_reasons,
                  human_review_required, conflicts_detected, synthesis_narrative, raw_response,
                  updated_at
           FROM watchlist_final_synthesis WHERE symbol = %s ORDER BY updated_at DESC LIMIT 1""",
        (symbol.upper(),),
        fetch="one",
    )
    return dict(rows) if rows else None


def _synthesis_narrative(synthesis: dict | None) -> str:
    if not synthesis:
        return ""
    for key in ("synthesis_narrative", "raw_response"):
        text = synthesis.get(key)
        if text and str(text).strip():
            return str(text).strip()
    return ""


def _watchlist_rating(wl: dict | None, synthesis: dict | None) -> str:
    if synthesis and synthesis.get("recommendation"):
        return str(synthesis["recommendation"])
    if wl and wl.get("holdings_llm_action"):
        return str(wl["holdings_llm_action"])
    if wl and wl.get("action"):
        return str(wl["action"])
    return "Review"


def _agent_notes(symbol: str) -> list[dict]:
    rows = _db_query(
        """SELECT agent, recommendation, confidence, summary, created_at
           FROM watchlist_agent_results WHERE symbol = %s
           ORDER BY created_at DESC LIMIT 8""",
        (symbol.upper(),),
    ) or []
    return [dict(r) for r in rows]


def _ensemble(symbol: str) -> dict | None:
    sym = symbol.upper()
    rows = _db_query(
        """SELECT target_id, target_type, subject, final_score, final_decision, final_confidence,
                  consensus_reached, lanes_used, votes, reasoning_summary, created_at
           FROM inference_ensemble_results
           WHERE UPPER(subject) = %s OR UPPER(target_id) = %s
           ORDER BY created_at DESC LIMIT 1""",
        (sym, sym),
        fetch="one",
    )
    return dict(rows) if rows else None


def _chart_url(path: Path | str) -> str:
    try:
        rel = Path(path).relative_to(PROJECT_ROOT)
        return "/" + str(rel).replace("\\", "/")
    except ValueError:
        return str(path)


def _attach_symbol_charts(symbol: str, enrich: dict, visuals: list[dict], proposal: dict | None = None) -> None:
    """Generate price + volume + RSI + risk/reward PNGs for UI and DOCX embed."""
    import importlib
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        import portfolio_technical_charts as _ptc
        import report_visuals as _rv
        _ptc = importlib.reload(_ptc)
        _rv = importlib.reload(_rv)
        chart_price_history = _ptc.chart_price_history
        chart_volume_rvol = _ptc.chart_volume_rvol
        chart_rsi_gauge = _rv.chart_rsi_gauge
        chart_risk_reward = _rv.chart_risk_reward

        sym = symbol.upper()
        holding = _holding_for_symbol(sym)
        price = _resolve_price(sym, enrich, holding)
        charts_dir = REPORT_OUT / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now().strftime("%Y%m%d")

        chart_path = charts_dir / f"{sym}_price_{day}.png"
        result = chart_price_history(sym, price, None, None, None, chart_path)
        if result and chart_path.exists():
            visuals.append({
                "type": "price_history",
                "chart_path": _chart_url(chart_path),
                "symbol": sym,
                "price": price or _f(enrich.get("price")),
            })

        vol_path = charts_dir / f"{sym}_volume_{day}.png"
        rvol = enrich.get("rvol")
        vol_result = chart_volume_rvol(sym, _f(rvol) if rvol is not None else None, vol_path)
        if vol_result and vol_path.exists():
            visuals.append({
                "type": "volume_rvol",
                "chart_path": _chart_url(vol_path),
                "symbol": sym,
                "rvol": rvol,
            })

        rsi = enrich.get("rsi")
        if rsi is not None:
            rg = chart_rsi_gauge(_f(rsi), sym)
            if rg.get("chart_path"):
                visuals.append(rg)

        if proposal and proposal.get("proposed_entry") and proposal.get("proposed_stop"):
            rr = chart_risk_reward(
                _f(proposal.get("proposed_entry")),
                _f(proposal.get("proposed_stop")),
                _f(proposal.get("proposed_target1")),
                price,
                sym,
            )
            if rr.get("chart_path"):
                visuals.append(rr)
    except Exception as exc:
        import logging
        logging.getLogger("analyst_report_builder").warning(
            "symbol chart generation failed for %s: %s", symbol, exc
        )


def _news_for_symbol(symbol: str, limit: int = 6) -> list[dict]:
    news = _load(STATE_DIR / "portfolio_news.json")
    sym = symbol.upper()
    articles = news.get("all_scored") or news.get("catalysts") or []
    out = []
    for a in articles:
        if a.get("portfolio_symbol") == sym or a.get("symbol") == sym:
            out.append({
                "title": a.get("title") or a.get("headline"),
                "score": a.get("score") or a.get("catalyst_score"),
                "source": a.get("source"),
                "date": a.get("published_at") or a.get("created_at"),
                "summary": (a.get("summary") or "")[:280],
            })
        if len(out) >= limit:
            break
    return out


def _proposal_context(symbol: str) -> dict | None:
    rows = _db_query(
        """SELECT id, symbol, status, strategy_id, proposed_entry, proposed_stop, proposed_target1,
                  current_price, price_drift_pct, origin
           FROM paper_trade_proposals
           WHERE symbol = %s AND status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')
           ORDER BY created_at DESC LIMIT 1""",
        (symbol.upper(),),
        fetch="one",
    )
    if not rows:
        return None
    row = dict(rows)
    try:
        from broker_thesis_validity import attach_thesis_validity
        attach_thesis_validity(row)
    except Exception:
        pass
    return row


def _thesis_visual(proposal: dict | None, enrich: dict, symbol: str = "") -> dict:
    tv = (proposal or {}).get("thesis_validity") or {}
    price = _f((proposal or {}).get("current_price") or enrich.get("price") or enrich.get("latest_price"))
    entry = _f((proposal or {}).get("proposed_entry"))
    stop = _f((proposal or {}).get("proposed_stop"))
    t1 = _f((proposal or {}).get("proposed_target1"))
    vis = {
        "type": "thesis_validity_bar",
        "price": price,
        "entry": entry,
        "stop": stop,
        "target1": t1,
        "zone_status": tv.get("zone_status"),
        "drift_pct": tv.get("drift_pct") or (proposal or {}).get("price_drift_pct"),
        "planned_rr": tv.get("planned_rr"),
        "current_rr": tv.get("current_rr"),
        "actionable": tv.get("actionable"),
        "valid_low": tv.get("valid_low"),
        "valid_high": tv.get("valid_high"),
    }
    if entry and stop and t1 and price:
        try:
            from report_visuals import chart_thesis_validity_range
            chart = chart_thesis_validity_range(
                symbol=symbol,
                entry=entry,
                stop=stop,
                target=t1,
                price=price,
                valid_low=_f(tv.get("valid_low")) or None,
                valid_high=_f(tv.get("valid_high")) or None,
                zone_status=str(tv.get("zone_status") or ""),
                drift_pct=tv.get("drift_pct"),
            )
            if chart.get("chart_path"):
                vis["chart_path"] = chart["chart_path"]
                vis["caption"] = chart.get("caption")
        except Exception:
            pass
    return vis


def _price_levels_visual(enrich: dict) -> dict:
    price = _f(enrich.get("price") or enrich.get("latest_price"))
    return {
        "type": "price_levels",
        "price": price,
        "sma20_pct": enrich.get("sma20_pct"),
        "sma50_pct": enrich.get("sma50_pct"),
        "sma200_pct": enrich.get("sma200_pct"),
        "week52_high_pct": enrich.get("week52_high_pct"),
        "week52_low_pct": enrich.get("week52_low_pct"),
        "rsi": enrich.get("rsi"),
        "rvol": enrich.get("rvol"),
        "atr": enrich.get("atr"),
    }


def _risk_visual(holding: dict | None, enrich: dict, proposal: dict | None) -> dict:
    return {
        "type": "risk_profile",
        "beta": enrich.get("beta"),
        "atr": enrich.get("atr"),
        "volatility_w_pct": enrich.get("volatility_w_pct"),
        "portfolio_pct": holding.get("portfolio_pct") if holding else None,
        "unrealized_pnl_pct": holding.get("unrealized_pnl_pct") if holding else None,
        "stop": (proposal or {}).get("proposed_stop"),
        "zone_status": ((proposal or {}).get("thesis_validity") or {}).get("zone_status"),
    }


def _build_executive_summary(
    symbol: str,
    enrich: dict,
    synthesis: dict | None,
    holding: dict | None,
    wl: dict | None,
    report_type: str,
) -> dict:
    rec = _watchlist_rating(wl, synthesis)
    safety = (synthesis or {}).get("decision_safety") or "unknown"
    company = enrich.get("company") or symbol
    sector = enrich.get("sector") or (wl or {}).get("sector") or "—"
    ctx = "portfolio holding" if holding else "watchlist candidate"
    if report_type == "symbol_custom":
        ctx = "custom instrument"
    price = _resolve_price(symbol, enrich, holding)
    day = enrich.get("day_change_pct") or (holding or {}).get("day_change_pct")
    text = (
        f"{company} ({symbol}) is tracked as a {ctx} in the {sector} space. "
        f"Last price ${price:,.2f} ({_pct(day)} today). "
        f"Synthesis recommendation: {rec} with decision safety '{safety}'."
    )
    if holding:
        text += f" Position represents {_f(holding.get('portfolio_pct')):.2f}% of portfolio."
    conf = None
    if synthesis and synthesis.get("human_review_required"):
        conf = 45.0
    elif synthesis and safety == "safe":
        conf = 72.0
    elif wl and wl.get("holdings_llm_confidence") is not None:
        conf = _normalize_confidence(wl.get("holdings_llm_confidence"))
    elif synthesis and synthesis.get("confidence") is not None:
        conf = _normalize_confidence(synthesis.get("confidence"))
    return {
        "text": text,
        "recommendation": rec,
        "confidence": conf,
        "confidence_label": _confidence_label(conf),
    }


def _default_symbol_sections(report_type: str) -> list[str]:
    from report_synthesis import HOLDING_REPORT_SECTIONS
    return list(HOLDING_REPORT_SECTIONS)


def _sector_peer_rows(symbol: str, sector: str | None, *, limit: int = 10) -> list[dict]:
    sym = symbol.upper()
    sec = str(sector or "").strip()
    if not sec or sec == "—":
        return []
    cache = _enrichment_cache()
    peers: list[dict] = []
    for s, ec in cache.items():
        if not isinstance(ec, dict) or str(s).upper() == sym:
            continue
        if str(ec.get("sector") or "") != sec:
            continue
        peers.append({
            "symbol": str(s).upper(),
            "day_change_pct": ec.get("day_change_pct") or ec.get("perf_day_pct"),
            "pe": ec.get("pe"),
            "price": ec.get("price") or ec.get("latest_price"),
            "perf_month_pct": ec.get("perf_month_pct"),
        })
    peers.sort(key=lambda x: abs(_f(x.get("day_change_pct"))), reverse=True)
    return peers[:limit]


def _options_for_underlying(symbol: str) -> list[dict]:
    sym = symbol.upper()
    out: list[dict] = []
    try:
        import options_engine as oe
        for p in oe._fetch_schwab_option_positions():
            if str(p.get("underlying") or "").upper() != sym:
                continue
            out.append({
                "occ": p.get("occ_symbol"),
                "side": p.get("side"),
                "qty": p.get("qty"),
                "strike": p.get("strike"),
                "option_type": p.get("option_type"),
                "dte": p.get("dte"),
                "avg_entry": p.get("avg_entry"),
                "market_value": p.get("market_value"),
            })
    except Exception:
        pass
    return out


def build_symbol_report(
    symbol: str,
    *,
    report_type: str = "symbol_watchlist",
    sections: list[str] | None = None,
    prior_report: dict | None = None,
    continuity: dict | None = None,
    generation: int | None = None,
) -> dict:
    """Compose actionable analyst-grade symbol report JSON (v3 narrative synthesis)."""
    from report_synthesis import aggregate_holdings, compose_symbol_sections

    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol required")
    sections = list(sections or _default_symbol_sections(report_type))
    holding = _holding_for_symbol(sym)
    personal = aggregate_holdings(sym, _holding_rows_raw) if holding else {}
    enrich = _enriched(sym, holding or personal.get("primary"))
    wl = _watchlist_row(sym)
    synthesis = _synthesis(sym)
    agents = _agent_notes(sym)
    ensemble = _normalize_ensemble_row(_ensemble(sym))
    news = _news_for_symbol(sym, limit=8)
    proposal = _proposal_context(sym)
    sector_name = enrich.get("sector") or (wl or {}).get("sector")
    peer_rows = _sector_peer_rows(sym, sector_name)
    option_rows = _options_for_underlying(sym)
    for extra in ("peer_comparison", "options_strategy"):
        if extra == "peer_comparison" and peer_rows and extra not in sections:
            sections.append(extra)
        if extra == "options_strategy" and option_rows and extra not in sections:
            sections.append(extra)

    if report_type == "symbol_holding" and not holding:
        report_type = "symbol_watchlist"
    if report_type == "symbol_watchlist" and holding:
        report_type = "symbol_holding"

    exec_metrics = _build_executive_summary(sym, enrich, synthesis, holding, wl, report_type)
    thesis_st = None
    try:
        from report_synthesis import thesis_status
        thesis_st = thesis_status(synthesis, proposal, enrich)
    except Exception:
        thesis_st = "Review"

    if continuity is None and prior_report is not None:
        try:
            from report_lineage import compute_continuity
            continuity = compute_continuity(
                prior_report,
                price=_resolve_price(sym, enrich, holding),
                recommendation=str(exec_metrics.get("recommendation") or "Review"),
                unrealized_pnl_pct=personal.get("unrealized_pnl_pct") or (holding.get("gain_loss_pct") if holding else None),
                thesis_status=thesis_st or "Review",
                fingerprint=None,
            )
        except Exception:
            continuity = None

    gen_num = generation or (continuity or {}).get("generation") or 1

    meta = {
        "report_type": report_type,
        "type_label": REPORT_TYPES.get(report_type, {}).get("label", report_type),
        "symbol": sym,
        "title": f"{sym} — {REPORT_TYPES.get(report_type, {}).get('label', 'Analyst Report')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": enrich.get("company") or personal.get("name"),
        "sector": enrich.get("sector") or (wl or {}).get("sector"),
        "context": "holding" if holding else "watchlist",
        "sections_included": sections,
        "version": "3.0",
        "document_class": "summary_prospectus",
        "generation": gen_num,
        "prior_report_at": ((prior_report or {}).get("meta") or {}).get("generated_at"),
    }

    meta["kpis"] = {
        "price": _resolve_price(sym, enrich, holding),
        "day_change_pct": enrich.get("day_change_pct"),
        "recommendation": exec_metrics.get("recommendation"),
        "confidence": exec_metrics.get("confidence"),
        "confidence_label": exec_metrics.get("confidence_label"),
        "portfolio_pct": personal.get("portfolio_pct") or (holding.get("portfolio_pct") if holding else None),
        "portfolio_value": personal.get("market_value") or (holding.get("market_value") if holding else None),
        "unrealized_pnl": personal.get("unrealized_pnl") or (holding.get("gain_loss") if holding else None),
        "unrealized_pnl_pct": personal.get("unrealized_pnl_pct") or (holding.get("gain_loss_pct") if holding else None),
        "entry_price": personal.get("entry_price"),
        "thesis_status": thesis_st,
        "sector": meta.get("sector"),
    }

    report_sections = compose_symbol_sections(
        symbol=sym,
        enrich=enrich,
        holding=holding,
        personal=personal,
        wl=wl,
        synthesis=synthesis,
        agents=agents,
        ensemble=ensemble,
        news=news,
        proposal=proposal,
        sections=sections,
        report_type=report_type,
        exec_metrics=exec_metrics,
        continuity=continuity,
        peer_rows=peer_rows,
        option_rows=option_rows,
    )

    visuals: list[dict] = []
    if peer_rows:
        try:
            from report_visuals import chart_peer_movers
            pm = chart_peer_movers(
                peer_rows, stem=sym, title=f"{sector_name or 'Sector'} — Peer Day Movers (%)",
            )
            if pm.get("chart_path"):
                visuals.append(pm)
        except Exception:
            pass
    try:
        from report_lineage import chart_continuity_points
        from report_visuals import chart_report_lineage
        pts = chart_continuity_points(sym)
        if len(pts) >= 2:
            lc = chart_report_lineage(sym, pts, _resolve_price(sym, enrich, holding))
            if lc.get("chart_path"):
                visuals.append(lc)
    except Exception:
        pass
    if "technical_analysis" in sections:
        visuals.append(_price_levels_visual(enrich))
        _attach_symbol_charts(sym, enrich, visuals, proposal)
    if "risk_assessment" in sections:
        if proposal:
            visuals.append(_thesis_visual(proposal, enrich, sym))
        visuals.append(_risk_visual(holding, enrich, proposal))

    sources = [
        {"id": "ticker_enrichment_cache", "label": "Market enrichment"},
        {"id": "watchlist_final_synthesis", "label": "Watchlist synthesis", "present": bool(synthesis)},
        {"id": "watchlist_agent_results", "label": "Agent notes", "count": len(agents)},
        {"id": "portfolio_news", "label": "News/catalysts", "count": len(news)},
        {"id": "inference_ensemble_results", "label": "Layer 4 ensemble", "present": bool(ensemble)},
        {"id": "paper_trade_proposals", "label": "Broker proposal", "present": bool(proposal)},
    ]

    return {
        "meta": meta,
        "sections": report_sections,
        "visuals": visuals,
        "sources": sources,
        "export_options": {"available_sections": list(SECTION_IDS), "selected": sections},
    }


def _portal_actions(days: int = 1, limit: int = 30, classes: str | None = None) -> list[dict]:
    try:
        import reports_portal as rp
        res = rp.action_items(days=days, limit=limit, classes=classes)
        return res.get("actions") or []
    except Exception:
        return []


def _action_rank(sev: str) -> int:
    return {"critical": 4, "urgent": 3, "warning": 2}.get(str(sev or "").lower(), 1)


def _dedupe_actions(actions: list[dict], limit: int = 25) -> list[dict]:
    """Prefer descriptive text; drop near-duplicates by class+symbol."""
    ranked = sorted(actions, key=lambda a: (_action_rank(a.get("severity", "")), len(a.get("text") or "")), reverse=True)
    out: list[dict] = []
    seen: set[str] = set()
    for a in ranked:
        key = f"{a.get('action_class')}|{(a.get('symbol') or '').upper()}|{(a.get('text') or '')[:48].lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
        if len(out) >= limit:
            break
    return out


def _recovery_actions(recovery_rows: list[dict], *, limit: int = 8) -> list[dict]:
    out = []
    for r in recovery_rows[:limit]:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        verdict = r.get("analyst_verdict") or r.get("verdict") or "review"
        exit_type = r.get("exit_type") or ""
        out.append({
            "id": f"recovery-{sym}",
            "text": f"Recovery {sym}: {verdict}" + (f" ({exit_type})" if exit_type else "") + " — review relist thesis",
            "symbol": sym,
            "severity": "warning",
            "action_class": "recovery",
            "route": f"/v3/risk?symbol={sym}&drawer=recovery",
            "route_label": "Recovery",
            "status": "open",
        })
    return out


def _health_finding_actions(findings: list[dict], *, limit: int = 6) -> list[dict]:
    out = []
    for i, f in enumerate(findings[:limit]):
        msg = str(f.get("message") or "").strip()
        if not msg:
            continue
        sev = str(f.get("severity") or "warning").lower()
        route = "/v3/trading" if "proposal" in msg.lower() else "/v3/system"
        label = "Trading" if route == "/v3/trading" else "System"
        out.append({
            "id": f"health-{i}",
            "text": msg,
            "severity": sev if sev in ("urgent", "warning", "critical") else "warning",
            "action_class": "system_health",
            "route": route,
            "route_label": label,
            "status": "open",
        })
    return out


def _merge_digest_actions(
    portal: list[dict],
    *,
    recovery: list[dict] | None = None,
    findings: list[dict] | None = None,
    limit: int = 25,
) -> list[dict]:
    merged = list(portal) + _recovery_actions(recovery or []) + _health_finding_actions(findings or [])
    return _dedupe_actions(merged, limit=limit)


def _holding_rows(min_mv: float = 50) -> list[dict]:
    h = _load(STATE_DIR / "holdings.json")
    return [
        x for x in h.get("holdings") or []
        if x.get("symbol") and not x.get("is_cash") and _f(x.get("market_value")) >= min_mv
    ]


def _watchlist_rows(*, exclude_held: bool = False, limit: int = 80) -> list[dict]:
    held = {str(h.get("symbol", "")).upper() for h in _holding_rows()} if exclude_held else set()
    rows = _db_query(
        """SELECT wi.symbol, wi.score, wi.trend, wi.status, wi.holdings_llm_action,
                  fs.recommendation, sp.sector
           FROM watchlist_items wi
           LEFT JOIN watchlist_final_synthesis fs ON fs.symbol = wi.symbol
           LEFT JOIN symbol_profiles sp ON sp.symbol = wi.symbol
           WHERE wi.status NOT IN ('removed')
           ORDER BY wi.score DESC NULLS LAST LIMIT %s""",
        (int(limit),),
    ) or []
    out = []
    for r in rows:
        sym = str(r.get("symbol", "")).upper()
        if exclude_held and sym in held:
            continue
        out.append(dict(r))
    return out


def _holdings_by_symbol() -> dict[str, dict]:
    return {
        str(h.get("symbol", "")).upper(): h
        for h in _holding_rows()
        if h.get("symbol")
    }


def _symbol_row_summary(
    sym: str,
    *,
    holding: dict | None = None,
    wl_map: dict | None = None,
    enrich_cache: dict | None = None,
    fast: bool = False,
) -> dict:
    holding = holding if holding is not None else (None if fast else _holding_for_symbol(sym))
    enrich = _enriched(sym, holding, fast=fast, enrich_cache=enrich_cache)
    wl = (wl_map or {}).get(sym) if wl_map is not None else _watchlist_row(sym)
    rec = str((wl or {}).get("recommendation") or (wl or {}).get("holdings_llm_action") or enrich.get("recommendation") or "Review")
    price = _resolve_price(sym, enrich, holding)
    is_holding = bool(holding)
    route = f"/v3/portfolio?symbol={sym}" if is_holding else f"/v3/watchlist?symbol={sym}"
    return {
        "symbol": sym,
        "recommendation": rec,
        "price": price,
        "day_change_pct": enrich.get("day_change_pct") or (holding or {}).get("day_change_pct"),
        "portfolio_pct": (holding or {}).get("portfolio_pct"),
        "market_value": (holding or {}).get("market_value"),
        "sector": enrich.get("sector") or (wl or {}).get("sector"),
        "score": _f((wl or {}).get("score")) if (wl or {}).get("score") is not None else None,
        "trend": (wl or {}).get("trend"),
        "is_holding": is_holding,
        "route": route,
        "route_label": "Portfolio" if is_holding else "Watchlist",
        "action_class": "portfolio_review",
        "severity": "info",
        "text": f"{sym}: {rec} · {_pct(enrich.get('day_change_pct') or (holding or {}).get('day_change_pct'))} today",
    }


def _watchlist_map(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    rows = _db_query(
        """SELECT wi.symbol, wi.score, wi.trend, wi.holdings_llm_action,
                  fs.recommendation, sp.sector
           FROM watchlist_items wi
           LEFT JOIN watchlist_final_synthesis fs ON fs.symbol = wi.symbol
           LEFT JOIN symbol_profiles sp ON sp.symbol = wi.symbol
           WHERE wi.symbol = ANY(%s)""",
        (symbols,),
    ) or []
    return {str(r.get("symbol", "")).upper(): dict(r) for r in rows}


def _events_to_actions(events: list[dict]) -> list[dict]:
    out = []
    kind_route = {
        "stop_hit": ("/v3/risk", "Risk", "stop_triggered", "urgent"),
        "thesis_invalidation": ("/v3/risk", "Risk", "risk_review", "warning"),
        "large_move": ("/v3/portfolio", "Portfolio", "portfolio_review", "warning"),
    }
    for i, e in enumerate(events):
        sym = (e.get("symbol") or "").upper() or None
        base, label, cls, sev = kind_route.get(e.get("kind"), ("/v3/reports", "Reports", "informational", "info"))
        route = f"{base}?symbol={sym}" if sym and "?" not in base else base
        if sym and base == "/v3/risk":
            route = f"/v3/risk?symbol={sym}"
        out.append({
            "id": f"evt-{i}",
            "text": e.get("text") or "",
            "symbol": sym,
            "severity": e.get("severity") or sev,
            "action_class": cls,
            "route": route,
            "route_label": label,
            "status": "open",
        })
    return out


def build_aggregate_symbol_report(report_type: str, sections: list[str] | None = None) -> dict:
    """Portfolio-wide report when no symbol filter — all holdings, watchlist, or union."""
    sections = sections or list(SECTION_IDS)
    type_meta = {
        "symbol_holding": ("All Portfolio Holdings", "holding"),
        "symbol_watchlist": ("All Watchlist Items", "watchlist"),
        "symbol_custom": ("All Tracked Instruments", "tracked"),
    }
    label, ctx = type_meta.get(report_type, ("All Instruments", "tracked"))

    holdings_map = _holdings_by_symbol()
    symbols: list[str] = []
    if report_type == "symbol_holding":
        symbols = sorted(
            holdings_map.keys(),
            key=lambda s: _f(holdings_map[s].get("market_value")),
            reverse=True,
        )[:40]
    elif report_type == "symbol_watchlist":
        symbols = [str(r.get("symbol", "")).upper() for r in _watchlist_rows(exclude_held=True)][:40]
    else:
        held_syms = list(holdings_map.keys())
        wl_syms = [str(r.get("symbol", "")).upper() for r in _watchlist_rows(exclude_held=False)]
        symbols = list(dict.fromkeys(held_syms + [s for s in wl_syms if s not in holdings_map]))[:50]

    enrich_cache = _enrichment_cache()
    wl_map = _watchlist_map(symbols)
    items = [
        _symbol_row_summary(
            s,
            holding=holdings_map.get(s),
            wl_map=wl_map,
            enrich_cache=enrich_cache,
            fast=True,
        )
        for s in symbols if s
    ]
    totals = _load(STATE_DIR / "holdings.json").get("portfolio_totals") or {}

    report_sections: list[dict] = []
    if "executive_summary" in sections:
        recs = {}
        for it in items:
            r = str(it.get("recommendation") or "Review")
            recs[r] = recs.get(r, 0) + 1
        top_rec = max(recs.items(), key=lambda x: x[1])[0] if recs else "Review"
        report_sections.append({
            "id": "executive_summary",
            "title": "Executive Summary",
            "content": (
                f"{label}: {len(items)} instruments. "
                f"Portfolio ${totals.get('total_value', 0):,.0f} ({_pct(totals.get('day_change_pct'))} today). "
                f"Dominant stance: {top_rec}."
            ),
            "metrics": {"instrument_count": len(items), "recommendation_mix": recs},
        })

    if "recommendation" in sections:
        report_sections.append({
            "id": "recommendation",
            "title": "Instrument Action Matrix",
            "bullets": [
                f"{it['symbol']}: {it.get('recommendation')} · "
                f"${_f(it.get('price')):,.2f} ({_pct(it.get('day_change_pct'))})"
                + (f" · { _f(it.get('portfolio_pct')):.2f}% port" if it.get("portfolio_pct") else "")
                + (f" · score {it.get('score')}" if it.get("score") is not None else "")
                for it in items[:40]
            ] or ["No instruments in scope."],
        })

    if "risk_assessment" in sections:
        risks = [
            f"{it['symbol']}: underwater / weak — review stop & thesis"
            for it in items
            if _f(it.get("day_change_pct")) <= -3 or str(it.get("recommendation", "")).upper() in ("SELL", "TRIM", "AVOID")
        ][:20]
        report_sections.append({
            "id": "risk_assessment",
            "title": "Risk Flags",
            "bullets": risks or ["No material risk flags across the universe."],
        })

    if "technical_analysis" in sections:
        if report_type == "symbol_watchlist":
            tech_bullets = [
                f"{it['symbol']}: score {_f(it.get('score')):.0f} · {it.get('trend') or '—'} · {it.get('sector') or '—'}"
                for it in sorted(items, key=lambda x: _f(x.get("score")), reverse=True)[:15]
            ]
            tech_title = "Watchlist Leaders (Score)"
        else:
            tech_bullets = [
                f"{it['symbol']}: {_pct(it.get('day_change_pct'))} · {it.get('sector') or '—'}"
                for it in sorted(items, key=lambda x: abs(_f(x.get("day_change_pct"))), reverse=True)[:15]
            ]
            tech_title = "Day Movers (Top)"
        report_sections.append({
            "id": "technical_analysis",
            "title": tech_title,
            "bullets": tech_bullets or ["No momentum data."],
        })

    agg_visuals: list[dict] = []
    try:
        from report_visuals import chart_portfolio_movers, chart_coverage_bars, chart_sector_allocation
        stem = report_type.replace("symbol_", "all_")
        if report_type in ("symbol_holding", "symbol_custom"):
            holdings = _holding_rows()
            mv = chart_portfolio_movers(holdings, stem=stem, limit=12)
            if mv.get("chart_path"):
                agg_visuals.append(mv)
        if report_type == "symbol_watchlist":
            top_scores = sorted(items, key=lambda x: _f(x.get("score")), reverse=True)[:12]
            if top_scores:
                sc = chart_coverage_bars(
                    [it["symbol"] for it in reversed(top_scores)],
                    [int(_f(it.get("score"))) for it in reversed(top_scores)],
                    stem=stem,
                    title="Watchlist Scores (Top)",
                )
                if sc.get("chart_path"):
                    agg_visuals.append(sc)
        by_sec: dict[str, float] = {}
        for it in items:
            sec = str(it.get("sector") or "Unknown")
            if report_type == "symbol_watchlist":
                by_sec[sec] = by_sec.get(sec, 0) + 1
            else:
                by_sec[sec] = by_sec.get(sec, 0) + _f(it.get("portfolio_pct"))
        if by_sec:
            sa = chart_sector_allocation(
                [{"sector": k, "weight_pct": v} for k, v in by_sec.items()],
                stem=stem,
                title="Watchlist Items by Sector" if report_type == "symbol_watchlist" else "Portfolio Weight by Sector (%)",
            )
            if sa.get("chart_path"):
                agg_visuals.append(sa)
    except Exception:
        pass

    action_items = [
        {
            "id": f"row-{it['symbol']}",
            "text": it["text"],
            "symbol": it["symbol"],
            "severity": "warning" if str(it.get("recommendation", "")).upper() in ("SELL", "TRIM", "AVOID") else "info",
            "action_class": it.get("action_class", "portfolio_review"),
            "route": it.get("route"),
            "route_label": it.get("route_label"),
            "status": "open",
        }
        for it in items[:25]
        if str(it.get("recommendation", "")).upper() not in ("HOLD", "REVIEW", "")
    ][:20]

    return {
        "meta": {
            "report_type": report_type,
            "type_label": REPORT_TYPES.get(report_type, {}).get("label", label),
            "scope": "all",
            "title": f"{label} — {datetime.now().strftime('%Y-%m-%d')}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "instrument_count": len(items),
            "version": "1.2",
            "kpis": {
                "instrument_count": len(items),
                "portfolio_value": totals.get("total_value"),
                "day_change_pct": totals.get("day_change_pct"),
            },
        },
        "sections": report_sections,
        "items": items,
        "visuals": agg_visuals,
        "action_items": action_items,
        "sources": [
            {"id": "holdings.json", "label": "Portfolio holdings"},
            {"id": "watchlist_items", "label": "Watchlist"},
            {"id": "ticker_enrichment_cache", "label": "Market enrichment"},
        ],
        "export_options": {"available_sections": sections, "selected": sections},
    }


def build_all_sectors_report(sections: list[str] | None = None) -> dict:
    """Sector overview when no sector filter — all sectors with holdings weight."""
    sections = sections or [
        "executive_summary", "investment_thesis", "technical_analysis",
        "fundamental_news", "risk_assessment", "recommendation", "key_risks",
    ]
    holdings = _holding_rows()
    enrich_cache = _load(STATE_DIR / "ticker_enrichment_cache.json")
    by_sector: dict[str, dict] = {}

    for h in holdings:
        sym = str(h.get("symbol", "")).upper()
        ec = enrich_cache.get(sym, {}) if isinstance(enrich_cache, dict) else {}
        sec = str(ec.get("sector") or h.get("sector") or "Unknown")
        bucket = by_sector.setdefault(sec, {
            "sector": sec, "weight_pct": 0.0, "symbols": [], "day_changes": [], "count": 0,
        })
        bucket["weight_pct"] += _f(h.get("portfolio_pct"))
        bucket["symbols"].append(sym)
        bucket["count"] += 1
        if h.get("day_change_pct") is not None:
            bucket["day_changes"].append(_f(h.get("day_change_pct")))

    sector_rows = sorted(by_sector.values(), key=lambda x: x["weight_pct"], reverse=True)
    totals = _load(STATE_DIR / "holdings.json").get("portfolio_totals") or {}

    report_sections: list[dict] = []
    if "executive_summary" in sections:
        report_sections.append({
            "id": "executive_summary",
            "title": "All Sectors — Executive Summary",
            "content": (
                f"{len(sector_rows)} sectors represented across {len(holdings)} holdings. "
                f"Portfolio ${totals.get('total_value', 0):,.0f} ({_pct(totals.get('day_change_pct'))} today)."
            ),
            "metrics": {"sector_count": len(sector_rows), "holding_count": len(holdings)},
        })

    if "technical_analysis" in sections:
        bullets = []
        for row in sector_rows[:15]:
            avg_day = sum(row["day_changes"]) / len(row["day_changes"]) if row["day_changes"] else None
            bullets.append(
                f"{row['sector']}: {_f(row['weight_pct']):.1f}% weight · "
                f"{row['count']} names · avg day {_pct(avg_day)}"
            )
        report_sections.append({
            "id": "technical_analysis",
            "title": "Sector Snapshot",
            "bullets": bullets or ["No sector allocation data."],
        })

    if "recommendation" in sections:
        report_sections.append({
            "id": "recommendation",
            "title": "Sector Drill-Down",
            "bullets": [
                f"{row['sector']}: top names {', '.join(row['symbols'][:5])}"
                for row in sector_rows[:12]
            ],
        })

    sector_visuals: list[dict] = []
    try:
        from report_visuals import chart_sector_allocation, chart_peer_movers
        sa = chart_sector_allocation(
            [{"sector": r["sector"], "weight_pct": r["weight_pct"]} for r in sector_rows],
            stem="all_sectors",
        )
        if sa.get("chart_path"):
            sector_visuals.append(sa)
        peer_rows = []
        for h in sorted(holdings, key=lambda x: abs(_f(x.get("day_change_pct"))), reverse=True)[:12]:
            sym = str(h.get("symbol", "")).upper()
            ec = enrich_cache.get(sym, {}) if isinstance(enrich_cache, dict) else {}
            peer_rows.append({
                "symbol": sym,
                "day_change_pct": h.get("day_change_pct"),
                "sector": ec.get("sector"),
            })
        pm = chart_peer_movers(peer_rows, stem="all_sectors", title="Cross-Sector Day Movers (%)")
        if pm.get("chart_path"):
            sector_visuals.append(pm)
    except Exception:
        pass

    action_items = [
        {
            "id": f"sec-{i}",
            "text": f"Review {row['sector']} — {_f(row['weight_pct']):.1f}% portfolio weight",
            "severity": "warning" if _f(row["weight_pct"]) > 15 else "info",
            "action_class": "portfolio_review",
            "route": f"/v3/sectors",
            "route_label": "Sectors",
            "status": "open",
        }
        for i, row in enumerate(sector_rows[:12])
    ]

    return {
        "meta": {
            "report_type": "sector_theme",
            "type_label": "All Sectors Overview",
            "scope": "all",
            "title": f"All Sectors — Theme Report — {datetime.now().strftime('%Y-%m-%d')}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sector_count": len(sector_rows),
            "version": "1.2",
            "kpis": {
                "sector_count": len(sector_rows),
                "holding_count": len(holdings),
                "portfolio_value": totals.get("total_value"),
            },
        },
        "sections": report_sections,
        "sectors": [{"sector": r["sector"], "weight_pct": r["weight_pct"], "symbols": r["symbols"][:8]} for r in sector_rows],
        "visuals": sector_visuals,
        "action_items": action_items,
        "sources": [
            {"id": "holdings.json", "label": "Holdings"},
            {"id": "symbol_profiles", "label": "Sector profiles"},
        ],
        "export_options": {"available_sections": sections, "selected": sections},
    }


def build_daily_digest(*, days: int = 1) -> dict:
    """Daily intelligence digest — memorializes alerts, health, proposals."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

    health = _load(STATE_DIR / "health_agent_status.json")
    overview = _load(STATE_DIR / "holdings.json").get("portfolio_totals") or {}

    try:
        from generate_daily_intelligence_report import generate_report as _gen_intel
        intel = _gen_intel()
    except Exception as e:
        intel = {"error": str(e)[:200]}

    try:
        import reports_portal as rp
        actions = rp.action_items(days=days, limit=50)
        summary = rp.portal_summary(days=days)
    except Exception as e:
        actions, summary = {"actions": []}, {"kpis": {}}

    proposals = _db_query(
        """SELECT status, COUNT(*) AS cnt FROM paper_trade_proposals
           WHERE created_at > NOW() - make_interval(days => %s) GROUP BY status""",
        (int(days),),
    ) or []

    action_list = actions.get("actions") or []
    findings = sorted(
        health.get("findings") or [],
        key=lambda f: {"critical": 0, "urgent": 1, "warning": 2}.get(str(f.get("severity", "")).lower(), 3),
    )
    digest_actions = _merge_digest_actions(action_list, findings=findings, limit=25)

    sections = [
        {
            "id": "executive_summary",
            "title": "Daily Intelligence Summary",
            "content": (
                f"Portfolio ${overview.get('total_value', 0):,.0f}, today {_pct(overview.get('day_change_pct'))}. "
                f"Health {health.get('overall_score', '—')} ({health.get('status', '—')}). "
                f"{len(digest_actions)} actionable items — use the Action Queue above to address each one."
            ),
        },
        {
            "id": "health_context",
            "title": "Health Agent Findings",
            "content": (
                f"{len(findings)} health signals this period — "
                f"{sum(1 for a in digest_actions if a.get('action_class') == 'system_health')} routed to Action Queue."
            ),
            "bullets": [] if digest_actions else [
                f"{f.get('severity', '').upper()}: {f.get('message', '')}"
                for f in findings[:5]
            ] or ["Health agent reports nominal."],
        },
        {
            "id": "risk_assessment",
            "title": "Risk & Protection Alerts",
            "content": "Stop, protection, and risk items are in the Action Queue — click to open the address modal.",
            "bullets": [],
        },
        {
            "id": "fundamental_news",
            "title": "Intelligence Layer Summary",
            "bullets": [
                f"Decision safety: {intel.get('decision_safety', intel.get('safety_counts', {}))}",
                f"Human reviews pending: {intel.get('human_reviews_required', len(intel.get('human_reviews') or []))}",
                f"Recent alerts (24h): {intel.get('alerts_24h', len(intel.get('recent_alerts') or []))}",
                f"Hermes research (24h): {(intel.get('hermes_research') or {}).get('research_24h', 0)}",
            ],
        },
        {
            "id": "recommendation",
            "title": "Proposal Outcomes",
            "bullets": [f"{r.get('status')}: {r.get('cnt')}" for r in proposals] or ["No proposal activity."],
        },
    ]

    digest_visuals: list[dict] = []
    try:
        from report_visuals import chart_health_gauge, chart_portfolio_movers, chart_proposal_pipeline
        hs = _f(health.get("overall_score"))
        if hs:
            digest_visuals.append(chart_health_gauge(hs, str(health.get("status") or ""), stem="daily_digest"))
        holdings_rows = _load(STATE_DIR / "holdings.json").get("holdings") or []
        mv = chart_portfolio_movers(holdings_rows, stem="daily_digest")
        if mv.get("chart_path"):
            digest_visuals.append(mv)
        pp = chart_proposal_pipeline(proposals, stem="daily_digest")
        if pp.get("chart_path"):
            digest_visuals.append(pp)
    except Exception:
        pass

    totals = overview if isinstance(overview, dict) else {}
    return {
        "meta": {
            "report_type": "daily_digest",
            "type_label": REPORT_TYPES["daily_digest"]["label"],
            "title": f"Daily Intelligence Digest — {datetime.now().strftime('%Y-%m-%d')}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": days,
            "version": "1.1",
            "kpis": {
                "portfolio_value": totals.get("total_value"),
                "day_change_pct": totals.get("day_change_pct"),
                "health_score": health.get("overall_score"),
                "health_status": health.get("status"),
                "action_items": len(digest_actions),
            },
        },
        "sections": sections,
        "visuals": digest_visuals,
        "action_items": digest_actions,
        "kpis": summary.get("kpis") or {},
        "sources": [
            {"id": "health_agent_status", "label": "Health agent"},
            {"id": "reports_portal", "label": "Operator actions"},
            {"id": "generate_daily_intelligence_report", "label": "DB intelligence"},
        ],
        "export_options": {"available_sections": [s["id"] for s in sections], "selected": [s["id"] for s in sections]},
    }


def build_weekly_review() -> dict:
    """Weekly portfolio & watchlist synthesis — analyst-grade with DB enrichment."""
    perf = _load(STATE_DIR / "performance_history.json")
    periods = perf.get("periods") or {}
    holdings = _load(STATE_DIR / "holdings.json")
    totals = holdings.get("portfolio_totals") or {}
    health = _load(STATE_DIR / "health_agent_status.json")

    weekly_db: dict = {}
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from generate_weekly_docx import _get_conn, gather_weekly_data
        conn = _get_conn()
        try:
            weekly_db = gather_weekly_data(conn)
        finally:
            conn.close()
    except Exception:
        weekly_db = {}

    pt = weekly_db.get("paper_trades") or {}
    wins = int(pt.get("wins") or 0)
    losses = int(pt.get("losses") or 0)
    wr = round(wins / max(wins + losses, 1) * 100, 1)

    sections = [
        {
            "id": "executive_summary",
            "title": "Weekly Executive Summary",
            "content": (
                f"Portfolio ${totals.get('total_value', 0):,.0f} across "
                f"{weekly_db.get('positions', len([h for h in holdings.get('holdings', []) if not h.get('is_cash')]))} positions. "
                f"1W {periods.get('1W', {}).get('change_pct', '—')}%, "
                f"1M {periods.get('1M', {}).get('change_pct', '—')}%, "
                f"YTD {periods.get('YTD', {}).get('change_pct', '—')}%. "
                f"Paper trades: {pt.get('open_trades', 0)} open, {wins + losses} closed ({wr}% win rate)."
            ),
            "metrics": {
                "health_score": health.get("overall_score"),
                "health_status": health.get("status"),
                "cash": weekly_db.get("cash"),
            },
        },
        {
            "id": "risk_assessment",
            "title": "Risk & Thesis Updates",
            "bullets": [
                f"{h.get('symbol')}: {_pct(h.get('unrealized_pnl_pct'))} unrealized"
                for h in (holdings.get("holdings") or [])
                if _f(h.get("unrealized_pnl_pct")) < -10
            ][:10] or ["No positions below -10% unrealized."],
        },
        {
            "id": "fundamental_news",
            "title": "Recovery Watch & CIO Activity",
            "bullets": [
                *(f"Recovery {r.get('symbol')}: {r.get('analyst_verdict')} ({r.get('exit_type')})"
                  for r in (weekly_db.get("recovery") or [])[:8]),
                *(f"CIO {r.get('action')}: {r.get('cnt')}" for r in (weekly_db.get("cio_decisions") or [])[:6]),
            ] or ["No recovery watch or CIO decision activity this week."],
        },
        {
            "id": "recommendation",
            "title": "Proposal & Agent Activity",
            "bullets": [
                *(f"Proposals {r.get('status')}: {r.get('cnt')}" for r in (weekly_db.get("proposals") or [])),
                *(f"{r.get('agent')}: {r.get('analyses')} analyses (avg conf {r.get('avg_conf')})"
                  for r in (weekly_db.get("agent_activity") or [])[:6]),
            ] or ["No proposal or agent activity recorded."],
        },
    ]
    findings = sorted(
        health.get("findings") or [],
        key=lambda f: {"critical": 0, "urgent": 1, "warning": 2}.get(str(f.get("severity", "")).lower(), 3),
    )
    weekly_actions = _merge_digest_actions(
        _portal_actions(days=7, limit=40),
        recovery=weekly_db.get("recovery") or [],
        findings=findings,
        limit=25,
    )
    sections.append({
        "id": "agent_synthesis",
        "title": "7-Day Operator Actions",
        "content": (
            f"{len(weekly_actions)} actionable items this week — "
            "use the Action Queue above (click any row to open the address modal)."
        ),
        "bullets": [],
    })
    sections.append({
        "id": "health_context",
        "title": "System Health Summary",
        "content": (
            f"{len(findings)} system health signals — "
            f"{sum(1 for a in weekly_actions if a.get('action_class') == 'system_health')} in Action Queue."
        ),
        "bullets": [] if weekly_actions else [
            f"{f.get('severity', '').upper()}: {f.get('message', '')}"
            for f in findings[:6]
        ] or ["Health agent reports nominal."],
    })

    weekly_visuals: list[dict] = []
    try:
        from report_visuals import chart_health_gauge, chart_period_performance, chart_proposal_pipeline
        hs = _f(health.get("overall_score"))
        if hs:
            weekly_visuals.append(chart_health_gauge(hs, str(health.get("status") or ""), stem="weekly"))
        pp_chart = chart_period_performance(periods, stem="weekly")
        if pp_chart.get("chart_path"):
            weekly_visuals.append(pp_chart)
        prop_rows = weekly_db.get("proposals") or []
        if prop_rows:
            pipe = chart_proposal_pipeline(
                [{"status": r.get("status"), "cnt": r.get("cnt")} for r in prop_rows],
                stem="weekly",
            )
            if pipe.get("chart_path"):
                weekly_visuals.append(pipe)
    except Exception:
        pass

    return {
        "meta": {
            "report_type": "weekly_review",
            "type_label": REPORT_TYPES["weekly_review"]["label"],
            "title": f"Weekly Portfolio Review — {datetime.now().strftime('%Y-%m-%d')}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period_start": weekly_db.get("period_start"),
            "period_end": weekly_db.get("period_end"),
            "version": "1.1",
            "kpis": {
                "portfolio_value": totals.get("total_value"),
                "health_score": health.get("overall_score"),
                "health_status": health.get("status"),
                "win_rate": wr,
                "action_items": len(weekly_actions),
            },
        },
        "sections": sections,
        "visuals": weekly_visuals,
        "action_items": weekly_actions,
        "periods": {k: v for k, v in periods.items() if isinstance(v, dict)},
        "weekly_data": {k: weekly_db.get(k) for k in ("paper_trades", "proposals", "recovery", "cio_decisions")},
        "export_options": {"available_sections": [s["id"] for s in sections], "selected": [s["id"] for s in sections]},
    }


def build_event_driven_report(
    *,
    symbol: str | None = None,
    event_filter: str = "all",
    hours: int = 24,
) -> dict:
    """Event-driven report — stops, thesis invalidations, large moves."""
    sym = (symbol or "").strip().upper() or None
    filt = (event_filter or "all").lower()
    if filt not in EVENT_FILTERS:
        filt = "all"

    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

    events: list[dict] = []
    try:
        import reports_portal as rp
        actions = rp.action_items(days=max(1, hours // 24 + 1), limit=200).get("actions") or []
        for a in actions:
            cls = a.get("action_class") or ""
            if sym and (a.get("symbol") or "").upper() != sym:
                continue
            if cls == "stop_triggered" and filt in ("all", "stop_hit"):
                events.append({"kind": "stop_hit", "symbol": a.get("symbol"), "text": a.get("text"), "severity": a.get("severity"), "at": a.get("created_at")})
            elif cls in ("risk_review", "unprotected_position") and filt in ("all", "thesis_invalidation"):
                events.append({"kind": "thesis_invalidation", "symbol": a.get("symbol"), "text": a.get("text"), "severity": a.get("severity"), "at": a.get("created_at")})
    except Exception:
        pass

    alerts = _db_query(
        """SELECT alert_type, symbol, severity, left(raw_text, 200) AS summary, created_at
           FROM alert_events
           WHERE created_at > NOW() - make_interval(hours => %s)
             AND (%s IS NULL OR UPPER(symbol) = %s)
           ORDER BY created_at DESC LIMIT 40""",
        (int(hours), sym, sym),
    ) or []
    for a in alerts:
        atype = (a.get("alert_type") or "").lower()
        text = a.get("summary") or ""
        if filt in ("all", "large_move") and ("large" in atype or "large" in text.lower() or "move" in text.lower()):
            events.append({"kind": "large_move", "symbol": a.get("symbol"), "text": text, "severity": a.get("severity"), "at": a.get("created_at")})

    enrich_cache = _load(STATE_DIR / "ticker_enrichment_cache.json")
    holdings = _load(STATE_DIR / "holdings.json").get("holdings") or []
    for h in holdings:
        hsym = str(h.get("symbol", "")).upper()
        if sym and hsym != sym:
            continue
        day_chg = _f(h.get("day_change_pct"))
        if filt in ("all", "large_move") and abs(day_chg) >= 4.0:
            events.append({
                "kind": "large_move",
                "symbol": hsym,
                "text": f"{hsym} moved {_pct(day_chg)} today (portfolio position).",
                "severity": "urgent" if abs(day_chg) >= 7 else "warning",
                "at": datetime.now(timezone.utc).isoformat(),
            })

    proposals = _db_query(
        """SELECT symbol, status, proposed_stop, current_price, price_drift_pct, strategy_id
           FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')
             AND (%s IS NULL OR UPPER(symbol) = %s)
           ORDER BY updated_at DESC LIMIT 30""",
        (sym, sym),
    ) or []
    for p in proposals:
        row = dict(p)
        try:
            from broker_thesis_validity import attach_thesis_validity
            attach_thesis_validity(row)
        except Exception:
            pass
        zone = (row.get("thesis_validity") or {}).get("zone_status")
        if filt in ("all", "thesis_invalidation") and zone in ("at_risk", "invalid"):
            events.append({
                "kind": "thesis_invalidation",
                "symbol": row.get("symbol"),
                "text": f"{row.get('symbol')} thesis zone {zone} — drift {_pct(row.get('price_drift_pct'))}.",
                "severity": "urgent",
                "at": datetime.now(timezone.utc).isoformat(),
            })

    events.sort(key=lambda e: str(e.get("at") or ""), reverse=True)
    events = events[:25]

    portal_acts = _portal_actions(days=max(1, hours // 24 + 1), limit=60)
    if sym:
        portal_acts = [a for a in portal_acts if (a.get("symbol") or "").upper() == sym]
    if filt == "stop_hit":
        portal_acts = [a for a in portal_acts if a.get("action_class") == "stop_triggered"]
    elif filt == "thesis_invalidation":
        portal_acts = [a for a in portal_acts if a.get("action_class") in ("risk_review", "unprotected_position", "recovery")]
    elif filt == "large_move":
        portal_acts = [a for a in portal_acts if a.get("action_class") not in ("stop_triggered", "unprotected_position")]

    event_actions = _events_to_actions(events)
    report_actions = _dedupe_actions(list(portal_acts) + list(event_actions), limit=25)

    title_sym = f" — {sym}" if sym else ""
    filter_label = filt.replace("_", " ").title()
    sections = [
        {
            "id": "executive_summary",
            "title": "Event Summary",
            "content": (
                f"{len(events)} event(s) in the last {hours}h"
                f"{f' for {sym}' if sym else ''} "
                f"(filter: {filter_label}). "
                f"{len(report_actions)} actionable items — use the Action Queue above."
            ),
            "metrics": {"event_count": len(events), "hours": hours, "filter": filt},
        },
        {
            "id": "risk_assessment",
            "title": "Stop Hits & Protection",
            "content": "Stop and protection events are in the Action Queue — click to address.",
            "bullets": [] if report_actions else (
                [e["text"] for e in events if e["kind"] == "stop_hit"][:12]
                or ["No stop-trigger events in this window."]
            ),
        },
        {
            "id": "key_risks",
            "title": "Thesis Invalidations",
            "content": "Thesis and drift flags are in the Action Queue — click to address.",
            "bullets": [] if report_actions else (
                [e["text"] for e in events if e["kind"] == "thesis_invalidation"][:12]
                or ["No thesis invalidation flags."]
            ),
        },
        {
            "id": "fundamental_news",
            "title": "Large Moves & Catalysts",
            "content": "Large moves and catalysts are in the Action Queue — click to address.",
            "bullets": [] if report_actions else (
                [e["text"] for e in events if e["kind"] == "large_move"][:12]
                or ["No large-move events detected."]
            ),
        },
    ]

    visuals: list[dict] = []
    chart_sym = sym or (events[0].get("symbol") if events else None)
    if chart_sym:
        ec = enrich_cache.get(str(chart_sym).upper(), {}) if isinstance(enrich_cache, dict) else {}
        _attach_symbol_charts(str(chart_sym), ec, visuals)

    return {
        "meta": {
            "report_type": "event_driven",
            "type_label": REPORT_TYPES["event_driven"]["label"],
            "symbol": sym,
            "title": f"Event-Driven Report{title_sym} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hours": hours,
            "event_filter": filt,
            "event_count": len(events),
            "version": "1.1",
            "kpis": {
                "event_count": len(events),
                "action_items": len(report_actions),
            },
        },
        "sections": sections,
        "events": events,
        "visuals": visuals,
        "action_items": report_actions,
        "sources": [
            {"id": "reports_portal", "label": "Operator actions"},
            {"id": "alert_events", "label": "SIEM alerts", "count": len(alerts)},
            {"id": "paper_trade_proposals", "label": "Broker proposals", "count": len(proposals)},
        ],
        "export_options": {"available_sections": [s["id"] for s in sections], "selected": [s["id"] for s in sections]},
    }


def build_sector_theme_report(
    sector: str,
    *,
    sections: list[str] | None = None,
) -> dict:
    """Sector & theme report — peers, watchlist coverage, rotation signals."""
    sector_name = (sector or "").strip()
    if not sector_name:
        raise ValueError("sector required")
    sections = sections or [
        "executive_summary", "investment_thesis", "technical_analysis",
        "fundamental_news", "risk_assessment", "recommendation", "key_risks",
    ]

    peers = _db_query(
        """SELECT symbol, sector, left(description_1s, 120) AS description
           FROM symbol_profiles
           WHERE lower(sector) = lower(%s) OR sector ILIKE %s
           ORDER BY symbol LIMIT 40""",
        (sector_name, f"%{sector_name}%"),
    ) or []

    watchlist_syms = _db_query(
        """SELECT DISTINCT wi.symbol, wi.score, wi.trend, fs.recommendation
           FROM watchlist_items wi
           JOIN symbol_profiles sp ON sp.symbol = wi.symbol
           LEFT JOIN watchlist_final_synthesis fs ON fs.symbol = wi.symbol
           WHERE (lower(sp.sector) = lower(%s) OR sp.sector ILIKE %s)
             AND wi.status NOT IN ('removed')
           ORDER BY wi.score DESC NULLS LAST LIMIT 20""",
        (sector_name, f"%{sector_name}%"),
    ) or []

    holdings = _load(STATE_DIR / "holdings.json").get("holdings") or []
    peer_set = {str(p.get("symbol", "")).upper() for p in peers}
    held = [
        h for h in holdings
        if str(h.get("symbol", "")).upper() in peer_set and not h.get("is_cash")
    ]

    directives = _db_query(
        """SELECT label, kind, spec FROM watch_directives
           WHERE status = 'active' AND kind IN ('sector', 'trend')
             AND (label ILIKE %s OR spec::text ILIKE %s)
           ORDER BY updated_at DESC LIMIT 5""",
        (f"%{sector_name}%", f"%{sector_name}%"),
    ) or []

    enrich_cache = _load(STATE_DIR / "ticker_enrichment_cache.json")
    perf_rows = []
    for p in peers[:15]:
        sym = str(p.get("symbol", "")).upper()
        e = enrich_cache.get(sym, {}) if isinstance(enrich_cache, dict) else {}
        if e:
            perf_rows.append({
                "symbol": sym,
                "day_change_pct": e.get("day_change_pct"),
                "perf_month_pct": e.get("perf_month_pct"),
                "rsi": e.get("rsi"),
            })

    meta = {
        "report_type": "sector_theme",
        "type_label": REPORT_TYPES["sector_theme"]["label"],
        "sector": sector_name,
        "title": f"{sector_name} — Sector & Theme Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "peer_count": len(peers),
        "watchlist_count": len(watchlist_syms),
        "holding_count": len(held),
        "sections_included": sections,
        "version": "1.0",
    }

    report_sections: list[dict] = []
    if "executive_summary" in sections:
        avg_day = None
        vals = [_f(r.get("day_change_pct")) for r in perf_rows if r.get("day_change_pct") is not None]
        if vals:
            avg_day = sum(vals) / len(vals)
        report_sections.append({
            "id": "executive_summary",
            "title": "Executive Summary",
            "content": (
                f"Sector/theme coverage for {sector_name}: {len(peers)} profiled symbols, "
                f"{len(watchlist_syms)} on watchlist, {len(held)} held in portfolio. "
                f"Average peer day change {_pct(avg_day)}."
            ),
            "metrics": {
                "peers": len(peers),
                "watchlist": len(watchlist_syms),
                "holdings": len(held),
                "avg_day_change_pct": round(avg_day, 2) if avg_day is not None else None,
            },
        })

    if "investment_thesis" in sections:
        bullets = [
            f"{d.get('label')} ({d.get('kind')})" for d in directives
        ] or [f"No active sector/trend directives match '{sector_name}'."]
        report_sections.append({
            "id": "investment_thesis",
            "title": "Theme Thesis / Catalyst Summary",
            "bullets": bullets,
        })

    if "technical_analysis" in sections:
        bullets = [
            f"{r['symbol']}: day {_pct(r.get('day_change_pct'))}, 1M {_pct(r.get('perf_month_pct'))}, RSI {r.get('rsi', '—')}"
            for r in sorted(perf_rows, key=lambda x: _f(x.get("day_change_pct")), reverse=True)[:10]
        ]
        report_sections.append({
            "id": "technical_analysis",
            "title": "Peer Technical Snapshot",
            "bullets": bullets or ["Insufficient enrichment data for peer technicals."],
        })

    if "fundamental_news" in sections:
        bullets = [
            f"{w.get('symbol')}: {w.get('recommendation') or '—'} (score {w.get('score', '—')}, trend {w.get('trend', '—')})"
            for w in watchlist_syms[:12]
        ]
        report_sections.append({
            "id": "fundamental_news",
            "title": "Watchlist & Coverage",
            "bullets": bullets or ["No watchlist symbols in this sector."],
        })

    if "risk_assessment" in sections:
        underwater = [
            f"{h.get('symbol')}: {_pct(h.get('unrealized_pnl_pct'))} unrealized"
            for h in held if _f(h.get("unrealized_pnl_pct")) < -5
        ]
        report_sections.append({
            "id": "risk_assessment",
            "title": "Portfolio Sector Risk",
            "bullets": underwater or ["No held positions materially underwater in this sector."],
        })

    if "recommendation" in sections:
        top = watchlist_syms[0] if watchlist_syms else (peers[0] if peers else None)
        rec_sym = (top or {}).get("symbol", "—")
        rec_view = (top or {}).get("recommendation", "Review sector rotation")
        report_sections.append({
            "id": "recommendation",
            "title": "Sector Recommendation",
            "content": f"Lead symbol {rec_sym}: {rec_view}. Review peer dispersion and portfolio weight.",
        })

    if "key_risks" in sections:
        report_sections.append({
            "id": "key_risks",
            "title": "Key Risks & Invalidation",
            "bullets": [
                "Sector-wide drawdown if macro regime shifts against theme.",
                "Thin watchlist coverage increases single-name concentration risk.",
                "Stale enrichment — refresh before sizing decisions.",
            ],
        })

    sector_visuals: list[dict] = []
    try:
        from report_visuals import chart_peer_movers, chart_coverage_bars
        stem = sector_name.replace(" ", "_").replace("/", "_")[:24]
        pm = chart_peer_movers(perf_rows, stem=stem, title=f"{sector_name} — Peer Day Movers (%)")
        if pm.get("chart_path"):
            sector_visuals.append(pm)
        cb = chart_coverage_bars(
            ["Peers", "Watchlist", "Held"],
            [len(peers), len(watchlist_syms), len(held)],
            stem=stem,
            title=f"{sector_name} — Coverage",
        )
        if cb.get("chart_path"):
            sector_visuals.append(cb)
        lead = (watchlist_syms[0] or {}).get("symbol") or (peers[0] or {}).get("symbol")
        if lead:
            ec = enrich_cache.get(str(lead).upper(), {}) if isinstance(enrich_cache, dict) else {}
            _attach_symbol_charts(str(lead), ec, sector_visuals)
    except Exception:
        pass

    meta["kpis"] = {
        "peers": len(peers),
        "watchlist": len(watchlist_syms),
        "holdings": len(held),
        "sector": sector_name,
    }

    return {
        "meta": meta,
        "sections": report_sections,
        "visuals": sector_visuals,
        "peers": [dict(p) for p in peers[:20]],
        "sources": [
            {"id": "symbol_profiles", "label": "Sector peers", "count": len(peers)},
            {"id": "watchlist_items", "label": "Watchlist", "count": len(watchlist_syms)},
            {"id": "watch_directives", "label": "Theme directives", "count": len(directives)},
            {"id": "ticker_enrichment_cache", "label": "Market enrichment", "count": len(perf_rows)},
        ],
        "export_options": {"available_sections": sections, "selected": sections},
    }


def build_intelligence_deep_report(*, topic: str | None = None, days: int = 7) -> dict:
    """Intelligence deep dive — Layer 4, Hermes, alerts, synthesis conflicts."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

    topic_label = (topic or "Macro & Regime").strip()
    try:
        from generate_daily_intelligence_report import generate_report as _gen_intel
        intel = _gen_intel()
    except Exception as e:
        intel = {"error": str(e)[:200]}

    if topic:
        hermes = _db_query(
            """SELECT topic, left(summary, 200) AS summary, research_type, created_at
               FROM hermes_research_intelligence
               WHERE created_at > NOW() - make_interval(days => %s)
                 AND (topic ILIKE %s OR summary ILIKE %s)
               ORDER BY created_at DESC LIMIT 12""",
            (int(days), f"%{topic_label}%", f"%{topic_label}%"),
        ) or []
    else:
        hermes = _db_query(
            """SELECT topic, left(summary, 200) AS summary, research_type, created_at
               FROM hermes_research_intelligence
               WHERE created_at > NOW() - make_interval(days => %s)
               ORDER BY created_at DESC LIMIT 12""",
            (int(days),),
        ) or []

    ensembles = _db_query(
        """SELECT subject, final_decision, final_score, consensus_reached, reasoning_summary, created_at
           FROM inference_ensemble_results
           WHERE created_at > NOW() - make_interval(days => %s)
           ORDER BY created_at DESC LIMIT 10""",
        (int(days),),
    ) or []

    safety = intel.get("decision_safety") or intel.get("safety_counts") or {}
    if isinstance(safety, str):
        safety = {}
    health = _load(STATE_DIR / "health_agent_status.json")

    intel_actions: list[dict] = list(_portal_actions(days=days, limit=20))
    for sym in (intel.get("human_review_symbols") or [])[:10]:
        if not sym:
            continue
        intel_actions.append({
            "id": f"review-{sym}",
            "text": f"{sym} requires human review before action",
            "symbol": str(sym).upper(),
            "severity": "warning",
            "action_class": "approval_needed",
            "route": f"/v3/trading?symbol={sym}",
            "route_label": "Trading",
            "status": "open",
        })
    for s in (intel.get("unsafe_symbols") or [])[:8]:
        sym = (s.get("symbol") if isinstance(s, dict) else str(s)).upper()
        if not sym:
            continue
        intel_actions.append({
            "id": f"unsafe-{sym}",
            "text": f"{sym} flagged unsafe — review synthesis before trading",
            "symbol": sym,
            "severity": "urgent",
            "action_class": "risk_review",
            "route": f"/v3/risk?symbol={sym}",
            "route_label": "Risk",
            "status": "open",
        })
    for e in ensembles:
        subj = str(e.get("subject") or "")
        if not subj or str(e.get("final_decision", "")).lower() != "block":
            continue
        intel_actions.append({
            "id": f"ens-{subj[:24]}",
            "text": f"{subj}: Layer 4 block (score {_normalize_score_10(e.get('final_score'))}/10) — review proposal",
            "symbol": subj.split()[0] if subj.split() else None,
            "severity": "warning",
            "action_class": "approval_needed",
            "route": "/v3/trading?tab=Broker%20Proposals",
            "route_label": "Trading",
            "status": "open",
        })
    report_actions = _dedupe_actions(intel_actions, limit=25)

    sections = [
        {
            "id": "executive_summary",
            "title": "Intelligence Executive Summary",
            "content": (
                f"Deep dive: {topic_label}. "
                f"Decision safety mix: {safety}. "
                f"Alerts 24h: {intel.get('alerts_24h', 0)}. "
                f"{len(report_actions)} actionable items — use the Action Queue above."
            ),
            "metrics": {
                "safe": safety.get("safe"),
                "pending": safety.get("pending"),
                "unsafe": safety.get("unsafe"),
                "hermes_count": len(hermes),
                "ensemble_count": len(ensembles),
            },
        },
        {
            "id": "fundamental_news",
            "title": "Hermes Research Synthesis",
            "content": "Hermes stop/trailing recommendations are summarized in Action Queue where actionable.",
            "bullets": [] if report_actions else [
                f"{h.get('topic', 'Research')}: {h.get('summary', '')}"
                for h in hermes
            ] or ["No Hermes research matched this topic window."],
        },
        {
            "id": "ensemble_validation",
            "title": "Layer 4 Ensemble Verdicts",
            "content": "Blocked ensemble decisions are in the Action Queue — click to review.",
            "bullets": [] if report_actions else [
                f"{e.get('subject')}: {e.get('final_decision')} "
                f"(score {_normalize_score_10(e.get('final_score'))}/10)"
                for e in ensembles
            ] or ["No recent ensemble validations."],
        },
        {
            "id": "key_risks",
            "title": "Conflicts & Human Review Queue",
            "content": (
                f"Human review ({len(intel.get('human_review_symbols') or [])}), "
                f"unsafe ({len(intel.get('unsafe_symbols') or [])}), "
                f"stale ({len(intel.get('stale_symbols') or [])}) — see Action Queue."
            ),
            "bullets": [] if report_actions else [
                f"Human reviews: {intel.get('human_review_symbols', [])[:8]}",
                f"Unsafe symbols: {[s.get('symbol') for s in intel.get('unsafe_symbols', [])][:8]}",
                f"Stale analyses: {intel.get('stale_symbols', [])[:8]}",
                f"Unresolved conflicts: {intel.get('unresolved_conflicts', 0)}",
            ],
        },
    ]

    intel_visuals: list[dict] = []
    try:
        from report_visuals import chart_decision_safety, chart_ensemble_scores, chart_health_gauge, chart_proposal_pipeline
        if safety:
            ds = chart_decision_safety(safety, stem="intel")
            if ds.get("chart_path"):
                intel_visuals.append(ds)
        es = chart_ensemble_scores(ensembles, stem="intel")
        if es.get("chart_path"):
            intel_visuals.append(es)
        hs = _f(health.get("overall_score"))
        if hs:
            intel_visuals.append(chart_health_gauge(hs, str(health.get("status") or ""), stem="intel"))
        props = _db_query(
            """SELECT status, COUNT(*) AS cnt FROM paper_trade_proposals
               WHERE created_at > NOW() - make_interval(days => %s) GROUP BY status""",
            (int(days),),
        ) or []
        pp = chart_proposal_pipeline(props, stem="intel")
        if pp.get("chart_path"):
            intel_visuals.append(pp)
    except Exception:
        pass

    return {
        "meta": {
            "report_type": "intelligence_deep",
            "type_label": REPORT_TYPES["intelligence_deep"]["label"],
            "topic": topic_label,
            "title": f"Intelligence Deep Dive — {topic_label}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": days,
            "version": "1.1",
            "kpis": {
                "health_score": health.get("overall_score"),
                "health_status": health.get("status"),
                "hermes_count": len(hermes),
                "ensemble_count": len(ensembles),
                "alerts_24h": intel.get("alerts_24h", 0),
                "action_items": len(report_actions),
            },
        },
        "sections": sections,
        "visuals": intel_visuals,
        "action_items": report_actions,
        "sources": [
            {"id": "generate_daily_intelligence_report", "label": "DB intelligence"},
            {"id": "hermes_research_intelligence", "label": "Hermes", "count": len(hermes)},
            {"id": "inference_ensemble_results", "label": "Layer 4", "count": len(ensembles)},
        ],
        "export_options": {"available_sections": [s["id"] for s in sections], "selected": [s["id"] for s in sections]},
    }


def build_report(
    *,
    report_type: str,
    symbol: str | None = None,
    sector: str | None = None,
    topic: str | None = None,
    sections: list[str] | None = None,
    days: int = 1,
    hours: int = 24,
    event_filter: str = "all",
    prior_report: dict | None = None,
    continuity: dict | None = None,
    generation: int | None = None,
) -> dict:
    """Unified entry point for all analyst report types."""
    rtype = report_type or "symbol_watchlist"
    if rtype == "daily_digest":
        return build_daily_digest(days=days)
    if rtype == "weekly_review":
        return build_weekly_review()
    if rtype == "event_driven":
        return build_event_driven_report(
            symbol=(symbol or "").strip().upper() or None,
            event_filter=event_filter,
            hours=hours,
        )
    if rtype == "sector_theme":
        sector_name = (sector or symbol or "").strip()
        if not sector_name:
            return build_all_sectors_report(sections=sections)
        return build_sector_theme_report(sector_name, sections=sections)
    if rtype == "intelligence_deep":
        return build_intelligence_deep_report(topic=topic or sector or symbol, days=days)
    sym = (symbol or "").strip().upper()
    if not sym:
        if rtype in ("symbol_holding", "symbol_watchlist", "symbol_custom"):
            return build_aggregate_symbol_report(rtype, sections=sections)
        raise ValueError("symbol required for symbol report types")
    return build_symbol_report(
        sym,
        report_type=rtype,
        sections=sections,
        prior_report=prior_report,
        continuity=continuity,
        generation=generation,
    )


def list_report_types() -> list[dict]:
    return [{"key": k, **v} for k, v in REPORT_TYPES.items()]


def save_report_json(report: dict, stem: str | None = None) -> Path:
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    sym = report.get("meta", {}).get("symbol") or report.get("meta", {}).get("report_type", "report")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = stem or f"{sym}_{ts}"
    path = REPORT_OUT / f"{name}.json"
    path.write_text(json.dumps(report, indent=2, default=str))
    return path