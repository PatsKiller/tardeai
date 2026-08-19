#!/usr/bin/env python3
"""finviz_screener_runner.py — Execute Finviz screeners and discover new candidates.

Reads screener URLs from DB, fetches results, classifies new tickers,
adds promising ones to watchlist.

Usage:
    python3 scripts/finviz_screener_runner.py --run [--json]
    python3 scripts/finviz_screener_runner.py --screener dividend_growth [--json]
    python3 scripts/finviz_screener_runner.py --dry-run [--json]
"""
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# GLOBAL Finviz rate limiter (cross-process). The screener runner previously bypassed this and
# hammered Finviz unthrottled — 29 screeners × (CSV + HTML fallback) tripped HTTP 429 storms that
# collapsed the daily universe to ~40-70 symbols → 0 GO/A+ scans → 0 signals. Fail-open if missing.
try:
    from finviz_throttle import acquire as _fv_acquire, cooldown as _fv_cooldown
except Exception:
    def _fv_acquire(*a, **k): return 0.0
    def _fv_cooldown(*a, **k): pass


class _RateLimited(Exception):
    """Raised on HTTP 429 after a global cooldown was recorded — caller must NOT retry/fall back."""


def _http_get(url: str, headers: dict, timeout: int = 15) -> str:
    """GET through the global Finviz throttle. Spaces every request across all processes; on HTTP 429
    records a global cooldown (so EVERY Finviz consumer backs off) and raises _RateLimited."""
    _fv_acquire()  # blocks until a global slot is free, honoring any active cooldown
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry_after = None
            try:
                _ra = e.headers.get("Retry-After") if e.headers else None
                retry_after = float(_ra) if _ra else None
            except (TypeError, ValueError):
                retry_after = None
            _fv_cooldown(retry_after)  # default 60s — applies to all Finviz consumers
            raise _RateLimited() from e
        raise


def _get_conn():
    """Use the shared adapter so idle/closed connections self-heal."""
    try:
        from db_adapter import _get_conn as _shared
        return _shared()
    except Exception:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
        return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _refresh_conn(conn):
    """After a long HTTP fetch the session may have been closed by idle timeout."""
    try:
        from db_adapter import ensure_conn
        return ensure_conn()
    except Exception:
        try:
            if conn is not None and not getattr(conn, "closed", 1):
                return conn
        except Exception:
            pass
        return _get_conn()


def _get_finviz_cookie():
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("FINVIZ_COOKIE="): return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def _fetch_screener_tickers(url: str, cookie: str) -> list:
    """Fetch tickers from a Finviz screener URL. Returns list of ticker strings."""
    tickers = []
    rate_limited = False
    try:
        # Convert to export URL for CSV download
        export_url = url.replace("/screener.ashx?", "/export?").replace("elite.finviz.com", "elite.finviz.com")
        if "elite.finviz.com" not in export_url:
            export_url = export_url.replace("finviz.com", "elite.finviz.com")

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
            "Referer": "https://elite.finviz.com/screener.ashx",
        }
        content = _http_get(export_url, headers)

        # CSV format: first column is "No.", second is "Ticker"
        lines = content.strip().split("\n")
        if len(lines) > 1:
            for line in lines[1:]:  # Skip header
                parts = line.split(",")
                if len(parts) >= 2:
                    ticker = parts[1].strip().strip('"')
                    if re.match(r'^[A-Z]{1,6}$', ticker):
                        tickers.append(ticker)
    except _RateLimited:
        rate_limited = True
        print("  [screener] Fetch error: HTTP 429 — global cooldown set, skipping HTML fallback")
    except Exception as e:
        print(f"  [screener] Fetch error: {e}")

    # Fallback: scrape HTML only if the CSV genuinely failed (NOT on 429 — a fallback request would
    # just hammer the rate limit again and prolong the cooldown).
    if not tickers and not rate_limited:
        try:
            html = _http_get(url, {
                "User-Agent": "Mozilla/5.0",
                "Cookie": cookie if cookie else "",
            })
            # Extract tickers from screener HTML
            ticker_pattern = re.findall(r'quote\.ashx\?t=([A-Z]{1,6})', html)
            tickers = list(dict.fromkeys(ticker_pattern))  # dedup preserving order
        except _RateLimited:
            print("  [screener] HTML fallback skipped — HTTP 429 (global cooldown set)")
        except Exception as e:
            print(f"  [screener] HTML fallback error: {e}")

    return tickers  # Full CSV result — capping handled by caller with screener_id context


def _sp_name(prefix: str, screener_id: str) -> str:
    """Postgres SAVEPOINT identifier — alphanumeric + underscore only."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", str(screener_id or "x"))[:48]
    return f"{prefix}_{safe}"


def _ensure_txn_usable(conn) -> bool:
    """If the connection is in aborted state, ROLLBACK so later screeners can proceed.

    Without this, a lock-timeout on membership leaves InFailedSqlTransaction and every
    subsequent INSERT fails with 'current transaction is aborted'.
    """
    try:
        from psycopg2.extensions import TRANSACTION_STATUS_INERROR
        if conn.get_transaction_status() == TRANSACTION_STATUS_INERROR:
            conn.rollback()
            return True
    except Exception:
        try:
            conn.rollback()
            return True
        except Exception:
            pass
    return False


def _update_screener_membership(cur, screener_id, present, run_id):
    """Keep screener_symbol_membership fresh — the runner previously only wrote new classifications, so
    membership went stale. Pattern per run: reset present_this_run → mark present symbols (seen++/miss=0)
    → increment the missing-streak for symbols that fell out (dropped→stale@3→expired@7)."""
    from psycopg2.extras import execute_values
    present = list({str(s).upper() for s in present if s})
    # 1) reset this screener's present flag
    cur.execute("UPDATE screener_symbol_membership SET present_this_run=FALSE WHERE screener_id=%s",
                (screener_id,))
    # 2) upsert present symbols
    if present:
        execute_values(cur, """
            INSERT INTO screener_symbol_membership
              (symbol, screener_id, first_seen_in_screener_at, last_seen_in_screener_at,
               last_seen_run_id, present_this_run, consecutive_seen_count, consecutive_missing_count,
               membership_status, updated_at)
            VALUES %s
            ON CONFLICT (symbol, screener_id) DO UPDATE SET
              last_seen_in_screener_at = now(),
              last_seen_run_id         = EXCLUDED.last_seen_run_id,
              present_this_run         = TRUE,
              consecutive_seen_count   = screener_symbol_membership.consecutive_seen_count + 1,
              consecutive_missing_count = 0,
              membership_status        = 'active',
              updated_at = now()
        """, [(s, screener_id, run_id) for s in present],
             template="(%s,%s,now(),now(),%s,TRUE,1,0,'active',now())")
    # 3) age the fall-offs (still FALSE after step 2 = absent this run)
    cur.execute("""
        UPDATE screener_symbol_membership
           SET consecutive_seen_count = 0,
               consecutive_missing_count = consecutive_missing_count + 1,
               membership_status = CASE WHEN consecutive_missing_count + 1 >= 7 THEN 'expired'
                                        WHEN consecutive_missing_count + 1 >= 3 THEN 'stale'
                                        ELSE 'dropped' END,
               updated_at = now()
         WHERE screener_id = %s AND present_this_run = FALSE
    """, (screener_id,))
    return len(present)


def run_screener(screener_id: str = None, dry_run: bool = False) -> dict:
    """Run one or all screeners. Returns discovery summary."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cookie = _get_finviz_cookie()
    _run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    if screener_id:
        cur.execute("SELECT * FROM finviz_screeners WHERE screener_id=%s AND active=TRUE", (screener_id,))
    else:
        cur.execute("SELECT * FROM finviz_screeners WHERE active=TRUE ORDER BY screener_id")
    screeners = cur.fetchall()

    # Get already classified symbols
    cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    known = set(r["symbol"] for r in cur.fetchall())

    results = []
    total_new = 0
    membership_failures = 0
    db_write_failures = 0

    for s in screeners:
        sid = s["screener_id"]
        strategy = s["strategy_type"]
        url = s["finviz_url"]

        print(f"  [{sid}] Fetching {s['display_name']}...")
        tickers = _fetch_screener_tickers(url, cookie)
        # HTTP can outlive PG idle_session_timeout — never reuse a dead handle.
        conn = _refresh_conn(conn)
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        except Exception:
            conn = _get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # SCREENER-ARCH-2B: Per-screener cap overrides for broad ETF/income screeners
        SCREENER_CAP_OVERRIDES = {
            "bond_etf_income": 10000,
            "covered_call_etf": 10000,
            "high_yield_income": 10000,
            "ira_income_friendly": 10000,
        }
        DEFAULT_MAX_ROWS = 5000
        effective_cap = SCREENER_CAP_OVERRIDES.get(sid, DEFAULT_MAX_ROWS)
        cap_status = "EXHAUSTED"
        raw_count = len(tickers)
        if raw_count > effective_cap:
            cap_status = "ROW_LIMIT_REACHED"
            print(f"  [screener] WARNING: {raw_count} rows fetched, capped at {effective_cap} ({sid})")
            tickers = tickers[:effective_cap]

        new_tickers = [t for t in tickers if t not in known]

        screener_result = {
            "screener_id": sid,
            "strategy_type": strategy,
            "total_found": len(tickers),
            "raw_fetched": raw_count,
            "effective_cap": effective_cap,
            "cap_status": cap_status,
            "new_tickers": len(new_tickers),
            "sample": new_tickers[:10],
        }
        results.append(screener_result)

        # Live DB writes: isolate each screener so lock timeout / partial failure cannot abort
        # the whole multi-screener transaction (root cause of pipeline_critical 2026-07-16).
        if not dry_run and (tickers or new_tickers):
            if _ensure_txn_usable(conn):
                print(f"  [screener] recovered aborted transaction before {sid}")
            sp = _sp_name("sp_scr", sid)
            try:
                cur.execute(f"SAVEPOINT {sp}")

                # Membership: nested savepoint — lock timeout must not poison classifications
                if tickers:
                    sp_mem = _sp_name("sp_mem", sid)
                    try:
                        cur.execute(f"SAVEPOINT {sp_mem}")
                        n_mem = _update_screener_membership(cur, sid, tickers, _run_id)
                        cur.execute(f"RELEASE SAVEPOINT {sp_mem}")
                        screener_result["membership_updated"] = n_mem
                    except Exception as _me:
                        membership_failures += 1
                        try:
                            cur.execute(f"ROLLBACK TO SAVEPOINT {sp_mem}")
                        except Exception:
                            # nested savepoint gone — roll outer and re-open outer for remaining writes
                            try:
                                cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                                cur.execute(f"SAVEPOINT {sp}")
                            except Exception:
                                _ensure_txn_usable(conn)
                                cur.execute(f"SAVEPOINT {sp}")
                        print(f"  [screener] membership update failed for {sid}: {str(_me)[:120]}")
                        screener_result["membership_error"] = str(_me)[:160]

                if new_tickers:
                    for ticker in new_tickers[:200]:  # SCREENER-ARCH-2: raised from 10 to 200 per screener
                        cur.execute("""
                            INSERT INTO ticker_strategy_classifications
                                (symbol, strategy_type, asset_type, classification_source, confidence, rationale)
                            VALUES (%s, %s, 'stock', 'screener', 0.7, %s)
                            ON CONFLICT (symbol) DO NOTHING
                        """, (ticker, strategy, f"Discovered by screener {sid}"))

                        cur.execute("""
                            INSERT INTO watchlist_items (symbol, source, status, origin_system, updated_at)
                            VALUES (%s, 'ai_discovered', 'active', 'finviz_screener', now())
                            ON CONFLICT DO NOTHING
                        """, (ticker,))

                        total_new += 1
                        known.add(ticker)

                    cur.execute("""
                        INSERT INTO portfolio_intelligence_events (event_type, severity, source, payload)
                        VALUES ('screener_discovery', 'info', 'finviz_screener_runner.py', %s)
                    """, (json.dumps({"screener": sid, "new": len(new_tickers), "sample": new_tickers[:5]}, default=str),))

                # Always stamp last_run when we fetched (even 0 new) so freshness isn't stuck
                if tickers or new_tickers:
                    cur.execute(
                        "UPDATE finviz_screeners SET last_run=now(), results_count=%s WHERE screener_id=%s",
                        (len(tickers), sid),
                    )

                cur.execute(f"RELEASE SAVEPOINT {sp}")
                screener_result["db_ok"] = True
            except Exception as _dbe:
                db_write_failures += 1
                try:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                except Exception:
                    if _ensure_txn_usable(conn):
                        print(f"  [screener] full rollback after DB failure on {sid}")
                print(f"  [screener] DB write failed for {sid}: {str(_dbe)[:120]}")
                screener_result["db_error"] = str(_dbe)[:160]
                screener_result["db_ok"] = False

        time.sleep(1)  # Rate limit between screeners

    if not dry_run:
        try:
            if _ensure_txn_usable(conn):
                print("  [screener] recovered aborted txn before final commit")
            conn.commit()
        except Exception as _ce:
            print(f"  [screener] final commit failed: {_ce}")
            try:
                conn.rollback()
            except Exception:
                pass
            raise

    # Shared adapter connection is thread-local — do not close it out from under other callers.
    try:
        if conn is not None and not getattr(conn, "autocommit", True):
            pass
    except Exception:
        pass

    summary = {
        "mode": "dry_run" if dry_run else "live",
        "screeners_run": len(results),
        "total_new_tickers": total_new,
        "membership_failures": membership_failures,
        "db_write_failures": db_write_failures,
        "results": results,
    }
    print(
        f"[screener] {'DRY RUN — ' if dry_run else ''}Ran {len(results)} screeners, "
        f"discovered {total_new} new tickers"
        + (f", membership_failures={membership_failures}" if membership_failures else "")
        + (f", db_write_failures={db_write_failures}" if db_write_failures else "")
    )
    return summary


if __name__ == "__main__":
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('finviz_screener_runner')
    except Exception:
        pass

    try:
        dry = "--dry-run" in sys.argv
        sid = None
        if "--screener" in sys.argv:
            sid = sys.argv[sys.argv.index("--screener") + 1]

        result = run_screener(screener_id=sid, dry_run=dry)

        if "--json" in sys.argv:
            print(json.dumps(result, indent=2, default=str))
        else:
            for r in result.get("results", []):
                if r["new_tickers"] > 0:
                    print(f"  {r['screener_id']:>25}: {r['total_found']} found, {r['new_tickers']} NEW → {r['sample'][:5]}")

        try:
            if _run_id:
                total_new = sum(r.get('new_tickers', 0) for r in result.get('results', []))
                run_complete(_run_id, rows_processed=total_new)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        raise
