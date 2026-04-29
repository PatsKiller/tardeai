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

    # Load feedback history for confidence adjustment
    feedback_adj = {}
    try:
        cur.execute("""
            SELECT symbol, strategy_type,
                   SUM(CASE WHEN decision='approved' THEN 1 ELSE 0 END) as approved,
                   SUM(CASE WHEN decision='rejected' THEN 1 ELSE 0 END) as rejected,
                   SUM(confidence_adjustment) as total_adj
            FROM agent_feedback_log
            WHERE created_at > NOW() - INTERVAL '90 days'
            GROUP BY symbol, strategy_type
        """)
        for row in cur.fetchall():
            key = (row["symbol"], row["strategy_type"])
            feedback_adj[key] = {
                "approved": int(row["approved"] or 0),
                "rejected": int(row["rejected"] or 0),
                "adj": float(row["total_adj"] or 0),
            }
    except Exception:
        pass  # Table may not exist yet

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

        # Apply feedback-based confidence adjustment
        base_conf = float(c["confidence"])
        fb = feedback_adj.get((c["symbol"], strategy))
        adj_conf = base_conf
        feedback_note = ""
        if fb:
            adj_conf = max(0.1, min(1.0, base_conf + fb["adj"]))
            if fb["rejected"] > fb["approved"]:
                feedback_note = f" [feedback: {fb['rejected']} rejected, skewing down]"
            elif fb["approved"] > 0:
                feedback_note = f" [feedback: {fb['approved']} approved, confidence boosted]"

        # Account-specific proposals
        positions = holdings_map.get(c["symbol"], [{"account": "Unknown", "shares": 0, "value": 0}])
        review_date = (datetime.now() + __import__("datetime").timedelta(days=14)).date()

        # Load personal situation for MAGI/threshold checks (once)
        if not hasattr(propose_rotations, '_ps_loaded'):
            propose_rotations._ps_cache = {}
            try:
                ps_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "personal_situation.json"
                if ps_path.exists():
                    ps = json.loads(ps_path.read_text())
                    fields = ps.get("fields", {})
                    propose_rotations._ps_cache = {
                        "agi": float(fields.get("schedule_c_gross", {}).get("current", 20000))
                              + float(fields.get("ssdi_annual", {}).get("current", 45600)),
                        "roth_ytd": float(fields.get("roth_conversion_ytd_2026", {}).get("current", 35000)),
                        "bracket_ceiling": float(fields.get("next_bracket_ceiling", {}).get("current", 94300)),
                        "ssdi_annual": float(fields.get("ssdi_annual", {}).get("current", 45600)),
                    }
            except Exception:
                pass
            propose_rotations._ps_loaded = True

        ps = propose_rotations._ps_cache
        current_magi = ps.get("agi", 65600) + ps.get("roth_ytd", 35000)
        irmaa_threshold = 103000  # 2026 MFS IRMAA Tier 1 threshold
        medicaid_limit = 20124    # NY Medicaid income limit
        bracket_ceiling = ps.get("bracket_ceiling", 94300)  # 22% bracket top for MFS

        for pos in positions:
            # SSDI-aware impact assessment with MAGI thresholds
            ssdi_impact = "none"
            income_impact = "none"
            irmaa_risk = False
            ssdi_warnings = []

            if pos["account"] in ("Rollover IRA", "401k"):
                ssdi_impact = "conversion_taxable"
                # IRMAA check: would this sale + current MAGI push past threshold?
                projected_magi = current_magi + pos["value"]
                irmaa_risk = projected_magi > irmaa_threshold
                # MFS bracket check: would this push AGI past 22% ceiling?
                if projected_magi > bracket_ceiling:
                    ssdi_warnings.append(f"MAGI ${projected_magi:,.0f} exceeds 22% ceiling ${bracket_ceiling:,.0f}")
                    income_impact = "bracket_jump"
                else:
                    income_impact = "taxable_event"
                # Medicaid 5-year lookback: flag if large distribution could affect eligibility
                if pos["value"] > 50000:
                    ssdi_warnings.append("Large IRA distribution may affect Medicaid 5-year lookback")
            elif pos["account"] == "Roth IRA":
                ssdi_impact = "none"
                income_impact = "none"
                # Roth distributions don't affect MAGI, SSDI, or Medicaid
            elif pos["account"] == "Taxable":
                ssdi_impact = "capital_gains"
                income_impact = "taxable_event"
                # Capital gains add to MAGI
                est_gain = pos["value"] * 0.5  # conservative 50% gain estimate
                if current_magi + est_gain > irmaa_threshold:
                    irmaa_risk = True
                    ssdi_warnings.append(f"Cap gains could push MAGI past IRMAA ${irmaa_threshold:,.0f}")

            # Build enhanced reason with warnings
            reason = f"{c['agent']}: {c['recommendation']} (conf:{base_conf:.0%}). {rule['rule']}{feedback_note}"
            if ssdi_warnings:
                reason += " | SSDI: " + "; ".join(ssdi_warnings)

            ucur.execute("""INSERT INTO watchlist_proposals
                (symbol, action, strategy_type, reason, confidence, proposed_by, status,
                 account_name, shares_to_sell, target_symbol, review_date,
                 ssdi_impact, income_impact, irmaa_risk)
                VALUES (%s, 'rotate', %s, %s, %s, 'rotation_engine', 'proposed',
                        %s, %s, 'cash', %s, %s, %s, %s)""",
                (c["symbol"], strategy, reason, adj_conf,
                 pos["account"], pos["shares"], review_date,
                 ssdi_impact, income_impact, irmaa_risk))
            rotations += 1
            risk_badge = " IRMAA!" if irmaa_risk else ""
            warn_str = f" WARN:{';'.join(ssdi_warnings)}" if ssdi_warnings else ""

            # Auto-execution check: conf≥90%, no SSDI/IRMAA risk, income_impact=none, Roth account
            auto_eligible = (adj_conf >= 0.90 and ssdi_impact == "none"
                             and not irmaa_risk and income_impact == "none"
                             and not ssdi_warnings)
            auto_tag = " [AUTO-ELIGIBLE]" if auto_eligible else ""

            # Check if auto-execute is enabled in intelligence rules
            if auto_eligible:
                try:
                    cur.execute("SELECT config FROM agent_intelligence_rules WHERE rule_type='auto_execute' AND rule_key='low_risk'")
                    ae_row = cur.fetchone()
                    ae_enabled = ae_row and ae_row.get("config", {}).get("enabled", False) if ae_row else False
                    if ae_enabled:
                        # Auto-approve: update status and generate trade instruction
                        ucur.execute("UPDATE watchlist_proposals SET status='approved', reviewed_by='auto_engine', reviewed_at=NOW() WHERE symbol=%s AND status='proposed' AND account_name=%s ORDER BY created_at DESC LIMIT 1",
                                     (c["symbol"], pos["account"]))
                        ucur.execute("""INSERT INTO trade_instructions
                            (symbol, action, account_name, shares, target_symbol,
                             estimated_tax_impact, ssdi_note, irmaa_note, execution_type, status, instruction_text)
                            VALUES (%s, 'sell', %s, %s, 'cash', 0, 'No SSDI impact', 'No IRMAA risk', 'auto_approved', 'pending', %s)""",
                            (c["symbol"], pos["account"], pos["shares"],
                             f"AUTO-APPROVED: Sell {pos['shares']:.0f} shares of {c['symbol']} in {pos['account']}. Conf:{adj_conf:.0%}. No risk flags."))
                        auto_tag = " [AUTO-APPROVED]"
                        print(f"  [auto] {c['symbol']} in {pos['account']}: auto-approved (conf:{adj_conf:.0%}, no risk)")
                except Exception:
                    pass

            print(f"  [rotate] {c['symbol']} in {pos['account']}: {pos['shares']:.0f} shares → cash.{risk_badge} SSDI:{ssdi_impact}{warn_str} conf:{adj_conf:.0%}{auto_tag}")

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

        # Get recent metrics
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT count(*) FROM qualified_intelligence WHERE discovered_at > NOW() - INTERVAL '7 days'")
        intel_count = cur.fetchone()["count"]
        cur.execute("SELECT count(*) FROM watchlist_proposals WHERE status='proposed'")
        proposals_count = cur.fetchone()["count"]
        cur.execute("SELECT count(*) FROM agent_handoffs WHERE escalated=TRUE AND created_at > NOW() - INTERVAL '7 days'")
        escalations = cur.fetchone()["count"]
        # Feedback stats
        feedback_line = ""
        try:
            cur.execute("SELECT decision, count(*) as cnt FROM agent_feedback_log GROUP BY decision")
            fb = {r["decision"]: r["cnt"] for r in cur.fetchall()}
            if fb:
                feedback_line = f"- Human feedback: {fb.get('approved', 0)} approved, {fb.get('rejected', 0)} rejected (confidence adjusted accordingly)\n"
        except Exception:
            pass
        conn.close()

        # FRED macro context
        macro_context = ""
        try:
            from external_market_data_ingest import get_macro_context
            mc = get_macro_context()
            if mc:
                macro_context = f"\n{mc}\n"
        except Exception:
            pass

        # Income data
        income_line = "Income: $14,285/yr vs $55K target. Gap: $40,715."
        try:
            div_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "dividend_calendar.json"
            if div_path.exists():
                dc = json.loads(div_path.read_text())
                annual = float(dc.get("total_annual", 14285))
                gap = 55000 - annual
                income_line = f"Income: ${annual:,.0f}/yr vs $55K target. Gap: ${gap:,.0f} ({annual/55000*100:.0f}% of target)."
        except Exception:
            pass

        prompt = f"""/no_think You are Alex, a disability-optimized retirement planner. Provide a weekly health check.

CLIENT: Age 58, SSDI $3,800/mo, MFS filing, Medicare Dec 2026, $1.2M portfolio.
{income_line}
Tax: {bracket}% bracket, ${room:,.0f} room, Roth YTD ${roth_ytd:,.0f}.
{macro_context}
THIS WEEK:
- {intel_count} qualified intelligence items discovered
- {proposals_count} watchlist proposals pending review
- {escalations} agent escalations
{feedback_line}
Provide weekly health check (under 300 words):
1. Income gap progress — are we on track? What's needed to close the $40K+ gap?
2. Roth conversion pace — ahead/behind schedule? How much more room in 22% bracket?
3. Tax bracket management — room remaining, optimal conversion timing?
4. SSDI/disability considerations — any macro changes affecting disability benefits?
5. Medicaid planning status — NY income limits, MAGI impact of conversions
6. Macro environment impact — how do current rates/inflation affect the retirement plan?
7. Top 3 specific actions for next week with dollar amounts
Be specific with numbers. Address disability implications. Reference macro data if relevant."""

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
