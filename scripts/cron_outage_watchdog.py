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
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.lib.cron_outage_watchdog import (  # noqa: E402
    advisory_mode, evaluate, identity, instant, iso, job_key)

LATEST = "data/runtime/cron_outage_watchdog_latest.json"
STATE = "data/runtime/cron_outage_watchdog_state.json"
ACKS = "data/runtime/cron_outage_watchdog_refusal_acks.jsonl"
#: Written every 20 min by lane crontab-snapshot-for-health-agent; a file read, never `crontab -l`.
CRONTAB_SNAPSHOT = "data/runtime/crontab_snapshot.txt"
#: Code/config that names the locks of n8n-dispatched and nested (wrapper-script) jobs.
CENSUS_SOURCES = ("config/n8n_run_allowlist.json", "config/lane_registry.json", "config/pipelines/*.json",
                  "scripts/*.sh", "scripts/**/*.sh")
_LOCK_TOKEN = re.compile(r"([A-Za-z0-9_.\-]+)\.lock(?:\.dryrun)?(?![A-Za-z0-9_])")
_CRON_WRAPPER = re.compile(r"cron_wrapper\.sh\s+[\"']?([A-Za-z0-9_.\-]+)")


def job_census(texts: list[str]) -> set[str]:
    """Wrapper job ids a registered schedule can produce: lock basenames and cron_wrapper names."""
    out = set()
    for text in texts:
        out |= {job_key(m.group(1)) for m in _LOCK_TOKEN.finditer(text)}
        out |= {job_key(m.group(1)) for m in _CRON_WRAPPER.finditer(text)}
    return out


def registered_jobs(state_root: Path, root: Path = ROOT) -> tuple[set[str] | None, list[str]]:
    """Registered job ids from the crontab snapshot plus code-declared locks.

    Without a readable crontab snapshot the census is unknown (None): every refusal
    then stays attributed and alerting. Only uncommented crontab lines count.
    """
    gaps = []
    try:
        snapshot = read_text(state_root / CRONTAB_SNAPSHOT, 4 * 1024 * 1024)
    except (OSError, ValueError):
        return None, ["crontab_snapshot_unavailable"]
    try:
        if datetime.now(timezone.utc).timestamp() - (state_root / CRONTAB_SNAPSHOT).stat().st_mtime > 2 * 3600:
            gaps.append("crontab_snapshot_stale")
    except OSError:
        gaps.append("crontab_snapshot_stale")
    texts = ["\n".join(line for line in snapshot.splitlines() if line.strip() and not line.lstrip().startswith("#"))]
    for pattern in CENSUS_SOURCES:
        for path in sorted(root.glob(pattern)):
            try:
                texts.append(read_text(path, 16 * 1024 * 1024))
            except (OSError, ValueError):
                gaps.append("census_source_unreadable:" + str(path.relative_to(root)))
    return job_census(texts), gaps


def read_text(path: Path, max_bytes: int) -> str:
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("oversized observation")
    return raw.decode("utf-8", errors="replace")


def read_acks(state_root: Path) -> tuple[dict[str, dict], list[str]]:
    """Operator acknowledgements of stale refusals, keyed by refusal key (append-only JSONL)."""
    path = state_root / ACKS
    try:
        text = read_text(path, 2 * 1024 * 1024)
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError):
        return {}, ["refusal_acks_unreadable"]
    acks, gaps = {}, []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            gaps.append("refusal_acks_malformed_line")
            continue
        if (isinstance(row, dict) and isinstance(row.get("key"), str) and row["key"]
                and isinstance(row.get("acknowledged_by"), str) and row["acknowledged_by"].strip()
                and isinstance(row.get("reason"), str) and row["reason"].strip() and instant(row.get("acknowledged_at"))):
            acks[row["key"]] = row
        else:
            gaps.append("refusal_acks_malformed_line")
    return acks, sorted(set(gaps))


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
    #: Lanes whose own declaration says a live receipt cannot exist (dry run / shadow / preflight).
    #: Reported separately: an expected absence is coverage, never a monitor gap.
    expected_absent = []
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
        # Only ACTIVE lanes are evaluated; a paused/retired/never-scheduled lane's absent log or
        # receipt is expected, not monitor blindness (it was 30 of 46 collection gaps 2026-10-24).
        active = lane.get("state") == "ACTIVE"
        # A lane that declares a dry-run/shadow dispatch writes no live receipt by design.
        advisory = advisory_mode(lane)
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
                    if active:
                        errors.append(f"{identity(lane)}:fallback_log_unavailable")
        # A JSON receipt is read when declared (json_key) or when a file_mtime signal names a
        # .json receipt: its explicit success fields count, its mtime never does.
        json_receipt = signal.get("kind") == "json_key" or (
            signal.get("kind") == "file_mtime" and str(signal.get("path") or "").endswith(".json"))
        if not active or not json_receipt:
            continue
        declared = signal.get("kind") == "json_key"
        path = (base / str(signal.get("path") or "")).resolve()
        if not path.is_relative_to(base / "data") and not path.is_relative_to(base / "logs"):
            if declared:
                if advisory:
                    expected_absent.append({"lane_id": identity(lane), "mode": advisory})
                else:
                    errors.append(f"{identity(lane)}:receipt_path_not_admitted")
            continue
        try:
            receipt = read_json(path)
        except (OSError, ValueError):
            if declared:
                if advisory:
                    expected_absent.append({"lane_id": identity(lane), "mode": advisory})
                else:
                    errors.append(f"{identity(lane)}:receipt_unavailable")
            continue
        found = receipt_success(receipt, key if declared else None)
        if found:
            successes[identity(lane)] = [{"at": iso(found[0]), "validated_success": True, "source": found[1]}]
    jobs, census_gaps = registered_jobs(state_root)
    errors += census_gaps
    return {"events": events, "successes": successes, "collection_gaps": sorted(set(errors)),
            "expected_absent_receipts": expected_absent,
            "registered_job_ids": sorted(jobs) if jobs is not None else None}


#: Receipt times that are only success with an explicit `ok: true` beside them.
OK_FLAG_TIME_KEYS = ("ended_at", "completed_at", "as_of")


def receipt_success(receipt: dict, key: str | None) -> tuple[datetime, str] | None:
    """(time, source) when a receipt itself says its run succeeded; never a file timestamp.

    ok_at / last_success_at are success by name; finished_at needs RUN_DONE + exit 0 or
    ok:true; any other declared key (or, for an undeclared .json receipt, ended_at /
    completed_at / as_of) needs an explicit boolean `ok: true` in the same receipt.
    """
    if receipt.get("dry_run") is True or receipt.get("mode") in {"dry_run", "dry-run", "shadow", "preflight"}:
        return None
    keys = [key] if key else ["ok_at", "last_success_at", "finished_at", *OK_FLAG_TIME_KEYS]
    for name in keys:
        at = instant(receipt.get(name))
        if at is None:
            continue
        if name in {"ok_at", "last_success_at"}:
            return at, name
        if name == "finished_at" and receipt.get("state") == "RUN_DONE" and receipt.get("exit_code") == 0:
            return at, name
        if receipt.get("ok") is True:
            return at, name + "+ok"
    return None


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
    parser.add_argument("--ack-refusal", metavar="KEY", help="acknowledge one stale refusal by its key (operator); "
                        "previews the ack record unless --apply-ack")
    parser.add_argument("--ack-by", help="who acknowledges (required with --ack-refusal)")
    parser.add_argument("--ack-reason", help="why the refusal is stale (required with --ack-refusal)")
    parser.add_argument("--apply-ack", action="store_true", help="append the ack record to " + ACKS)
    args = parser.parse_args()
    if args.ack_refusal:
        return acknowledge(args)
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
    acks, ack_gaps = read_acks(args.state_root)
    census = snapshot.get("registered_job_ids")
    report = evaluate(registry, snapshot.get("events") or [], snapshot.get("successes") or {}, now=now,
                      grace_seconds=int(cfg.get("grace_seconds", 120)),
                      previous_refusal_keys=set(prior.get("delivered_refusal_keys") or []), trading_day=is_trading_day,
                      registered_jobs=set(census) if isinstance(census, list) else None, acknowledged=acks)
    report["mode"] = "monitor" if args.run else "dry_run"
    snapshot = {**snapshot, "collection_gaps": sorted(set((snapshot.get("collection_gaps") or []) + ack_gaps))}
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


def acknowledge(args) -> int:
    """Operator acknowledgement of one stale refusal: preview by default, append-only with --apply-ack.

    Only a refusal key present in the current journal observation can be acknowledged; the
    journal itself is never edited. An ack silences that one refusal event, not its job.
    """
    if not (args.ack_by and args.ack_by.strip() and args.ack_reason and args.ack_reason.strip()):
        print(json.dumps({"ok": False, "reason": "ack_requires_by_and_reason"}))
        return 2
    if args.run or args.send_alerts or args.snapshot or args.at:
        print(json.dumps({"ok": False, "reason": "ack_is_its_own_mode"}))
        return 2
    registry = read_json(args.registry, 8 * 1024 * 1024)
    events = collect(registry, args.state_root)["events"]
    match = [e for e in events if e.get("event_type") == "refused"
             and args.ack_refusal in {str(e.get("event_id") or ""), str(e.get("capture_key") or "")}]
    if not match:
        print(json.dumps({"ok": False, "reason": "refusal_key_not_in_current_journal_window", "key": args.ack_refusal}))
        return 1
    event = match[0]
    record = {"key": args.ack_refusal, "job_id": event.get("job_id") or event.get("component"),
              "refusal_at": event.get("ts"), "reason": args.ack_reason.strip(), "acknowledged_by": args.ack_by.strip(),
              "acknowledged_at": iso(datetime.now(timezone.utc))}
    if not args.apply_ack:
        print(json.dumps({"ok": True, "mode": "preview", "would_append": str(args.state_root / ACKS), "record": record}))
        return 0
    path = args.state_root / ACKS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"ok": True, "mode": "applied", "appended": str(path), "record": record}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
