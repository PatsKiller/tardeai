#!/usr/bin/env python3
"""watchlist_hygiene.py — Automated watchlist cleanup and rotation.

Removes or demotes symbols that are no longer relevant:
1. AI-discovered symbols with low confidence after analysis → remove
2. All agents recommend SELL/TRIM/AVOID → flag for removal
3. Stale symbols with no analysis in 30+ days → remove
4. Blocked/unsafe synthesis results → review or remove
5. Symbols with zero portfolio weight + no recent intel → prune

Also handles rotation: when agents identify better alternatives,
log the rotation suggestion for human review.

Runs weekly (Sunday) after agent analysis has accumulated.

Usage:
    python3 scripts/watchlist_hygiene.py [--telegram] [--dry-run] [--force]
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


def find_removals() -> dict:
    """Find symbols that should be removed or demoted from watchlist."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    removals = []
    reviews = []
    rotations = []

    # 1. AI-discovered with low confidence after full analysis
    cur.execute("""
        SELECT wi.symbol, wfs.recommendation, wfs.confidence, wfs.conflicts
        FROM watchlist_items wi
        JOIN watchlist_final_synthesis wfs ON wi.symbol = wfs.symbol
        WHERE wi.source = 'ai_discovered' AND wi.status = 'active'
          AND wfs.confidence < 0.35
          AND wfs.recommendation IN ('AVOID', 'SELL', 'IGNORE')
    """)
    for r in cur.fetchall():
        removals.append({
            "symbol": r["symbol"],
            "reason": f"AI-discovered, low confidence ({float(r['confidence']):.0%}), rec={r['recommendation']}",
            "action": "remove",
            "source": "low_confidence_discovery",
        })

    # 2. ALL agents recommend SELL/TRIM/AVOID (consensus negative)
    cur.execute("""
        WITH latest_recs AS (
            SELECT DISTINCT ON (symbol, agent) symbol, agent, recommendation, confidence
            FROM watchlist_agent_results
            WHERE created_at > NOW() - INTERVAL '14 days'
            ORDER BY symbol, agent, created_at DESC
        )
        SELECT symbol,
               array_agg(agent || ':' || recommendation) as recs,
               avg(confidence) as avg_conf
        FROM latest_recs
        GROUP BY symbol
        HAVING count(*) >= 2
           AND bool_and(recommendation IN ('SELL','TRIM','AVOID','IGNORE'))
    """)
    for r in cur.fetchall():
        # Don't remove live portfolio holdings — flag for review instead.
        # source='portfolio' alone is NOT "currently held" (sold names leave stale rows).
        try:
            from sync_portfolio_watchlist_membership import held_symbols_from_holdings
            is_held = r["symbol"] and str(r["symbol"]).upper() in held_symbols_from_holdings()
        except Exception:
            cur.execute("""SELECT symbol FROM watchlist_items
                           WHERE symbol=%s AND source='portfolio' AND status<>'removed'""",
                        (r["symbol"],))
            is_held = cur.fetchone()
        entry = {
            "symbol": r["symbol"],
            "reason": f"All agents negative: {', '.join(r['recs'])} (avg conf {float(r['avg_conf']):.0%})",
            "source": "consensus_negative",
        }
        if is_held:
            entry["action"] = "review"
            reviews.append(entry)
        else:
            entry["action"] = "remove"
            removals.append(entry)

    # 3. Stale — no analysis in 30+ days, not a portfolio holding
    cur.execute("""
        WITH latest AS (
            SELECT symbol, max(created_at) as last_analyzed
            FROM watchlist_agent_results GROUP BY symbol
        )
        SELECT wi.symbol, l.last_analyzed
        FROM watchlist_items wi
        LEFT JOIN latest l ON wi.symbol = l.symbol
        WHERE wi.status = 'active'
          AND wi.source != 'portfolio'
          AND (l.last_analyzed IS NULL OR l.last_analyzed < NOW() - INTERVAL '30 days')
    """)
    for r in cur.fetchall():
        removals.append({
            "symbol": r["symbol"],
            "reason": f"Stale: last analysis {str(r.get('last_analyzed', 'never'))[:10]}",
            "action": "remove",
            "source": "stale",
        })

    # 4. Synthesis blocked/unsafe (non-portfolio)
    cur.execute("""
        SELECT DISTINCT wsh.symbol, wsh.decision_safety
        FROM watchlist_synthesis_safety_history wsh
        JOIN watchlist_items wi ON wsh.symbol = wi.symbol
        WHERE wsh.decision_safety IN ('blocked', 'unsafe')
          AND wi.source != 'portfolio'
          AND wi.status = 'active'
          AND wsh.created_at > NOW() - INTERVAL '14 days'
    """)
    for r in cur.fetchall():
        reviews.append({
            "symbol": r["symbol"],
            "reason": f"Synthesis {r['decision_safety']} — safety gate blocked",
            "action": "review",
            "source": "safety_blocked",
        })

    # 5. Rotation suggestions — symbols where agents found better alternatives
    cur.execute("""
        SELECT DISTINCT ON (symbol) symbol, recommendation, confidence,
               reason_codes, next_action
        FROM watchlist_agent_results
        WHERE recommendation = 'SELL'
          AND confidence > 0.6
          AND created_at > NOW() - INTERVAL '14 days'
          AND next_action IS NOT NULL
          AND next_action != ''
        ORDER BY symbol, created_at DESC
    """)
    for r in cur.fetchall():
        if r.get("next_action"):
            rotations.append({
                "symbol": r["symbol"],
                "reason": f"High-confidence SELL ({float(r['confidence']):.0%})",
                "next_action": r["next_action"][:150],
                "source": "rotation_candidate",
            })

    conn.close()
    return {
        "removals": removals,
        "reviews": reviews,
        "rotations": rotations,
    }


def execute_removals(removals: list, dry_run: bool = False) -> int:
    """Remove symbols from active watchlist."""
    if not removals or dry_run:
        return 0

    conn = _get_conn()
    cur = conn.cursor()
    removed = 0

    for r in removals:
        sym = r["symbol"]
        cur.execute("UPDATE watchlist_items SET status='removed', updated_at=NOW() WHERE symbol=%s AND status='active'", (sym,))
        cur.execute("UPDATE ticker_strategy_classifications SET active=FALSE WHERE symbol=%s", (sym,))
        # Log the removal
        cur.execute("""
            INSERT INTO portfolio_intelligence_events
                (symbol, event_type, severity, source, payload)
            VALUES (%s, 'hygiene_removal', 'info', 'watchlist_hygiene.py', %s)
        """, (sym, json.dumps({"reason": r["reason"], "source": r["source"]}, default=str)))
        removed += 1

    conn.commit()
    conn.close()
    return removed


def run(send_telegram: bool = False, dry_run: bool = False):
    """Run watchlist hygiene check."""
    print(f"[hygiene] {datetime.now().isoformat()} — Running watchlist hygiene")

    results = find_removals()
    removals = results["removals"]
    reviews = results["reviews"]
    rotations = results["rotations"]

    print(f"[hygiene] Found: {len(removals)} to remove, {len(reviews)} to review, {len(rotations)} rotation candidates")

    # Log everything
    for r in removals:
        label = "[DRY RUN] " if dry_run else ""
        print(f"  {label}REMOVE: {r['symbol']:8} — {r['reason']}")
    for r in reviews:
        print(f"  REVIEW: {r['symbol']:8} — {r['reason']}")
    for r in rotations:
        print(f"  ROTATE: {r['symbol']:8} — {r['reason']} → {r['next_action'][:60]}")

    # Execute removals
    removed = execute_removals(removals, dry_run=dry_run)

    # Telegram summary
    if send_telegram and (removals or reviews or rotations):
        try:
            from telegram_alert import send_telegram as _tg
            divider = "\u2501" * 24
            lines = [f"\U0001F9F9 *Watchlist Hygiene Report*", divider, ""]

            if removals:
                lines.append(f"\u274C *Removed ({len(removals)}):*")
                for r in removals[:5]:
                    lines.append(f"  {r['symbol']}: {r['reason'][:50]}")
                lines.append("")

            if reviews:
                lines.append(f"\u26A0\uFE0F *Needs Review ({len(reviews)}):*")
                for r in reviews[:5]:
                    lines.append(f"  {r['symbol']}: {r['reason'][:50]}")
                lines.append("")

            if rotations:
                lines.append(f"\U0001F504 *Rotation Candidates ({len(rotations)}):*")
                for r in rotations[:3]:
                    lines.append(f"  {r['symbol']}: {r['next_action'][:60]}")
                lines.append("")

            lines.append(divider)
            lines.append(f"_Review at /v2/watchlist_")
            _tg("\n".join(lines))
        except Exception:
            pass

    print(f"[hygiene] Done: {removed} removed, {len(reviews)} flagged for review")
    return {
        "removed": removed,
        "reviews": len(reviews),
        "rotations": len(rotations),
        "details": results,
    }


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    dry = "--dry-run" in sys.argv
    run(send_telegram=tg, dry_run=dry)
