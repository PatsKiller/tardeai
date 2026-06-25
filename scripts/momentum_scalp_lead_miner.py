"""momentum_scalp_lead_miner.py — Momentum scalp leads beyond Finviz.

Mines intraday/momentum candidates from social scalp scans, trade_ai_scans (non-Finviz
sources), intelligence_entities, live quotes, news catalysts, and curator signals —
then stages them into incubator_universe (momentum_scalp) for screening and proposal promotion.

Bypasses the watch_directive firewall (directive_promotion excludes SAME_DAY/scalp).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRATEGY_ID = "momentum_scalp"

NON_FINVIZ_SCAN_SOURCES = frozenset({
    "social", "continuous", "premarket_social", "stocktwits_premarket",
    "stocktwits", "catalyst_api", "hermes", "intelligence", "news_catalyst",
    "scalp_social", "social_scalp",
})
MOMENTUM_NEWS = re.compile(
    r"\b(breakout|surge|momentum|rvol|gap up|spike|upgrade|contract|fda|earnings beat|short squeeze)\b",
    re.I,
)
HELD_SCORE_BOOST = 10.0
ACTIVE_WATCHLIST_BOOST = 5.0
DIRECTIVE_WATCH_BOOST = 3.0
BUY_RATED_BOOST = 3.0


def load_portfolio_priority(conn) -> dict:
    """Held positions + watchlist tiers used to boost and refresh known symbols."""
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT UPPER(symbol) FROM trades
           WHERE lower(status) = 'open' AND symbol ~ '^[A-Z]{1,5}$'
           UNION
           SELECT DISTINCT UPPER(symbol) FROM paper_trades
           WHERE lower(status) = 'open' AND symbol ~ '^[A-Z]{1,5}$'"""
    )
    held = {r[0] for r in cur.fetchall() if r[0]}

    active: set[str] = set()
    directive: set[str] = set()
    known_watchlist: set[str] = set()
    cur.execute(
        """SELECT UPPER(symbol),
                  bool_or(COALESCE(in_directive_watch, false)) AS in_dir,
                  bool_or(status = 'active') AS is_active
           FROM watchlist_items
           WHERE status <> 'removed' AND symbol IS NOT NULL
           GROUP BY UPPER(symbol)"""
    )
    for sym, in_dir, is_active in cur.fetchall():
        if not sym:
            continue
        known_watchlist.add(sym)
        if in_dir:
            directive.add(sym)
        if is_active:
            active.add(sym)

    cur.execute(
        """SELECT DISTINCT UPPER(symbol) FROM watchlist_research_cards
           WHERE UPPER(COALESCE(latest_recommendation, '')) IN ('BUY', 'STRONG_BUY')"""
    )
    buy_rated = {r[0] for r in cur.fetchall() if r[0]}

    return {
        "held": held,
        "watchlist_active": active,
        "watchlist_directive": directive,
        "watchlist_buy": buy_rated,
        "known_watchlist": known_watchlist,
    }


def _priority_boost_for_symbol(sym: str, priority: dict) -> tuple[float, list[str]]:
    boost = 0.0
    tags: list[str] = []
    if sym in priority.get("held", ()):
        boost += HELD_SCORE_BOOST
        tags.append("held")
    if sym in priority.get("watchlist_directive", ()):
        boost += DIRECTIVE_WATCH_BOOST
        tags.append("directive_watch")
    if sym in priority.get("watchlist_active", ()):
        boost += ACTIVE_WATCHLIST_BOOST
        tags.append("active_watchlist")
    elif sym in priority.get("watchlist_buy", ()):
        boost += BUY_RATED_BOOST
        tags.append("buy_rated")
    return boost, tags


def _apply_priority_boosts(leads: dict[str, dict], priority: dict) -> int:
    boosted = 0
    for lead in leads.values():
        sym = lead["symbol"]
        boost, tags = _priority_boost_for_symbol(sym, priority)
        if not boost:
            continue
        lead["score"] = _clamp_score(float(lead["score"]) + boost)
        lead["priority_boost"] = boost
        lead["priority_tags"] = tags
        boosted += 1
    return boosted


def _mine_priority_refresh(cur, priority: dict, leads: dict[str, dict]) -> int:
    """Re-mine held + watchlist symbols for fresh scalp/catalyst signals."""
    refresh_syms = sorted(
        priority.get("held", set())
        | priority.get("watchlist_directive", set())
        | priority.get("watchlist_active", set()),
    )[:60]
    if not refresh_syms:
        return 0

    added = 0
    cur.execute(
        """SELECT symbol, score, grade, decision, rvol, gap_pct, change_pct
           FROM scalp_scan_results
           WHERE symbol = ANY(%s)
             AND scanned_at > NOW() - INTERVAL '36 hours'
             AND decision IN ('GO', 'A+', 'WAIT')
           ORDER BY score DESC NULLS LAST, scanned_at DESC""",
        (refresh_syms,),
    )
    for sym, score, grade, decision, rvol, gap, chg in cur.fetchall():
        before = len(leads)
        _merge_lead(
            leads, sym,
            score=float(score or 38) + (8 if decision == "GO" else 4),
            thesis=f"Portfolio refresh — social scalp {grade}/{decision}",
            source="portfolio_scalp_refresh",
            rvol=rvol, gap_pct=gap, change_pct=chg, refresh=True,
        )
        if len(leads) > before:
            added += 1

    cur.execute(
        """SELECT symbol, score, decision, rvol, gap_pct, change_pct, catalyst, source
           FROM trade_ai_scans
           WHERE symbol = ANY(%s)
             AND scanned_at > NOW() - INTERVAL '24 hours'
             AND decision IN ('GO', 'WAIT')
           ORDER BY score DESC NULLS LAST""",
        (refresh_syms,),
    )
    for sym, score, decision, rvol, gap, chg, catalyst, source in cur.fetchall():
        before = len(leads)
        _merge_lead(
            leads, sym,
            score=float(score or 34) + (6 if decision == "GO" else 0),
            thesis=f"Portfolio refresh — {source or 'scan'}: {str(catalyst or 'momentum')[:60]}",
            source="portfolio_scan_refresh",
            rvol=rvol, gap_pct=gap, change_pct=chg, catalyst=catalyst, refresh=True,
        )
        if len(leads) > before:
            added += 1

    cur.execute(
        """SELECT symbol, day_change_pct, volume, avg_volume
           FROM market_quotes
           WHERE symbol = ANY(%s)
             AND fetched_at > NOW() - INTERVAL '6 hours'
             AND day_change_pct IS NOT NULL
             AND ABS(day_change_pct) >= 1.5
             AND volume IS NOT NULL AND avg_volume IS NOT NULL AND avg_volume > 0""",
        (refresh_syms,),
    )
    for sym, chg, vol, avg_vol in cur.fetchall():
        rvol_est = float(vol) / float(avg_vol) if avg_vol else 0
        if rvol_est < 1.0 and abs(float(chg or 0)) < 2.5:
            continue
        before = len(leads)
        _merge_lead(
            leads, sym,
            score=34 + min(16, abs(float(chg or 0)) * 2) + min(10, rvol_est * 3),
            thesis=f"Portfolio refresh — quote {float(chg or 0):+.1f}% rvol~{rvol_est:.1f}x",
            source="portfolio_quote_refresh",
            rvol=round(rvol_est, 2), change_pct=chg, refresh=True,
        )
        if len(leads) > before:
            added += 1

    cur.execute(
        """SELECT symbol, title, relevance_score, source
           FROM news_articles
           WHERE symbol = ANY(%s)
             AND created_at > NOW() - INTERVAL '36 hours'
             AND COALESCE(relevance_score, 0) >= 0.4
           ORDER BY relevance_score DESC NULLS LAST, created_at DESC""",
        (refresh_syms,),
    )
    for sym, title, rel, src in cur.fetchall():
        if not MOMENTUM_NEWS.search(title or ""):
            continue
        before = len(leads)
        _merge_lead(
            leads, sym,
            score=32 + float(rel or 0) * 22,
            thesis=f"Portfolio refresh — news: {(title or '')[:90]}",
            source="portfolio_news_refresh",
            catalyst=title, refresh=True,
        )
        if len(leads) > before:
            added += 1

    return added


def _clamp_score(v: float) -> float:
    return max(20.0, min(95.0, v))


def _merge_lead(leads: dict[str, dict], sym: str, *, score: float, thesis: str, source: str, **extra):
    s = str(sym or "").upper().strip()
    if not re.match(r"^[A-Z]{1,5}$", s):
        return
    prev = leads.get(s)
    payload = {"thesis": thesis[:160], "source": source, **extra}
    if not prev or score > prev["score"]:
        leads[s] = {"symbol": s, "score": _clamp_score(score), **payload}
    elif prev:
        prev["sources"] = sorted(set((prev.get("sources") or [prev.get("source")]) + [source]))


def mine_scalp_leads(conn, signals: dict | None = None, *, max_leads: int = 24) -> list[dict]:
    """Aggregate momentum scalp candidates from non-Finviz-primary sources."""
    cur = conn.cursor()
    signals = signals or {}
    leads: dict[str, dict] = {}

    # 1) Social scalp scanner results (GO / A+)
    cur.execute(
        """SELECT symbol, score, grade, decision, rvol, gap_pct, change_pct, sources, catalyst_verified
           FROM scalp_scan_results
           WHERE scanned_at > NOW() - INTERVAL '36 hours'
             AND decision IN ('GO', 'A+', 'WAIT')
             AND COALESCE(score, 0) >= 35
           ORDER BY score DESC NULLS LAST, scanned_at DESC
           LIMIT 30"""
    )
    for sym, score, grade, decision, rvol, gap, chg, sources, cat_ver in cur.fetchall():
        srcs = sources or []
        if isinstance(srcs, str):
            try:
                srcs = json.loads(srcs)
            except Exception:
                srcs = [srcs]
        bonus = 8 if decision == "GO" else 4
        _merge_lead(
            leads, sym,
            score=float(score or 40) + bonus,
            thesis=f"Social scalp {grade}/{decision} rvol={rvol or '—'}",
            source="scalp_scan_results",
            rvol=rvol, gap_pct=gap, change_pct=chg, sources=srcs, catalyst_verified=cat_ver,
        )

    # 2) trade_ai_scans — non-Finviz sources (premarket social, continuous, catalyst)
    cur.execute(
        """SELECT symbol, score, decision, rvol, gap_pct, change_pct, catalyst, source
           FROM trade_ai_scans
           WHERE scanned_at > NOW() - INTERVAL '24 hours'
             AND decision IN ('GO', 'WAIT')
             AND COALESCE(score, 0) >= 32
             AND (
               source IS NULL
               OR source NOT ILIKE '%%finviz%%'
               OR source = ANY(%s)
             )
           ORDER BY score DESC NULLS LAST
           LIMIT 40""",
        (list(NON_FINVIZ_SCAN_SOURCES),),
    )
    for sym, score, decision, rvol, gap, chg, catalyst, source in cur.fetchall():
        src = source or "trade_ai_scans"
        if "finviz" in src.lower() and src not in NON_FINVIZ_SCAN_SOURCES:
            continue
        _merge_lead(
            leads, sym,
            score=float(score or 35) + (6 if decision == "GO" else 0),
            thesis=f"Scan {src}: {str(catalyst or 'momentum')[:80]}",
            source=src,
            rvol=rvol, gap_pct=gap, change_pct=chg, catalyst=catalyst,
        )

    # 3) intelligence_entities — rvol / social / catalyst (enrichment lane, not Finviz screeners)
    cur.execute(
        """SELECT display_name, rvol, gap_pct, change_pct, social_score, catalyst,
                  confluence_score, sector
           FROM intelligence_entities
           WHERE active = true
             AND display_name ~ '^[A-Z]{1,5}$'
             AND (
               COALESCE(rvol, 0) >= 1.4
               OR COALESCE(social_score, 0) >= 55
               OR (catalyst IS NOT NULL AND catalyst <> '')
             )
             AND COALESCE(last_enriched, created_at) > NOW() - INTERVAL '5 days'
           ORDER BY COALESCE(confluence_score, 0) DESC, COALESCE(rvol, 0) DESC
           LIMIT 35"""
    )
    for sym, rvol, gap, chg, social, catalyst, conf, sector in cur.fetchall():
        base = 38 + min(20, float(rvol or 0) * 4) + min(10, float(social or 0) / 10)
        _merge_lead(
            leads, sym,
            score=base,
            thesis=f"Intel entity: {str(catalyst or sector or 'momentum')[:80]}",
            source="intelligence_entities",
            rvol=rvol, gap_pct=gap, change_pct=chg, catalyst=catalyst, sector=sector,
        )

    # 4) Live market quotes — intraday movers
    cur.execute(
        """SELECT symbol, day_change_pct, volume, avg_volume
           FROM market_quotes
           WHERE fetched_at > NOW() - INTERVAL '6 hours'
             AND day_change_pct IS NOT NULL
             AND ABS(day_change_pct) >= 2.5
             AND volume IS NOT NULL AND avg_volume IS NOT NULL AND avg_volume > 0
           ORDER BY ABS(day_change_pct) DESC
           LIMIT 25"""
    )
    for sym, chg, vol, avg_vol in cur.fetchall():
        rvol_est = float(vol) / float(avg_vol) if avg_vol else 0
        if rvol_est < 1.2 and abs(float(chg or 0)) < 4:
            continue
        _merge_lead(
            leads, sym,
            score=36 + min(18, abs(float(chg or 0)) * 2) + min(12, rvol_est * 3),
            thesis=f"Live quote mover {float(chg or 0):+.1f}% rvol~{rvol_est:.1f}x",
            source="market_quotes",
            rvol=round(rvol_est, 2), change_pct=chg,
        )

    # 5) News catalysts with momentum language
    cur.execute(
        """SELECT symbol, title, relevance_score, source
           FROM news_articles
           WHERE created_at > NOW() - INTERVAL '36 hours'
             AND symbol IS NOT NULL AND symbol ~ '^[A-Z]{1,5}$'
             AND COALESCE(relevance_score, 0) >= 0.45
           ORDER BY relevance_score DESC NULLS LAST, created_at DESC
           LIMIT 60"""
    )
    for sym, title, rel, src in cur.fetchall():
        if not MOMENTUM_NEWS.search(title or ""):
            continue
        _merge_lead(
            leads, sym,
            score=34 + float(rel or 0) * 25,
            thesis=f"News: {(title or '')[:100]}",
            source=f"news:{src or 'feed'}",
            catalyst=title,
        )

    # 6) Curator catalyst themes → symbols from Hermes research clusters
    for row in (signals.get("catalysts") or [])[:6]:
        theme = str(row.get("theme") or "")
        if not theme:
            continue
        cur.execute(
            """SELECT symbol, topic, confidence_score
               FROM hermes_research_intelligence
               WHERE symbol IS NOT NULL
                 AND status IN ('staged', 'promoted')
                 AND created_at > NOW() - INTERVAL '7 days'
                 AND (topic ILIKE %s OR summary ILIKE %s)
               ORDER BY confidence_score DESC NULLS LAST
               LIMIT 8""",
            (f"%{theme[:40]}%", f"%{theme[:40]}%"),
        )
        for sym, topic, conf in cur.fetchall():
            _merge_lead(
                leads, sym,
                score=40 + float(conf or 0.4) * 30,
                thesis=f"Catalyst theme {theme}: {(topic or '')[:80]}",
                source="hermes_catalyst_theme",
            )

    # 7) RS/RSI from signals — tag as scalp adjunct (Finviz snapshot) but lower weight vs social
    rs = signals.get("rs_rsi") or {}
    for r in (rs.get("rsi_momentum") or [])[:4]:
        _merge_lead(
            leads, r.get("symbol"),
            score=42 + min(15, float(r.get("perf_week_pct") or 0)),
            thesis=f"RSI momentum band {r.get('rsi', 0):.0f}",
            source="rs_rsi_adjunct",
            change_pct=r.get("perf_week_pct"),
        )

    priority = load_portfolio_priority(conn)
    _mine_priority_refresh(cur, priority, leads)
    _apply_priority_boosts(leads, priority)

    def _sort_key(lead: dict):
        tags = lead.get("priority_tags") or []
        tier = 0 if "held" in tags else 1 if tags else 2
        return (tier, -float(lead.get("score") or 0))

    ranked = sorted(leads.values(), key=_sort_key)
    result = ranked[:max_leads]
    for lead in result:
        lead["portfolio_refresh"] = bool(lead.get("refresh")) or bool(lead.get("priority_tags"))
    return result


def stage_scalp_leads_to_incubator(
    conn,
    leads: list[dict],
    *,
    apply: bool,
    max_stage: int = 12,
) -> dict:
    """Upsert momentum_scalp rows into incubator_universe for promoter/screening."""
    if not leads:
        return {"staged": 0, "skipped": 0, "detail": []}

    cur = conn.cursor()
    staged = 0
    detail = []
    run_label = f"scalp_lead_miner:{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')}"

    for lead in leads[:max_stage]:
        sym = lead["symbol"]
        score = lead["score"]
        source = lead.get("source") or "multi_source"
        evidence = {k: lead.get(k) for k in (
            "thesis", "rvol", "gap_pct", "change_pct", "catalyst", "sector", "sources",
            "priority_boost", "priority_tags", "portfolio_refresh", "refresh",
        ) if lead.get(k) is not None}

        if apply:
            cur.execute(
                """INSERT INTO incubator_universe (
                       symbol, strategy_id, status, lifecycle_state,
                       source_first_seen, source_latest, source_run_label,
                       baseline_score, latest_score, best_score, score_delta,
                       rvol_baseline, rvol_latest, gap_baseline, gap_latest,
                       catalyst, catalyst_verified, sector,
                       days_active, first_seen_at, last_seen_at, updated_at,
                       evidence_payload
                   ) VALUES (
                       %s, %s, 'ACTIVE', 'ROLLED_ON',
                       %s, %s, %s,
                       %s, %s, %s, 0,
                       %s, %s, %s, %s,
                       %s, false, %s,
                       0, NOW(), NOW(), NOW(),
                       %s::jsonb
                   )
                   ON CONFLICT (symbol, strategy_id) DO UPDATE SET
                       status = 'ACTIVE',
                       source_latest = EXCLUDED.source_latest,
                       source_run_label = EXCLUDED.source_run_label,
                       latest_score = GREATEST(incubator_universe.latest_score, EXCLUDED.latest_score),
                       best_score = GREATEST(COALESCE(incubator_universe.best_score, 0), EXCLUDED.latest_score),
                       rvol_latest = COALESCE(EXCLUDED.rvol_latest, incubator_universe.rvol_latest),
                       gap_latest = COALESCE(EXCLUDED.gap_latest, incubator_universe.gap_latest),
                       catalyst = COALESCE(EXCLUDED.catalyst, incubator_universe.catalyst),
                       last_seen_at = NOW(),
                       updated_at = NOW(),
                       evidence_payload = EXCLUDED.evidence_payload
                   RETURNING id""",
                (
                    sym, STRATEGY_ID,
                    source, source, run_label,
                    score, score, score,
                    lead.get("rvol"), lead.get("rvol"),
                    lead.get("gap_pct"), lead.get("gap_pct"),
                    lead.get("catalyst") or lead.get("thesis"),
                    lead.get("sector"),
                    json.dumps(evidence, default=str),
                ),
            )
            cur.execute(
                """UPDATE watchlist_items SET
                       origin_system = COALESCE(origin_system, 'scalp_lead_discovery'),
                       origin_detail = COALESCE(origin_detail, '{}'::jsonb) || %s::jsonb,
                       last_validated_at = NOW()
                   WHERE UPPER(symbol) = %s""",
                (json.dumps({"strategy": STRATEGY_ID, "source": source, "score": score}), sym),
            )
            if cur.rowcount == 0 and apply:
                cur.execute(
                    """INSERT INTO watchlist_items (symbol, source, status, origin_system, origin_detail, first_seen_at)
                       VALUES (%s, 'scalp_lead_discovery', 'active', 'scalp_lead_discovery', %s::jsonb, NOW())
                       ON CONFLICT (symbol, source, COALESCE(bucket, '__none__')) DO NOTHING""",
                    (sym, json.dumps({"strategy": STRATEGY_ID, "source": source})),
                )
        staged += 1
        detail.append({"symbol": sym, "score": round(score, 1), "source": source})

    if apply and staged:
        conn.commit()
    return {"staged": staged, "skipped": max(0, len(leads) - staged), "detail": detail[:10]}


def run_scalp_lead_pipeline(
    conn,
    signals: dict | None = None,
    *,
    apply: bool,
    max_mine: int = 24,
    max_stage: int = 12,
) -> dict:
    priority = load_portfolio_priority(conn)
    leads = mine_scalp_leads(conn, signals, max_leads=max_mine)
    priority_boosted = sum(1 for l in leads if l.get("priority_boost"))
    portfolio_refresh = sum(1 for l in leads if l.get("portfolio_refresh"))
    staged = stage_scalp_leads_to_incubator(conn, leads, apply=apply, max_stage=max_stage)
    return {
        "mined": len(leads),
        "priority_boosted": priority_boosted,
        "portfolio_refresh": portfolio_refresh,
        "held_tracked": len(priority.get("held") or ()),
        "watchlist_tracked": len(priority.get("known_watchlist") or ()),
        "leads_sample": leads[:6],
        "incubator": staged,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Mine momentum scalp leads beyond Finviz")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-mine", type=int, default=24)
    parser.add_argument("--max-stage", type=int, default=12)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "scripts"))
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

    import psycopg2
    from think_tank_signal_miner import mine_all_signals

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    signals = mine_all_signals(conn, skip_web=True)
    report = run_scalp_lead_pipeline(conn, signals, apply=args.apply, max_mine=args.max_mine, max_stage=args.max_stage)
    conn.close()
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())