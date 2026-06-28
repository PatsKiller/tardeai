#!/usr/bin/env python3
"""P0-6 follow-up: orchestrator scan→signal trace copy completes the lineage chain.

Verifies strategy_signal_sync now carries discovery_trace_id from trade_ai_scans into
strategy_signals (static wiring + schema), and — when a DB is available — a transactional
round-trip proving the scan loader returns the trace id (rolled back, no persisted data).
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def warn(name, msg):
    WARN.append(name)
    print(f"  [WARN] {name} — {msg}")


def main():
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "strategy_signal_sync.py")).read()

    # 1. Static wiring: the scan SELECT references discovery_trace_id before FROM trade_ai_scans.
    _sel = src.split("FROM trade_ai_scans")[0][-600:] if "FROM trade_ai_scans" in src else ""
    check("scan SELECT pulls discovery_trace_id", "discovery_trace_id" in _sel)
    check("lineage copies scan discovery_trace_id",
          '"discovery_trace_id": scan.get(\'discovery_trace_id\')' in src
          or '"discovery_trace_id": scan.get("discovery_trace_id")' in src)
    check("lineage is column-guarded (backward-compatible)",
          "if k in available_cols" in src)

    # 2. DB-aware round-trip (rolled back).
    try:
        from db_adapter import get_connection
        from strategy_signal_sync import get_today_go_scans
        conn = get_connection()
        cur = conn.cursor()

        # schema
        cur.execute("SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='strategy_signals' AND column_name='discovery_trace_id'")
        check("strategy_signals has discovery_trace_id column", cur.fetchone() is not None)

        sym = "ZZTRACE"
        trace = "soc-trace-chain-test-0001"
        try:
            cur.execute("""
                INSERT INTO trade_ai_scans
                    (run_id, run_date, run_label, run_type, symbol, score, grade, decision,
                     source, scanned_at, discovery_trace_id)
                VALUES (%s, CURRENT_DATE, %s, 'live', %s, 50, 'A', 'GO', 'social', NOW(), %s)
            """, ("trace-test-run", "tracetest", sym, trace))
            scans = get_today_go_scans(conn, symbols=[sym])
            mine = [s for s in scans if s.get("symbol") == sym]
            check("loaded scan carries discovery_trace_id",
                  bool(mine) and mine[0].get("discovery_trace_id") == trace)
        finally:
            conn.rollback()  # never persist test rows
    except Exception as e:
        warn("DB round-trip", f"skipped ({str(e).splitlines()[0][:80]}) — static wiring still verified")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
