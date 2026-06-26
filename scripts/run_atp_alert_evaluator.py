#!/usr/bin/env python3
"""run_atp_alert_evaluator.py — Evaluate pending proposals for urgent review alerts.

Checks target-crossed, large-move, blocked-but-moved conditions.
Default: dry-run. No trades. No orders. No approvals.
"""
import argparse, json, sys, hashlib, time
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

# In-memory dedupe
_sent_alerts = {}

LARGE_MOVE_PCT = 5.0  # Alert if price moved >5% from entry


def evaluate_proposals(conn, symbols=None):
    """Evaluate pending proposals for alert conditions."""
    cur = conn.cursor()
    sql = """SELECT id, symbol, strategy_id, status, proposed_entry, proposed_stop,
        proposed_target1, current_price, last_price_checked_at, last_price_source,
        approval_blocked_reason
        FROM paper_trade_proposals WHERE status = 'PENDING'"""
    if symbols:
        sql += " AND symbol = ANY(%s)"
        cur.execute(sql, [symbols])
    else:
        cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def classify_alert(prop):
    """Classify what alert type a proposal needs, if any."""
    entry = float(prop.get("proposed_entry") or 0)
    current = float(prop.get("current_price") or 0)
    target = float(prop.get("proposed_target1") or 0)
    stop = float(prop.get("proposed_stop") or 0)

    if entry <= 0 or current <= 0:
        return None

    alerts = []

    # Target crossed before review
    if target > 0 and current >= target:
        pct = ((current - entry) / entry * 100) if entry > 0 else 0
        alerts.append({
            "type": "target_crossed_before_review",
            "severity": "URGENT",
            "reason": f"Price ${current:.2f} crossed target ${target:.2f} (+{pct:.1f}% from entry ${entry:.2f})",
        })

    # Stop crossed
    if stop > 0 and current <= stop:
        alerts.append({
            "type": "stop_crossed_pending",
            "severity": "URGENT",
            "reason": f"Price ${current:.2f} at or below stop ${stop:.2f}",
        })

    # Large move before review
    if entry > 0:
        move_pct = (current - entry) / entry * 100
        if abs(move_pct) >= LARGE_MOVE_PCT and not any(a["type"] == "target_crossed_before_review" for a in alerts):
            alerts.append({
                "type": "large_move_before_review",
                "severity": "HIGH",
                "reason": f"Price moved {move_pct:+.1f}% from entry ${entry:.2f} to ${current:.2f}",
            })

    return alerts if alerts else None


def build_telegram_message(prop, alert):
    """Build a concise Telegram alert message."""
    entry = float(prop.get("proposed_entry") or 0)
    current = float(prop.get("current_price") or 0)
    target = float(prop.get("proposed_target1") or 0)
    stop = float(prop.get("proposed_stop") or 0)
    pct = ((current - entry) / entry * 100) if entry > 0 else 0
    rr = ((target - entry) / (entry - stop)) if entry > stop > 0 and target > 0 else 0

    icon = "\U0001f6a8" if alert["severity"] == "URGENT" else "\u26a0\ufe0f"
    type_label = alert["type"].replace("_", " ").upper()
    try:
        from proposal_alerter import friendly_status as _friendly_status
    except Exception:
        _friendly_status = lambda s: str(s or "?")

    msg = f"""{icon} ATP REVIEW ALERT -- {type_label}
Symbol: {prop['symbol']}
Strategy: {prop.get('strategy_id', '?')}
Entry: ${entry:.2f}
Current: ${current:.2f} ({pct:+.1f}%)
Target: ${target:.2f}
Stop: ${stop:.2f}
R:R: {rr:.1f}x
Status: {_friendly_status(prop.get('status'))}
Approval: BLOCKED

{alert['reason']}

Action: Review /v3/trading
No order auto-submitted — review to route (paper-test or live Path-B, 2FA)."""
    return msg


def dedupe_key(prop, alert):
    """Build dedupe key."""
    return hashlib.md5(f"{prop['id']}_{alert['type']}".encode()).hexdigest()[:12]


def is_deduped(prop, alert, window_minutes=60):
    """Check if alert was recently sent."""
    key = dedupe_key(prop, alert)
    last = _sent_alerts.get(key, 0)
    return (time.time() - last) < window_minutes * 60


def mark_sent(prop, alert):
    """Record alert as sent for dedupe."""
    key = dedupe_key(prop, alert)
    _sent_alerts[key] = time.time()


def main():
    p = argparse.ArgumentParser(description="ATP alert evaluator (default: dry-run)")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--symbols", type=str)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)

    symbols = args.symbols.split(",") if args.symbols else None
    proposals = evaluate_proposals(conn, symbols)
    conn.close()

    mode = "DRY RUN" if args.dry_run else "APPLY"
    results = []

    for prop in proposals:
        alerts = classify_alert(prop)
        if not alerts:
            results.append({"proposal_id": prop["id"], "symbol": prop["symbol"], "alerts": [], "action": "no_alert"})
            continue

        for alert in alerts:
            deduped = is_deduped(prop, alert)
            msg = build_telegram_message(prop, alert)

            entry = {
                "proposal_id": prop["id"],
                "symbol": prop["symbol"],
                "alert_type": alert["type"],
                "severity": alert["severity"],
                "reason": alert["reason"],
                "deduped": deduped,
                "message_preview": msg[:200],
            }

            if not args.dry_run and not deduped:
                try:
                    # Use rich alerter with inline buttons + throttling
                    from proposal_alerter import maybe_send_threshold_alert
                    alert_type_map = {
                        "target_crossed_before_review": "TARGET_CROSSED",
                        "stop_crossed_pending": "STOP_CROSSED",
                        "large_move_before_review": "LARGE_MOVE",
                    }
                    rich_type = alert_type_map.get(alert["type"], alert["type"])
                    maybe_send_threshold_alert(prop["id"], rich_type, float(prop.get("current_price") or 0))
                    mark_sent(prop, alert)
                    entry["sent"] = True
                except Exception as e:
                    entry["sent"] = False
                    entry["error"] = str(e)[:100]
            else:
                entry["sent"] = False
                entry["action"] = "would_send" if not deduped else "suppressed_dedupe"

            results.append(entry)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "proposals_checked": len(proposals),
        "alerts_generated": sum(1 for r in results if r.get("alert_type")),
        "would_send": sum(1 for r in results if r.get("action") == "would_send"),
        "results": results,
    }

    if args.verbose:
        print(f"[{mode}] ATP Alert Evaluator")
        print(f"  Proposals: {len(proposals)} | Alerts: {report['alerts_generated']}")
        for r in results:
            if r.get("alert_type"):
                print(f"  #{r['proposal_id']} {r['symbol']:6s} {r['alert_type']} [{r['severity']}] deduped={r.get('deduped')} sent={r.get('sent')}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# ATP Alert Evaluator ({mode})\n",
              f"Proposals: {len(proposals)} | Alerts: {report['alerts_generated']}"]
        for r in results:
            if r.get("alert_type"):
                md.append(f"- #{r['proposal_id']} {r['symbol']} {r['alert_type']} [{r['severity']}]")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
