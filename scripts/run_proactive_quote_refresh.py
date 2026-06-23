#!/usr/bin/env python3
"""run_proactive_quote_refresh.py — Refresh quotes for proposals/incubator candidates.

Default: dry-run. Requires --apply to fetch and store quotes.
Does NOT create trades. Does NOT submit orders. Does NOT approve proposals.

Usage:
    .venv/bin/python scripts/run_proactive_quote_refresh.py --mode all --dry-run --verbose
    .venv/bin/python scripts/run_proactive_quote_refresh.py --mode pending --apply --verbose
"""
import argparse, json, logging, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

log = logging.getLogger("proactive_quote_refresh")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def main():
    p = argparse.ArgumentParser(description="Proactive quote refresh (default: dry-run)")
    p.add_argument("--mode", choices=["pending", "incubator", "broker", "all"], default="all")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.apply:
        args.dry_run = False

    # Select targets
    from select_quote_refresh_targets import _db_query
    import subprocess
    target_result = subprocess.run(
        [str(PROJ / ".venv/bin/python"), str(PROJ / "scripts/select_quote_refresh_targets.py"),
         "--mode", args.mode, "--limit", str(args.limit), "--output-json", "/dev/stdout"],
        capture_output=True, text=True, timeout=30
    )
    targets = []
    if target_result.returncode == 0:
        try:
            data = json.loads(target_result.stdout)
            targets = data.get("targets", [])
        except Exception:
            pass

    log.info(f"Quote refresh {'DRY RUN' if args.dry_run else 'APPLY'} — {len(targets)} targets")

    results = []
    refreshed = 0
    failed = 0

    if not args.dry_run and targets:
        try:
            from market_quote_provider import get_best_quote, store_quote
            from db_adapter import _get_conn
        except ImportError as e:
            log.error(f"Cannot import quote provider: {e}")
            args.dry_run = True

    for t in targets:
        symbol = t["symbol"]
        result = {"symbol": symbol, "source": t["source"], "status": "dry_run"}

        if args.dry_run:
            result["status"] = "dry_run"
            result["action"] = "would_refresh"
        else:
            try:
                quote = get_best_quote(symbol)
                if quote and quote.get("last_price"):
                    conn = _get_conn()
                    if conn:
                        store_quote(conn, symbol, quote)
                        # Q-1C: Write back to pending proposals so UNKNOWN_QUOTE clears
                        try:
                            cur = conn.cursor()
                            _src = quote.get("provider", "unknown")
                            _px = float(quote.get("last_price") or 0)
                            cur.execute("""
                                UPDATE paper_trade_proposals SET
                                    last_price_checked_at = NOW(),
                                    last_price_source = %s,
                                    current_price = %s,
                                    updated_at = NOW()
                                WHERE symbol = %s
                                  AND status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST')
                                  AND (
                                    lower(COALESCE(intended_broker, target_account, proposed_account, '')) LIKE 'schwab%%'
                                    OR lower(COALESCE(intended_broker, target_account, proposed_account, '')) LIKE 'fidelity%%'
                                    OR status = 'PENDING'
                                  )
                            """, [_src, _px, symbol])
                            conn.commit()
                        except Exception as _we:
                            log.warning(f"  Proposal writeback failed for {symbol}: {_we}")
                            try: conn.rollback()
                            except: pass
                        conn.close()
                    result["status"] = "refreshed"
                    result["provider"] = quote.get("provider")
                    result["last_price"] = quote.get("last_price")
                    result["is_execution_eligible"] = quote.get("is_execution_eligible")
                    result["spread_pct"] = quote.get("spread_pct")
                    refreshed += 1
                else:
                    result["status"] = "no_quote"
                    failed += 1
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)[:100]
                failed += 1

            # Rate limit — 200ms between calls
            time.sleep(0.2)

        results.append(result)
        if args.verbose:
            log.info(f"  {symbol}: {result['status']}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode, "dry_run": args.dry_run,
        "total_targets": len(targets),
        "refreshed": refreshed, "failed": failed,
        "results": results[:200],
    }

    if args.verbose:
        log.info(f"Summary: {len(targets)} targets, {refreshed} refreshed, {failed} failed")

    # ATP-ALERT-1: Run alert evaluator after quote refresh
    if not args.dry_run and refreshed > 0:
        try:
            from run_atp_alert_evaluator import evaluate_proposals, classify_alert, build_telegram_message, is_deduped, mark_sent
            from db_adapter import _get_conn as _gc2
            _ac = _gc2()
            if _ac:
                _props = evaluate_proposals(_ac)
                _ac.close()
                for _p in _props:
                    _alerts = classify_alert(_p)
                    if _alerts:
                        for _a in _alerts:
                            if not is_deduped(_p, _a):
                                _msg = build_telegram_message(_p, _a)
                                try:
                                    from telegram_alert import send_telegram
                                    _sent = send_telegram(_msg)  # Respect alert router (no bypass)
                                    if _sent:
                                        mark_sent(_p, _a)
                                        log.info(f"  ALERT sent: {_p['symbol']} {_a['type']} [{_a['severity']}]")
                                    # If router suppressed, don't log as sent
                                except Exception as _te:
                                    log.warning(f"  Alert send failed: {_te}")
        except Exception as _ae:
            log.warning(f"  Alert evaluation skipped: {_ae}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Proactive Quote Refresh {'DRY RUN' if args.dry_run else 'APPLIED'}\n",
              f"Targets: {len(targets)} | Refreshed: {refreshed} | Failed: {failed}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
