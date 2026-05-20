#!/usr/bin/env python3
"""report_candidate_status_breakdown.py — Candidate status breakdown report.

Read-only. No trades, no orders.

Queries universe_strategy_fit_audit and afterhours_candidate_snapshot
to produce a detailed breakdown of candidate statuses.

Usage:
    .venv/bin/python scripts/report_candidate_status_breakdown.py --verbose
    .venv/bin/python scripts/report_candidate_status_breakdown.py --output-json out.json --output-md out.md
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from db_adapter import _get_conn  # noqa: E402


# ── Database queries ───────────────────────────────────────────────────

def _query_fit_audit(conn, verbose: bool) -> dict:
    """Query universe_strategy_fit_audit for latest run, top_match_for_symbol=TRUE."""
    cur = conn.cursor()

    # Latest audit_run_id
    cur.execute(
        "SELECT audit_run_id FROM universe_strategy_fit_audit "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        return {"error": "no audit data found", "audit_run_id": None}
    run_id = row[0]

    if verbose:
        print(f"[candidate-breakdown] Using audit_run_id={run_id}")

    base_where = (
        "WHERE audit_run_id = %s AND top_match_for_symbol = TRUE"
    )

    # ── no_fit breakdown ────────────────────────────────────────────
    cur.execute(
        f"SELECT strategy_family, COUNT(*) FROM universe_strategy_fit_audit "
        f"{base_where} AND recommendation = 'no_fit' "
        f"GROUP BY strategy_family ORDER BY COUNT(*) DESC",
        (run_id,),
    )
    no_fit_by_family = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    cur.execute(
        f"SELECT match_strength, COUNT(*) FROM universe_strategy_fit_audit "
        f"{base_where} AND recommendation = 'no_fit' "
        f"GROUP BY match_strength ORDER BY COUNT(*) DESC",
        (run_id,),
    )
    no_fit_by_strength = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    # ── blocked_by_strategy_fit breakdown ───────────────────────────
    cur.execute(
        f"SELECT family_gate_status, COUNT(*) FROM universe_strategy_fit_audit "
        f"{base_where} AND recommendation = 'blocked_by_strategy_fit' "
        f"GROUP BY family_gate_status ORDER BY COUNT(*) DESC",
        (run_id,),
    )
    blocked_by_family_gate = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    cur.execute(
        f"SELECT liquidity_gate_status, COUNT(*) FROM universe_strategy_fit_audit "
        f"{base_where} AND recommendation = 'blocked_by_strategy_fit' "
        f"GROUP BY liquidity_gate_status ORDER BY COUNT(*) DESC",
        (run_id,),
    )
    blocked_by_liquidity_gate = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    # ── watchpool_candidate breakdown ───────────────────────────────
    cur.execute(
        f"SELECT strategy_id, COUNT(*) FROM universe_strategy_fit_audit "
        f"{base_where} AND recommendation = 'watchpool_candidate' "
        f"GROUP BY strategy_id ORDER BY COUNT(*) DESC",
        (run_id,),
    )
    watchpool_by_strategy = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    # ── proposal_candidate_pending_gates breakdown ──────────────────
    cur.execute(
        f"SELECT strategy_id, COUNT(*) FROM universe_strategy_fit_audit "
        f"{base_where} AND recommendation = 'proposal_candidate_pending_gates' "
        f"GROUP BY strategy_id ORDER BY COUNT(*) DESC",
        (run_id,),
    )
    proposal_pending_by_strategy = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    # ── Overall recommendation counts ───────────────────────────────
    cur.execute(
        f"SELECT recommendation, COUNT(*) FROM universe_strategy_fit_audit "
        f"{base_where} GROUP BY recommendation ORDER BY COUNT(*) DESC",
        (run_id,),
    )
    recommendation_totals = {r[0]: r[1] for r in cur.fetchall()}

    cur.close()
    return {
        "audit_run_id": run_id,
        "recommendation_totals": recommendation_totals,
        "no_fit": {
            "by_strategy_family": no_fit_by_family,
            "by_match_strength": no_fit_by_strength,
        },
        "blocked_by_strategy_fit": {
            "by_family_gate_status": blocked_by_family_gate,
            "by_liquidity_gate_status": blocked_by_liquidity_gate,
        },
        "watchpool_candidate": {
            "by_strategy_id": watchpool_by_strategy,
        },
        "proposal_candidate_pending_gates": {
            "by_strategy_id": proposal_pending_by_strategy,
        },
    }


def _query_afterhours(conn, verbose: bool) -> dict:
    """Query afterhours_candidate_snapshot for latest snapshot."""
    cur = conn.cursor()

    # Latest snapshot_id
    cur.execute(
        "SELECT snapshot_id FROM afterhours_candidate_snapshot "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        return {"error": "no afterhours snapshot found", "snapshot_id": None}
    snap_id = row[0]

    if verbose:
        print(f"[candidate-breakdown] Using afterhours snapshot_id={snap_id}")

    # readiness_status by quote_status
    cur.execute(
        "SELECT readiness_status, quote_status, COUNT(*) "
        "FROM afterhours_candidate_snapshot "
        "WHERE snapshot_id = %s "
        "GROUP BY readiness_status, quote_status "
        "ORDER BY readiness_status, quote_status",
        (snap_id,),
    )
    by_readiness_quote: dict[str, dict[str, int]] = {}
    for r_status, q_status, cnt in cur.fetchall():
        r_status = r_status or "NULL"
        q_status = q_status or "NULL"
        by_readiness_quote.setdefault(r_status, {})[q_status] = cnt

    # readiness_status by top_strategy
    cur.execute(
        "SELECT readiness_status, top_strategy, COUNT(*) "
        "FROM afterhours_candidate_snapshot "
        "WHERE snapshot_id = %s "
        "GROUP BY readiness_status, top_strategy "
        "ORDER BY readiness_status, top_strategy",
        (snap_id,),
    )
    by_readiness_strategy: dict[str, dict[str, int]] = {}
    for r_status, strategy, cnt in cur.fetchall():
        r_status = r_status or "NULL"
        strategy = strategy or "NULL"
        by_readiness_strategy.setdefault(r_status, {})[strategy] = cnt

    # Overall readiness totals
    cur.execute(
        "SELECT readiness_status, COUNT(*) "
        "FROM afterhours_candidate_snapshot "
        "WHERE snapshot_id = %s "
        "GROUP BY readiness_status ORDER BY COUNT(*) DESC",
        (snap_id,),
    )
    readiness_totals = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    cur.close()
    return {
        "snapshot_id": snap_id,
        "readiness_totals": readiness_totals,
        "by_readiness_and_quote_status": by_readiness_quote,
        "by_readiness_and_top_strategy": by_readiness_strategy,
    }


# ── Markdown renderer ──────────────────────────────────────────────────

def _render_md(report: dict) -> str:
    lines = [
        "# Candidate Status Breakdown Report",
        f"Generated: {report['generated_at']}",
        "",
    ]

    audit = report.get("fit_audit", {})
    if audit.get("error"):
        lines.append(f"**Fit Audit Error:** {audit['error']}")
    else:
        lines += [
            f"## Universe Strategy Fit Audit (run: {audit['audit_run_id']})",
            "",
            "### Recommendation Totals",
            "",
            "| Recommendation | Count |",
            "|----------------|-------|",
        ]
        for k, v in audit.get("recommendation_totals", {}).items():
            lines.append(f"| {k} | {v} |")

        # no_fit detail
        nf = audit.get("no_fit", {})
        if nf.get("by_strategy_family"):
            lines += [
                "",
                "### no_fit — by Strategy Family",
                "",
                "| Strategy Family | Count |",
                "|-----------------|-------|",
            ]
            for k, v in nf["by_strategy_family"].items():
                lines.append(f"| {k} | {v} |")

        if nf.get("by_match_strength"):
            lines += [
                "",
                "### no_fit — by Match Strength",
                "",
                "| Match Strength | Count |",
                "|----------------|-------|",
            ]
            for k, v in nf["by_match_strength"].items():
                lines.append(f"| {k} | {v} |")

        # blocked detail
        bl = audit.get("blocked_by_strategy_fit", {})
        if bl.get("by_family_gate_status"):
            lines += [
                "",
                "### blocked_by_strategy_fit — by Family Gate Status",
                "",
                "| Family Gate | Count |",
                "|-------------|-------|",
            ]
            for k, v in bl["by_family_gate_status"].items():
                lines.append(f"| {k} | {v} |")

        if bl.get("by_liquidity_gate_status"):
            lines += [
                "",
                "### blocked_by_strategy_fit — by Liquidity Gate Status",
                "",
                "| Liquidity Gate | Count |",
                "|----------------|-------|",
            ]
            for k, v in bl["by_liquidity_gate_status"].items():
                lines.append(f"| {k} | {v} |")

        # watchpool detail
        wp = audit.get("watchpool_candidate", {})
        if wp.get("by_strategy_id"):
            lines += [
                "",
                "### watchpool_candidate — by Strategy ID",
                "",
                "| Strategy ID | Count |",
                "|-------------|-------|",
            ]
            for k, v in wp["by_strategy_id"].items():
                lines.append(f"| {k} | {v} |")

        # proposal pending detail
        pp = audit.get("proposal_candidate_pending_gates", {})
        if pp.get("by_strategy_id"):
            lines += [
                "",
                "### proposal_candidate_pending_gates — by Strategy ID",
                "",
                "| Strategy ID | Count |",
                "|-------------|-------|",
            ]
            for k, v in pp["by_strategy_id"].items():
                lines.append(f"| {k} | {v} |")

    # Afterhours section
    ah = report.get("afterhours", {})
    if ah.get("error"):
        lines += ["", f"**Afterhours Error:** {ah['error']}"]
    elif ah.get("snapshot_id"):
        lines += [
            "",
            f"## Afterhours Candidate Snapshot (snapshot: {ah['snapshot_id']})",
            "",
            "### Readiness Status Totals",
            "",
            "| Readiness Status | Count |",
            "|------------------|-------|",
        ]
        for k, v in ah.get("readiness_totals", {}).items():
            lines.append(f"| {k} | {v} |")

        rq = ah.get("by_readiness_and_quote_status", {})
        if rq:
            lines += [
                "",
                "### Readiness by Quote Status",
                "",
                "| Readiness Status | Quote Status | Count |",
                "|------------------|--------------|-------|",
            ]
            for r_status, qs in sorted(rq.items()):
                for q_status, cnt in sorted(qs.items()):
                    lines.append(f"| {r_status} | {q_status} | {cnt} |")

        rs = ah.get("by_readiness_and_top_strategy", {})
        if rs:
            lines += [
                "",
                "### Readiness by Top Strategy",
                "",
                "| Readiness Status | Top Strategy | Count |",
                "|------------------|--------------|-------|",
            ]
            for r_status, strats in sorted(rs.items()):
                for strategy, cnt in sorted(strats.items()):
                    lines.append(f"| {r_status} | {strategy} | {cnt} |")

    lines.append("")
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Candidate status breakdown report (read-only)"
    )
    p.add_argument("--output-json", type=str, help="Write JSON report to path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to path")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = _get_conn()
    if conn is None:
        print("[candidate-breakdown] ERROR: Could not connect to database", file=sys.stderr)
        sys.exit(1)

    fit_audit = _query_fit_audit(conn, args.verbose)
    afterhours = _query_afterhours(conn, args.verbose)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fit_audit": fit_audit,
        "afterhours": afterhours,
    }

    if args.verbose:
        totals = fit_audit.get("recommendation_totals", {})
        print(f"[candidate-breakdown] Fit audit recommendations: {totals}")
        print(f"[candidate-breakdown] Afterhours readiness: {afterhours.get('readiness_totals', {})}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(
            json.dumps(report, indent=2, default=str) + "\n"
        )
        if args.verbose:
            print(f"  JSON written to {args.output_json}")

    if args.output_md:
        md = _render_md(report)
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md)
        if args.verbose:
            print(f"  Markdown written to {args.output_md}")

    if not args.output_json and not args.output_md:
        print(_render_md(report))


if __name__ == "__main__":
    main()
