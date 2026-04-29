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
