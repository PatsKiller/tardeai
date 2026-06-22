#!/usr/bin/env python3
"""STOP-V2.2 — Unified stop supervisor.

Single entry point for stop monitoring, replacing the racing
open_trade_monitor (*/2) and paper_trade_monitor (*/5) crons.

Runs every 3 minutes during market hours:
1. Reconcile broker stops (V2.1)
2. Run open_trade_monitor logic (stop hits, time stops, news, alerts)
3. Run paper_trade_monitor logic (trailing, phantom, integrity)
4. Report unified health

Does NOT create, cancel, or move stops in this phase (V2.2).
Stop movement preserved from existing monitors only.
"""
import argparse, json, logging, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [stop_supervisor] %(message)s")
log = logging.getLogger("stop_supervisor")


def _safety_checks():
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    assert os.environ.get("ALPACA_MODE") == "paper", "ALPACA_MODE must be paper"
    assert os.environ.get("LLM_DISABLE_LIVE_EXECUTION") == "true", "LLM_DISABLE must be true"


def _is_market_hours():
    """Check if within market hours (9:30-16:00 ET)."""
    try:
        import pytz
        et = pytz.timezone("US/Eastern")
        now = datetime.now(et)
        if now.weekday() >= 5:
            return False
        h, m = now.hour, now.minute
        return (h > 9 or (h == 9 and m >= 30)) and h < 16
    except Exception:
        return True  # fail-open for monitoring


def _run_reconciliation(verbose=False):
    """Run STOP-V2.1 broker stop reconciliation."""
    t0 = time.time()
    try:
        from reconcile_stop_v21_broker_stops import reconcile
        result = reconcile(verbose=verbose)
        dur = time.time() - t0
        summary = result.get("summary", {})
        log.info(f"Reconciliation: {summary.get('reconciled', 0)}/{summary.get('total_trades', 0)} reconciled, "
                 f"{summary.get('critical', 0)} critical, {dur:.1f}s")
        return result
    except Exception as e:
        log.error(f"Reconciliation failed: {e}")
        return {"error": str(e), "summary": {"reconciled": 0, "critical": -1}}


def _run_open_trade_monitor(dry_run=True, verbose=False):
    """Run open_trade_monitor logic."""
    t0 = time.time()
    try:
        from open_trade_monitor import run_monitor
        result = run_monitor(dry_run=dry_run)
        dur = time.time() - t0
        log.info(f"Open trade monitor: {dur:.1f}s")
        return {"success": True, "duration": round(dur, 1)}
    except Exception as e:
        log.error(f"Open trade monitor failed: {e}")
        return {"success": False, "error": str(e)}


def _run_paper_trade_monitor(dry_run=True, verbose=False):
    """Run paper_trade_monitor logic."""
    t0 = time.time()
    try:
        from paper_trade_monitor import monitor
        result = monitor(dry_run=dry_run)
        dur = time.time() - t0
        log.info(f"Paper trade monitor: {dur:.1f}s")
        return {"success": True, "duration": round(dur, 1)}
    except Exception as e:
        log.error(f"Paper trade monitor failed: {e}")
        return {"success": False, "error": str(e)}


def _write_audit(event_type, details):
    try:
        from db_adapter import get_connection
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO audit_log (event_type, input_snapshot, actor) VALUES (%s, %s, 'stop_supervisor')",
                        [event_type, json.dumps(details, default=str)])
            conn.commit()
    except Exception:
        pass


def run_cycle(dry_run=True, reconcile_only=False, verbose=False):
    """Run one unified monitoring cycle."""
    _safety_checks()
    t0 = time.time()
    in_hours = _is_market_hours()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_hours": in_hours,
        "dry_run": dry_run,
        "reconcile_only": reconcile_only,
    }

    # Step 1: Reconciliation (always runs)
    recon = _run_reconciliation(verbose=verbose)
    report["reconciliation"] = recon.get("summary", {})
    report["reconciliation_findings"] = recon.get("findings", [])

    critical = recon.get("summary", {}).get("critical", 0)
    if critical > 0:
        log.warning(f"CRITICAL: {critical} reconciliation findings — positions may be unprotected")

    # Phase 190D: route paper-position protection defects to SIEM (alert_events) and,
    # when PROTECTION_ALERTS_TELEGRAM=true, to Telegram. Best-effort — must never break
    # the supervisor. Reads paper_trades directly (not brokerage JSON); dedups internally.
    try:
        import protection_alerts
        _send_tg = os.environ.get("PROTECTION_ALERTS_TELEGRAM", "").lower() == "true"
        _pa = protection_alerts.run(send=_send_tg)
        report["protection_alerts"] = {
            "defects_found": _pa.get("defects_found"),
            "siem_emitted": len(_pa.get("siem_emitted", [])),
            "telegram_sent": bool(_pa.get("telegram_sent")),
        }
        if _pa.get("siem_emitted"):
            log.warning(f"PROTECTION: emitted {len(_pa['siem_emitted'])} SIEM defect events")
    except Exception as _pe:
        log.error(f"protection_alerts hook failed (non-fatal): {_pe}")
        report["protection_alerts"] = {"error": str(_pe)}

    # Synthetic stops for FRACTIONAL Schwab positions (operator 2026-06-21): Schwab rejects resting STOP
    # orders on fractional qtys, so these positions are watched here — on a price breach (apply mode, RTH)
    # a Market-Day sell-all 2FA is requested (operator approves to fire; never auto-submits). Best-effort.
    try:
        import synthetic_stop_monitor as _ssm
        _syn = _ssm.check_and_trigger(dry_run=dry_run or not in_hours)
        _trig = [r for r in _syn if r.get("status") == "triggered"]
        _would = [r for r in _syn if r.get("status") == "would_trigger"]
        report["synthetic_stops"] = {"checked": len(_syn), "triggered": len(_trig),
                                     "would_trigger": len(_would), "detail": _syn}
        if _trig:
            log.warning(f"SYNTHETIC STOP: {len(_trig)} fractional position(s) breached → Market-Day sell-all 2FA requested")
    except Exception as _se:
        log.error(f"synthetic_stop hook failed (non-fatal): {_se}")
        report["synthetic_stops"] = {"error": str(_se)}

    if reconcile_only:
        report["monitors_skipped"] = "reconcile_only mode"
        report["duration"] = round(time.time() - t0, 1)
        return report

    # Step 2: Open trade monitor (stop hits, time stops, news, alerts)
    if in_hours:
        otm = _run_open_trade_monitor(dry_run=dry_run, verbose=verbose)
        report["open_trade_monitor"] = otm
    else:
        report["open_trade_monitor"] = {"skipped": "after_hours"}
        log.info("After hours — skipping open_trade_monitor (reconciliation only)")

    # Step 3: Paper trade monitor (trailing, phantom, integrity)
    if in_hours:
        ptm = _run_paper_trade_monitor(dry_run=dry_run, verbose=verbose)
        report["paper_trade_monitor"] = ptm
    else:
        report["paper_trade_monitor"] = {"skipped": "after_hours"}
        log.info("After hours — skipping paper_trade_monitor trailing")

    # Step 4: Strategy-aware trailing recommendations (V2.3)
    trailing_recs = []
    _tc = None
    try:
        from strategy_trailing_policy import recommend_stop, get_strategy_family
        from db_adapter import get_connection as _gc_trail
        _tc = _gc_trail()
        if _tc:
            _tcur = _tc.cursor()
            _tcur.execute("""
                SELECT id, symbol, strategy_id, entry_price, planned_stop, stop_loss, current_price
                FROM paper_trades WHERE status='open'
            """)
            _tcols = [d[0] for d in _tcur.description]
            for _trow in _tcur.fetchall():
                _t = dict(zip(_tcols, _trow))
                rec = recommend_stop(
                    _t["strategy_id"] or "unknown",
                    float(_t["entry_price"] or 0),
                    float(_t["planned_stop"] or _t["stop_loss"] or 0),
                    float(_t["stop_loss"] or 0),
                    float(_t["current_price"] or 0),
                    market_hours=in_hours,
                    symbol=_t["symbol"],   # STOP-V2.4: enables the structural overlay when config'd on
                )
                rec["trade_id"] = _t["id"]
                rec["symbol"] = _t["symbol"]
                trailing_recs.append(rec)
                if verbose and rec.get("action") != "hold":
                    log.info(f"  #{_t['id']} {_t['symbol']}: {rec['action']} — {rec.get('reason','')}")
            _tcur.close()
    except Exception as e:
        log.warning(f"Trailing policy check failed: {e}")
    finally:
        # End the read-only transaction so the SHARED db_adapter connection is never left
        # idle-in-transaction (root cause of the 2026-06-09 connection-slot/lock pile-up that took the
        # whole DB to its slot limit). Rollback (not close) — the connection is a module-level singleton.
        if _tc is not None:
            try:
                _tc.rollback()
            except Exception:
                pass

    report["trailing_recommendations"] = trailing_recs
    report["trailing_summary"] = {
        "total": len(trailing_recs),
        "hold": sum(1 for r in trailing_recs if r.get("action") == "hold"),
        "recommend_trail": sum(1 for r in trailing_recs if r.get("action") == "recommend_trail"),
        "recommend_deferred": sum(1 for r in trailing_recs if r.get("action") == "recommend_deferred"),
        "recommend_review": sum(1 for r in trailing_recs if r.get("action") == "recommend_review"),
    }

    report["duration"] = round(time.time() - t0, 1)

    # Summary
    all_reconciled = recon.get("summary", {}).get("all_protected", False)
    report["health"] = {
        "all_protected": all_reconciled,
        "critical_findings": critical,
        "market_hours": in_hours,
        "stops_created": False,
        "stops_canceled": False,
        "stops_moved": False,
    }

    return report


def main():
    ap = argparse.ArgumentParser(description="Unified stop supervisor (STOP-V2.2)")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reconcile-only", action="store_true")
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    is_dry = not args.apply
    report = run_cycle(dry_run=is_dry, reconcile_only=args.reconcile_only, verbose=args.verbose)

    if args.apply:
        _write_audit("stop_v22_supervisor_cycle", report.get("health", {}))

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(report, f, indent=2, default=str)

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        h = report.get("health", {})
        r = report.get("reconciliation", {})
        lines = [
            f"# Unified Stop Supervisor Report\n\n",
            f"Generated: {report.get('generated_at')}\n",
            f"Mode: {'DRY RUN' if report.get('dry_run') else 'APPLY'}\n",
            f"Market hours: {report.get('market_hours')}\n",
            f"Duration: {report.get('duration')}s\n\n",
            f"## Reconciliation\n",
            f"- Reconciled: {r.get('reconciled', 0)}/{r.get('total_trades', 0)}\n",
            f"- Critical: {r.get('critical', 0)} | Warning: {r.get('warning', 0)}\n",
            f"- All protected: {'YES' if h.get('all_protected') else 'NO'}\n\n",
            f"## Monitors\n",
            f"- Open trade monitor: {json.dumps(report.get('open_trade_monitor', {}))}\n",
            f"- Paper trade monitor: {json.dumps(report.get('paper_trade_monitor', {}))}\n\n",
            f"## Safety\n",
            f"- Stops created: {h.get('stops_created', False)}\n",
            f"- Stops canceled: {h.get('stops_canceled', False)}\n",
            f"- Stops moved: {h.get('stops_moved', False)}\n",
        ]
        with open(args.output_md, "w") as f:
            f.writelines(lines)

    h = report.get("health", {})
    r = report.get("reconciliation", {})
    print(f"\nReconciled: {r.get('reconciled', 0)}/{r.get('total_trades', 0)} | "
          f"Critical: {r.get('critical', 0)} | Protected: {'YES' if h.get('all_protected') else 'NO'} | "
          f"Duration: {report.get('duration')}s")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
