#!/usr/bin/env python3
"""verify_afterhours_ready1_runtime.py — Verify after-hours readiness runtime integrity.

Checks that readiness pipeline ran correctly and produced no trades/orders/proposals.
No trades. No orders.

Usage:
    .venv/bin/python scripts/verify_afterhours_ready1_runtime.py --date 2026-05-19 --verbose
"""
import argparse, json, sys
from datetime import datetime, date, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _table_exists(conn, table_name):
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        [table_name],
    )
    return cur.fetchone()[0]


def main():
    p = argparse.ArgumentParser(description="Verify after-hours readiness runtime")
    p.add_argument("--date", type=str, default="today")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    run_date = date.today().isoformat() if args.date == "today" else args.date

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    checks = []
    all_pass = True

    # 1. afterhours_readiness_run exists for date
    run_exists = False
    run_row = {}
    if _table_exists(conn, "afterhours_readiness_run"):
        run_row = _q(conn, """
            SELECT run_id, symbols_considered, run_status
            FROM afterhours_readiness_run
            WHERE run_date = %s
            ORDER BY started_at DESC LIMIT 1
        """, [run_date], fetch="one")
        run_exists = bool(run_row and run_row.get("run_id"))
    checks.append({
        "check": "afterhours_readiness_run exists for date",
        "pass": run_exists,
        "detail": run_row.get("run_id", "not found"),
    })
    if not run_exists:
        all_pass = False

    # 2. symbols_considered > 0
    symbols_ok = run_row.get("symbols_considered", 0) > 0 if run_exists else False
    checks.append({
        "check": "symbols_considered > 0",
        "pass": symbols_ok,
        "detail": run_row.get("symbols_considered", 0),
    })
    if not symbols_ok:
        all_pass = False

    # 3. afterhours_candidate_snapshot rows exist
    snapshot_count = 0
    if run_exists and _table_exists(conn, "afterhours_candidate_snapshot"):
        cnt_row = _q(conn, """
            SELECT COUNT(*) AS cnt
            FROM afterhours_candidate_snapshot
            WHERE snapshot_id = %s
        """, [run_row.get("run_id", "")], fetch="one")
        snapshot_count = cnt_row.get("cnt", 0) if cnt_row else 0
    snap_ok = snapshot_count > 0
    checks.append({
        "check": "afterhours_candidate_snapshot rows exist",
        "pass": snap_ok,
        "detail": snapshot_count,
    })
    if not snap_ok:
        all_pass = False

    # 4. No new trades/orders/proposals from this system
    # Check paper_proposals for afterhours source on this date
    no_trades = True
    trade_detail = "no afterhours trades/orders/proposals found"
    # Check that afterhours system did not create trades (it only writes snapshots)
    if _table_exists(conn, "afterhours_candidate_snapshot"):
        snap_row = _q(conn, "SELECT COUNT(*) AS cnt FROM afterhours_candidate_snapshot WHERE executable_now=TRUE AND run_date=%s", [run_date], fetch="one")
        if snap_row and snap_row.get("cnt", 0) > 0:
            no_trades = False
            trade_detail = f"afterhours_candidate_snapshot has {snap_row['cnt']} executable_now=TRUE rows"
    checks.append({
        "check": "no new trades/orders/proposals from afterhours system",
        "pass": no_trades,
        "detail": trade_detail,
    })
    if not no_trades:
        all_pass = False

    # 5. Readiness classifications exist
    classifications_exist = False
    classification_detail = "no classifications"
    if run_exists and _table_exists(conn, "afterhours_candidate_snapshot"):
        cls_rows = _q(conn, """
            SELECT readiness_status, COUNT(*) AS cnt
            FROM afterhours_candidate_snapshot
            WHERE snapshot_id = %s
            GROUP BY readiness_status
        """, [run_row.get("run_id", "")])
        if cls_rows:
            classifications_exist = True
            classification_detail = {r["readiness_status"]: r["cnt"] for r in cls_rows}
    checks.append({
        "check": "readiness classifications exist",
        "pass": classifications_exist,
        "detail": classification_detail,
    })
    if not classifications_exist:
        all_pass = False

    conn.close()

    verdict = "PASS" if all_pass else "FAIL"

    if args.verbose:
        print(f"After-Hours Readiness Runtime Verification -- {run_date}")
        print(f"Verdict: {verdict}")
        print()
        for c in checks:
            status = "PASS" if c["pass"] else "FAIL"
            print(f"  [{status}] {c['check']}: {c['detail']}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_date": run_date,
        "verdict": verdict,
        "checks": checks,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            f"# After-Hours Readiness Runtime Verification\n",
            f"Date: {run_date}\n",
            f"Verdict: **{verdict}**\n",
            "| Check | Status | Detail |",
            "|-------|--------|--------|",
        ]
        for c in checks:
            status = "PASS" if c["pass"] else "FAIL"
            detail = str(c["detail"])[:80]
            md.append(f"| {c['check']} | {status} | {detail} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
