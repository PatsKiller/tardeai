#!/usr/bin/env python3
"""momentum_scalp_early_lane_runner.py — P0-4: one command runs the momentum_scalp early lane:

    Finviz source refresh
      → strategy_signal_sync --today
      → auto_proposal_generator --today --apply
      → momentum_scalp_validation_fast_path --submit-sandbox

Each stage shells out to the EXISTING, proven script (no new broker/DB-write code), is idempotent, and
emits a JSON summary with latency. Default is DRY-RUN. Writing scan rows/signals/proposals needs
--apply; sandbox validation submit needs an explicit --submit-validation (or env).

SAFETY: no live broker writes; sandbox/simulated validation only; operator confirmation / 2FA untouched;
quote freshness / TTL / route policy / liquidity / risk gates / kill switches never weakened here. The
standalone */2 validation runner remains the backup — this is the immediate, chained early lane.

    python3 scripts/momentum_scalp_early_lane_runner.py --dry-run            # report only (default)
    python3 scripts/momentum_scalp_early_lane_runner.py --apply             # scan + signals + proposals (no submit)
    python3 scripts/momentum_scalp_early_lane_runner.py --apply --submit-validation
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
WINDOW = {"start": "06:00", "end": "12:00"}      # full strategy window, ET, trading days
FINVIZ_TIMEOUT = 240
STAGE_TIMEOUT = 300
#: 2026-09-28 (plan "Momentum scalps: why none arrive", root cause 2): the cron line that was
#: supposed to refresh Finviz ran `timeout 150` around a stage allowed 240 s, so it was killed
#: silently every quarter-hour while holding the lane lock — the lane had not refreshed since
#: 2026-09-18. The refresh now (a) honours an OUTER deadline (env MOMENTUM_SCALP_OUTER_DEADLINE_S
#: or --deadline-s, set by cron a little below its `timeout`), (b) runs only the scalp screeners
#: (config `refresh.screener_ids`) instead of all 45, and (c) writes a durable receipt BEFORE and
#: AFTER the stage so a killed run is visible as STARTED-without-DONE.
OUTER_DEADLINE_ENV = "MOMENTUM_SCALP_OUTER_DEADLINE_S"
REFRESH_RECEIPT_ENV = "MOMENTUM_SCALP_REFRESH_RECEIPT"
REFRESH_RECEIPT_NAME = "momentum_scalp_refresh_receipt.json"
DEADLINE_HEADROOM_S = 15


def now_et(stamp: str | None = None) -> datetime:
    if stamp:
        return datetime.fromisoformat(stamp)
    n = datetime.now(_ET) if _ET else datetime.now()
    return n


def _hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


def in_window(t: datetime, window=WINDOW) -> bool:
    return window["start"] <= _hhmm(t) <= window["end"]


def is_trading_day(t: datetime) -> bool:
    return t.weekday() < 5     # Mon-Fri (holidays handled by the scan being a safe no-op)


def _run(cmd: list, timeout: int = STAGE_TIMEOUT) -> dict:
    """Run a subprocess, capturing rc/stdout tail/latency. Never raises."""
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        return {"rc": p.returncode, "latency_ms": int((time.monotonic() - t0) * 1000),
                "stdout_tail": out[-600:], "stderr_tail": (p.stderr or "").strip()[-300:]}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "latency_ms": int((time.monotonic() - t0) * 1000),
                "stdout_tail": "", "stderr_tail": f"timeout after {timeout}s"}
    except Exception as e:
        return {"rc": 1, "latency_ms": int((time.monotonic() - t0) * 1000),
                "stdout_tail": "", "stderr_tail": str(e)[:300]}


def _py() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


# ── Stages (each returns a JSON-able summary) ───────────────────────────────────────────────

def _served_data_root() -> Path:
    """Where receipts live: the served persistent-state data root from data_source_authority.json
    (never a hard-coded host path); falls back to this tree's data/ when the registry is absent."""
    try:
        reg = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
        root = (reg.get("served_from") or {}).get("root")
        if root:
            return Path(root)
    except Exception:
        pass
    return ROOT / "data"


def refresh_receipt_path() -> Path:
    override = os.environ.get(REFRESH_RECEIPT_ENV, "").strip()
    if override:
        return Path(override)
    return _served_data_root() / "runtime" / REFRESH_RECEIPT_NAME


def write_refresh_receipt(state: str, **fields) -> dict:
    """Durable, atomic. STARTED before the slow stage; DONE/FAILED after. Never raises."""
    rec = {"schema": "MomentumScalpRefreshReceipt@v1", "state": state,
           "at": (datetime.now(_ET) if _ET else datetime.now()).isoformat(),
           "pid": os.getpid(), **fields}
    try:
        path = refresh_receipt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(rec, default=str))
        os.replace(tmp, path)
    except Exception as exc:  # a receipt failure must never kill the lane
        rec["receipt_error"] = str(exc)
    return rec


def read_refresh_receipt() -> dict | None:
    try:
        return json.loads(refresh_receipt_path().read_text())
    except Exception:
        return None


def refresh_age_min(now: datetime | None = None, receipt: dict | None = None) -> float | None:
    """Minutes since the last DONE refresh; None when there is no DONE receipt."""
    rec = receipt if receipt is not None else read_refresh_receipt()
    if not rec or rec.get("state") != "DONE":
        return None
    try:
        done_at = datetime.fromisoformat(str(rec.get("at")))
    except Exception:
        return None
    now = now or (datetime.now(_ET) if _ET else datetime.now())
    if done_at.tzinfo is None and now.tzinfo is not None:
        done_at = done_at.replace(tzinfo=now.tzinfo)
    if done_at.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=done_at.tzinfo)
    return max(0.0, (now - done_at).total_seconds() / 60.0)


def outer_deadline_s(cli_value: float | None = None) -> float | None:
    """Seconds the whole run may take (cron `timeout` minus headroom). None = unbounded."""
    raw = cli_value if cli_value is not None else os.environ.get(OUTER_DEADLINE_ENV, "")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def stage_timeout(stage_default: int, deadline_s: float | None, started_monotonic: float | None) -> int:
    """Clamp a stage timeout so it ends before the outer deadline (with headroom)."""
    if deadline_s is None:
        return int(stage_default)
    elapsed = 0.0 if started_monotonic is None else max(0.0, time.monotonic() - started_monotonic)
    remaining = deadline_s - elapsed - DEADLINE_HEADROOM_S
    return int(max(1, min(stage_default, remaining)))


def refresh_screener_ids(config_path: Path | None = None) -> list[str]:
    """Scalp screeners to refresh (config `refresh.screener_ids`); empty = full runner (legacy)."""
    path = config_path or (ROOT / "config" / "finviz_momentum_scalp_screen.yaml")
    try:
        import yaml
        cfg = yaml.safe_load(path.read_text()) or {}
        ids = ((cfg.get("momentum_scalp_finviz_screen") or {}).get("refresh") or {}).get("screener_ids") or []
        return [str(x) for x in ids]
    except Exception:
        return []


_ROWS_RE = re.compile(r"(\d+)\s+(?:found|rows|tickers|symbols)")   # runner prints "<id>: N found, M NEW"


def stage_finviz_scan(dry_run: bool, deadline_s: float | None = None, started_monotonic: float | None = None,
                      screener_ids: list[str] | None = None) -> dict:
    """Finviz source refresh — reuses the throttle-safe finviz_screener_runner. Source rows only.

    Runs one `--screener <id>` call per scalp screener (config) so the refresh fits the cron slot;
    with no ids configured it falls back to the full `--run`. Writes STARTED/DONE|FAILED receipts.
    """
    s = {"stage": "finviz_scan", "ran": not dry_run}
    if dry_run:
        s.update(ok=True, reason="dry_run_no_refresh")
        return s
    ids = refresh_screener_ids() if screener_ids is None else list(screener_ids)
    write_refresh_receipt("STARTED", screener_ids=ids, deadline_s=deadline_s)
    results, rows_total, rc_worst = [], 0, 0
    runner = str(SCRIPTS / "finviz_screener_runner.py")
    calls = [[_py(), runner, "--screener", sid] for sid in ids] or [[_py(), runner, "--run"]]
    for cmd in calls:
        t_out = stage_timeout(FINVIZ_TIMEOUT, deadline_s, started_monotonic)
        r = _run(cmd, timeout=t_out)
        rc_worst = max(rc_worst, int(r["rc"]))
        rows_total += sum(int(x) for x in _ROWS_RE.findall(r.get("stdout_tail") or ""))
        results.append({"cmd": cmd[-2:], "rc": r["rc"], "latency_ms": r["latency_ms"], "timeout_s": t_out,
                        "stderr": r["stderr_tail"]})
    ok = rc_worst == 0
    write_refresh_receipt("DONE" if ok else "FAILED", rc=rc_worst, rows=rows_total, screener_ids=ids,
                          calls=len(calls))
    s.update(ok=ok, rc=rc_worst, latency_ms=sum(x["latency_ms"] for x in results), rows=rows_total,
             reason=("finviz_screener_runner --screener x%d" % len(ids)) if ids else "finviz_screener_runner --run",
             calls=results)
    return s


def stage_signal_sync(dry_run: bool) -> dict:
    s = {"stage": "signal_sync", "ran": True}
    cmd = [_py(), str(SCRIPTS / "strategy_signal_sync.py"), "--today"]
    if dry_run:
        cmd.append("--dry-run")
    r = _run(cmd)
    s.update(ok=(r["rc"] == 0), latency_ms=r["latency_ms"], rc=r["rc"],
             reason="strategy_signal_sync --today" + (" --dry-run" if dry_run else ""),
             stdout_tail=r["stdout_tail"], stderr=r["stderr_tail"])
    return s


def stage_proposal_gen(dry_run: bool) -> dict:
    s = {"stage": "proposal_gen", "ran": True}
    cmd = [_py(), str(SCRIPTS / "auto_proposal_generator.py"), "--today"]
    cmd.append("--dry-run" if dry_run else "--apply")
    r = _run(cmd)
    s.update(ok=(r["rc"] == 0), latency_ms=r["latency_ms"], rc=r["rc"],
             reason="auto_proposal_generator --today " + ("--dry-run" if dry_run else "--apply"),
             stdout_tail=r["stdout_tail"], stderr=r["stderr_tail"])
    return s


def stage_validation(submit: bool) -> dict:
    """Validation fast path — sandbox/simulated only. submit=False → dry-run evaluation."""
    s = {"stage": "validation_fast_path", "ran": True, "submit": submit}
    cmd = [_py(), str(SCRIPTS / "momentum_scalp_validation_fast_path.py"),
           "--submit-sandbox" if submit else "--dry-run", "--once"]
    r = _run(cmd)
    s.update(ok=(r["rc"] == 0), latency_ms=r["latency_ms"], rc=r["rc"],
             reason="momentum_scalp_validation_fast_path " + ("--submit-sandbox" if submit else "--dry-run"),
             stdout_tail=r["stdout_tail"], stderr=r["stderr_tail"])
    return s


def scan_counts(window_days: int = 1) -> dict:
    """Read-only count of today's momentum-scalp-relevant scan rows (GO/WAIT/SCOUT). Degrades safely."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT decision, scout_status FROM trade_ai_scans
            WHERE run_date >= CURRENT_DATE - INTERVAL '%s day'
        """ % int(window_days))
        rows = cur.fetchall()
        go = sum(1 for d, _ in rows if d == "GO")
        wait = sum(1 for d, _ in rows if d == "WAIT")
        scout = sum(1 for _, sstat in rows if sstat == "SOCIAL_SCOUT")
        return {"rows": len(rows), "go": go, "wait": wait, "scout": scout, "ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"counts unavailable: {str(e).splitlines()[0][:100]}"}


def run_pipeline(dry_run: bool, submit_validation: bool, stages: list | None = None,
                 now: datetime | None = None, ignore_window: bool = False) -> dict:
    t = now or now_et()
    window_ok = is_trading_day(t) and in_window(t)
    started = datetime.now().isoformat()
    stages = stages or ["finviz_scan", "signal_sync", "proposal_gen", "validation_fast_path"]

    if not window_ok and not ignore_window:
        return {"ok": True, "status": "SKIPPED_OFF_WINDOW", "generated_at": started,
                "now_et": _hhmm(t), "trading_day": is_trading_day(t), "window": WINDOW,
                "note": "Off-window no-op (06:00-12:00 ET trading days). Use --ignore-window to force.",
                "stages": []}

    results, t0 = [], time.monotonic()
    fn = {"finviz_scan": lambda: stage_finviz_scan(dry_run),
          "signal_sync": lambda: stage_signal_sync(dry_run),
          "proposal_gen": lambda: stage_proposal_gen(dry_run),
          "validation_fast_path": lambda: stage_validation(submit_validation and not dry_run)}
    for name in stages:
        if name in fn:
            results.append(fn[name]())

    counts = scan_counts()
    failed = [r["stage"] for r in results if not r.get("ok")]
    return {
        "ok": not failed,
        "status": "DRY_RUN" if dry_run else ("PASS" if not failed else "PARTIAL"),
        "generated_at": started, "now_et": _hhmm(t), "window": WINDOW, "window_ok": window_ok,
        "dry_run": dry_run, "submit_validation": submit_validation and not dry_run,
        "total_latency_ms": int((time.monotonic() - t0) * 1000),
        "scan_counts": counts,
        "stages": results,
        "failed_stages": failed,
        "validation_note": "Sandbox/simulated only. Validation maturity is unchanged by this run — the "
                           "empirical sample (confirmed closed simulated validation trades) remains the "
                           "blocker to strategy maturity 4.5.",
        "safety_note": "No live broker writes. Operator confirmation / 2FA untouched.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Momentum scalp early lane: scan→signals→proposals→validation")
    ap.add_argument("--dry-run", action="store_true", help="report only (default)")
    ap.add_argument("--apply", action="store_true", help="write scan rows / signals / proposals")
    ap.add_argument("--submit-validation", action="store_true",
                    help="sandbox validation submit (also honors MOMENTUM_SCALP_VALIDATION_SUBMIT=1)")
    ap.add_argument("--ignore-window", action="store_true", help="run even outside 06:00-12:00 ET")
    ap.add_argument("--now", type=str, help="override ET now (ISO) for testing")
    ap.add_argument("--json", action="store_true", help="emit JSON (default)")
    args = ap.parse_args()

    dry_run = not args.apply
    submit = args.submit_validation or os.getenv("MOMENTUM_SCALP_VALIDATION_SUBMIT") == "1"
    rep = run_pipeline(dry_run=dry_run, submit_validation=submit,
                       now=now_et(args.now), ignore_window=args.ignore_window)
    print(json.dumps(rep, indent=2, default=str))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
