"""agent_collab.py — Agent collaboration: cross-agent context and escalation.

Agents are LLM prompt calls, not autonomous services. "Collaboration" means:
1. Pulling another agent's latest analysis for a symbol into your prompt
2. Logging handoffs for audit trail
3. Flagging low-confidence or conflicting results for human review

Usage:
    from agent_collab import get_agent_context, log_handoff, check_escalation

    # Get Maria + Risk + Steph latest for V
    ctx = get_agent_context("V", requesting_agent="Alex")

    # Log a handoff
    log_handoff("Alex", "Maria", "V", "Requested latest research for V analysis")

    # Check if escalation needed
    esc = check_escalation("V")
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def get_latest_agent_result(symbol: str, agent: str) -> dict | None:
    """Get the most recent analysis from a specific agent for a symbol."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT symbol, agent, recommendation, confidence, summary,
               next_action, reason_codes, created_at
        FROM watchlist_agent_results
        WHERE symbol = %s AND agent = %s
        ORDER BY created_at DESC LIMIT 1
    """, (symbol.upper(), agent))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_agent_context(symbol: str, requesting_agent: str = "Alex",
                      agents: list = None) -> str:
    """Pull latest analysis from other agents for a symbol.

    Returns formatted text for LLM prompt injection.
    Logs handoffs automatically.
    """
    if agents is None:
        # Default: pull from the three main analysis agents
        agents = ["maria", "steph", "risk_agent"]

    lines = []
    for agent in agents:
        result = get_latest_agent_result(symbol, agent)
        if not result:
            continue

        # Format
        rec = result.get("recommendation", "—")
        conf = result.get("confidence", 0)
        summary = (result.get("summary") or "")[:150]
        next_act = result.get("next_action") or ""
        created = result.get("created_at", "")

        agent_display = agent.replace("_agent", "").title()
        lines.append(f"  {agent_display}: {rec} (conf:{conf}) — {summary}")
        if next_act:
            lines.append(f"    Next: {next_act}")

        # Log handoff
        log_handoff(
            from_agent=requesting_agent,
            to_agent=agent,
            symbol=symbol,
            intent=f"Pulled latest {agent_display} analysis for {symbol}",
            confidence=float(conf) if conf else 0,
        )

    if not lines:
        return ""

    header = f"CROSS-AGENT CONTEXT FOR {symbol.upper()} (latest from other agents):"
    return header + "\n" + "\n".join(lines)


def log_handoff(from_agent: str, to_agent: str, symbol: str = "",
                intent: str = "", confidence: float = 0,
                response_summary: str = "", escalated: bool = False):
    """Log an agent-to-agent handoff for audit."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO agent_handoffs
                (from_agent, to_agent, symbol, intent, confidence,
                 response_summary, escalated, status, user_message, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed', %s, NOW())
        """, (from_agent, to_agent, symbol, intent, confidence,
              response_summary, escalated, intent))
        conn.commit()
        conn.close()
    except Exception:
        pass  # Don't let logging failures break the analysis


def check_escalation(symbol: str) -> dict:
    """Check if a symbol needs escalation based on agent conflicts or low confidence.

    Returns:
        {"needs_escalation": bool, "reasons": [...], "agents": {...}}
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get latest results from all agents for this symbol
    cur.execute("""
        SELECT DISTINCT ON (agent)
            agent, recommendation, confidence, summary, created_at
        FROM watchlist_agent_results
        WHERE symbol = %s
        ORDER BY agent, created_at DESC
    """, (symbol.upper(),))
    results = cur.fetchall()
    conn.close()

    if not results:
        return {"needs_escalation": False, "reasons": ["No agent data"], "agents": {}}

    reasons = []
    agents = {}

    # Collect recommendations
    recs = {}
    for r in results:
        agent = r["agent"]
        rec = (r.get("recommendation") or "").upper()
        conf = float(r.get("confidence") or 0)
        agents[agent] = {"recommendation": rec, "confidence": conf}
        recs[agent] = rec

        # Low confidence check
        if conf < 0.4:
            reasons.append(f"{agent} has low confidence ({conf:.1f})")

    # Conflict detection: BUY vs SELL
    buy_agents = [a for a, r in recs.items() if r in ("BUY", "ADD", "STRONG_BUY")]
    sell_agents = [a for a, r in recs.items() if r in ("SELL", "TRIM", "REDUCE")]
    if buy_agents and sell_agents:
        reasons.append(f"Conflict: {','.join(buy_agents)} say BUY vs {','.join(sell_agents)} say SELL")

    # Check if any critical agents are missing
    expected = {"maria", "steph", "risk_agent"}
    present = {r["agent"] for r in results}
    missing = expected - present
    if missing:
        reasons.append(f"Missing analysis from: {', '.join(missing)}")

    needs_escalation = len(reasons) > 0

    if needs_escalation:
        # Log escalation
        log_handoff(
            from_agent="system",
            to_agent="human_review",
            symbol=symbol,
            intent=f"Escalation: {'; '.join(reasons)}",
            escalated=True,
        )

    return {
        "needs_escalation": needs_escalation,
        "reasons": reasons,
        "agents": agents,
    }


def get_confluence_context(symbol: str, conn, profile: str = 'swing') -> str:
    """Return formatted indicator confluence context for injection into agent prompts.

    Non-fatal — returns empty string if data unavailable.
    Sources: indicator_confluence_cache + live indicator_engine call if cache stale.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT confluence_tier, confluence_score, strategy_badges,
                   key_levels, stop_price, target_price, atr, adx_regime,
                   entry_quality, computed_at
            FROM indicator_confluence_cache
            WHERE symbol = %s AND profile = %s
            AND computed_at > NOW() - INTERVAL '1 hour'
            ORDER BY computed_at DESC LIMIT 1
        """, [symbol, profile])
        row = cur.fetchone()

        if not row:
            # Try live computation (non-fatal)
            try:
                import sys as _sys
                _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                from indicator_engine import analyze_confluence
                result = analyze_confluence(symbol, profile)
                if not result or not result.get('confluence_tier'):
                    return ''
                tier = result.get('confluence_tier', 'NONE')
                score = result.get('confluence_score', 0)
                badges = result.get('strategy_badges', [])
                levels = result.get('key_levels', {})
                stop = result.get('stop_price')
                target = result.get('target_price')
                atr_val = result.get('atr')
                regime = result.get('adx_regime', 'unknown')
            except Exception:
                return ''
        else:
            tier = row[0]
            score = row[1]
            badges = row[2] if row[2] else []
            levels = row[3] if row[3] else {}
            stop = row[4]
            target = row[5]
            atr_val = row[6]
            regime = row[7] or 'unknown'

        if tier == 'NONE' and score == 0:
            return f"\n[TECHNICAL CONFLUENCE: No significant signals for {symbol}]\n"

        badge_str = ', '.join(badges) if badges else 'none'

        lines = [
            f"\n=== TECHNICAL CONFLUENCE ({profile.upper()}) ===",
            f"Symbol: {symbol} | Tier: {tier} | Score: {score}/100",
            f"Active signals: {badge_str}",
            f"Regime: {regime}" + (f" | ATR: ${atr_val:.2f}" if atr_val else ""),
        ]

        if stop or target:
            parts = []
            if stop:
                parts.append(f"Stop: ${stop:.2f}")
            if target:
                parts.append(f"Target: ${target:.2f}")
            lines.append(" | ".join(parts))

        # Key levels from JSONB
        if levels:
            level_parts = []
            pivots = levels.get('pivots_weekly', {})
            if pivots.get('s1'):
                level_parts.append(f"S1: ${pivots['s1']:.2f}")
            if pivots.get('r1'):
                level_parts.append(f"R1: ${pivots['r1']:.2f}")
            bb = levels.get('bollinger', {})
            if bb.get('lower'):
                level_parts.append(f"BB lower: ${bb['lower']:.2f}")
            if bb.get('squeeze'):
                level_parts.append("TTM SQUEEZE ACTIVE")
            if level_parts:
                lines.append("Levels: " + " | ".join(level_parts))

        lines.append("=" * 40)
        return '\n'.join(lines)

    except Exception:
        return ''


def get_prospects_context(symbol: str, conn) -> str:
    """Return pipeline source metadata for a symbol.

    Shows agents which pipelines surfaced this ticker and key scan data.
    Non-fatal — returns empty string if no scan data.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT score, decision, rvol, gap_pct, float_m,
                   social_reddit, social_stocktwits, social_score,
                   social_sentiment, mention_count, social_sources,
                   source, screener_label, catalyst, catalyst_verified
            FROM trade_ai_scans
            WHERE symbol = %s
            AND scanned_at > NOW() - INTERVAL '3 days'
            ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()

        if not row:
            return ''

        (score, decision, rvol, gap_pct, float_m,
         reddit, stocktwits, social_score, social_sentiment,
         mention_count, social_sources, source, screener_label,
         catalyst, catalyst_verified) = row

        lines = [f"\n=== PIPELINE CONTEXT ==="]

        # Source tags
        source_tags = []
        if source and 'screener' in str(source):
            label = "Finviz screener"
            if screener_label:
                label += f" [{screener_label}]"
            source_tags.append(label)
        if source and 'social' in str(source):
            parts = []
            if reddit and reddit > 0:
                parts.append(f"{reddit} Reddit")
            if stocktwits and stocktwits > 0:
                parts.append(f"{stocktwits} StockTwits")
            if mention_count and mention_count > 0:
                parts.append(f"{mention_count} total mentions")
            source_tags.append("Social: " + ", ".join(parts) if parts else "Social")

        if source_tags:
            lines.append("Surfaced by: " + " + ".join(source_tags))

        # Scan data
        scan_parts = []
        if score:
            scan_parts.append(f"Trade AI score: {score} ({decision})")
        if rvol:
            scan_parts.append(f"RVOL: {rvol:.1f}x")
        if gap_pct:
            scan_parts.append(f"Gap: {gap_pct:+.1f}%")
        if float_m:
            scan_parts.append(f"Float: {float_m:.0f}M")
        if scan_parts:
            lines.append(" | ".join(scan_parts))

        # Social signal
        if social_sentiment:
            lines.append(f"Social sentiment: {social_sentiment}" +
                        (f" (score: {social_score:.1f})" if social_score else ""))

        # Catalyst
        if catalyst:
            lines.append(f"Catalyst: {catalyst}" +
                        (" [VERIFIED]" if catalyst_verified else " [unverified]"))

        lines.append("=" * 40)
        return '\n'.join(lines)

    except Exception:
        return ''


def get_scan_intelligence(symbol: str, conn) -> str:
    """
    PRIMARY intelligence source for micro-cap scalp candidates.
    Reads directly from trade_ai_scans — the richest context for GO tickers.
    For micro-caps with no mainstream news, this IS the intelligence.
    Non-fatal — returns empty string if no data.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, score, decision, price, rvol, float_m,
                   gap_pct, change_pct, sector, industry,
                   catalyst, catalyst_verified, catalyst_confidence,
                   catalyst_source, critic_verdict, critic_reasoning,
                   social_reddit, social_stocktwits, social_score,
                   social_sentiment, social_bullish_pct, mention_count,
                   source, screener_label, run_label,
                   ticker_perf_1m, sector_perf_1m, vs_sector_pct, scanned_at
            FROM trade_ai_scans
            WHERE symbol = %s AND scanned_at > NOW() - INTERVAL '7 days'
            ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()
        if not row:
            return ''

        (sym, score, decision, price, rvol, float_m, gap_pct, change_pct,
         sector, industry, catalyst, catalyst_verified, catalyst_confidence,
         catalyst_source, critic_verdict, critic_reasoning,
         social_reddit, social_stocktwits, social_score,
         social_sentiment, social_bullish_pct, mention_count,
         source, screener_label, run_label,
         ticker_perf_1m, sector_perf_1m, vs_sector_pct, scanned_at) = row

        lines = [f"\n=== TRADE AI SCAN: {sym} ==="]
        lines.append(f"{decision} | Score: {score}/65 | Price: ${price:.2f}"
                     + (f" | Gap: {gap_pct:+.1f}%" if gap_pct else ""))

        parts = []
        if rvol:
            label = "EXTREME" if rvol >= 10 else "HIGH" if rvol >= 5 else "moderate"
            parts.append(f"RVOL: {rvol:.1f}x ({label})")
        if float_m:
            label = "micro-float" if float_m < 10 else "small" if float_m < 50 else "mid"
            parts.append(f"Float: {float_m:.1f}M ({label})")
        if change_pct:
            parts.append(f"Change: {change_pct:+.1f}%")
        if parts:
            lines.append(" | ".join(parts))

        if catalyst:
            tag = " [VERIFIED]" if catalyst_verified else " [unverified]"
            conf = f" ({catalyst_confidence:.0%})" if catalyst_confidence else ""
            lines.append(f"Catalyst: {catalyst}{tag}{conf}")
            if catalyst_source:
                lines.append(f"  Source: {catalyst_source}")
        else:
            lines.append("Catalyst: Not identified — pure technical/volume setup")

        if critic_verdict:
            lines.append(f"Critic: {critic_verdict}" +
                        (f" — {critic_reasoning[:120]}" if critic_reasoning else ""))

        social_parts = []
        if social_reddit and social_reddit > 0:
            social_parts.append(f"{social_reddit} Reddit")
        if social_stocktwits and social_stocktwits > 0:
            social_parts.append(f"{social_stocktwits} StockTwits")
        if social_sentiment:
            social_parts.append(f"sentiment: {social_sentiment}")
        if social_parts:
            lines.append("Social: " + " | ".join(social_parts))

        if sector:
            s = [sector]
            if vs_sector_pct:
                s.append(f"{'outperforming' if vs_sector_pct > 0 else 'underperforming'} sector by {abs(vs_sector_pct):.1f}%")
            lines.append("Sector: " + " | ".join(s))

        if screener_label or run_label:
            lines.append(f"Discovered by: {screener_label or run_label or source}")

        lines.append("=" * 40)
        return '\n'.join(lines) + '\n'
    except Exception:
        return ''


def get_scalp_agent_instructions(symbol: str, conn) -> str:
    """
    Returns scalp-specific analysis instructions for micro-cap GO tickers.
    Only injects for price<$100, float<200M symbols from screener.
    Non-fatal — returns empty string if not applicable.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT price, float_m, decision, rvol
            FROM trade_ai_scans
            WHERE symbol = %s AND decision IN ('GO','WAIT')
            AND scanned_at > NOW() - INTERVAL '7 days'
            ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()
        if not row:
            return ''
        price, float_m, decision, rvol = row
        if price and price > 100:
            return ''
        if float_m and float_m > 200:
            return ''

        return """
=== SCALP ANALYSIS CONTEXT ===
This is a MICRO-CAP MOMENTUM SCALP candidate from the Trade AI screener.
Apply scalp-specific analysis, NOT portfolio/retirement analysis.

ANALYZE:
1. CATALYST QUALITY: Hard (FDA/earnings/8-K) = high conviction. Soft (rumor/buzz) = lower.
2. ENTRY TIMING: Is price extended from gap? Is RVOL fading? Continuation or late-stage?
3. RISK FACTORS: Float <5M = extreme vol. Dilution risk from S-1/424B filings. Halt risk.
4. TRADE PARAMS: Entry level, stop (0.5x ATR below), target (1.5-3x ATR above), hold=intraday.
5. VERDICT: "SCALP: [BUY/AVOID/WAIT] — [reason in 10 words]"

DO NOT analyze as portfolio position. No IRMAA/SSDI/retirement references for scalps.
=================================
"""
    except Exception:
        return ''


def get_entity_intelligence(entity_id: str, conn) -> str:
    """
    Get complete formatted intelligence context for any entity.
    Uses intelligence_entity_manager for the canonical IER record.
    Falls back to get_confluence_context() + get_prospects_context() if IEM unavailable.
    Non-fatal — returns empty string on error.
    """
    try:
        from scripts.intelligence_entity_manager import get_entity_context_for_prompt
        return get_entity_context_for_prompt(conn, entity_id)
    except Exception:
        # Fallback to old scatter-gather
        try:
            ctx = get_confluence_context(entity_id, conn)
            ctx += get_prospects_context(entity_id, conn)
            return ctx
        except Exception:
            return ''


def get_calibration_context(agent_name: str, conn) -> str:
    """
    Return this agent's recommendation accuracy for prompt injection.
    Non-fatal — returns '' if no data yet.
    Agents see their own track record before analyzing any symbol.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT config FROM agent_intelligence_rules
            WHERE rule_type = 'calibration_stats' AND rule_key = %s
            ORDER BY updated_at DESC LIMIT 1
        """, [f"accuracy_{agent_name}"])
        row = cur.fetchone()
        if row and row[0]:
            data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            text = data.get('text', '')
            if text:
                return f"\n{text}\n"
        # Fallback: direct query
        cur.execute("""
            SELECT accuracy_pct, correct_count, wrong_count,
                   total_recommendations, trending
            FROM agent_calibration
            WHERE agent_name = %s AND window_days = 90
            AND strategy_type IS NULL AND total_recommendations >= 3
        """, [agent_name])
        row = cur.fetchone()
        if row and row[0]:
            acc, correct, wrong, total, trending = row
            trend = {'IMPROVING': '↑', 'DECLINING': '↓', 'STABLE': '→'}.get(trending or '', '')
            return (f"\n=== YOUR ACCURACY (90d) ===\n"
                    f"Overall: {acc:.0f}% ({correct}/{total} correct) {trend}\n"
                    f"Calibrate confidence accordingly.\n{'=' * 40}\n")

        # No calibration data yet — show accumulating message
        try:
            cur.execute("SELECT COUNT(*) FROM agent_recommendation_outcomes")
            total_outcomes = cur.fetchone()[0] or 0
        except Exception:
            total_outcomes = 0

        if total_outcomes > 0:
            return (f"\n=== CALIBRATION STATUS ===\n"
                    f"Accuracy tracking: {total_outcomes} trade outcome(s) scored.\n"
                    f"Need 3+ per strategy type for meaningful accuracy data.\n"
                    f"Continue analyzing — calibration improves with each closed trade.\n"
                    f"{'=' * 40}\n")
        else:
            return (f"\n=== CALIBRATION STATUS ===\n"
                    f"No closed trades scored yet. "
                    f"System will track your accuracy as trades close.\n"
                    f"{'=' * 40}\n")
    except Exception:
        return ''
