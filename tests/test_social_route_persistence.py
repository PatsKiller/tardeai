#!/usr/bin/env python3
"""P0-3: durable route/actionability persistence on scalp_scan_results + trade_ai_scans."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from migrate_social_route_fields import COLUMNS  # noqa: E402
from social_route_policy import route_social_candidate  # noqa: E402

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def warn(name, msg):
    WARN.append(name)
    print(f"  [WARN] {name} — {msg}")


def main():
    # 1. Migration defines the required durable columns on both tables.
    ssr = {c for c, _ in COLUMNS["scalp_scan_results"]}
    check("scalp_scan_results route columns defined",
          {"route", "route_actionability", "route_strategy_id", "route_reason_codes",
           "catalyst_verified", "catalyst_source"} <= ssr)
    tas = {c for c, _ in COLUMNS["trade_ai_scans"]}
    check("trade_ai_scans route columns defined",
          {"route", "route_actionability", "route_strategy_id", "route_reason_codes"} <= tas)

    # 2. DB-aware: columns exist + stamp persists the deterministic route output (rolled back).
    try:
        from db_adapter import get_connection
        from social_scalp_scanner import stamp_route_fields, _has_col
        conn = get_connection()
        cur = conn.cursor()

        check("scalp_scan_results.route column present", _has_col(conn, "scalp_scan_results", "route"))
        check("scalp_scan_results.catalyst_verified present", _has_col(conn, "scalp_scan_results", "catalyst_verified"))

        sym = "ZZROUTE"
        route = route_social_candidate(
            {"symbol": sym, "mention_count": 30, "sources": ["reddit"], "strategy_tags": []},
            {"price": 5, "rvol": 7, "float_m": 8, "gap_pct": 6},
            {"catalyst_verified": True, "catalyst_source": "news"}, trace_id="t")
        try:
            cur.execute("INSERT INTO scalp_scan_results (symbol, mention_count, score, grade, decision, "
                        "sources, alerted, scanned_at) VALUES (%s,1,50,'A','GO','{}',true,NOW())", (sym,))
            stamp_route_fields(conn, "scalp_scan_results", sym, route,
                               {"catalyst_verified": True, "catalyst_source": "news"})
            cur.execute("SELECT route, route_actionability, route_strategy_id, catalyst_verified "
                        "FROM scalp_scan_results WHERE symbol=%s ORDER BY scanned_at DESC LIMIT 1", (sym,))
            r = cur.fetchone()
            check("persisted route == deterministic route output", r[0] == route["route"] == "momentum_scalp")
            check("persisted actionability == route output", r[1] == route["actionability"] == "GO")
            check("persisted route_strategy_id", r[2] == "momentum_scalp")
            check("persisted catalyst_verified", r[3] is True)

            # social-only persists as watch_only / not GO.
            so = route_social_candidate(
                {"symbol": sym, "mention_count": 99, "sources": ["reddit"], "strategy_tags": []},
                {"price": 5, "rvol": 7, "float_m": 8, "gap_pct": 6}, {}, trace_id="t")
            stamp_route_fields(conn, "scalp_scan_results", sym, so, {})
            cur.execute("SELECT route, route_actionability FROM scalp_scan_results WHERE symbol=%s "
                        "ORDER BY scanned_at DESC LIMIT 1", (sym,))
            r2 = cur.fetchone()
            check("social-only persists watch_only/not-GO", r2[0] == "watch_only" and r2[1] != "GO")
        finally:
            conn.rollback()

        # 3. Missing column does not crash the stamp.
        stamp_route_fields(conn, "no_such_table_xyz", sym, route, {})
        check("stamp on missing table does not crash", True)
    except Exception as e:
        warn("DB persistence", f"no DB ({str(e)[:70]})")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
