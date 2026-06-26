#!/usr/bin/env python3
"""
run_automated_trade_proposal_revalidation.py
Automated Trade Proposal Revalidation

Queries pending/approved paper_trade_proposals and checks each for:
  - Quote freshness (trade_ai_scans scanned_at)
  - Proposal age (created_at)
  - Price drift from proposed_entry
  - Stop breach

Classifies revalidation_status without approving, trading, or ordering.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

from db_adapter import _get_conn

NOW = datetime.now()


def _q(sql: str, params=None) -> list[dict]:
    """Execute a query and return list of dicts."""
    conn = _get_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            return [dict(r) for r in rows]
    except Exception as e:
        conn.rollback()
        print(f"  [revalidation] SQL error: {e}")
        return []


def revalidate_proposals(limit: int | None = None, verbose: bool = False, *, refresh_quotes: bool = False) -> dict:
    """Revalidate all pending/approved proposals."""
    limit_clause = f"LIMIT {limit}" if limit else ""
    proposals = _q(
        f"SELECT id, symbol, strategy_id, status, proposed_entry, proposed_stop, "
        f"proposed_target1, proposed_shares, proposed_dollar_risk, "
        f"created_at, expires_at, current_price, price_drift_pct "
        f"FROM paper_trade_proposals "
        f"WHERE status IN ('PENDING', 'pending', 'APPROVED', 'approved') "
        f"ORDER BY created_at DESC {limit_clause}"
    )

    results = []
    for p in proposals:
        sym = p["symbol"]
        created = p.get("created_at")
        proposed_entry = float(p["proposed_entry"]) if p.get("proposed_entry") else None
        proposed_stop = float(p["proposed_stop"]) if p.get("proposed_stop") else None

        # Proposal age
        age_hours = None
        if created:
            age_hours = round((NOW - created.replace(tzinfo=None)).total_seconds() / 3600, 1)

        # Latest scan for quote freshness
        scan = _q(
            "SELECT scanned_at, price, rvol, change_pct, gap_pct "
            "FROM trade_ai_scans WHERE symbol = %s ORDER BY scanned_at DESC LIMIT 1",
            (sym,)
        )
        quote_age_hours = None
        latest_price = None
        quote_fresh = False
        if scan:
            scanned_at = scan[0].get("scanned_at")
            latest_price = float(scan[0]["price"]) if scan[0].get("price") else None
            if scanned_at:
                quote_age_hours = round(
                    (NOW - scanned_at.replace(tzinfo=None)).total_seconds() / 3600, 1
                )
                quote_fresh = quote_age_hours < 1

        # Price drift from proposed_entry
        price_drift_pct = None
        if proposed_entry and latest_price and proposed_entry > 0:
            price_drift_pct = round((latest_price - proposed_entry) / proposed_entry * 100, 2)

        # Stop breach check
        stop_breached = False
        if proposed_stop and latest_price:
            stop_breached = latest_price <= proposed_stop

        # ── Classification logic ──
        flags = []
        if stop_breached:
            flags.append("stop_breached")
        if price_drift_pct is not None and abs(price_drift_pct) > 10:
            flags.append("price_drift_gt_10pct")
        if age_hours is not None and age_hours > 48:
            flags.append("expired_gt_48h")
        elif age_hours is not None and age_hours > 24:
            flags.append("stale_gt_24h")
        if not quote_fresh:
            flags.append("quote_stale")

        # Determine revalidation_status
        if stop_breached:
            reval_status = "rebuild_recommended"
        elif age_hours is not None and age_hours > 48:
            reval_status = "expired"
        elif price_drift_pct is not None and abs(price_drift_pct) > 10:
            reval_status = "human_review_required"
        elif age_hours is not None and age_hours > 24:
            reval_status = "stale"
        elif not quote_fresh:
            reval_status = "needs_quote_refresh"
        else:
            reval_status = "still_valid"

        detail = {
            "proposal_id": p["id"],
            "symbol": sym,
            "strategy": p.get("strategy_id"),
            "proposal_status": p.get("status"),
            "proposed_entry": proposed_entry,
            "proposed_stop": proposed_stop,
            "latest_price": latest_price,
            "age_hours": age_hours,
            "quote_age_hours": quote_age_hours,
            "quote_fresh": quote_fresh,
            "price_drift_pct": price_drift_pct,
            "stop_breached": stop_breached,
            "revalidation_status": reval_status,
            "flags": flags,
        }

        if verbose and scan:
            detail["latest_scan"] = {
                "rvol": scan[0].get("rvol"),
                "change_pct": scan[0].get("change_pct"),
                "gap_pct": scan[0].get("gap_pct"),
            }

        results.append(detail)

    # Summary counts
    by_status: dict[str, int] = {}
    for r in results:
        st = r["revalidation_status"]
        by_status[st] = by_status.get(st, 0) + 1

    quote_refresh = None
    price_dominated = (
        by_status.get("needs_quote_refresh", 0) + by_status.get("human_review_required", 0)
    ) > max(1, len(results) // 4)
    if refresh_quotes and (price_dominated or by_status.get("needs_quote_refresh", 0) > 0):
        try:
            from proposal_execution_readiness import refresh_stale_proposal_quotes
            quote_refresh = refresh_stale_proposal_quotes(limit=limit or 25)
            if verbose:
                print(f"[revalidation] quote refresh: {quote_refresh}")
        except Exception as e:
            quote_refresh = {"error": str(e)[:120]}

    return {
        "report": "Automated Trade Proposal Revalidation",
        "generated_at": NOW.isoformat(),
        "total_proposals_checked": len(results),
        "by_revalidation_status": by_status,
        "still_valid_count": by_status.get("still_valid", 0),
        "needs_attention_count": len(results) - by_status.get("still_valid", 0),
        "quote_refresh": quote_refresh,
        "proposals": results,
    }


def render_markdown(report: dict) -> str:
    """Render revalidation report as markdown."""
    lines = [
        f"# {report['report']}",
        f"Generated: {report['generated_at']}",
        "",
        f"**Total checked:** {report['total_proposals_checked']}",
        f"**Still valid:** {report['still_valid_count']}",
        f"**Needs attention:** {report['needs_attention_count']}",
        "",
        "## Status Breakdown",
    ]
    for st, cnt in sorted(report["by_revalidation_status"].items()):
        lines.append(f"- **{st}:** {cnt}")

    lines.append("")
    lines.append("## Proposal Details")
    lines.append("")
    lines.append("| ID | Symbol | Strategy | Status | Age (h) | Quote Age (h) | Drift % | Reval Status |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for p in report["proposals"][:50]:
        drift = f"{p['price_drift_pct']:.1f}" if p.get("price_drift_pct") is not None else "-"
        age = f"{p['age_hours']:.0f}" if p.get("age_hours") is not None else "-"
        q_age = f"{p['quote_age_hours']:.1f}" if p.get("quote_age_hours") is not None else "-"
        lines.append(
            f"| {p['proposal_id']} | {p['symbol']} | {p.get('strategy', '-')} | "
            f"{p.get('proposal_status', '-')} | {age} | {q_age} | {drift} | "
            f"{p['revalidation_status']} |"
        )

    # Highlight urgent items
    urgent = [p for p in report["proposals"]
              if p["revalidation_status"] in ("rebuild_recommended", "human_review_required", "expired")]
    if urgent:
        lines.append("")
        lines.append("## Urgent Items")
        for p in urgent:
            flags = ", ".join(p.get("flags", []))
            lines.append(f"- **{p['symbol']}** (#{p['proposal_id']}): {p['revalidation_status']} [{flags}]")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Automated Trade Proposal Revalidation")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Dry run mode (default, read-only)")
    parser.add_argument("--apply", action="store_true",
                        help="Apply mode (currently same as dry-run: no writes)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of proposals to check")
    parser.add_argument("--output-json", type=str, help="Write JSON report to file")
    parser.add_argument("--output-md", type=str, help="Write Markdown report to file")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--refresh-quotes", action="store_true",
                        help="Refresh stale live quotes when price/quote blocks dominate")
    args = parser.parse_args()

    print("[revalidation] Checking pending/approved proposals ...")
    report = revalidate_proposals(
        limit=args.limit, verbose=args.verbose, refresh_quotes=args.refresh_quotes,
    )

    # Console summary
    print(f"[revalidation] Total checked: {report['total_proposals_checked']}")
    print(f"[revalidation] Still valid: {report['still_valid_count']}")
    print(f"[revalidation] Needs attention: {report['needs_attention_count']}")
    for st, cnt in report["by_revalidation_status"].items():
        print(f"  {st}: {cnt}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"[revalidation] JSON written to {args.output_json}")

    if args.output_md:
        md = render_markdown(report)
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md)
        print(f"[revalidation] Markdown written to {args.output_md}")

    if not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
