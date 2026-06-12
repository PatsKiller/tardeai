"""watch_universe.py — THE canonical watch-grade symbol universe (single source of truth).

Root cause fixed 2026-06-12: five enrichment pipelines (analyst fetch, news ingestion, external-LLM
curation, pro-analyst read model, position intelligence) each hand-rolled their own universe SQL.
Operator-directive symbols (status='researched', deep hermes ranks) fell through EVERY one — no
analyst pills, no news, no ✦ LLM badges, invisible until the operator noticed.

RULES ENCODED HERE, ONCE:
  • held positions (paper last 30d + portfolio holdings)
  • open/pending proposals
  • today's GO/WAIT scans
  • ACTIVE watchlist items
  • OPERATOR DIRECTIVES — in_directive_watch=true, ANY lifecycle status except removed.
    Operator standing instructions OUTRANK scores and statuses. Always.

Use UNIVERSE_SQL inside a larger query, or symbols(cur) for the resolved set.
audit_enrichment_coverage.py verifies every consumer actually honors this — daily, with alerts.
"""

UNIVERSE_SQL = """
    SELECT DISTINCT symbol FROM (
        SELECT symbol FROM paper_trades
              WHERE entry_time > now() - interval '30 days' AND symbol IS NOT NULL
        UNION SELECT symbol FROM paper_trade_proposals
              WHERE status IN ('PENDING','APPROVED') AND symbol IS NOT NULL
        UNION SELECT symbol FROM trade_ai_scans
              WHERE run_date >= CURRENT_DATE AND decision IN ('GO','WAIT') AND symbol IS NOT NULL
        UNION SELECT symbol FROM watchlist_items
              WHERE status = 'active' AND symbol IS NOT NULL
        UNION SELECT symbol FROM watchlist_items
              WHERE in_directive_watch = true AND status <> 'removed' AND symbol IS NOT NULL
        UNION SELECT symbol FROM watchlist_items
              WHERE source = 'portfolio' AND status <> 'removed' AND symbol IS NOT NULL
    ) watch_universe
"""

TICKER_SHAPE = r"^[A-Z]{1,5}$"


def symbols(cur, tickers_only=True) -> set:
    """Resolved watch-grade symbol set. tickers_only filters to public-ticker shape."""
    q = UNIVERSE_SQL + (f" WHERE symbol ~ '{TICKER_SHAPE}'" if tickers_only else "")
    cur.execute(q)
    return {r[0] if not isinstance(r, dict) else r["symbol"] for r in cur.fetchall()}


def directive_symbols(cur) -> set:
    """Just the operator-directive symbols (the must-never-miss set)."""
    cur.execute("""SELECT DISTINCT symbol FROM watchlist_items
                   WHERE in_directive_watch = true AND status <> 'removed' AND symbol IS NOT NULL""")
    return {r[0] if not isinstance(r, dict) else r["symbol"] for r in cur.fetchall()}
