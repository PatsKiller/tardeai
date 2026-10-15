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
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.provider_health import (  # noqa: E402
    STALL_CRITICAL,
    evaluate,
    evaluate_stalls,
    format_alert,
    format_stall_alert,
    pageable,
    stall_policy,
)

STATE_PATH = PROJECT_ROOT / "data/runtime/llm_provider_health_alert.json"
# Stall thresholds and alert priorities (2026-10-15). The routing policy says which lanes each process may use,
# which decides digest (another lane open) versus page (no lane left).
CONFIG_PATH = PROJECT_ROOT / "config/llm_provider_health.json"
ROUTING_POLICY_PATH = PROJECT_ROOT / "config/llm_routing_policy.json"
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
            rows.append(
                {
                    "model_name": r[0],
                    "model_lane": r[1],
                    "process_id": r[2],
                    "success": r[3],
                    "error_message": r[4],
                    "created_at": r[5],
                }
            )
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


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _routing_doc() -> dict:
    raw = os.environ.get("TRADEAI_LLM_ROUTING_POLICY")
    return _read_json(Path(raw) if raw else ROUTING_POLICY_PATH)


def _events_path() -> Path | None:
    """The provider_cost event ledger the emitters write. Under pytest, only an explicit env path is read,
    so a test never judges the host's live ledger."""
    raw = os.environ.get("PROVIDER_COST_EVENT_LOG")
    if raw:
        return Path(raw)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    from lib.provider_cost.emit import _dest

    return _dest()


def _provider_events(tail_bytes: int) -> list[dict]:
    """The newest `tail_bytes` of the ledger, parsed. The file is append-only and large (84 MB on 10-15), and
    the stall window is minutes wide, so only its tail is read; a torn first line is dropped."""
    path = _events_path()
    if path is None:
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - max(0, int(tail_bytes)))
            fh.seek(start)
            blob = fh.read()
    except OSError:
        return []
    lines = blob.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


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


def _record_delivery_failure(heartbeat: dict, reason: str, undelivered: list[str]) -> None:
    """The alarm failing to deliver is the one failure nobody else would notice.

    A dead provider lane and an undeliverable alert look identical from the outside:
    silence. So the delivery failure goes onto the heartbeat — the durable artifact
    `config/lane_registry.json` already watches for this lane — and not only into a
    cron log nobody reads. Re-written rather than appended: the next run's outcome is
    what matters, and a heartbeat that only grows is its own problem.
    """
    prior = heartbeat.get("alert_delivery") if isinstance(heartbeat.get("alert_delivery"), dict) else {}
    heartbeat["alert_delivery"] = {
        "ok": False,
        "reason": str(reason)[:300],
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        # Two alerts (lane findings, stall findings) can fail in one run; neither may hide the other.
        "undelivered": list(prior.get("undelivered") or []) + list(undelivered),
    }
    _write_heartbeat(heartbeat)
    print(f"[provider-health] ALERT UNDELIVERED ({reason}) — recorded to {HEARTBEAT_PATH.name}", file=sys.stderr)


def _deliver(message: str, priority: str, heartbeat: dict, labels: list[str]) -> bool:
    """The one transport call. True when accepted; a failure is recorded on the heartbeat, never only logged."""
    try:
        from telegram_alert import send_telegram

        sent = send_telegram(message, priority=priority, producer="check_llm_provider_health")
    except Exception as e:
        _record_delivery_failure(heartbeat, f"{type(e).__name__}: {e}", labels)
        return False
    if not sent:
        # send_telegram reports failure by return value as well as by raising.
        _record_delivery_failure(heartbeat, "send_telegram returned falsy", labels)
        return False
    return True


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
    balance = (
        _deepseek_balance() if any(f.kind == "BILLING" or "deepseek" in f.lane.lower() for f in findings) else None
    )

    # Stalls (2026-10-15): judged from the provider_cost event ledger over a short window, because the bridge's
    # failed attempts never reach llm_consumption_log and a 3 h aggregate hides a 30 minute outage.
    spol = stall_policy(_read_json(CONFIG_PATH))
    stalls = evaluate_stalls(
        _provider_events(int(spol["tail_bytes"])),
        now=datetime.now(timezone.utc),
        policy=spol,
        routing_doc=_routing_doc(),
    )
    live_stalls = [s for s in stalls if not s.recovered]
    stall_rows = [
        {
            "provider": s.provider,
            "severity": s.severity,
            "consecutive_stalls": s.consecutive_stalls,
            "window_minutes": s.window_minutes,
            "window_events": s.window_events,
            "window_stalls": s.window_stalls,
            "stall_rate": round(s.stall_rate, 4),
            "error_classes": s.error_classes,
            "processes": s.processes,
            "all_lanes_down_processes": s.all_lanes_down_processes,
            "last_stall_at": s.last_stall_at,
            "recovered": s.recovered,
        }
        for s in stalls
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "window_hours": args.hours,
                    "calls_examined": len(rows),
                    "balance": balance,
                    "findings": [
                        {
                            "lane": f.lane,
                            "kind": f.kind,
                            "severity": f.severity,
                            "calls": f.calls,
                            "failures": f.failures,
                            "fail_rate": round(f.fail_rate, 4),
                            "processes": f.processes,
                            "sample_error": f.sample_error,
                            "recovered": f.recovered,
                        }
                        for f in findings
                    ],
                    "stall_findings": stall_rows,
                },
                indent=2,
            )
        )
    else:
        print(
            f"[provider-health] {len(rows)} calls in the last {args.hours:g}h, "
            f"{len(findings)} finding(s), {len(stalls)} stall finding(s)"
        )
        for f in findings:
            note = "  [recovered — not paged]" if f.recovered else ""
            print(f"  {f.severity:<8} {f.lane}: {f.failures}/{f.calls} failed ({f.fail_rate:.0%}) — {f.kind}{note}")
        for s in stalls:
            note = "  [recovered — not paged]" if s.recovered else ""
            print(
                f"  {s.severity:<8} {s.provider}: {s.window_stalls}/{s.window_events} stalled in "
                f"{s.window_minutes:g} min, {s.consecutive_stalls} in a row{note}"
            )

    stall_critical = any(s.severity == STALL_CRITICAL for s in live_stalls)
    critical = any(f.severity == "CRITICAL" for f in live) or stall_critical
    heartbeat = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "window_hours": args.hours,
        "calls_examined": len(rows),
        # Stays in OK / WARN / CRITICAL: the bridge's routing selector reads this word.
        "worst_severity": ("CRITICAL" if critical else "WARN" if (live or live_stalls) else "OK"),
        "balance": balance,
        "findings": [
            {
                "lane": f.lane,
                "kind": f.kind,
                "severity": f.severity,
                "calls": f.calls,
                "failures": f.failures,
                "recovered": f.recovered,
            }
            for f in findings
        ],
        # Kept apart from `findings`, which the bridge's lane-health gate reads: a stall alerts, it does not
        # by itself re-route (the bridge's per-provider breaker does that from what it sees).
        "stall_findings": stall_rows,
        "stall_worst": ("CRITICAL" if stall_critical else "DEGRADED" if live_stalls else "OK"),
    }
    if not args.dry_run:
        _write_heartbeat(heartbeat)
    if live and not args.dry_run:
        now = time.time()
        state = _load_state()
        fresh = _fresh(live, state, now)
        if fresh:
            message = format_alert(fresh, window_hours=args.hours, balance=balance)
            if _deliver(message, "P2", heartbeat, [f"{f.lane}:{f.kind}" for f in fresh]):
                for f in fresh:
                    state[f"{f.lane}:{f.kind}"] = now
                _save_state(state)
                print(f"[provider-health] alerted on {len(fresh)} lane(s)")
        else:
            print("[provider-health] findings suppressed by dedupe window")
    if live_stalls and not args.dry_run:
        # A lane down while every caller still has another goes to the digest; a process with no lane left pages.
        now = time.time()
        state = _load_state()
        dedupe_s = float(spol["dedupe_minutes"]) * 60
        due = [s for s in live_stalls if now - float(state.get(f"stall:{s.provider}:{s.severity}", 0) or 0) >= dedupe_s]
        if due:
            priority = str(
                spol["priority_all_lanes_down"]
                if any(s.severity == STALL_CRITICAL for s in due)
                else spol["priority_degraded"]
            )
            labels = [f"stall:{s.provider}:{s.severity}" for s in due]
            if _deliver(format_stall_alert(due), priority, heartbeat, labels):
                for label in labels:
                    state[label] = now
                _save_state(state)
                print(f"[provider-health] stall alert ({priority}) on {len(due)} provider(s)")
        else:
            print("[provider-health] stall findings suppressed by dedupe window")

    return 1 if (critical and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
