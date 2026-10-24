#!/usr/bin/env python3
"""Independent wrapper/missed-run monitor. Default is read-only; --run is operator-installed.

No cron/systemd commands, producer imports, DB connections or provider calls.
Only --send-alerts calls the existing host Telegram chokepoint. Never repairs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.lib.cron_outage_watchdog import evaluate, identity, instant, iso  # noqa: E402

LATEST = "data/runtime/cron_outage_watchdog_latest.json"
STATE = "data/runtime/cron_outage_watchdog_state.json"


def bind_components(registry: dict, cfg: dict) -> dict:
    """Reader-only binding to a captured wrapper component, pinned to registry intent.

    Most cron registry expressions contain only five schedule fields. Matching a
    Python filename heuristically could attach one stage's success to unrelated
    lanes, so only explicit exact-source bindings are used.
    """
    rows = []
    for row in registry.get("lanes", []):
        item = dict(row)
        scheduler = row.get("scheduler") or {}
        binding = (cfg.get("wrapper_bindings") or {}).get(identity(row)) or {}
        if (binding.get("scheduler_match") == scheduler.get("match")
                and binding.get("expression") == scheduler.get("expression")
                and isinstance(binding.get("component"), str)):
            item["watchdog_wrapper_component"] = binding["component"]
        rows.append(item)
    return {**registry, "lanes": rows}


def read_json(path: Path, max_bytes=2 * 1024 * 1024) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("oversized observation")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("observation is not an object")
    return result


def collect(registry: dict, state_root: Path) -> dict:
    """Read only declared nonsecret data/log artifacts. Mtime is never collected as success."""
    events, successes, errors = [], {}, []
    journal = state_root / "logs/safe_flock_events.jsonl"
    try:
        st = journal.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid():
            raise OSError("unsafe journal; do not follow arbitrary targets")
        with journal.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            start = max(0, size - 8 * 1024 * 1024)
            stream.seek(start)
            raw = stream.read(8 * 1024 * 1024)
        offset = start
        for line in raw.splitlines(keepends=True):
            if offset == start and start:
                offset += len(line)
                continue
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    event["capture_key"] = hashlib.sha256(line).hexdigest()
                    events.append(event)
            except ValueError:
                errors.append("journal_malformed_line")
            offset += len(line)
        if start:
            errors.append("journal_history_window_truncated")
    except OSError:
        errors.append("journal_unavailable")
    base = state_root.resolve()
    for lane in registry.get("lanes", []):
        signal = lane.get("output_signal") or {}
        key = signal.get("key")
        if signal.get("kind") == "file_mtime" and str(signal.get("path") or "").endswith(".log"):
            # The journal itself can be refused/immutable. An explicit UTC
            # refusal on the wrapper's original stderr is still an observation;
            # an arbitrary old error line or this file's mtime is not.
            fallback = (base / str(signal["path"])).resolve()
            if fallback.is_relative_to(base / "logs"):
                try:
                    with fallback.open("rb") as stream:
                        stream.seek(0, os.SEEK_END)
                        size = stream.tell()
                        start = max(0, size - 64 * 1024)
                        stream.seek(start)
                        tail = stream.read(64 * 1024)
                    for index, line in enumerate(tail.splitlines()):
                        if start and index == 0:
                            continue
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if (isinstance(event, dict) and event.get("journal_fallback") == "stderr"
                                and event.get("event_type") == "refused" and instant(event.get("ts"))):
                            events.append(event)
                except OSError:
                    errors.append(f"{identity(lane)}:fallback_log_unavailable")
        if signal.get("kind") != "json_key" or key not in {"ok_at", "last_success_at", "finished_at"}:
            continue
        path = (base / str(signal.get("path") or "")).resolve()
        if not path.is_relative_to(base / "data") and not path.is_relative_to(base / "logs"):
            errors.append(f"{identity(lane)}:receipt_path_not_admitted")
            continue
        try:
            receipt = read_json(path)
        except (OSError, ValueError):
            errors.append(f"{identity(lane)}:receipt_unavailable")
            continue
        if receipt.get("dry_run") is True or receipt.get("mode") in {"dry_run", "dry-run", "shadow", "preflight"}:
            continue
        if key == "finished_at" and not (receipt.get("state") == "RUN_DONE" and receipt.get("exit_code") == 0):
            continue
        at = instant(receipt.get(key))
        if at:
            successes[identity(lane)] = [{"at": iso(at), "validated_success": True, "source": key}]
    return {"events": events, "successes": successes, "collection_gaps": sorted(set(errors))}


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with tmp.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def monitor_findings(report: dict, snapshot: dict) -> dict:
    """Input blindness is its own incident, never a fabricated missed-run count."""
    report["collection_gaps"] = snapshot.get("collection_gaps") or []
    report["monitor_incidents"] = []
    if "journal_unavailable" in report["collection_gaps"]:
        report["monitor_incidents"].append({"id": "wrapper_journal_unavailable", "kind": "MONITOR_BLINDNESS",
            "reason": "wrapper success/refusal stream unreadable; missing fires NOT_MEASURED",
            "observed_at": report["observed_at"]})
        report["alert_required"] = True
        report["status"] = "CRIT"
    elif report["collection_gaps"] and report["status"] == "OK":
        report["status"] = "UNKNOWN"
    return report


def deliver(report: dict, prior: dict, *, sender, now: datetime, reminder_seconds=1800) -> tuple[dict, dict]:
    """Receipt actual delivery; failed/queued is never promoted to delivered.

    Alert fingerprint uses named findings, not a volatile poll timestamp. New
    refusals bypass reminder suppression. Delivery failure remains retryable.
    """
    seen = set(prior.get("delivered_refusal_keys") or [])
    new_refusals = [x for x in report["refusals"] if not x["key"] or x["key"] not in seen]
    active_monitor = sorted(x["id"] for x in report.get("monitor_incidents") or [])
    previous_monitor = prior.get("active_monitor_incidents") or []
    recovery = not active_monitor and bool(previous_monitor or prior.get("pending_monitor_recovery"))
    key = hashlib.sha256(json.dumps({"missed": report["missed_lane_ids"], "monitor": active_monitor}, sort_keys=True).encode()).hexdigest()
    last = instant(prior.get("last_delivered_at"))
    overdue = last is None or (now - last).total_seconds() >= reminder_seconds
    required = bool(new_refusals or recovery or ((report["missed_lane_ids"] or active_monitor)
                                                and (key != prior.get("finding_key") or overdue)))
    state = dict(prior)
    state["active_monitor_incidents"] = active_monitor
    if recovery:
        state["pending_monitor_recovery"] = previous_monitor or prior.get("pending_monitor_recovery")
    if not required:
        if not report["missed_lane_ids"] and not active_monitor:
            state["finding_key"] = None
        return {"status": "NOT_REQUIRED", "delivered": False}, state
    body = (("CRON WRAPPER WATCHDOG · MONITOR COVERAGE RESTORED\n" if recovery else "CRON WRAPPER WATCHDOG · action required\n")
            + "Monitor incident: " + (", ".join(active_monitor) or "none active")
            + "\nProven >=2 scheduled misses: " + (", ".join(report["missed_lane_ids"]) or "none proven; uncovered history remains NOT_MEASURED")
            + "\nWrapper refusals: " + (", ".join(str(x["job_id"]) + ":" + str(x["reason"]) for x in new_refusals) or "none")
            + f"\nCoverage gaps: {len(report['coverage_gap_lane_ids'])}; observation {report['observed_at']}"
            + "\nInspect wrapper paths and release layout; this monitor runs no repairs.")
    try:
        outcome = sender(body)
    except Exception:
        outcome = {"status": "FAILED", "accepted": False, "delivered": False}
    if not isinstance(outcome, dict):
        outcome = {"status": "UNCONFIRMED", "accepted": bool(outcome), "delivered": False}
    result = {k: outcome.get(k) for k in ["status", "accepted", "delivered"]}
    result["kind"] = "MONITOR_RECOVERED" if recovery else "WATCHDOG_FINDING"
    if result["delivered"] is True:
        state.update(delivered_refusal_keys=sorted(seen | {x["key"] for x in new_refusals if x["key"]}),
                     last_delivered_at=iso(now), finding_key=key)
        state.pop("pending_monitor_recovery", None)
    return result, state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "config/lane_registry.json")
    parser.add_argument("--config", type=Path, default=ROOT / "config/cron_outage_watchdog.json")
    parser.add_argument("--state-root", type=Path, default=Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases/persistent-state"))
    parser.add_argument("--snapshot", type=Path, help="captured events/successes only; never collect host inputs")
    parser.add_argument("--at", help="aware historical clock; default current UTC")
    parser.add_argument("--run", action="store_true", help="write operational state; operator installation only")
    parser.add_argument("--dry-run", action="store_true", help="explicit read-only default")
    parser.add_argument("--send-alerts", action="store_true", help="host P1 chokepoint; requires --run")
    args = parser.parse_args()
    if args.send_alerts and not args.run:
        parser.error("--send-alerts requires --run")
    if args.dry_run and args.run:
        parser.error("--run and --dry-run are mutually exclusive")
    if args.at and args.run:
        parser.error("historical clock cannot publish current health or send")
    now = instant(args.at) if args.at else datetime.now(timezone.utc)
    if now is None:
        parser.error("--at requires an explicit timezone")
    cfg = read_json(args.config)
    if args.run and (cfg.get("enabled") is not True or cfg.get("review_status") != "REVIEWED"
                     or not isinstance(cfg.get("approved_by"), str) or not cfg["approved_by"].strip()):
        print(json.dumps({"status": "PENDING_OPERATOR_REVIEW", "reason": "watchdog admission disabled; no write or send"}))
        return 78
    registry = bind_components(read_json(args.registry, 8 * 1024 * 1024), cfg)
    snapshot = read_json(args.snapshot, 16 * 1024 * 1024) if args.snapshot else collect(registry, args.state_root)
    from scripts.market_session import is_trading_day
    prior = {}
    if args.run:
        try:
            prior = read_json(args.state_root / STATE)
        except (OSError, ValueError):
            prior = {}
    report = evaluate(registry, snapshot.get("events") or [], snapshot.get("successes") or {}, now=now,
                      grace_seconds=int(cfg.get("grace_seconds", 120)),
                      previous_refusal_keys=set(prior.get("delivered_refusal_keys") or []), trading_day=is_trading_day)
    report["mode"] = "monitor" if args.run else "dry_run"
    report = monitor_findings(report, snapshot)
    report["notification"] = {"status": "NOT_REQUESTED", "delivered": False}
    if args.send_alerts:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram_outcome
        report["notification"], prior = deliver(report, prior, now=now, reminder_seconds=int(cfg.get("reminder_seconds", 1800)), sender=lambda body: send_telegram_outcome(
            body, priority="P1", dedupe_minutes=0, producer="cron_outage_watchdog", message_class="operator_alert"))
        if (report["notification"].get("status") not in {"NOT_REQUESTED", "NOT_REQUIRED"}
                and report["notification"].get("delivered") is not True):
            report["status"] = "CRIT"
            report["alert_delivery_status"] = "FAILED_OR_UNCONFIRMED"
    if args.run:
        atomic_json(args.state_root / STATE, prior)
        atomic_json(args.state_root / LATEST, report)
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "CRIT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
