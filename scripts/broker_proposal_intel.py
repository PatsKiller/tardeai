#!/usr/bin/env python3
"""broker_proposal_intel.py — decision context for broker queue (company, catalyst, technicals, analyst, why buy)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"


def _q(sql, params=None, one=False):
    try:
        cur = _get_conn().cursor()
        cur.execute(sql, params or ())
        if one:
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return None if one else []


def _load_enrichment_cache(sym: str) -> dict:
    try:
        path = STATE_DIR / "ticker_enrichment_cache.json"
        if path.exists():
            row = json.loads(path.read_text()).get(sym.upper(), {})
            return row if isinstance(row, dict) else {}
    except Exception:
        pass
    return {}


def _load_pro_analyst_pill(sym: str) -> dict:
    try:
        path = RUNTIME_DIR / "pro_analyst_pills_latest.json"
        if path.exists():
            for pill in json.loads(path.read_text()).get("pills", []):
                if str(pill.get("symbol") or "").upper() == sym:
                    return pill if isinstance(pill, dict) else {}
    except Exception:
        pass
    return {}


def _analyst_intel(sym: str, live_price: float | None = None) -> dict | None:
    """Multi-source analyst view: Yahoo (primary), Finviz (if valid), pro_analyst monitor."""
    an = _q(
        """SELECT recommendation_key, recommendation_mean, number_of_analyst_opinions,
                  target_mean_price, target_high_price, target_low_price, current_price, snapshot_date
           FROM yahoo_analyst_targets_history WHERE symbol=%s
           ORDER BY created_at DESC LIMIT 1""",
        (sym,), one=True,
    ) or {}
    dist_row = _q(
        "SELECT payload, as_of FROM analyst_data_history WHERE symbol=%s ORDER BY as_of DESC LIMIT 1",
        (sym,), one=True,
    )
    dist = {}
    dist_provider = None
    dist_as_of = None
    if dist_row and dist_row.get("payload"):
        p = dist_row["payload"]
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except Exception:
                p = {}
        if isinstance(p, dict):
            dist_provider = p.get("provider")
            dist_as_of = str(dist_row.get("as_of") or "")[:10] or None
            if any(p.get(k) is not None for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")):
                dist = {k: int(p.get(k) or 0) for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")}

    enrich = _load_enrichment_cache(sym)
    pill = _load_pro_analyst_pill(sym)
    sources = []
    warnings = []

    yahoo = None
    if an:
        tm, cp = an.get("target_mean_price"), an.get("current_price")
        price_for_upside = live_price if live_price and live_price > 0 else cp
        upside = None
        if tm and price_for_upside and float(price_for_upside) > 0:
            upside = round((float(tm) - float(price_for_upside)) / float(price_for_upside) * 100, 1)
        if live_price and cp and float(cp) > 0:
            stale_drift = abs(float(live_price) - float(cp)) / float(cp) * 100
            if stale_drift > 12:
                warnings.append(
                    f"Analyst snapshot price ${float(cp):.2f} is stale vs live ${float(live_price):.2f} "
                    f"({stale_drift:.0f}% drift) — upside % recalculated on live"
                )
        yahoo = {
            "source": "yahoo",
            "rating": an.get("recommendation_key"),
            "mean": float(an["recommendation_mean"]) if an.get("recommendation_mean") is not None else None,
            "opinions": an.get("number_of_analyst_opinions"),
            "target": float(tm) if tm is not None else None,
            "target_high": float(an["target_high_price"]) if an.get("target_high_price") is not None else None,
            "target_low": float(an["target_low_price"]) if an.get("target_low_price") is not None else None,
            "upside_pct": upside,
            "snapshot_price": float(cp) if cp is not None else None,
            "live_price": float(live_price) if live_price else None,
            "as_of": str(an.get("snapshot_date") or "")[:10] or None,
            "distribution": dist or None,
            "distribution_provider": dist_provider,
            "distribution_as_of": dist_as_of,
        }
        sources.append(yahoo)
        n = int(an.get("number_of_analyst_opinions") or 0)
        if n < 3:
            warnings.append(f"Thin Yahoo coverage — only {n} sell-side analyst{'s' if n != 1 else ''}")

    finviz = None
    rs = enrich.get("recom_score")
    try:
        rs_f = float(rs) if rs is not None else None
    except Exception:
        rs_f = None
    if rs_f is not None and 1.0 <= rs_f <= 5.0:
        finviz = {
            "source": "finviz",
            "rating": enrich.get("analyst_rating"),
            "recom_score": rs_f,
            "as_of": enrich.get("as_of") or enrich.get("updated_at"),
        }
        sources.append(finviz)
        if yahoo and finviz.get("rating") and yahoo.get("rating"):
            y_r = str(yahoo["rating"]).replace("_", " ").lower()
            f_r = str(finviz["rating"]).lower()
            if y_r not in f_r and f_r not in y_r and not (
                ("buy" in y_r and "buy" in f_r) or ("hold" in y_r and "hold" in f_r) or ("sell" in y_r and "sell" in f_r)
            ):
                warnings.append(f"Yahoo ({yahoo['rating']}) vs Finviz ({finviz['rating']}) disagree")
    elif enrich.get("recom") is not None or enrich.get("analyst_rating"):
        warnings.append("Finviz recom present but invalid — ignored (micro-cap field noise)")

    if pill:
        sources.append({
            "source": "pro_analyst",
            "rating": pill.get("recommendation_key"),
            "opinions": pill.get("number_of_analyst_opinions"),
            "target": pill.get("target_mean_price"),
            "upside_pct": pill.get("upside_to_mean_target_pct"),
            "divergence": pill.get("divergence"),
            "confidence": pill.get("confidence"),
            "internal_direction": pill.get("internal_direction"),
            "street_direction": pill.get("street_direction"),
            "latest_event": pill.get("latest_event_headline"),
            "latest_event_type": pill.get("latest_event_type"),
            "latest_event_at": str(pill.get("latest_event_at") or "")[:19],
            "has_professional_coverage": pill.get("has_professional_coverage"),
            "provenance": pill.get("provenance"),
        })
        if pill.get("divergence") in ("mixed", "divergent"):
            warnings.append(
                f"Internal ({pill.get('internal_direction')}) vs Street ({pill.get('street_direction')}) — {pill.get('divergence')}"
            )
        if str(pill.get("confidence") or "").lower() == "low":
            warnings.append("Pro-analyst layer confidence: LOW")

    if not sources:
        return None

    primary = yahoo or sources[0]
    opinions = int(primary.get("opinions") or pill.get("number_of_analyst_opinions") or 0)
    coverage = "none"
    if opinions >= 10:
        coverage = "broad"
    elif opinions >= 3:
        coverage = "moderate"
    elif opinions >= 1:
        coverage = "thin"

    return {
        "rating": primary.get("rating"),
        "mean": primary.get("mean"),
        "opinions": primary.get("opinions"),
        "target": primary.get("target"),
        "target_high": primary.get("target_high"),
        "target_low": primary.get("target_low"),
        "upside_pct": primary.get("upside_pct"),
        "distribution": primary.get("distribution") or dist or None,
        "primary_source": primary.get("source") or "yahoo",
        "sources": sources,
        "quality": {
            "coverage": coverage,
            "confidence": pill.get("confidence") if pill else ("low" if opinions < 3 else "moderate"),
            "warnings": warnings,
            "source_count": len(sources),
        },
    }


def _symbol_card(symbol: str, live_price: float | None = None) -> dict:
    sym = (symbol or "").upper().strip()
    if not sym:
        return {}
    prof = _q(
        "SELECT description_1s, sector, industry, instrument_type FROM symbol_profiles WHERE symbol=%s",
        (sym,), one=True,
    ) or {}
    analyst = _analyst_intel(sym, live_price=live_price)

    news = _q(
        """SELECT title, source, published_at FROM news_articles
           WHERE symbol=%s AND published_at > NOW() - INTERVAL '3 days'
           ORDER BY published_at DESC LIMIT 3""",
        (sym,),
    ) or []

    return {
        "description": prof.get("description_1s"),
        "sector": prof.get("sector"),
        "industry": prof.get("industry"),
        "instrument_type": prof.get("instrument_type"),
        "analyst": analyst,
        "news": [
            {"title": n.get("title"), "source": n.get("source"), "at": str(n.get("published_at") or "")[:19]}
            for n in news
        ],
    }


def get_intel_packet(proposal_id: int, *, include_oversight: bool = True) -> dict:
    """Full broker decision context for a paper_trade_proposals row.

    include_oversight=False breaks the evaluate_oversight→evaluate_intel_diligence cycle
    when diligence only needs catalyst/analyst fields from the packet.
    """
    pid = int(proposal_id)
    row = _q(
        """SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.sizing_basis, ptp.catalyst, ptp.catalyst_verified,
                  ptp.proposed_entry, ptp.proposed_stop, ptp.proposed_target1, ptp.proposed_rr,
                  ptp.current_price, ptp.rvol, ptp.float_m, ptp.gap_pct, ptp.intel_readiness,
                  scan.catalyst as scan_catalyst, scan.catalyst_verified as scan_catalyst_verified,
                  scan.catalyst_confidence, scan.critic_verdict, scan.critic_reasoning,
                  scan.sector, scan.industry, scan.rvol as scan_rvol, scan.gap_pct as scan_gap_pct,
                  scan.change_pct, scan.grade, scan.score,
                  ind.atr, ind.confluence_score, ind.confluence_tier, ind.adx_regime,
                  ind.full_result as ind_full_result,
                  pa.summary, pa.approve_case, pa.reject_case, pa.invalidation,
                  pa.catalyst_summary, pa.technical_summary, pa.risk_summary, pa.confidence
           FROM paper_trade_proposals ptp
           LEFT JOIN LATERAL (
               SELECT * FROM trade_ai_scans WHERE symbol = ptp.symbol ORDER BY scanned_at DESC LIMIT 1
           ) scan ON true
           LEFT JOIN LATERAL (
               SELECT * FROM indicator_confluence_cache WHERE symbol = ptp.symbol ORDER BY computed_at DESC LIMIT 1
           ) ind ON true
           LEFT JOIN LATERAL (
               SELECT * FROM paper_proposal_analysis WHERE proposal_id = ptp.id ORDER BY created_at DESC LIMIT 1
           ) pa ON true
           WHERE ptp.id = %s""",
        (pid,), one=True,
    )
    if not row:
        return {"ok": False, "error": f"proposal #{pid} not found"}

    sym = str(row.get("symbol") or "").upper()
    live_px = row.get("current_price")
    if live_px is None:
        try:
            from market_quote_provider import get_best_quote
            q = get_best_quote(sym) or {}
            live_px = q.get("last_price") or q.get("last")
        except Exception:
            live_px = None
    try:
        live_px = float(live_px) if live_px is not None else None
    except (TypeError, ValueError):
        live_px = None
    card = _symbol_card(sym, live_price=live_px)

    catalyst = row.get("catalyst") or row.get("scan_catalyst")
    catalyst_verified = row.get("scan_catalyst_verified") if row.get("scan_catalyst_verified") is not None else row.get("catalyst_verified")
    rvol = row.get("rvol") or row.get("scan_rvol")
    gap_pct = row.get("gap_pct") or row.get("scan_gap_pct")

    # Social / meme-momentum signal — Hermes momentum_catalyst research (Reddit/StockTwits discovery).
    # Surfacing this on the proposal lets the card's meme/high-risk banner fire even when the proposal
    # itself came from a non-social strategy (e.g. fib bounce) but the symbol is socially pumping.
    social_flag = False
    social_sources = None
    social_summary = None
    try:
        soc = _q(
            """SELECT summary, confidence_score FROM hermes_research_intelligence
               WHERE symbol=%s AND research_type='momentum_catalyst'
                 AND created_at > NOW() - INTERVAL '36 hours'
               ORDER BY created_at DESC LIMIT 1""",
            (sym,), one=True,
        )
        if soc and soc.get("summary"):
            social_flag = True
            social_summary = str(soc.get("summary"))[:200]
            import re as _re
            m = _re.search(r"(\d+)\s+sources", social_summary)
            social_sources = int(m.group(1)) if m else None
    except Exception:
        social_flag = False

    rsi = vwap_dist = None
    ind_result = row.get("ind_full_result")
    if isinstance(ind_result, str):
        try:
            ind_result = json.loads(ind_result)
        except Exception:
            ind_result = {}
    if isinstance(ind_result, dict):
        sig = ind_result.get("signals") or {}
        if "rsi" in sig:
            rsi = sig["rsi"].get("value")
        if "vwap" in sig:
            vwap_dist = sig["vwap"].get("distance_pct")

    tech_parts = []
    if rsi is not None:
        tech_parts.append(f"RSI {float(rsi):.1f}")
    if vwap_dist is not None:
        tech_parts.append(f"VWAP {float(vwap_dist):+.1f}%")
    if row.get("atr"):
        tech_parts.append(f"ATR ${float(row['atr']):.2f}")
    if rvol:
        tech_parts.append(f"RVOL {float(rvol):.1f}x")
    if gap_pct:
        tech_parts.append(f"Gap {float(gap_pct):+.1f}%")
    if row.get("adx_regime"):
        tech_parts.append(f"ADX {row['adx_regime']}")

    ts = _q(
        """SELECT rsi_14, atr_14, technical_grade, ema_alignment, opening_range_status
           FROM proposal_technical_snapshots WHERE proposal_id=%s ORDER BY computed_at DESC LIMIT 1""",
        (pid,), one=True,
    ) or {}

    agent_rows = _q(
        """SELECT agent_name, status, vote, confidence, summary, reviewed_by_model
           FROM proposal_agent_reviews WHERE proposal_id=%s ORDER BY agent_name""",
        (pid,),
    ) or []

    entry = float(row.get("proposed_entry") or 0)
    stop = float(row.get("proposed_stop") or 0)
    target = float(row.get("proposed_target1") or 0)
    rr = row.get("proposed_rr")
    if not rr and entry > stop and target > entry:
        rr = round((target - entry) / (entry - stop), 2)

    why_parts = []
    if row.get("approve_case"):
        why_parts.append(str(row["approve_case"]))
    elif row.get("summary"):
        why_parts.append(str(row["summary"])[:400])
    elif catalyst and catalyst_verified:
        why_parts.append(f"Verified catalyst: {str(catalyst)[:200]}. Momentum scalp entry on volume surge.")
    elif catalyst:
        why_parts.append(f"Unverified catalyst: {str(catalyst)[:180]}. Paper/broker test only — confirm before size.")
    if row.get("catalyst_summary"):
        why_parts.append(f"Catalyst: {str(row['catalyst_summary'])[:200]}")
    if tech_parts and not why_parts:
        why_parts.append(f"Technical setup: {' · '.join(tech_parts)}. Strategy {row.get('strategy_id')}.")

    # Honesty guard: a STORED approve_case/summary can claim a 'verified catalyst' that the LIVE
    # catalyst data contradicts (TECH: approve_case read 'Verified catalyst with clear trade plan' while
    # live catalyst confidence was 0% / unverified). Prepend the real status so the rationale can't
    # overstate the catalyst — a high R:R + 'verified' claim on an unverified setup is exactly the kind
    # of misleading green light to avoid.
    import re as _re
    _cconf = None
    try:
        _cc = row.get("catalyst_confidence")
        _cconf = float(_cc) if _cc is not None else None
        if _cconf is not None and _cconf > 1:   # some rows store 0-100
            _cconf = _cconf / 100.0
    except Exception:
        _cconf = None
    _cat_unverified = bool(catalyst) and (not catalyst_verified or (_cconf is not None and _cconf < 0.30))
    if (_cat_unverified and why_parts
            and _re.search(r'verified catalyst', why_parts[0], _re.I)
            and not _re.search(r'unverified', why_parts[0], _re.I)):
        _pct = f"{int(round((_cconf or 0) * 100))}%" if _cconf is not None else "unconfirmed"
        why_parts.insert(0, f"⚠ Catalyst NOT verified (confidence {_pct}) — rationale below may overstate it; "
                            f"confirm a real catalyst before any size.")

    import broker_strategy_resolver as bsr
    resolved = bsr.resolve_executable_strategy(sym, str(row.get("strategy_id") or ""))
    strategy_meta: dict = {}
    strategy_purpose = None
    try:
        from proposal_lifecycle import get_strategy_metadata
        strategy_meta = dict(get_strategy_metadata(resolved.get("strategy_id") or "") or {})
        strategy_purpose = strategy_meta.get("purpose")
        if not strategy_purpose:
            from strategy_config_loader import load_strategy_config
            cfg = load_strategy_config(resolved.get("strategy_id") or "") or {}
            strategy_purpose = cfg.get("purpose")
            if cfg.get("display_name"):
                strategy_meta["display_name"] = cfg["display_name"]
            if strategy_purpose:
                strategy_meta["purpose"] = strategy_purpose
    except Exception:
        strategy_meta = {}
    basis = row.get("sizing_basis")
    if isinstance(basis, str):
        try:
            basis = json.loads(basis)
        except Exception:
            basis = {}
    if not isinstance(basis, dict):
        basis = {}
    exit_rationale = basis.get("exit_rationale") or {}
    if not exit_rationale and resolved.get("strategy_id"):
        _, _, _, exit_rationale = bsr.apply_strategy_exit_plan(
            float(row.get("proposed_entry") or 0),
            float(row.get("proposed_stop") or 0) if row.get("proposed_stop") else None,
            float(row.get("proposed_target1") or 0) if row.get("proposed_target1") else None,
            resolved["strategy_id"],
        )

    oversight = {}
    if include_oversight:
        try:
            import broker_promote_oversight as bpo
            oversight = bpo.evaluate_oversight(pid)
        except Exception:
            oversight = {}

    return {
        "ok": True,
        "proposal_id": pid,
        "symbol": sym,
        "oversight": oversight,
        "strategy_id": row.get("strategy_id"),
        "strategy": {
            "strategy_id": resolved.get("strategy_id") or row.get("strategy_id"),
            "proposal_strategy_id": row.get("strategy_id"),
            "watchlist_sleeve": basis.get("watchlist_sleeve") or resolved.get("watchlist_sleeve"),
            "resolve_source": basis.get("strategy_resolve_source") or resolved.get("resolve_source"),
            "display_name": strategy_meta.get("display_name")
            or str(resolved.get("strategy_id") or row.get("strategy_id") or "").replace("_", " ").title(),
            "strategy_type": strategy_meta.get("strategy_type"),
            "strategy_type_label": strategy_meta.get("strategy_type_label"),
            "purpose": strategy_purpose,
            "timeframe": strategy_meta.get("timeframe") or strategy_meta.get("timeframe_class"),
        },
        "exit_plan": {
            "summary": basis.get("exit_summary") or bsr.build_exit_summary(
                exit_rationale,
                float(row.get("proposed_entry") or 0),
                float(row.get("proposed_stop") or 0),
                float(row.get("proposed_target1") or 0),
            ),
            "rationale": exit_rationale,
            "entry": float(row.get("proposed_entry") or 0) or None,
            "stop": float(row.get("proposed_stop") or 0) or None,
            "target": float(row.get("proposed_target1") or 0) or None,
            "planned_rr": float(row.get("proposed_rr") or 0) or None,
        },
        "company": {
            "description": card.get("description"),
            "sector": card.get("sector") or row.get("sector"),
            "industry": card.get("industry") or row.get("industry"),
            "instrument_type": card.get("instrument_type") or row.get("instrument_type"),
        },
        "catalyst": {
            "text": catalyst,
            "verified": bool(catalyst_verified),
            "confidence": float(row["catalyst_confidence"]) if row.get("catalyst_confidence") is not None else None,
            "critic_verdict": row.get("critic_verdict"),
            "critic_reasoning": (str(row.get("critic_reasoning") or ""))[:600] or None,
            "rvol": float(rvol) if rvol else None,
            "gap_pct": float(gap_pct) if gap_pct else None,
            "social": social_flag,
            "social_sources": social_sources,
            "social_summary": social_summary,
        },
        "technicals": {
            "summary": " · ".join(tech_parts) if tech_parts else row.get("technical_summary"),
            "rsi": float(rsi) if rsi is not None else (float(ts["rsi_14"]) if ts.get("rsi_14") is not None else None),
            "atr": float(row["atr"]) if row.get("atr") else (float(ts["atr_14"]) if ts.get("atr_14") is not None else None),
            "rvol": float(rvol) if rvol else None,
            "gap_pct": float(gap_pct) if gap_pct else None,
            "change_pct": float(row["change_pct"]) if row.get("change_pct") is not None else None,
            "vwap_distance_pct": float(vwap_dist) if vwap_dist is not None else None,
            "technical_grade": ts.get("technical_grade"),
            "confluence_tier": row.get("confluence_tier"),
            "confluence_score": float(row["confluence_score"]) if row.get("confluence_score") is not None else None,
            "grade": row.get("grade"),
            "score": row.get("score"),
        },
        "analyst": card.get("analyst"),
        "why_purchase": {
            "headline": why_parts[0] if why_parts else None,
            "approve_case": row.get("approve_case"),
            "summary": row.get("summary"),
            "strategy_purpose": strategy_purpose,
            "invalidation": row.get("invalidation"),
            "reject_case": row.get("reject_case"),
            "risk_summary": row.get("risk_summary"),
            "rr": float(rr) if rr else None,
            "signal_grade": row.get("grade"),
        },
        "agent_reviews": [
            {
                "agent": ar.get("agent_name"),
                "status": ar.get("status"),
                "verdict": ar.get("vote"),
                "confidence": float(ar["confidence"]) if ar.get("confidence") is not None else None,
                "summary": (ar.get("summary") or "")[:200],
                "model": ar.get("reviewed_by_model"),
            }
            for ar in agent_rows
        ],
        "news": card.get("news") or [],
        "intel_readiness": float(row["intel_readiness"]) if row.get("intel_readiness") is not None else None,
    }