#!/usr/bin/env python3
"""After losing days / tilt tags — queue Morning Brief / cockpit review item."""
from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


RECEIPT_NAME = "journal_tilt_morning_hook"


def decide(beh: dict) -> dict:
    """Pure: whether the tilt review item is needed, from behavioral_analytics() output."""
    tilt = beh.get("tilt") or {}
    after_loss = beh.get("after_losing_day") or {}
    needs_review = (
        (tilt.get("trades") or 0) >= 2
        or (after_loss.get("net_pnl") or 0) < -500
        or (after_loss.get("win_rate") or 100) < 40
    )
    rid = f"tradeinview-tilt-{date.today().isoformat()}"
    title = "TradeInView: review tilt / post-loss trading"
    summary = (
        f"Tilt-tagged trades: {tilt.get('trades', 0)} (${tilt.get('net_pnl', 0):,.0f}). "
        f"After losing days: {after_loss.get('trades', 0)}t, {after_loss.get('win_rate', 0)}% WR, "
        f"${after_loss.get('net_pnl', 0):,.0f}. Annotate recent trades and review Exit Intel."
    )
    return {"needs_review": bool(needs_review), "review_item_id": rid, "title": title,
            "summary": summary, "tilt": tilt, "after_losing_day": after_loss}


def _insert(q, d: dict) -> None:
    # db_adapter._execute swallows SQL errors and returns None; success with fetch="none" is True.
    ok = q("""
        INSERT INTO operator_review_queue
          (review_item_id, source_domain, source_table, title, summary, severity, review_type,
           status, requires_action, action_label, action_url, linked_dashboard_route, payload)
        VALUES (%s, 'trade_in_view', 'journal_trade_reviews', %s, %s, 'warning', 'tilt_review',
                'open', true, 'Open TradeInView', '/v3/trade-in-view', '/v3/trade-in-view', %s::jsonb)
    """, [d["review_item_id"], d["title"], d["summary"],
          json.dumps({"tilt": d["tilt"], "after_losing_day": d["after_losing_day"]})], "none")
    if ok is not True:
        raise RuntimeError(f"operator_review_queue insert failed for {d['review_item_id']}")


def run(dry_run: bool = False) -> dict:
    """One tick. Returns {"outcome": ..., "review_item_id": ...}.

    Dry run (AGENTS.md §6): the same reads (behavioral analytics + the idempotency SELECT) on a
    READ ONLY session, then returns BEFORE _insert is reachable and says what it would queue.
    """
    import journal_trade_in_view as tiv
    from db_adapter import _execute as q

    if dry_run:
        from db_adapter import _get_conn
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(_get_conn())
    d = decide(tiv.behavioral_analytics(days=7))
    if not d["needs_review"]:
        print("no tilt hook needed")
        return {"outcome": "not_needed", "review_item_id": None}

    rid = d["review_item_id"]
    existing = q("SELECT id FROM operator_review_queue WHERE review_item_id=%s", [rid], "one")
    if existing:
        print("already queued")
        return {"outcome": "already_queued", "review_item_id": rid}
    if dry_run:
        print(f"[DRY RUN] would queue {rid} into operator_review_queue: {d['summary']}")
        return {"outcome": "would_queue", "review_item_id": rid}

    _insert(q, d)
    print(f"queued {rid}")
    return {"outcome": "queued", "review_item_id": rid}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="read-only: report whether a tilt review item would be queued; writes nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        run(dry_run=True)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        res = run(dry_run=False)
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"journal tilt hook FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_receipt(RECEIPT_NAME, ok=True, summary=res, started_at=started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
