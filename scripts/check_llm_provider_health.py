#!/usr/bin/env python3
"""check_llm_provider_health.py — alarm when a paid LLM lane is dead.

Reads the recent `llm_consumption_log` window, classifies the failures, and alerts the
operator when a lane is failing for a reason no retry will fix — a billing stop (HTTP 402)
or a rejected key (401/403). Transport blips are reported only when a lane is failing
essentially every call.

Standing gap this closes: from 2026-09-17 the DeepSeek balance went to -$0.09 and every
deepseek-flash call returned HTTP 402 for three days. 660+ failures, risk/steph/tax silent,
hermes_external_research silent, and nothing anywhere noticed — the health agents watch data
freshness, not provider errors. Each failed call still settled a cap reservation, so the
outage also drained the daily request pools.

  check_llm_provider_health.py                 # check + alert (deduped)
  check_llm_provider_health.py --dry-run       # print, never send
  check_llm_provider_health.py --hours 24      # wider window
  check_llm_provider_health.py --strict        # exit 1 when a finding is CRITICAL

Exit 0 = nothing to report (or alert sent). Exit 1 = CRITICAL finding under --strict.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.provider_health import evaluate, format_alert, pageable  # noqa: E402

STATE_PATH = PROJECT_ROOT / "data/runtime/llm_provider_health_alert.json"
# Durable proof the check itself ran, written every real run — a lane is verified by an
# artifact, never by an exit code (config/lane_registry.json, lane `llm-provider-health`).
# A monitor that can go silent unnoticed is the failure this whole change is about.
HEARTBEAT_PATH = PROJECT_ROOT / "data/runtime/llm_provider_health.json"
DEFAULT_WINDOW_HOURS = 3.0
# One page per lane per cause per 6h. A billing stop lasts until the operator acts, and
# repeating it every cron tick trains them to ignore it.
DEDUPE_SECONDS = int(os.environ.get("PROVIDER_HEALTH_DEDUPE_SEC", str(6 * 3600)))
BALANCE_URL = "https://api.deepseek.com/user/balance"


def _rows(hours: float) -> list[dict]:
    from db_adapter import _execute

    sql = """
        SELECT model_name, model_lane, process_id, success, error_message, created_at
        FROM llm_consumption_log
        WHERE created_at > NOW() - (%s || ' hours')::interval
    """
    out = _execute(sql, (str(hours),), fetch="all") or []
    rows = []
    for r in out:
        if isinstance(r, dict):
            rows.append(r)
        else:  # tuple cursor
            rows.append({
                "model_name": r[0], "model_lane": r[1], "process_id": r[2],
                "success": r[3], "error_message": r[4], "created_at": r[5],
            })
    return rows


def _deepseek_balance() -> dict | None:
    """Best-effort balance read. Never logs or returns the key.

    Uses the canonical resolver rather than reading os.environ directly, and loads the
    tmpfs/disk env first: under cron nothing else in this process needs a provider key,
    so without that the probe would silently return None on exactly the day it matters.
    """
    key = None
    try:
        from lib.env_bootstrap import load_env
        load_env()
        from lib.llm_model_registry import get_deepseek_api_key
        key, _env_name, _alias = get_deepseek_api_key()
    except Exception:
        key = os.environ.get("deepseek_tradeai") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None
    req = urllib.request.Request(BALANCE_URL, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    infos = data.get("balance_infos") or []
    usd = next((i for i in infos if str(i.get("currency", "")).upper() == "USD"), None)
    return {
        "is_available": data.get("is_available"),
        "total_balance": (usd or {}).get("total_balance"),
    }


def _write_heartbeat(payload: dict) -> None:
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(json.dumps(payload, indent=2))
    except OSError as e:
        print(f"[provider-health] could not write heartbeat: {e}", file=sys.stderr)


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2))
    except OSError as e:
        print(f"[provider-health] could not persist dedupe state: {e}", file=sys.stderr)


def _fresh(findings: list, state: dict, now: float) -> list:
    """Drop findings already alerted inside the dedupe window."""
    out = []
    for f in findings:
        last = float(state.get(f"{f.lane}:{f.kind}", 0) or 0)
        if now - last >= DEDUPE_SECONDS:
            out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=DEFAULT_WINDOW_HOURS)
    ap.add_argument("--min-calls", type=int, default=5)
    ap.add_argument("--fail-rate", type=float, default=0.9)
    ap.add_argument("--dry-run", action="store_true", help="print, never send, never mark")
    ap.add_argument("--strict", action="store_true", help="exit 1 on a CRITICAL finding")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        rows = _rows(args.hours)
    except Exception as e:  # DB down is its own alarm elsewhere; do not mask it as healthy
        print(f"[provider-health] ledger query failed: {e}", file=sys.stderr)
        return 2

    findings = evaluate(rows, min_calls=args.min_calls, fail_rate=args.fail_rate)
    # A lane that failed earlier in the window but is answering again is reported
    # everywhere below and paged nowhere: the operator already fixed it.
    live = pageable(findings)
    balance = _deepseek_balance() if any(
        f.kind == "BILLING" or "deepseek" in f.lane.lower() for f in findings
    ) else None

    if args.json:
        print(json.dumps({
            "window_hours": args.hours,
            "calls_examined": len(rows),
            "balance": balance,
            "findings": [
                {"lane": f.lane, "kind": f.kind, "severity": f.severity, "calls": f.calls,
                 "failures": f.failures, "fail_rate": round(f.fail_rate, 4),
                 "processes": f.processes, "sample_error": f.sample_error,
                 "recovered": f.recovered}
                for f in findings
            ],
        }, indent=2))
    else:
        print(f"[provider-health] {len(rows)} calls in the last {args.hours:g}h, "
              f"{len(findings)} finding(s)")
        for f in findings:
            note = "  [recovered — not paged]" if f.recovered else ""
            print(f"  {f.severity:<8} {f.lane}: {f.failures}/{f.calls} failed "
                  f"({f.fail_rate:.0%}) — {f.kind}{note}")

    critical = any(f.severity == "CRITICAL" for f in live)
    if not args.dry_run:
        _write_heartbeat({
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "window_hours": args.hours,
            "calls_examined": len(rows),
            "worst_severity": ("CRITICAL" if critical else
                               "WARN" if live else "OK"),
            "balance": balance,
            "findings": [
                {"lane": f.lane, "kind": f.kind, "severity": f.severity,
                 "calls": f.calls, "failures": f.failures, "recovered": f.recovered}
                for f in findings
            ],
        })
    if live and not args.dry_run:
        now = time.time()
        state = _load_state()
        fresh = _fresh(live, state, now)
        if fresh:
            message = format_alert(fresh, window_hours=args.hours, balance=balance)
            try:
                from telegram_alert import send_telegram
                sent = send_telegram(message)
            except Exception as e:
                print(f"[provider-health] alert send failed: {e}", file=sys.stderr)
                sent = False
            if sent:
                for f in fresh:
                    state[f"{f.lane}:{f.kind}"] = now
                _save_state(state)
                print(f"[provider-health] alerted on {len(fresh)} lane(s)")
        else:
            print("[provider-health] findings suppressed by dedupe window")

    return 1 if (critical and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
