#!/usr/bin/env python3
"""data_gap_resolver.py — closes data gaps before overnight runs.

For each open gap in data_gap_registry, dispatch the appropriate
enrichment or agent job. Updates status to 'enriching' then 'resolved'.

Usage:
    .venv/bin/python scripts/data_gap_resolver.py
    .venv/bin/python scripts/data_gap_resolver.py --pre-overnight
    .venv/bin/python scripts/data_gap_resolver.py --weekly-audit
    .venv/bin/python scripts/data_gap_resolver.py --dry-run

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

# One write module owns data_gap_registry (One Source of Truth, phase 9 pattern).
from lib.writers.data_gap_registry_writer import (  # noqa: E402
    abandon,
    abandon_stale,
    mark_dispatched,
    mark_enriching,
    mark_resolved,
    reopen,
)

#: A resolver action returns True when the data is present (proven now), False
#: when it cannot help, or ("dispatched", job_id) when it queued an agent job.
#: A dispatched gap stays 'enriching' until verify_dispatched() sees the job
#: complete with a result row. Before 2026-09-13 dispatch marked it 'resolved'.
DISPATCHED = "dispatched"
#: Failed dispatches before a gap is abandoned instead of re-queued.
MAX_DISPATCH_ATTEMPTS = int(os.environ.get("DATA_GAP_MAX_DISPATCH_ATTEMPTS", "3"))
#: Job states that mean the work will not arrive.
_JOB_DEAD = ("failed", "expired", "superseded", "cancelled", "canceled")


def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [gap-resolver] {msg}", flush=True)


# ── Resolution actions ───────────────────────────────────────────────

def _resolve_missing_div_yield(symbol, conn):
    """Force re-snapshot of ticker to pick up dividend yield."""
    cur = conn.cursor()
    # Check if we already have div_yield somewhere
    cur.execute("""
        SELECT data->>'div_yield' FROM ticker_snapshot_daily
        WHERE symbol = %s ORDER BY snapshot_date DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row and row[0] and row[0] not in ('', 'None', 'null'):
        return True  # Already resolved
    # Queue enrichment agent job
    try:
        # Check if already queued
        cur.execute("""
            SELECT id FROM watchlist_agent_jobs
            WHERE symbol = %s AND requested_agent = 'maria_research'
              AND submitted_from = 'gap_resolver' AND status IN ('queued', 'pending', 'processing')
        """, [symbol])
        existing = cur.fetchone()
        if existing:
            return (DISPATCHED, existing[0])  # already dispatched: track that job
        import hashlib
        job_id = f"gap_{symbol.lower()}_maria_{hashlib.md5(f'{symbol}:enrich:{datetime.now().date()}'.encode()).hexdigest()[:6]}"
        cur.execute("""
            INSERT INTO watchlist_agent_jobs
                (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, created_at)
            VALUES (%s, %s, 'maria_research', 'enrichment', 'data_gap: missing div_yield', 'queued', 1, 'gap_resolver', NOW())
        """, [job_id, symbol])
        conn.commit()
        return (DISPATCHED, job_id)
    except Exception:
        conn.rollback()
        return False


def _resolve_missing_sector(symbol, conn):
    """Similar to div_yield — queue enrichment."""
    return _resolve_missing_div_yield(symbol, conn)


def _resolve_missing_market_data(symbol, conn):
    """Queue enrichment for missing market data fields."""
    return _resolve_missing_div_yield(symbol, conn)


def _resolve_missing_catalyst(symbol, conn):
    """Dispatch Maria research agent to find catalysts."""
    cur = conn.cursor()
    try:
        cur = conn.cursor()
        # Check if already queued
        cur.execute("""
            SELECT id FROM watchlist_agent_jobs
            WHERE symbol = %s AND requested_agent = 'maria_research'
              AND submitted_from = 'gap_resolver' AND status IN ('queued', 'pending', 'processing')
        """, [symbol])
        existing = cur.fetchone()
        if existing:
            return (DISPATCHED, existing[0])  # already queued: track that job
        import hashlib
        job_id = f"gap_{symbol.lower()}_catalyst_{hashlib.md5(f'{symbol}:catalyst:{datetime.now().date()}'.encode()).hexdigest()[:6]}"
        cur.execute("""
            INSERT INTO watchlist_agent_jobs
                (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, created_at)
            VALUES (%s, %s, 'maria_research', 'catalyst_research', 'data_gap: missing catalyst for recovery watch', 'queued', 1, 'gap_resolver', NOW())
        """, [job_id, symbol])
        conn.commit()
        return (DISPATCHED, job_id)
    except Exception:
        conn.rollback()
        return False


def _resolve_missing_thesis(symbol, conn):
    """Recover original buy thesis from proposals or trade journal."""
    cur = conn.cursor()
    # Try paper_trade_proposals
    cur.execute("""
        SELECT setup_description, catalyst, strategy_prompt_context
        FROM paper_trade_proposals
        WHERE symbol = %s AND setup_description IS NOT NULL
        ORDER BY created_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row and any(row):
        thesis = row[0] or row[2] or row[1] or ''
        if thesis:
            # Store recovered thesis in ticker_strategy_classifications notes
            cur.execute("""
                UPDATE ticker_strategy_classifications
                SET notes = COALESCE(notes, '') || E'\nRecovered thesis: ' || %s
                WHERE symbol = %s AND active = true
            """, [thesis[:500], symbol])
            conn.commit()
            return True
    return False


def _resolve_stale_news(symbol, conn):
    """Queue Maria for fresh news research."""
    return _resolve_missing_catalyst(symbol, conn)


def _resolve_missing_setup(symbol, conn):
    """Reconstruct setup from paper_trades + proposals."""
    cur = conn.cursor()
    cur.execute("""
        SELECT pt.id, pp.setup_description, pp.catalyst,
               pp.proposed_entry, pp.proposed_stop
        FROM paper_trades pt
        LEFT JOIN paper_trade_proposals pp ON pp.paper_trade_id = pt.id
        WHERE pt.symbol = %s
        ORDER BY pt.created_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row and any(row[1:]):
        return True  # Data exists, gap may have been about format not absence
    return False


GAP_RESOLVERS = {
    'missing_div_yield': _resolve_missing_div_yield,
    'missing_sector': _resolve_missing_sector,
    'missing_market_data': _resolve_missing_market_data,
    'missing_catalyst': _resolve_missing_catalyst,
    'missing_thesis': _resolve_missing_thesis,
    'stale_news': _resolve_stale_news,
    'missing_setup_details': _resolve_missing_setup,
}

#: gap_type → data_source_authority domain for the on_gap / quality-escalate chain.
#: Corrects the 2026-09-19 false claim that this cron already called gap_resolver.resolve.
CHAIN_GAP_DOMAINS = {
    "missing_catalyst": "catalyst_news",
    "stale_news": "catalyst_news",
    "explicit": "catalyst_news",
}
CHAIN_RESOLVE_LIMIT = int(os.environ.get("DATA_GAP_CHAIN_RESOLVE_LIMIT", "5"))
#: When the registry has zero catalyst-shaped opens (measured 2026-09-20: all
#: rows resolved since 2026-05), walk held symbols whose news is older than the
#: catalyst_news stale window so quality_escalate can still leave organic receipts.
CHAIN_STALE_NEWS_HOURS = float(os.environ.get("DATA_GAP_CHAIN_STALE_NEWS_HOURS", "18"))
CHAIN_STALE_HELD_LIMIT = int(os.environ.get("DATA_GAP_CHAIN_STALE_HELD_LIMIT", "3"))


def _stale_held_catalyst_symbols(conn, *, hours: float, limit: int) -> list[str]:
    """Held symbols (schwab_positions_live) with no news inside ``hours``.

    Read-only measurement. Returns UPPER symbols, oldest-news first. Fail-soft
    to [] when the position or news table is absent.
    """
    if limit <= 0 or hours <= 0:
        return []
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT p.symbol
            FROM schwab_positions_live p
            LEFT JOIN LATERAL (
              SELECT MAX(n.created_at) AS last_news
              FROM news_articles n
              WHERE UPPER(n.symbol) = UPPER(p.symbol)
            ) news ON TRUE
            WHERE COALESCE(p.qty, 0) <> 0
              AND p.symbol IS NOT NULL
              AND (
                news.last_news IS NULL
                OR news.last_news < NOW() - (%s * INTERVAL '1 hour')
              )
            ORDER BY news.last_news ASC NULLS FIRST
            LIMIT %s
            """,
            [float(hours), int(limit)],
        )
        rows = cur.fetchall() or []
    except Exception as exc:  # noqa: BLE001 — positions/news schema drift must not kill cron
        log(f"Stale-held catalyst probe skipped: {exc}")
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        sym = str(row[0] or "").upper().strip()
        # schwab_positions_live occasionally carries CUSIP-like ids; never resolve those.
        if not sym or sym in seen or sym.isdigit() or len(sym) > 10:
            continue
        if not sym[0].isalpha() or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for ch in sym):
            continue
        seen.add(sym)
        out.append(sym)
    return out


def chain_resolve_open_gaps(conn, *, dry_run: bool = False, limit: int | None = None) -> int:
    """Walk ``gap_resolver.resolve`` for catalyst-shaped open gaps.

    Fail-soft: one bad gap must not abort the cron. Uses Context dry-run unless
    ``GAP_RESOLVER_LIVE=1`` (same rail as the desk). Stamps
    ``requester=data_gap_resolver`` so quality_escalate receipts are not
    confused with controlled canaries.

    When the registry has no catalyst-shaped opens, falls back to held symbols
    with stale news (measured age vs ``CHAIN_STALE_NEWS_HOURS``) so the organic
    quality_escalate path is not starved by an empty queue.
    """
    lim = CHAIN_RESOLVE_LIMIT if limit is None else int(limit)
    if lim <= 0:
        return 0
    types = tuple(CHAIN_GAP_DOMAINS.keys())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, symbol, gap_type, gap_detail
        FROM data_gap_registry
        WHERE status = 'open' AND gap_type = ANY(%s) AND symbol IS NOT NULL
        ORDER BY
          CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
          detected_at ASC
        LIMIT %s
        """,
        [list(types), lim],
    )
    rows = cur.fetchall() or []
    synthetic = False
    if not rows:
        held = _stale_held_catalyst_symbols(
            conn, hours=CHAIN_STALE_NEWS_HOURS, limit=min(lim, CHAIN_STALE_HELD_LIMIT)
        )
        if not held:
            log("Chain resolve: 0 catalyst-shaped open gaps")
            return 0
        # In-memory gaps only — do not invent registry rows. Proof is the receipt.
        rows = [
            (f"stale-held-{sym}", sym, "stale_news", f"news older than {CHAIN_STALE_NEWS_HOURS:g}h or absent")
            for sym in held
        ]
        synthetic = True
        log(f"Chain resolve: 0 registry opens; walking {len(rows)} stale-held symbols")
    try:
        from scripts.lib.gap_resolver import Context, DataGap, resolve
    except ImportError:  # pragma: no cover — hub import path
        from lib.gap_resolver import Context, DataGap, resolve  # type: ignore

    ctx = Context()  # honors GAP_RESOLVER_LIVE / host file; default dry-run
    n = 0
    for gap_id, symbol, gap_type, detail in rows:
        domain = CHAIN_GAP_DOMAINS.get(str(gap_type) or "")
        if not domain or not symbol:
            continue
        sym = str(symbol).upper().strip()
        question = (
            str(detail).strip()
            if detail and str(detail).strip()
            else f"what is the near-term catalyst for {sym}?"
        )
        if dry_run:
            log(f"  [DRY chain] {sym}: {gap_type} -> would gap_resolver.resolve({domain})")
            n += 1
            continue
        try:
            gap = DataGap(
                domain=domain,
                subject=sym,
                question=question[:500],
                why="stale_hours" if synthetic or gap_type == "stale_news" else "no_coverage",
                requester="data_gap_resolver",
                symbols=[sym],
                gap_id=f"dgr-{gap_id}",
            )
            res = resolve(gap, ctx=ctx)
            n += 1
            log(
                f"  CHAIN {sym}: {gap_type} outcome={getattr(res, 'outcome', None)} "
                f"vector={getattr(res, 'vector', None)}"
            )
        except Exception as exc:  # noqa: BLE001 — one gap must not kill the cron
            log(f"  CHAIN ERROR {symbol}: {gap_type} — {exc}")
    log(f"Chain resolve: {n}/{len(rows)} catalyst gaps walked via gap_resolver.resolve")
    return n


def _requeue_source_job(gap_id, conn):
    """Re-queue the original job that flagged this gap with elevated priority."""
    cur = conn.cursor()
    cur.execute("""
        SELECT q.job_type, q.symbol, q.reason_codes, q.source_table, q.source_id
        FROM data_gap_registry g
        JOIN deep_overnight_llm_queue q ON q.id = g.source_job_id
        WHERE g.id = %s
    """, [gap_id])
    row = cur.fetchone()
    if not row:
        return False
    job_type, symbol, reasons, src_table, src_id = row
    import hashlib
    new_hash = hashlib.md5(f"{job_type}:{symbol}:gap_resolved:{gap_id}".encode()).hexdigest()
    cur.execute("""
        INSERT INTO deep_overnight_llm_queue
            (job_type, symbol, priority_tier, priority_score,
             reason_codes, input_hash, source_table, source_id,
             source_script, status)
        VALUES (%s, %s, 'P1', 80, %s, %s, %s, %s, 'gap_resolver', 'pending')
        ON CONFLICT DO NOTHING
    """, [job_type, symbol, ['gap_resolved', f'gap_id:{gap_id}'],
          new_hash, src_table, src_id])
    conn.commit()
    return cur.rowcount > 0


def verify_dispatched(conn, cur, dry_run=False, limit=200):
    """Settle gaps whose agent job has finished. Returns (resolved, reopened, abandoned, waiting).

    Resolved only when the job completed AND wrote a result row (result_id) --
    a durable artifact that would not exist had the work not run -- and that
    result was not demoted for numbers missing from its supplied data (rule G0). A dead job
    reopens the gap with the failure recorded; after MAX_DISPATCH_ATTEMPTS
    failures the gap is abandoned with its reason instead of re-queued hourly.
    """
    cur.execute("""
        SELECT g.id, g.symbol, g.gap_type, g.resolution_data->>'job_id',
               j.status, j.result_id, COALESCE((g.resolution_data->>'attempts')::int, 0),
               COALESCE('UNGROUNDED_NUMBERS' = ANY(r.reason_codes), false)
        FROM data_gap_registry g
        LEFT JOIN watchlist_agent_jobs j ON j.id = g.resolution_data->>'job_id'
        LEFT JOIN watchlist_agent_results r ON r.id = j.result_id
        WHERE g.status = 'enriching' AND g.resolution_data ? 'job_id'
        ORDER BY g.id
        LIMIT %s
    """, [limit])
    rows = cur.fetchall()
    resolved = reopened = abandoned = waiting = 0
    for gap_id, symbol, gap_type, job_id, job_status, result_id, attempts, ungrounded in rows:
        if job_status == 'completed' and result_id and not ungrounded:
            if not dry_run:
                mark_resolved(cur, gap_id, resolved_by='gap_resolver_v2', evidence={
                    'job_id': job_id, 'result_id': result_id,
                    'proof': 'agent job completed with a result row',
                })
            resolved += 1
            log(f"  VERIFIED {symbol}: {gap_type} (job {job_id} -> {result_id})")
        elif job_status is None or job_status in _JOB_DEAD or job_status == 'completed':
            if job_status == 'completed' and result_id:
                why = f"job {job_id} result {result_id} was demoted for unverified numbers"
            else:
                why = f"job {job_id} {job_status or 'missing'}" + (" without a result row" if job_status == 'completed' else "")
            if attempts + 1 >= MAX_DISPATCH_ATTEMPTS:
                if not dry_run:
                    abandon(cur, gap_id, reason=f"{why}; {attempts + 1} failed attempts")
                abandoned += 1
                log(f"  ABANDON {symbol}: {gap_type} ({why}; {attempts + 1} attempts)")
            else:
                if not dry_run:
                    reopen(cur, gap_id, reason=why)
                reopened += 1
                log(f"  REOPEN {symbol}: {gap_type} ({why})")
        else:
            waiting += 1
    if not dry_run:
        conn.commit()
    if rows:
        log(f"Dispatched work: {resolved} verified, {reopened} reopened, {abandoned} abandoned, {waiting} still running")
    return resolved, reopened, abandoned, waiting


def resolve_gaps(dry_run=False, pre_overnight=False, weekly_audit=False):
    """Main gap resolution loop."""
    conn = get_db_connection()
    cur = conn.cursor()
    verify_dispatched(conn, cur, dry_run=dry_run)

    # Get open gaps, high severity first
    limit = 100 if pre_overnight else 50
    cur.execute("""
        SELECT id, symbol, gap_type, gap_detail, source_job_id
        FROM data_gap_registry
        WHERE status = 'open'
        ORDER BY
          CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
          detected_at ASC
        LIMIT %s
    """, [limit])
    gaps = cur.fetchall()
    log(f"Found {len(gaps)} open gaps" + (" (pre-overnight sweep)" if pre_overnight else ""))

    if not gaps and not weekly_audit:
        # Still walk on_gap for catalyst-shaped opens (separate query) before exit.
        try:
            chain_resolve_open_gaps(conn, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            log(f"Chain resolve skipped: {exc}")
        conn.close()
        return

    resolved, failed, skipped, dispatched = 0, 0, 0, 0
    for gap_id, symbol, gap_type, detail, source_job_id in gaps:
        if not symbol:
            skipped += 1
            continue

        resolver = GAP_RESOLVERS.get(gap_type)
        if not resolver:
            # For 'explicit' type gaps, try catalyst resolver as fallback
            if gap_type == 'explicit':
                resolver = _resolve_missing_catalyst
            else:
                log(f"  SKIP {symbol}: no resolver for {gap_type}")
                skipped += 1
                continue

        if dry_run:
            log(f"  [DRY] {symbol}: {gap_type} -> would resolve")
            resolved += 1
            continue

        # Mark enriching
        mark_enriching(cur, gap_id)
        conn.commit()

        try:
            success = resolver(symbol, conn)
            if isinstance(success, tuple) and success and success[0] == DISPATCHED:
                mark_dispatched(cur, gap_id, job_id=str(success[1]), action=gap_type)
                conn.commit()
                dispatched += 1
                log(f"  DISPATCHED {symbol}: {gap_type} -> job {success[1]} (enriching until it completes)")
            elif success:
                mark_resolved(cur, gap_id, resolved_by='gap_resolver_v1')
                conn.commit()
                # Re-queue source job with enriched data
                if source_job_id:
                    _requeue_source_job(gap_id, conn)
                resolved += 1
                log(f"  OK {symbol}: {gap_type}")
            else:
                conn.rollback()
                reopen(cur, gap_id)
                conn.commit()
                failed += 1
                log(f"  FAIL {symbol}: {gap_type}")
        except Exception as e:
            conn.rollback()
            reopen(cur, gap_id)
            conn.commit()
            failed += 1
            import traceback
            log(f"  ERROR {symbol}: {gap_type} — {e}")
            traceback.print_exc()

    if weekly_audit:
        # Report persistent gaps (open > 7 days)
        cur.execute("""
            SELECT symbol, gap_type, detected_at
            FROM data_gap_registry
            WHERE status = 'open' AND detected_at < NOW() - INTERVAL '7 days'
            ORDER BY detected_at ASC
        """)
        persistent = cur.fetchall()
        if persistent:
            log(f"Persistent gaps (>7 days): {len(persistent)}")
            for sym, gt, det in persistent[:10]:
                log(f"  {sym}: {gt} (since {det})")
            # Mark as abandoned if > 30 days
            abandoned = abandon_stale(cur, older_than_days=30)
            if abandoned:
                log(f"Abandoned {abandoned} gaps older than 30 days")
            conn.commit()

    # on_gap / quality-escalate after enrichment so FakeCursor hermetic sequences
    # (and live Maria dispatch) are not starved by an earlier SELECT.
    try:
        chain_resolve_open_gaps(conn, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — enrichment path already finished
        log(f"Chain resolve skipped: {exc}")

    log(f"Done: {resolved} resolved, {dispatched} dispatched, {failed} failed, {skipped} skipped")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Resolve data gaps before overnight runs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pre-overnight", action="store_true", help="Pre-overnight sweep (higher limit)")
    parser.add_argument("--weekly-audit", action="store_true", help="Report persistent gaps")
    args = parser.parse_args()

    resolve_gaps(dry_run=args.dry_run, pre_overnight=args.pre_overnight,
                 weekly_audit=args.weekly_audit)


if __name__ == "__main__":
    main()
