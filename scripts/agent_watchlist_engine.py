#!/usr/bin/env python3
"""agent_watchlist_engine.py — Qualified intelligence + watchlist proposals + discovery summaries.

Three jobs:
1. Promote high-quality intel to qualified_intelligence (Q≥70, ai_validated)
2. Propose watchlist adds from qualified intel (symbols not yet tracked)
3. Generate daily "What I Discovered" summary

Usage:
    python3 scripts/agent_watchlist_engine.py --promote          # Promote high-Q intel
    python3 scripts/agent_watchlist_engine.py --propose          # Propose watchlist adds
    python3 scripts/agent_watchlist_engine.py --discovery [--telegram]  # Daily discovery summary
    python3 scripts/agent_watchlist_engine.py --all [--telegram]
    python3 scripts/agent_watchlist_engine.py --test
    python3 scripts/agent_watchlist_engine.py --status
"""
import json, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _send_tg(msg):
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass


# ── Job 1: Promote high-quality intel ────────────────────────────────

def promote_qualified_intel() -> dict:
    """Scan all content tables and promote high-quality items to qualified_intelligence."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ucur = conn.cursor()
    promoted = 0

    # News articles (relevance as quality proxy — 0-1 scale, so Q≥0.7)
    cur.execute("""
        SELECT id, symbol, title, source, relevance_score, strategy_tags, agent_tags
        FROM news_articles
        WHERE relevance_score >= 0.7
          AND id NOT IN (SELECT source_id FROM qualified_intelligence WHERE source_type='news')
        ORDER BY relevance_score DESC LIMIT 50
    """)
    for r in cur.fetchall():
        ucur.execute("""INSERT INTO qualified_intelligence
            (source_type, source_table, source_id, symbol, title, strategy_focus, quality_score, relevance_score)
            VALUES ('news', 'news_articles', %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING""",
            (r["id"], r["symbol"], r["title"][:200],
             (r.get("strategy_tags") or [""])[0] if r.get("strategy_tags") else "",
             int(float(r["relevance_score"]) * 100), r["relevance_score"]))
        promoted += 1

    # YouTube transcripts (Q≥70 + ai_validated)
    cur.execute("""
        SELECT id, title, channel_name, quality_score, relevance_score, validation_status,
               structured_json, sub_tags, strategy_tags
        FROM youtube_transcripts
        WHERE quality_score >= 70 AND validation_status = 'ai_validated'
          AND id NOT IN (SELECT source_id FROM qualified_intelligence WHERE source_type='youtube')
    """)
    for r in cur.fetchall():
        sj = r.get("structured_json") or {}
        retirement_rel = sj.get("retirement_relevance", "medium") if isinstance(sj, dict) else "medium"
        ucur.execute("""INSERT INTO qualified_intelligence
            (source_type, source_table, source_id, title, strategy_focus, sub_tags,
             quality_score, relevance_score, retirement_relevance, structured_json)
            VALUES ('youtube', 'youtube_transcripts', %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING""",
            (r["id"], r["title"][:200], r.get("channel_name", ""),
             json.dumps(r.get("sub_tags") or []),
             r["quality_score"], float(r["relevance_score"]),
             retirement_rel, json.dumps(sj) if sj else None))
        promoted += 1

    # SEC Form 4 (all insider filings are qualified by definition)
    cur.execute("""
        SELECT id, symbol, filer_name, transaction_type, filing_date
        FROM sec_form4
        WHERE id NOT IN (SELECT source_id FROM qualified_intelligence WHERE source_type='sec_form4')
    """)
    for r in cur.fetchall():
        ucur.execute("""INSERT INTO qualified_intelligence
            (source_type, source_table, source_id, symbol, title, quality_score, relevance_score)
            VALUES ('sec_form4', 'sec_form4', %s, %s, %s, 80, 0.8)
            ON CONFLICT DO NOTHING""",
            (r["id"], r["symbol"], f"Form 4: {r['filer_name']} {r['transaction_type']}"[:200]))
        promoted += 1

    conn.commit()
    conn.close()
    print(f"[qualify] Promoted {promoted} items to qualified_intelligence")
    return {"promoted": promoted}


# ── Job 2: Propose watchlist adds ────────────────────────────────────

def propose_watchlist_adds() -> dict:
    """Find symbols in qualified intel that aren't on watchlist, propose additions."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Symbols in qualified intel but not on watchlist
    cur.execute("""
        SELECT qi.symbol, count(*) as mentions, avg(qi.quality_score) as avg_q,
               array_agg(DISTINCT qi.strategy_focus) as strategies,
               array_agg(qi.id) as intel_ids
        FROM qualified_intelligence qi
        WHERE qi.symbol != '' AND qi.symbol IS NOT NULL
          AND qi.symbol NOT IN (SELECT symbol FROM watchlist_items)
          AND qi.symbol NOT IN (SELECT symbol FROM watchlist_proposals WHERE status='proposed')
        GROUP BY qi.symbol
        HAVING count(*) >= 2
        ORDER BY avg(qi.quality_score) DESC
        LIMIT 10
    """)
    proposals = cur.fetchall()

    ucur = conn.cursor()
    proposed = 0
    for p in proposals:
        strat = [s for s in (p["strategies"] or []) if s]
        strategy = strat[0] if strat else "core_growth_compounder"
        ucur.execute("""INSERT INTO watchlist_proposals
            (symbol, action, strategy_type, reason, source_intel_ids, confidence, proposed_by)
            VALUES (%s, 'add', %s, %s, %s, %s, 'agent_watchlist_engine')
            ON CONFLICT DO NOTHING""",
            (p["symbol"], strategy,
             f"{p['mentions']} qualified intel mentions, avg Q:{float(p['avg_q']):.0f}",
             list(p["intel_ids"][:10]) if p.get("intel_ids") else [], float(p["avg_q"]) / 100))
        proposed += 1

    conn.commit()
    conn.close()
    print(f"[propose] Created {proposed} watchlist proposals")
    return {"proposed": proposed}


# ── Job 3: Daily discovery summary ───────────────────────────────────

def generate_discovery_summary(send_telegram: bool = False) -> dict:
    """Alex generates 'What I Discovered Today' from qualified intel."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Today's qualified intel
    cur.execute("""
        SELECT source_type, title, symbol, quality_score, retirement_relevance, strategy_focus
        FROM qualified_intelligence
        WHERE discovered_at > CURRENT_DATE
        ORDER BY quality_score DESC LIMIT 15
    """)
    items = cur.fetchall()

    # Pending proposals
    cur.execute("SELECT symbol, strategy_type, confidence FROM watchlist_proposals WHERE status='proposed'")
    proposals = cur.fetchall()

    conn.close()

    if not items and not proposals:
        print("[discovery] Nothing new today")
        return {"items": 0, "proposals": 0}

    # Build summary
    lines = [f"\U0001F4A1 *Alex: What I Discovered Today*", f"_{datetime.now().strftime('%B %d, %Y')}_", ""]

    if items:
        lines.append(f"*{len(items)} high-quality intelligence items:*")
        for item in items[:8]:
            src = item["source_type"][0].upper()
            q = item["quality_score"]
            sym = f" ({item['symbol']})" if item["symbol"] else ""
            rel = item.get("retirement_relevance", "")
            rel_badge = " \U0001F3AF" if rel == "high" else ""
            lines.append(f"  [{src}] Q:{q}{rel_badge} {item['title'][:55]}{sym}")

    if proposals:
        lines.append("")
        lines.append(f"*{len(proposals)} watchlist proposals (pending review):*")
        for p in proposals[:5]:
            lines.append(f"  {p['symbol']} ({p['strategy_type'].replace('_',' ')}) conf:{float(p['confidence']):.0%}")

    summary_text = "\n".join(lines)

    # Store in discovery log
    try:
        conn = _get_conn()
        cur = conn.cursor()
        symbols = list(set(i["symbol"] for i in items if i.get("symbol")))
        cur.execute("""INSERT INTO agent_discovery_log (discovery_type, title, summary, symbols_mentioned, intel_count)
            VALUES ('daily', %s, %s, %s, %s)""",
            (f"Daily Discovery — {datetime.now().strftime('%Y-%m-%d')}",
             summary_text[:2000], json.dumps(symbols[:20]), len(items)))
        conn.commit()
        conn.close()
    except Exception:
        pass

    if send_telegram:
        _send_tg(summary_text)

    print(f"[discovery] {len(items)} items, {len(proposals)} proposals")
    print(summary_text)
    return {"items": len(items), "proposals": len(proposals)}


# ── Job 4: Rotation proposals (strategy-aware) ──────────────────────

ROTATION_RULES = {
    # NEVER auto-rotate income assets unless income floor threatened
    "dividend_growth_compounder": {"auto_rotate": False, "rule": "HOLD unless dividend cut or payout unsafe"},
    "dividend_growth_compounding": {"auto_rotate": False, "rule": "HOLD unless dividend cut or payout unsafe"},
    "high_yield_income_bdc": {"auto_rotate": False, "rule": "HOLD unless income floor threatened (>20% of portfolio income)"},
    "tactical_income": {"auto_rotate": False, "rule": "HOLD unless yield drops below 4%"},
    "reit_income": {"auto_rotate": False, "rule": "HOLD unless occupancy collapse"},
    "bond_income": {"auto_rotate": False, "rule": "HOLD unless duration mismatch"},
    # Swing/tactical CAN rotate
    "swing_trade": {"auto_rotate": True, "rule": "Rotate on RSI >75 or <25 + catalyst exhaustion"},
    "core_growth_compounder": {"auto_rotate": True, "rule": "Rotate if PE >40 AND growth decelerating"},
    # Retirement: Alex-specific
    "retirement_planning": {"auto_rotate": False, "rule": "Alex reviews: Roth ladder, tax bracket, SSDI impact"},
    "disability_retirement_planning": {"auto_rotate": False, "rule": "Alex reviews: Medicaid, IRMAA, MFS implications"},
}


def propose_rotations() -> dict:
    """Check positions against rotation rules. Account-specific, SSDI-aware proposals."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get latest agent results with strategy + account info
    cur.execute("""
        SELECT DISTINCT ON (r.symbol)
            r.symbol, r.agent, r.recommendation, r.confidence,
            tsc.strategy_type
        FROM watchlist_agent_results r
        JOIN ticker_strategy_classifications tsc ON r.symbol = tsc.symbol AND tsc.active=TRUE
        WHERE r.created_at > NOW() - INTERVAL '14 days'
          AND r.recommendation IN ('SELL', 'TRIM', 'AVOID')
          AND r.confidence > 0.5
        ORDER BY r.symbol, r.confidence DESC
    """)
    sell_candidates = cur.fetchall()

    # Load holdings for account-specific details
    holdings_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    holdings_map = {}
    try:
        import json as _j
        h = _j.loads(holdings_path.read_text())
        for pos in h.get("holdings", []):
            sym = pos.get("symbol", "")
            if sym:
                if sym not in holdings_map:
                    holdings_map[sym] = []
                aid = pos.get("account_id", pos.get("account", ""))
                acct_type = "Roth IRA" if "roth" in aid.lower() else "Rollover IRA" if "rollover" in aid.lower() or "ira" in aid.lower() else "401k" if "401k" in aid.lower() else "Taxable"
                holdings_map[sym].append({
                    "account": acct_type,
                    "shares": float(pos.get("shares", 0) or 0),
                    "value": float(pos.get("market_value", 0) or 0),
                })
    except Exception:
        pass

    ucur = conn.cursor()
    rotations = 0

    for c in sell_candidates:
        strategy = c.get("strategy_type", "")
        rule = ROTATION_RULES.get(strategy, {"auto_rotate": False, "rule": "Unknown — manual review"})

        if not rule["auto_rotate"]:
            continue

        # Skip if already proposed
        cur.execute("SELECT id FROM watchlist_proposals WHERE symbol=%s AND status='proposed' AND action='rotate'", (c["symbol"],))
        if cur.fetchone():
            continue

        # Account-specific proposals
        positions = holdings_map.get(c["symbol"], [{"account": "Unknown", "shares": 0, "value": 0}])
        review_date = (datetime.now() + __import__("datetime").timedelta(days=14)).date()

        for pos in positions:
            # SSDI impact assessment
            ssdi_impact = "none"
            income_impact = "none"
            irmaa_risk = False

            if pos["account"] in ("Rollover IRA", "401k"):
                ssdi_impact = "conversion_taxable"  # Selling here creates taxable event if converted
                irmaa_risk = pos["value"] > 50000  # Large IRA sale could push MAGI up
            elif pos["account"] == "Roth IRA":
                ssdi_impact = "none"  # Roth sales are tax-free
                income_impact = "none"
            elif pos["account"] == "Taxable":
                ssdi_impact = "capital_gains"  # May trigger capital gains
                income_impact = "taxable_event"

            ucur.execute("""INSERT INTO watchlist_proposals
                (symbol, action, strategy_type, reason, confidence, proposed_by, status,
                 account_name, shares_to_sell, target_symbol, review_date,
                 ssdi_impact, income_impact, irmaa_risk)
                VALUES (%s, 'rotate', %s, %s, %s, 'rotation_engine', 'proposed',
                        %s, %s, 'cash', %s, %s, %s, %s)""",
                (c["symbol"], strategy,
                 f"{c['agent']}: {c['recommendation']} (conf:{float(c['confidence']):.0%}). {rule['rule']}",
                 float(c["confidence"]),
                 pos["account"], pos["shares"], review_date,
                 ssdi_impact, income_impact, irmaa_risk))
            rotations += 1
            risk_badge = " IRMAA!" if irmaa_risk else ""
            print(f"  [rotate] {c['symbol']} in {pos['account']}: {pos['shares']:.0f} shares → cash.{risk_badge} SSDI:{ssdi_impact}")

    conn.commit()
    conn.close()
    print(f"[rotate] {rotations} rotation proposals created")
    return {"rotations": rotations}


# ── Job 5: Weekly retirement health check ────────────────────────────

def weekly_health_check(send_telegram: bool = False) -> dict:
    """Deep weekly check: income gap, Roth progress, allocation drift, disability considerations."""
    if datetime.now().weekday() != 6 and "--force" not in sys.argv:
        print("[health] Not Sunday — skipping (use --force to override)")
        return {"skipped": True}

    try:
        from llm_router import get_llm_response
        from alex_retirement_advisor import get_tax_context

        tax = get_tax_context(2026)
        bracket = tax.get("current_bracket", 12)
        room = tax.get("bracket_room_22pct", 0)
        roth_ytd = tax.get("roth_conversions_ytd", 0)

        # Get recent qualified intel count
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT count(*) FROM qualified_intelligence WHERE discovered_at > NOW() - INTERVAL '7 days'")
        intel_count = cur.fetchone()["count"]
        cur.execute("SELECT count(*) FROM watchlist_proposals WHERE status='proposed'")
        proposals_count = cur.fetchone()["count"]
        cur.execute("SELECT count(*) FROM agent_handoffs WHERE escalated=TRUE AND created_at > NOW() - INTERVAL '7 days'")
        escalations = cur.fetchone()["count"]
        conn.close()

        prompt = f"""/no_think You are Alex, a disability-optimized retirement planner. Provide a weekly health check.

CLIENT: Age 58, SSDI $3,800/mo, MFS filing, Medicare Dec 2026, $1.2M portfolio.
Income: $14,285/yr vs $55K target. Gap: $40,715.
Tax: {bracket}% bracket, ${room:,.0f} room, Roth YTD ${roth_ytd:,.0f}.

THIS WEEK:
- {intel_count} qualified intelligence items discovered
- {proposals_count} watchlist proposals pending review
- {escalations} agent escalations

Provide weekly health check (under 250 words):
1. Income gap progress — are we on track?
2. Roth conversion pace — ahead/behind schedule?
3. Tax bracket management — room remaining?
4. SSDI/disability considerations — anything changed?
5. Medicaid planning status
6. Top 3 actions for next week
Be specific with numbers. Address disability implications."""

        result = get_llm_response("cio_synthesis", prompt, max_tokens=500, high_impact=True)
        review = result.get("response", "Health check unavailable") if result.get("success") else "Health check failed"

        # Store
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""INSERT INTO agent_discovery_log (discovery_type, title, summary, intel_count, provider)
                VALUES ('weekly_health', %s, %s, %s, %s)""",
                (f"Weekly Health Check — {datetime.now().strftime('%Y-%m-%d')}",
                 review[:2000], intel_count, result.get("provider", "")))
            cur.execute("""INSERT INTO ai_reports (report_type, title, content, provider)
                VALUES ('weekly_health', %s, %s, %s)""",
                (f"Weekly Health Check — {datetime.now().strftime('%b %d, %Y')}",
                 review, result.get("provider", "")))
            conn.commit()
            conn.close()
        except Exception:
            pass

        if send_telegram:
            divider = "\u2501" * 24
            _send_tg(f"\U0001F3E5 *Alex Weekly Health Check*\n{divider}\n\n{review[:1800]}\n\n{divider}\n_via {result.get('provider','?')}_")

        print(f"[health] Weekly check complete via {result.get('provider', '?')}")
        return {"status": "completed", "provider": result.get("provider")}
    except Exception as e:
        print(f"[health] Error: {e}")
        return {"error": str(e)}


# ── Status ───────────────────────────────────────────────────────────

def show_status():
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT source_type, count(*) FROM qualified_intelligence GROUP BY source_type")
    print("Qualified Intelligence:")
    for r in cur.fetchall():
        print(f"  {r['source_type']}: {r['count']}")

    cur.execute("SELECT count(*) FROM qualified_intelligence")
    print(f"  Total: {cur.fetchone()['count']}")

    cur.execute("SELECT status, count(*) FROM watchlist_proposals GROUP BY status")
    print("\nWatchlist Proposals:")
    for r in cur.fetchall():
        print(f"  {r['status']}: {r['count']}")

    cur.execute("SELECT count(*) FROM agent_discovery_log")
    print(f"\nDiscovery Logs: {cur.fetchone()['count']}")
    conn.close()


def test():
    print("=== Agent Watchlist Engine Test ===\n")
    print("1. Promoting qualified intel...")
    r1 = promote_qualified_intel()
    print(f"   {r1}")

    print("\n2. Proposing watchlist adds...")
    r2 = propose_watchlist_adds()
    print(f"   {r2}")

    print("\n3. Proposing rotations...")
    r3 = propose_rotations()
    print(f"   {r3}")

    print("\n4. Generating discovery summary...")
    r4 = generate_discovery_summary()
    print(f"   {r4}")

    print("\n5. Status:")
    show_status()
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    if "--test" in sys.argv:
        test()
    elif "--promote" in sys.argv:
        promote_qualified_intel()
    elif "--propose" in sys.argv:
        propose_watchlist_adds()
    elif "--discovery" in sys.argv:
        generate_discovery_summary(send_telegram=tg)
    elif "--rotate" in sys.argv:
        propose_rotations()
    elif "--health" in sys.argv:
        weekly_health_check(send_telegram=tg)
    elif "--all" in sys.argv or "--daily" in sys.argv:
        promote_qualified_intel()
        propose_watchlist_adds()
        propose_rotations()
        generate_discovery_summary(send_telegram=tg)
    elif "--weekly" in sys.argv:
        promote_qualified_intel()
        propose_watchlist_adds()
        propose_rotations()
        generate_discovery_summary(send_telegram=tg)
        weekly_health_check(send_telegram=tg)
    elif "--status" in sys.argv:
        show_status()
    else:
        print("Usage:")
        print("  --test              Full test run")
        print("  --daily / --all     Promote + propose + rotate + discovery")
        print("  --weekly            Daily + weekly health check")
        print("  --promote           Promote high-Q intel only")
        print("  --propose           Propose watchlist adds only")
        print("  --rotate            Propose rotations only")
        print("  --discovery         Discovery summary only")
        print("  --health [--force]  Weekly retirement health check")
        print("  --status            Show current counts")
        print("  Add --telegram to send alerts")
