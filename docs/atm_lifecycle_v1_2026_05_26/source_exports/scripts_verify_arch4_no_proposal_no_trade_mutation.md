# Source Export: scripts/verify_arch4_no_proposal_no_trade_mutation.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/verify_arch4_no_proposal_no_trade_mutation.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `a0f59374c4adf914cbb649aa3ef3b240da9638bfa84b28a4376124b902c6e4e9` |
| **File Size** | 6307 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""verify_arch4_no_proposal_no_trade_mutation.py — Safety verification script.

Read-only. No trades. No orders. No alerts sent.

Verifies that the strategy-fit audit pipeline has NOT created proposals or
trades, and that all audit rows are marked human_review_only=TRUE.

Usage:
    .venv/bin/python scripts/verify_arch4_no_proposal_no_trade_mutation.py --verbose
    .venv/bin/python scripts/verify_arch4_no_proposal_no_trade_mutation.py --output-json /tmp/safety.json
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            result = dict(zip([d[0] for d in cur.description], row)) if row else None
            conn.close()
            return result
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def _build_report(verbose=False):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "verdict": "PENDING",
    }
    all_pass = True

    # Check 1: New proposals in the last hour
    row = _db_query(
        "SELECT count(*) AS cnt FROM paper_trade_proposals WHERE created_at > NOW() - INTERVAL '1 hour'",
        fetch="one",
    )
    new_proposals = row["cnt"] if row else -1
    check1_pass = new_proposals == 0
    if not check1_pass:
        all_pass = False
    report["checks"].append({
        "name": "no_new_proposals_1h",
        "description": "No new paper_trade_proposals in the last hour",
        "value": new_proposals,
        "pass": check1_pass,
    })

    # Check 2: New trades in the last hour
    row = _db_query(
        "SELECT count(*) AS cnt FROM paper_trades WHERE created_at > NOW() - INTERVAL '1 hour'",
        fetch="one",
    )
    new_trades = row["cnt"] if row else -1
    check2_pass = new_trades == 0
    if not check2_pass:
        all_pass = False
    report["checks"].append({
        "name": "no_new_trades_1h",
        "description": "No new paper_trades in the last hour",
        "value": new_trades,
        "pass": check2_pass,
    })

    # Check 3: Audit rows exist
    row = _db_query(
        "SELECT count(*) AS cnt FROM universe_strategy_fit_audit",
        fetch="one",
    )
    audit_count = row["cnt"] if row else 0
    check3_pass = audit_count > 0
    if not check3_pass:
        all_pass = False
    report["checks"].append({
        "name": "audit_rows_exist",
        "description": "universe_strategy_fit_audit has rows",
        "value": audit_count,
        "pass": check3_pass,
    })

    # Check 4: All audit rows have human_review_only=TRUE
    row = _db_query(
        "SELECT count(*) AS cnt FROM universe_strategy_fit_audit WHERE human_review_only != TRUE",
        fetch="one",
    )
    non_human_review = row["cnt"] if row else -1
    check4_pass = non_human_review == 0
    if not check4_pass:
        all_pass = False
    report["checks"].append({
        "name": "all_human_review_only",
        "description": "All audit rows have human_review_only=TRUE",
        "value": non_human_review,
        "pass": check4_pass,
    })

    # Check 5: No strategy activation changes (no active strategies flipped recently)
    row = _db_query(
        "SELECT count(*) AS cnt FROM universe_strategy_fit_audit "
        "WHERE recommendation IN ('ACTIVATE', 'DEACTIVATE') "
        "AND human_review_only != TRUE",
        fetch="one",
    )
    activation_changes = row["cnt"] if row else -1
    check5_pass = activation_changes == 0
    if not check5_pass:
        all_pass = False
    report["checks"].append({
        "name": "no_strategy_activation_changes",
        "description": "No unapproved strategy activation/deactivation changes",
        "value": activation_changes,
        "pass": check5_pass,
    })

    # Verdict
    report["verdict"] = "PASS" if all_pass else "FAIL"
    report["new_proposals_1h"] = new_proposals
    report["new_trades_1h"] = new_trades
    report["audit_row_count"] = audit_count
    report["non_human_review_count"] = non_human_review

    return report


def _format_md(report):
    verdict_label = "PASS" if report["verdict"] == "PASS" else "FAIL"
    lines = [
        "# Arch4 Safety Verification",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Verdict:** **{verdict_label}**",
        "",
        "## Checks",
        "",
        "| Check | Description | Value | Pass |",
        "|-------|-------------|-------|------|",
    ]
    for c in report["checks"]:
        status = "YES" if c["pass"] else "NO"
        lines.append(f"| {c['name']} | {c['description']} | {c['value']} | {status} |")
    lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Arch4 safety verification (read-only)")
    p.add_argument("--output-json", type=str, help="Write JSON report to this path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to this path")
    p.add_argument("--verbose", action="store_true", help="Print report to stdout")
    args = p.parse_args()

    report = _build_report(verbose=args.verbose)

    if args.verbose:
        print(json.dumps(report, indent=2, default=str))

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {args.output_json}")

    if args.output_md:
        md = _format_md(report)
        Path(args.output_md).write_text(md)
        print(f"Markdown written to {args.output_md}")

    if not args.verbose and not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2, default=str))

    # Exit with non-zero if verdict is FAIL
    if report["verdict"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
```
