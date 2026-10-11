#!/usr/bin/env python3
"""heartbeat_watch.py — host lane ``heartbeat-watch``: a dead-man for the health plane itself (design 02 §7, phase 1).

Fired every 5 minutes by n8n (``tradeai-heartbeat-watcher`` and ``tradeai-dispatcher`` through relay ``POST /run`` and
the executor). It checks that the six lanes that make up the alert path are still producing. Each lane's
``output_signal`` (``lane_registry.observe_signal``, read under the persistent state root) is checked against
2 x its cadence:

    supervisor-breach-detector  n8n-incident-fanin  incident-notifier
    n8n-siem-bridge             health-tick         n8n-lab-watchdog

Verdicts per lane:

* ``FRESH``: output since the last due slot.
* ``LATE``: past 1x, not past 2x. Recorded, no breach.
* ``STALE``: past the 2x deadline, or no output at all → Breach@v1 ``kind STALE_2X``, ``state OPEN``.
* ``EXPECTED_SILENT``: row not ACTIVE, or today (America/New_York) is not one of the row's ``active_days``.
* ``UNVERIFIABLE``: no signal, or it cannot be read.

How the deadline is computed:

* cron rows: the latest scheduled fire at or before ``now - max_run_s - (factor - 1) x period``. A weekday-only line
  is therefore judged against Friday's last fire on a Sunday, not against a 2x window.
* every other row: ``factor x expected_cadence_hours``.

Detect and record only; it sends nothing (AGENTS.md §24.1). STALE rows are appended to the existing breach ledger
``data/runtime/supervisor_breaches.jsonl``, which the incident fan-in reads (``STALE_2X`` is P1 there) and the
incident notifier sends from:

* one ``OPEN`` row when a lane turns STALE, re-emitted after 24 h so it stays inside the fan-in's 48 h window;
* one ``CLEARED`` row when it is FRESH again, which closes the fan-in incident.

Each row is a single ``O_APPEND`` write, so it cannot interleave with the breach detector's own appends.

The lane receipt is ``data/runtime/heartbeat-watch_last.json`` (LaneRunReceipt@v1). ``ok_at`` advances only when the
check completed and every write landed.

``--dry-run`` reads the registry and the six signals, prints what a live run would write (``dry_run_report``) and
writes nothing: no breach row, no receipt.

Exit: 0 = the check completed (STALE lanes are findings, not a failed run); 1 = the registry is unreadable, a
watch-set lane has no registry row, or a write failed; 2 = usage.

MBI_BEHAVIOR = 0: no broker, no send, no DB, no network, no subprocess. Authority: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

PROJ = Path(__file__).resolve().parents[1]
# scripts.lib.X only (one import identity; scripts/lib/__init__.py DualImportIdentityError). The libs' own bare
# fallbacks resolve through scripts/ and scripts/lib, appended after the root.
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))
for _p in (str(PROJ / "scripts"), str(PROJ / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.append(_p)

LANE_ID = "heartbeat-watch"
#: Phase 1 watch set: the alert path. Phase 2 (design 02 §7 --factor-from-registry) widens this to every ACTIVE row.
WATCH_SET = (
    "supervisor-breach-detector",
    "n8n-incident-fanin",
    "incident-notifier",
    "n8n-siem-bridge",
    "health-tick",
    "n8n-lab-watchdog",
)
FACTOR = 2.0
DEFAULT_MAX_RUN_S = 300.0
REEMIT_AFTER = timedelta(hours=24)          # the fan-in reads breach rows of the last 48 h
BREACH_KIND = "STALE_2X"
BREACH_SCHEMA = "Breach@v1"
LEDGER_REL = "data/runtime/supervisor_breaches.jsonl"
TAIL_BYTES = 2_000_000
TZ = ZoneInfo("America/New_York")

FRESH, LATE, STALE, SILENT_OK, UNVERIFIABLE = "FRESH", "LATE", "STALE", "EXPECTED_SILENT", "UNVERIFIABLE"


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _last_fire(schedules: Iterable[str], ref: datetime) -> Optional[datetime]:
    """Latest fire at or before ``ref`` over every schedule (America/New_York, DST-safe), or None."""
    from scripts.lib.cron_schedule import last_fire_at_or_before

    best: Optional[datetime] = None
    for fields in schedules:
        if fields == "@reboot":
            continue
        try:
            f = last_fire_at_or_before(fields, ref, "America/New_York", lookback_days=400)
        except Exception:  # noqa: BLE001 — an unreadable schedule falls back to the cadence rule
            continue
        if f is not None:
            at = f.at.astimezone(timezone.utc)
            best = at if best is None or at > best else best
    return best


def classify(row: Mapping[str, Any], observed: Mapping[str, Any], now: datetime, *,
             factor: float = FACTOR) -> dict[str, Any]:
    """Pure verdict for one registry row and its observed signal ({last_output_at, readable, detail})."""
    lane = str(row.get("lane_id"))
    out: dict[str, Any] = {"lane_id": lane, "state": row.get("state"), "verdict": None, "basis": None,
                           "last_output_at": None, "due_since": None, "expected_by": None}
    if row.get("state") != "ACTIVE":
        out.update(verdict=SILENT_OK, basis=f"registry_state:{row.get('state')}")
        return out
    days = row.get("active_days")
    if isinstance(days, (list, tuple)) and days and now.astimezone(TZ).weekday() not in days:
        out.update(verdict=SILENT_OK, basis="inactive_day:America/New_York")
        return out
    sig = row.get("output_signal") or {}
    if str(sig.get("kind") or "none") == "none":
        out.update(verdict=UNVERIFIABLE, basis="output_signal.kind none")
        return out
    if observed.get("readable") is False:
        out.update(verdict=UNVERIFIABLE, basis=f"unreadable: {str(observed.get('detail') or '')[:120]}")
        return out
    last = _parse(observed.get("last_output_at"))
    out["last_output_at"] = last.isoformat() if last else None
    cad_h = row.get("expected_cadence_hours")
    if not cad_h:
        out.update(verdict=UNVERIFIABLE, basis="no expected_cadence_hours")
        return out
    period = timedelta(hours=float(cad_h))
    max_run = timedelta(seconds=float((row.get("watch") or {}).get("max_run_s") or DEFAULT_MAX_RUN_S))
    sched = row.get("scheduler") or {}
    due_since = expected_by = None
    if sched.get("kind") == "cron":
        from scripts.lib.cron_schedule import cron_schedules

        expr = sched.get("expression") or ""
        due = sched.get("due_schedules")
        if isinstance(due, list) and due and all(isinstance(x, str) and x.strip() for x in due):
            expr = " + ".join(x.strip() for x in due)
        schedules = cron_schedules(str(expr))
        due_since = _last_fire(schedules, now - max_run)
        expected_by = _last_fire(schedules, now - max_run - (factor - 1) * period)
        if due_since is not None and expected_by is not None:
            out["basis"] = f"cron:{' + '.join(schedules)} x{factor:g}"
    if out["basis"] is None:
        due_since, expected_by = now - period, now - factor * period
        out["basis"] = f"cadence:{float(cad_h):g}h x{factor:g}"
    out["due_since"], out["expected_by"] = due_since.isoformat(), expected_by.isoformat()
    if last is None:
        out["verdict"] = STALE
        out["basis"] += " (no output)"
    elif last >= due_since:
        out["verdict"] = FRESH
    elif last >= expected_by:
        out["verdict"] = LATE
    else:
        out["verdict"] = STALE
    return out


def _breach_id(lane: str, state: str, at: datetime) -> str:
    return "br_" + hashlib.sha256(f"{lane}|{BREACH_KIND}|{state}|{at.isoformat()}".encode()).hexdigest()[:16]


def last_own_rows(ledger_rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """This lane's latest breach row per watched lane (append order = time order)."""
    latest: dict[str, Mapping[str, Any]] = {}
    for r in ledger_rows:
        if r.get("kind") == BREACH_KIND and (r.get("evidence") or {}).get("watcher") == LANE_ID:
            latest[str(r.get("lane_id"))] = r
    return latest


def plan_rows(verdicts: Iterable[Mapping[str, Any]], latest: Mapping[str, Mapping[str, Any]],
              now: datetime) -> list[dict[str, Any]]:
    """Breach rows to append: OPEN on a new or 24 h-old STALE, CLEARED when an OPEN lane is FRESH again."""
    rows: list[dict[str, Any]] = []
    for v in verdicts:
        lane = str(v["lane_id"])
        prev = latest.get(lane)
        prev_open = prev is not None and prev.get("state") == "OPEN"
        prev_at = _parse(prev.get("detected_at")) if prev else None
        if v["verdict"] == STALE:
            if prev_open and prev_at is not None and now - prev_at < REEMIT_AFTER:
                continue
            state, level = "OPEN", 2
        elif v["verdict"] == FRESH and prev_open:
            state, level = "CLEARED", 1
        else:
            continue
        rows.append({
            "schema": BREACH_SCHEMA, "breach_id": _breach_id(lane, state, now), "lane_id": lane, "silo_id": None,
            "kind": BREACH_KIND, "state": state, "detected_at": now.isoformat(), "level": level, "recovery": [],
            "authority": "READ_ONLY_ADVISORY",
            "evidence": {"watcher": LANE_ID, "verdict": v["verdict"], "last_output_at": v.get("last_output_at"),
                         "expected_by": v.get("expected_by"), "basis": v.get("basis"),
                         "clears": prev.get("breach_id") if state == "CLEARED" and prev else None},
        })
    return rows


def _tail_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            chunk = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for ln in chunk.splitlines()[1 if size > TAIL_BYTES else 0:]:
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """One O_APPEND write per row, so a concurrent detector append cannot split a line."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        for r in rows:
            os.write(fd, (json.dumps(r, sort_keys=True, default=str) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def run(*, registry_path: Path, state_root: Path, now: datetime, dry_run: bool,
        observe: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        receipt: Optional[Path] = None) -> int:
    from scripts.lib import lane_last_receipt as R
    from scripts.lib import lane_registry as LR

    receipt = receipt or (state_root / "data" / "runtime" / f"{LANE_ID}_last.json")
    ledger = state_root / LEDGER_REL
    observe = observe or (lambda sig: LR.observe_signal(dict(sig), root=state_root))
    try:
        reg = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        rows = {str(r.get("lane_id")): r for r in reg.get("lanes") or []}
    except (OSError, ValueError) as exc:
        return _finish(R, dry_run, receipt, ok=False, summary={"error": f"{type(exc).__name__}: registry"},
                       would=[], now=now)
    missing = [lid for lid in WATCH_SET if lid not in rows]
    verdicts = []
    for lid in WATCH_SET:
        if lid in rows:
            row = rows[lid]
            verdicts.append(classify(row, observe(row.get("output_signal") or {}) or {}, now))
    planned = plan_rows(verdicts, last_own_rows(_tail_jsonl(ledger)), now)
    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    summary = {"as_of": now.isoformat(), "factor": FACTOR, "watch_set": list(WATCH_SET), "counts": counts,
               "stale": [v["lane_id"] for v in verdicts if v["verdict"] == STALE],
               "late": [v["lane_id"] for v in verdicts if v["verdict"] == LATE],
               "missing_rows": missing, "breach_rows": [f"{r['lane_id']}:{r['state']}" for r in planned],
               "verdicts": verdicts}
    for v in verdicts:
        print(f"  {v['verdict']:<16} {v['lane_id']:<28} last={v['last_output_at']} expected_by={v['expected_by']} "
              f"[{v['basis']}]")
    if missing:
        print(f"missing registry rows: {missing}", file=sys.stderr)
    if dry_run:
        return _finish(R, True, receipt, ok=not missing, summary=summary,
                       would=[f"{LEDGER_REL} +{len(planned)} rows"] if planned else [], now=now)
    try:
        append_rows(ledger, planned)
    except OSError as exc:
        summary["error"] = f"{type(exc).__name__}: breach ledger"
        return _finish(R, False, receipt, ok=False, summary=summary, would=[], now=now)
    summary["rows_written"] = len(planned)
    return _finish(R, False, receipt, ok=not missing, summary=summary, would=[], now=now)


def _finish(R: Any, dry_run: bool, receipt: Path, *, ok: bool, summary: dict[str, Any], would: list[str],
            now: datetime) -> int:
    if dry_run:
        R.dry_run_report(LANE_ID, {k: v for k, v in summary.items() if k != "verdicts"}, would_write=would,
                         receipt=receipt)
        return 0 if ok else 1
    written = R.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=now,
                                   script="scripts/heartbeat_watch.py", summary=summary, path=receipt)
    if written is None:
        return 1
    return 0 if ok else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="read and print only; writes nothing")
    ap.add_argument("--root", default=str(PROJ), help="code root holding config/lane_registry.json")
    ap.add_argument("--state-root", help="persistent-state root (default: TRADEAI_STATE_ROOT, else the resolver)")
    ap.add_argument("--now", help=argparse.SUPPRESS)          # tests: pin the clock (ISO 8601, aware)
    a = ap.parse_args(argv)
    if a.state_root:
        state_root = Path(a.state_root)
    else:
        from scripts.lib import lane_last_receipt as R

        state_root = R.runtime_dir().parent.parent
    now = _parse(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        print("--now is not an ISO timestamp", file=sys.stderr)
        return 2
    return run(registry_path=Path(a.root) / "config" / "lane_registry.json", state_root=state_root, now=now,
               dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
