#!/usr/bin/env python3
"""handle_telegram_proposal_callback.py — Handle Telegram proposal callbacks safely.

Default: dry-run. Requires --apply for actual action execution.
Uses existing paper approval flow. Does NOT create live trades.

Usage:
    .venv/bin/python scripts/handle_telegram_proposal_callback.py --payload-json FILE --dry-run
    .venv/bin/python scripts/handle_telegram_proposal_callback.py --payload-json FILE --apply
"""
import argparse, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

log = logging.getLogger("telegram_callback")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

CALLBACK_LOG = PROJ / "logs" / "telegram_callback_audit.log"


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def _log_callback(cb_id, proposal_id, symbol, action, allowed, applied, status, error=None):
    try:
        CALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "callback_id": cb_id, "proposal_id": proposal_id,
            "symbol": symbol, "action": action, "allowed": allowed,
            "applied": applied, "status": status, "error": error,
        })
        with open(CALLBACK_LOG, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser(description="Handle Telegram proposal callbacks (default: dry-run)")
    p.add_argument("--payload-json", type=str)
    p.add_argument("--payload", type=str)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.apply:
        args.dry_run = False

    # Load payload
    if args.payload_json:
        payload = json.loads(Path(args.payload_json).read_text())
    elif args.payload:
        payload = json.loads(args.payload)
    else:
        payload = {"action": "OPEN_DETAILS", "symbol": "TEST"}

    from telegram_callback_policy import parse_callback_payload, classify_callback_action, callback_suppression_key

    parsed = parse_callback_payload(payload)
    action = parsed["action"]
    symbol = parsed.get("symbol")
    pid_raw = parsed.get("proposal_id")

    # Resolve proposal
    proposal = None
    if pid_raw == "latest" and symbol:
        proposal = _db_query("SELECT * FROM paper_trade_proposals WHERE symbol=%s ORDER BY created_at DESC LIMIT 1", [symbol], fetch="one")
    elif pid_raw:
        try:
            proposal = _db_query("SELECT * FROM paper_trade_proposals WHERE id=%s", [int(pid_raw)], fetch="one")
        except (ValueError, TypeError):
            pass

    if not proposal:
        proposal = {"symbol": symbol or "?", "status": "UNKNOWN", "approval_blockers": [{"reason": "proposal_not_found"}]}

    # Load execution readiness
    if proposal.get("id"):
        er = _db_query("SELECT * FROM proposal_execution_readiness WHERE proposal_id=%s ORDER BY created_at DESC LIMIT 1",
                       [proposal["id"]], fetch="one")
        if er:
            proposal["execution_readiness"] = er
            # Parse blockers
            bl = er.get("blockers")
            if isinstance(bl, str):
                try: bl = json.loads(bl)
                except: bl = [bl]
            proposal["approval_blockers"] = [{"reason": b} if isinstance(b, str) else b for b in (bl or [])]

    # Classify
    result = classify_callback_action(parsed, proposal)
    cb_key = callback_suppression_key(parsed)

    action_result = {
        "callback_id": cb_key,
        "proposal_id": proposal.get("id"),
        "symbol": proposal.get("symbol"),
        "action": action,
        "classification": result,
        "dry_run": args.dry_run,
        "applied": False,
        "success": False,
        "message": "",
    }

    if args.verbose:
        log.info(f"Callback: {action} for {symbol} #{proposal.get('id','?')} — {'ALLOWED' if result['allowed'] else 'BLOCKED'}")
        if result.get("blockers"):
            for b in result["blockers"]:
                log.info(f"  Blocker: {b}")

    # Execute action
    if not result["allowed"]:
        action_result["message"] = f"BLOCKED: {'; '.join(result['blockers'][:3])}"
        _log_callback(cb_key, proposal.get("id"), symbol, action, False, False, "blocked")
    elif args.dry_run:
        action_result["message"] = f"DRY RUN: {action} would execute for {symbol}"
        _log_callback(cb_key, proposal.get("id"), symbol, action, True, False, "dry_run")
    else:
        # Apply
        try:
            if action == "APPROVE_PAPER":
                from paper_trade_logger import approve_proposal
                r = approve_proposal(proposal["id"])
                action_result["success"] = r.get("success", False)
                action_result["message"] = r.get("message", "Approval attempted")
                action_result["applied"] = True

            elif action == "REJECT":
                from paper_trade_logger import reject_proposal
                r = reject_proposal(proposal["id"], "telegram_reject")
                action_result["success"] = r.get("success", False)
                action_result["message"] = r.get("message", "Rejection attempted")
                action_result["applied"] = True

            elif action == "REBUILD":
                action_result["message"] = f"REBUILD requested for {symbol} #{proposal.get('id')}. Manual rebuild required."
                action_result["success"] = True
                action_result["applied"] = True

            elif action == "WATCH":
                action_result["message"] = f"WATCH noted for {symbol} #{proposal.get('id')}. No action taken."
                action_result["success"] = True
                action_result["applied"] = True

            elif action == "OPEN_DETAILS":
                try:
                    from notification_url_builder import build_proposal_url
                    action_result["message"] = build_proposal_url(proposal.get("id"), proposal.get("symbol"))
                except Exception:
                    action_result["message"] = f"/v3/trading?tab=Proposals&proposal={proposal.get('id')}"
                action_result["success"] = True

            _log_callback(cb_key, proposal.get("id"), symbol, action, True, True,
                         "success" if action_result["success"] else "failed")
        except Exception as e:
            action_result["message"] = f"Error: {str(e)[:100]}"
            _log_callback(cb_key, proposal.get("id"), symbol, action, True, False, "error", str(e)[:100])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": action_result,
    }

    if args.verbose:
        log.info(f"Result: {action_result['message']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Callback: {action} — {symbol}\n",
              f"Status: {'ALLOWED' if result['allowed'] else 'BLOCKED'} | {'Applied' if action_result['applied'] else 'Dry-run'}\n",
              f"Message: {action_result['message']}"]
        if result.get("blockers"):
            md.append(f"\nBlockers: {', '.join(result['blockers'][:5])}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
