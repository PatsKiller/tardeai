"""Stuck-work detection and the safe deterministic heals — the pure core (no I/O, no subprocess, no sends).

Operator 2026-10-31 (verbatim): "validate all stuck agents and processes fix montior and make auto healings with
claude code". Born from the 2026-10-30 disk-full aftermath: the CIO wake pipeline self-deadlocked for 31 hours on a
half-written JSONL tail, ``tradeai-cio-reactive`` sat "activating" forever, zero-byte state files broke two units,
eight n8n breakers stayed open and the overnight LLM queue completed nothing — and no monitor said so.

``scripts/stuck_work_monitor.py`` collects raw facts (lslocks, ps, systemctl, files, read-only SQL, the n8n ledger
opened read-only, the lane registry) and hands them here. This module decides:

* ``StuckFinding@v1`` per item: class, item, since, evidence, severity, heal key;
* which findings may get a deterministic heal (AGENTS.md §28.14: only reruns, generated files, the disk re-pin and
  the stale-lock reconcile; here the reconcile siblings are a truncated-final-line JSONL repair and a zero-byte
  restore from the newest valid backup) — and the plan for it, never the act;
* which findings are code defects for the Claude Code fixer (``N8nCodeDefect@v1``, the contract
  ``scripts/self_heal_fixer.py`` consumes).

Never here: ending a process. §28.1 names the four automations that end a run; a stuck process gets a page and, when
it is a code defect, a fixer intake — the kill stays with ``process_reaper.py`` rules whose caps are measured.
MBI_BEHAVIOR = 0: nothing here touches a broker, an order, a stop or a size.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from typing import Any, Iterable, Mapping, Optional

SCHEMA_FINDING = "StuckFinding@v1"
SCHEMA_DEFECT = "N8nCodeDefect@v1"
DEFECT_CONSUMER = "claude_code_iterative_fix"

CLASSES = (
    "self_deadlock",
    "lock_wait",
    "process_stuck",
    "unit_activating",
    "unit_failed",
    "jsonl_truncated_tail",
    "zero_byte_state",
    "queue_stalled",
    "breaker_open",
    "heartbeat_stale",
    "lane_silent",
    "stale_release",
    "unit_no_timeout",
    "unit_overrun",
    "cpu_spin",
    "orphan_runaway",
    "deleted_open_space",
    "zombie",
    "breaker_no_probe",
    "poison_item",
    "registry_drift",
    "missed_window",
    "stuck_claim",
    "starved_consumer",
    "heal_loop",
    "resource_precursor",
    "verifier_blind",
    "stale_lock",
)
#: heal keys: what may follow a finding. "page" = alert only; "repair_tail" / "restore_backup" = deterministic heal;
#: "code" = Claude Code fixer intake; "reaper" = needs a measured process_reaper rule (never killed here);
#: "restart" = systemctl --user restart, only for a unit on the stale_release allowlist (never a broker/server unit);
#: "reconcile_lock" = archive a pid-file lock whose pid is dead and that nobody holds (§28.14 stale-lock reconcile).
HEAL_KEYS = ("page", "repair_tail", "restore_backup", "code", "reaper", "restart", "reconcile_lock")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _age_min(since: Optional[datetime], now: datetime) -> Optional[float]:
    if since is None:
        return None
    return max(0.0, (now - since).total_seconds() / 60.0)


def finding(
    cls: str,
    item: str,
    *,
    since: Optional[datetime],
    now: datetime,
    severity: str,
    heal: str,
    evidence: Mapping[str, Any],
    lane: Optional[str] = None,
) -> dict:
    if cls not in CLASSES:
        raise ValueError(f"unknown class {cls!r}")
    if heal not in HEAL_KEYS:
        raise ValueError(f"unknown heal key {heal!r}")
    return {
        "schema": SCHEMA_FINDING,
        "class": cls,
        "item": item,
        "lane": lane,
        "since": _iso(since) if since else None,
        "age_min": round(_age_min(since, now), 1) if since else None,
        "severity": severity,
        "heal": heal,
        "evidence": dict(evidence),
        "dedupe_key": f"{cls}|{item}",
    }


def lane_for(text: str, cfg: Mapping[str, Any]) -> Optional[dict]:
    """The configured lane mapping whose pattern matches a command line or lock path (first match wins)."""
    for row in cfg.get("code_lanes") or []:
        if re.search(str(row["match"]), text or ""):
            return dict(row)
    return None


# ---------------------------------------------------------------- locks and processes
def lock_findings(
    locks: Iterable[Mapping[str, Any]], procs: Mapping[int, Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime
) -> list[dict]:
    """A waiter is an lslocks row whose mode ends in ``*`` (or that names a blocker). False-positive guard: the
    waiting process must be in a kernel lock wait right now (wchan) and older than ``lock_wait_min``; a process that
    both holds and waits on the same path is a self-deadlock and a code defect."""
    c = cfg["locks"]
    ignore = [str(p) for p in c.get("ignore_path_globs") or []]
    holders: dict[str, set[int]] = {}
    waiters: dict[str, set[int]] = {}
    for row in locks or []:
        path, pid = str(row.get("path") or ""), int(row.get("pid") or 0)
        if not path or not pid or any(fnmatch(path, g) for g in ignore):
            continue
        waiting = str(row.get("mode") or "").endswith("*") or bool(row.get("blocker"))
        (waiters if waiting else holders).setdefault(path, set()).add(pid)
    out: list[dict] = []
    for path, wpids in sorted(waiters.items()):
        for pid in sorted(wpids):
            p = procs.get(pid) or {}
            if str(p.get("wchan") or "") not in set(c.get("lock_wait_wchans") or []):
                continue
            started = p.get("started")
            age = _age_min(started, now)
            if age is None or age < float(c["lock_wait_min"]):
                continue
            cmd = str(p.get("args") or "")
            ln = lane_for(cmd + " " + path, cfg) or {}
            self_dead = pid in holders.get(path, set())
            cls = "self_deadlock" if self_dead else "lock_wait"
            out.append(
                finding(
                    cls,
                    f"pid {pid} on {path}",
                    since=started,
                    now=now,
                    severity="P1" if self_dead or ln.get("production") else "P2",
                    heal="code" if self_dead else "page",
                    lane=ln.get("lane"),
                    evidence={
                        "pid": pid,
                        "path": path,
                        "wchan": p.get("wchan"),
                        "command": cmd[:240],
                        "holders": sorted(holders.get(path, set())),
                        "self_deadlock": self_dead,
                    },
                )
            )
    return out


def process_findings(
    procs: Mapping[int, Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime, already: set[int]
) -> list[dict]:
    """D state (uninterruptible) past ``d_state_min``, or a configured watched process past its MEASURED cap. A
    process already reported as a lock waiter is not reported twice."""
    c = cfg["processes"]
    out: list[dict] = []
    owners = set(c.get("owner_uids") or [])
    for pid, p in sorted(procs.items()):
        if pid in already or (owners and p.get("uid") not in owners):
            continue
        cmd, stat = str(p.get("args") or ""), str(p.get("stat") or "")
        if not any(re.search(m, cmd) for m in c.get("command_patterns") or []):
            continue
        age = _age_min(p.get("started"), now)
        if age is None:
            continue
        if stat.startswith("D") and p.get("d_confirmed") and age >= float(c["d_state_min"]):
            ln = lane_for(cmd, cfg) or {}
            out.append(
                finding(
                    "process_stuck",
                    f"pid {pid}",
                    since=p.get("started"),
                    now=now,
                    severity="P2",
                    heal="reaper",
                    lane=ln.get("lane"),
                    evidence={
                        "pid": pid,
                        "stat": stat,
                        "wchan": p.get("wchan"),
                        "command": cmd[:240],
                        "why": "uninterruptible sleep past d_state_min",
                    },
                )
            )
            continue
        for w in c.get("watched") or []:
            if re.search(str(w["match"]), cmd) and age >= float(w["cap_min"]):
                out.append(
                    finding(
                        "process_stuck",
                        f"pid {pid}",
                        since=p.get("started"),
                        now=now,
                        severity=str(w.get("severity", "P2")),
                        heal="reaper",
                        lane=w.get("lane"),
                        evidence={
                            "pid": pid,
                            "command": cmd[:240],
                            "cap_min": w["cap_min"],
                            "cap_source": w.get("cap_source"),
                            "age_min": round(age, 1),
                        },
                    )
                )
                break
    return out


# ---------------------------------------------------------------- systemd units
def unit_findings(units: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """``activating`` past ``activating_min`` (a hung oneshot) or ``failed`` past ``failed_grace_min``. A failure on
    the expected-refusal list (e.g. disk-hygiene-enforcer exit 77, refused by §24.12 every day) is P3 "retire the
    unit", never a page. ``ignore_globs`` units are never findings."""
    c = cfg["units"]
    expected = {k: {str(x) for x in v} for k, v in (c.get("expected_failures") or {}).items()}
    out: list[dict] = []
    for u in units or []:
        name = str(u.get("unit") or "")
        if not name or any(fnmatch(name, g) for g in c.get("ignore_globs") or []):
            continue
        since = u.get("since")
        age = _age_min(since, now)
        ln = lane_for(name, cfg) or {}
        prod = bool(ln.get("production")) or any(fnmatch(name, g) for g in c.get("production_globs") or [])
        if u.get("active") == "activating" and age is not None and age >= float(c["activating_min"]):
            out.append(
                finding(
                    "unit_activating",
                    name,
                    since=since,
                    now=now,
                    severity="P1" if prod else "P2",
                    heal="code",
                    lane=ln.get("lane"),
                    evidence={
                        "unit": name,
                        "active": "activating",
                        "sub": u.get("sub"),
                        "timeout_start": u.get("timeout_start"),
                    },
                )
            )
        elif u.get("active") == "failed" and str(u.get("exit_status")) in expected.get(name, set()):
            out.append(
                finding(
                    "unit_failed",
                    name,
                    since=since,
                    now=now,
                    severity="P3",
                    heal="page",
                    lane=ln.get("lane"),
                    evidence={
                        "unit": name,
                        "exit_status": u.get("exit_status"),
                        "expected_refusal": True,
                        "why": "fails by design every run; retire the unit or its timer",
                    },
                )
            )
        elif u.get("active") == "failed" and (age is None or age >= float(c["failed_grace_min"])):
            out.append(
                finding(
                    "unit_failed",
                    name,
                    since=since,
                    now=now,
                    severity="P1" if prod else "P2",
                    heal="code",
                    lane=ln.get("lane"),
                    evidence={
                        "unit": name,
                        "active": "failed",
                        "result": u.get("result"),
                        "exit_status": u.get("exit_status"),
                        "journal_tail": (u.get("journal_tail") or "")[-1500:],
                    },
                )
            )
    return out


# ---------------------------------------------------------------- state files
def tail_state(data: bytes) -> dict:
    """The end of a JSONL store: is the final record parseable, and is the damage confined to the final line?
    ``data`` is the file's last bytes (the monitor reads at most ``tail_bytes``). Splits on b"\\n" only."""
    if not data:
        return {"empty": True, "ok": True}
    body = data[:-1] if data.endswith(b"\n") else data
    lines = body.split(b"\n")
    last = lines[-1]
    try:
        json.loads(last)
        return {"ok": True, "ends_newline": data.endswith(b"\n")}
    except ValueError:
        pass
    prev_ok = True
    if len(lines) >= 2:
        try:
            json.loads(lines[-2])
        except ValueError:
            prev_ok = False
    return {"ok": False, "bad_bytes": len(last), "prev_ok": prev_ok, "ends_newline": data.endswith(b"\n")}


def file_findings(facts: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """``facts`` rows: {path, kind: jsonl|state, size, mtime, tail: tail_state(...), locked: bool, backup: path|None}.
    A truncated final JSONL line is repairable only when the line before it parses and no process holds the
    store's lock right now; otherwise it is paged (a middle-of-file corruption is never auto-repaired)."""
    out: list[dict] = []
    for f in facts or []:
        path, kind = str(f["path"]), f.get("kind")
        ln = lane_for(path, cfg) or {}
        if kind == "jsonl" and f.get("size") and not (f.get("tail") or {}).get("ok", True):
            t = f["tail"]
            safe = bool(t.get("prev_ok")) and not f.get("locked")
            out.append(
                finding(
                    "jsonl_truncated_tail",
                    path,
                    since=f.get("mtime"),
                    now=now,
                    severity="P1",
                    heal="repair_tail" if safe else "page",
                    lane=ln.get("lane"),
                    evidence={
                        "bad_bytes": t.get("bad_bytes"),
                        "prev_line_ok": t.get("prev_ok"),
                        "locked": bool(f.get("locked")),
                        "why_not_auto": None
                        if safe
                        else ("store lock held" if f.get("locked") else "damage beyond the final line"),
                    },
                )
            )
        elif kind == "state" and f.get("size") == 0:
            out.append(
                finding(
                    "zero_byte_state",
                    path,
                    since=f.get("mtime"),
                    now=now,
                    severity="P1",
                    heal="restore_backup" if f.get("backup") else "page",
                    lane=ln.get("lane"),
                    evidence={
                        "backup": f.get("backup"),
                        "why_not_auto": None if f.get("backup") else "no valid backup found",
                    },
                )
            )
    return out


# ---------------------------------------------------------------- queues, breakers, heartbeats, lanes
def queue_findings(rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """rows: {name, pending, last_done (datetime|None), stuck_processing, consumer_fresh, error}. A query error is
    unknown, never zero. Rows claimed ("processing") and never finished are a stuck claim. Pending work with nothing
    completed in ``stale_hours`` is a stalled queue, or a starved consumer when the consumer lane runs but does no
    work."""
    out: list[dict] = []
    by_name = {q["name"]: q for q in cfg.get("queues") or []}
    for r in rows or []:
        q = by_name.get(r["name"]) or {}
        if r.get("error"):
            out.append(
                finding(
                    "queue_stalled",
                    r["name"],
                    since=None,
                    now=now,
                    severity="P2",
                    heal="page",
                    evidence={"unknown": True, "error": str(r["error"])[:200]},
                )
            )
            continue
        pending, last = int(r.get("pending") or 0), r.get("last_done")
        idle_h = None if last is None else (now - last).total_seconds() / 3600.0
        stalled = pending > 0 and (idle_h is None or idle_h >= float(q.get("stale_hours", 24)))
        stuck = int(r.get("stuck_processing") or 0)
        ev = {
            "pending": pending,
            "last_done": _iso(last) if last else None,
            "idle_hours": round(idle_h, 1) if idle_h is not None else None,
        }
        if stuck:
            out.append(
                finding(
                    "stuck_claim",
                    f"{r['name']}: {stuck} rows processing",
                    since=None,
                    now=now,
                    severity="P2",
                    heal=str(q.get("heal", "code")),
                    lane=q.get("lane"),
                    evidence={**ev, "stuck_processing": stuck, "why": "claimed by a consumer that never finished"},
                )
            )
        if stalled and r.get("consumer_fresh"):
            out.append(
                finding(
                    "starved_consumer",
                    r["name"],
                    since=last,
                    now=now,
                    severity="P2",
                    heal=str(q.get("heal", "code")),
                    lane=q.get("lane"),
                    evidence={
                        **ev,
                        "consumer_lane": q.get("consumer_lane"),
                        "why": "the consumer runs but completes nothing",
                    },
                )
            )
        elif stalled:
            out.append(
                finding(
                    "queue_stalled",
                    r["name"],
                    since=last,
                    now=now,
                    severity=str(q.get("severity", "P2")),
                    heal=str(q.get("heal", "code")),
                    lane=q.get("lane"),
                    evidence=ev,
                )
            )
    return out


def breaker_findings(rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    c = cfg["breakers"]
    out: list[dict] = []
    for r in rows or []:
        opened = r.get("opened_at")
        age = _age_min(opened, now)
        if r.get("released_at") is None and age is not None and age >= float(c["open_hours"]) * 60:
            out.append(
                finding(
                    "breaker_open",
                    str(r["lane_id"]),
                    since=opened,
                    now=now,
                    severity="P2",
                    heal="code",
                    lane=str(r["lane_id"]),
                    evidence={
                        "consecutive": r.get("consecutive"),
                        "last_error": r.get("last_error"),
                        "release_cmd": c["release_cmd"].replace("{lane}", str(r["lane_id"])),
                    },
                )
            )
    return out


def heartbeat_findings(rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """Stale ``last_seen`` only. Blind spot (sweep class 18): ``error_count`` is never used; one agent counts every
    non-HEALTHY inspection as an error, so the number means nothing."""
    c = cfg["heartbeats"]
    ignore = set(c.get("ignore_agents") or [])
    caps = c.get("stale_hours_by_agent") or {}
    out: list[dict] = []
    for r in rows or []:
        aid = str(r.get("agent_id"))
        if aid in ignore:
            continue
        seen = r.get("last_seen")
        cap = float(caps.get(aid, c["default_stale_hours"]))
        if seen is None or (now - seen).total_seconds() / 3600.0 >= cap:
            out.append(
                finding(
                    "heartbeat_stale",
                    aid,
                    since=seen,
                    now=now,
                    severity="P2",
                    heal="page",
                    evidence={"status": r.get("status"), "stale_hours_cap": cap},
                )
            )
    return out


def lane_findings(rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """rows: {lane_id, cadence_hours, signal_at, signal, state_since, signal_missing, stage, ledger_done_at}. A lane
    in a ``ledger_liveness_stages`` stage (shadow, canary) is alive by its newest ledger RUN_DONE. A lane whose signal
    does not exist is registry drift (fix the path before alarming), not silence. Silent = signal older than cadence
    x multiplier + margin; a lane that became ACTIVE inside one window is skipped. Watched lanes page; the rest are
    one P3 summary."""
    c = cfg["lanes"]
    watched = set(c.get("watched") or [])
    silent: list[dict] = []
    drift: list[dict] = []
    out: list[dict] = []
    ledger_stages = set(c.get("ledger_liveness_stages") or [])
    for r in rows or []:
        cad = float(r.get("cadence_hours") or 0)
        if cad <= 0:
            continue
        if r.get("stage") in ledger_stages:
            # A shadow/canary lane never writes the live receipt by design (a dry run that wrote one would falsify
            # output); its liveness is the coordination ledger's newest RUN_DONE.
            r = {
                **r,
                "signal_at": r.get("ledger_done_at"),
                "signal_missing": None,
                "signal": {"kind": "ledger_run_done", "stage": r.get("stage")},
            }
        if r.get("signal_missing"):
            drift.append({"lane": r["lane_id"], "signal": r.get("signal"), "why": r.get("signal_missing")})
            continue
        limit_h = cad * float(c["cadence_multiplier"]) + float(c["margin_hours"])
        at = r.get("signal_at")
        age_h = None if at is None else (now - at).total_seconds() / 3600.0
        if age_h is not None and age_h < limit_h:
            continue
        since = r.get("state_since")
        if at is None and since is not None and (now - since).total_seconds() / 3600.0 < limit_h:
            continue
        row = {
            "lane": r["lane_id"],
            "age_hours": round(age_h, 1) if age_h is not None else None,
            "limit_hours": round(limit_h, 1),
        }
        if r["lane_id"] in watched:
            out.append(
                finding(
                    "lane_silent",
                    r["lane_id"],
                    since=at,
                    now=now,
                    severity="P2",
                    heal="page",
                    lane=r["lane_id"],
                    evidence={**row, "signal": r.get("signal")},
                )
            )
        else:
            silent.append(row)
    n = int(c.get("summary_max", 40))
    if drift:
        out.append(
            finding(
                "registry_drift",
                f"{len(drift)} ACTIVE lanes with a missing signal",
                since=None,
                now=now,
                severity="P3",
                heal="page",
                evidence={"lanes": drift[:n], "count": len(drift)},
            )
        )
    if silent:
        out.append(
            finding(
                "lane_silent",
                f"{len(silent)} unwatched lanes",
                since=None,
                now=now,
                severity="P3",
                heal="page",
                evidence={"lanes": silent[:n], "count": len(silent)},
            )
        )
    return out


# ---------------------------------------------------------------- dedupe, alerts, heals, fixer intake
def due_alerts(findings: Iterable[Mapping[str, Any]], sent: Mapping[str, str], day: str) -> list[dict]:
    """One alert per item per day (``sent`` maps dedupe_key -> last day sent). P3 findings never page."""
    return [f for f in findings if f["severity"] in ("P1", "P2") and sent.get(f["dedupe_key"]) != day]


def render(findings: list[dict], when: str) -> str:
    head = f"🧯 *STUCK WORK* — {len(findings)} item(s) · {when}"
    lines = [head]
    for f in findings[:12]:
        age = f"{f['age_min'] / 60:.1f} h" if f.get("age_min") is not None else "age unknown"
        lines.append(f"• {f['severity']} {f['class'].replace('_', ' ')}: {f['item']} ({age}) → {f['heal']}")
    if len(findings) > 12:
        lines.append(f"…and {len(findings) - 12} more in the receipt")
    lines.append("Heals run only when heals_enabled; code defects go to the Claude Code fixer as PRs, never merged.")
    return "\n".join(lines)


def heal_plan(f: Mapping[str, Any], cfg: Mapping[str, Any]) -> Optional[dict]:
    """The deterministic heal for a finding, as a plan (the monitor executes it only with heals_enabled + --apply)."""
    arch = cfg["heals"]["archive_dir"]
    if f["heal"] == "repair_tail":
        return {"action": "repair_tail", "path": f["item"], "archive_dir": arch, "drop": "final unparseable line only"}
    if f["heal"] == "restart":
        return {"action": "restart", "unit": f["item"], "path": f["item"]}
    if f["heal"] == "restore_backup":
        return {"action": "restore_backup", "path": f["item"], "from": f["evidence"]["backup"], "archive_dir": arch}
    if f["heal"] == "reconcile_lock":
        return {"action": "reconcile_lock", "path": f["item"], "pid": f["evidence"]["pid"], "archive_dir": arch}
    return None


def repaired_bytes(data: bytes) -> Optional[bytes]:
    """The store with only its final unparseable line removed, or None when that would not be safe (the line
    before it does not parse, or the file is fine)."""
    body = data[:-1] if data.endswith(b"\n") else data
    lines = body.split(b"\n")
    try:
        json.loads(lines[-1])
        return None
    except ValueError:
        pass
    if len(lines) < 2:
        return b""
    try:
        json.loads(lines[-2])
    except ValueError:
        return None
    return b"\n".join(lines[:-1]) + b"\n"


def signature(f: Mapping[str, Any]) -> str:
    """Stable per defect: class + lane/item, no pid, no timestamp (a pid changes every run)."""
    base = f"{f['class']}|{f.get('lane') or re.sub(r'pid [0-9]+ on ', '', str(f['item']))}"
    return hashlib.sha256(base.encode()).hexdigest()[:12]


def fixer_defect(f: Mapping[str, Any], now: datetime, *, receipt: str) -> Optional[dict]:
    """A ``N8nCodeDefect@v1`` hand-off record for ``scripts/self_heal_fixer.py`` (store
    ``data/self_heal/fixer_defects.jsonl``, the same contract the n8n diagnoser publishes). Only heal == "code" with
    a known lane; the fixer applies its own refusal patterns (broker, order, stop, execution …) on top."""
    if f["heal"] != "code" or not f.get("lane"):
        return None
    sig = signature(f)
    return {
        "at": _iso(now),
        "source": "stuck-work-monitor",
        "code_defect": {
            "schema": SCHEMA_DEFECT,
            "consumer": DEFECT_CONSUMER,
            "consumer_status": "pending_consumer",
            "kind": "code_defect",
            "defect_id": f"cd-{f['lane']}-{sig}-ep1",
            "lane": f["lane"],
            "signature": sig,
            "episode": 1,
            "failure_kind": f["class"],
            "failure_class": "code_error",
            "evidence": {"receipt": receipt, "finding": dict(f), "incident_key": f["dedupe_key"]},
        },
    }


# ---------------------------------------------------------------- units stranded on an old release
def stale_release_findings(
    units: Iterable[Mapping[str, Any]],
    current: str,
    promoted_at: Optional[datetime],
    cfg: Mapping[str, Any],
    now: datetime,
) -> list[dict]:
    """A long-lived unit resolves ``.../portfolio-server/CURRENT`` once at start and keeps that release after every
    promote (2026-10-31: tradeai-ops-applier served f7c1e96cb from 10-22 and refused every newer Ops Controls kind as
    KIND_UNKNOWN). ``units`` rows: {unit, pid, cwd (resolved)}. Flagged when the cwd is a release directory other
    than CURRENT's target for more than ``grace_min`` after the promote. Heal = restart only for units on
    ``restart_allowlist`` and never for a name matching ``never_restart_globs`` (portfolio-server, broker and
    execution units, AGENTS.md §23.14)."""
    c = cfg["stale_release"]
    releases = os.path.expanduser(str(c["releases_dir"]))
    if not current or promoted_at is None or (now - promoted_at).total_seconds() / 60.0 < float(c["grace_min"]):
        return []
    allow = set(c.get("restart_allowlist") or [])
    never = [str(g) for g in c.get("never_restart_globs") or []]
    out: list[dict] = []
    for u in units or []:
        cwd, name = str(u.get("cwd") or ""), str(u.get("unit") or "")
        if not cwd.startswith(releases.rstrip("/") + "/") or cwd == current:
            continue
        blocked = any(fnmatch(name, g) for g in never)
        heal = "restart" if name in allow and not blocked else "page"
        ln = lane_for(name, cfg) or {}
        out.append(
            finding(
                "stale_release",
                name,
                since=promoted_at,
                now=now,
                severity="P2",
                heal=heal,
                lane=ln.get("lane"),
                evidence={
                    "unit": name,
                    "pid": u.get("pid"),
                    "serving": cwd.rsplit("/", 1)[-1],
                    "current": current.rsplit("/", 1)[-1],
                    "why_not_auto": None
                    if heal == "restart"
                    else ("never restarted by policy (§23.14)" if blocked else "not on restart_allowlist"),
                },
            )
        )
    return out


# ---------------------------------------------------------------- sweep classes 2, 3, 4, 5, 6 (units and processes)
def unit_lint_findings(units: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """Class 2: Trade AI oneshot units with ``TimeoutStartUSec=infinity`` can hang forever (tradeai-cio-reactive,
    29 h). One P3 lint listing them; class 3 (``unit_overrun``): a timer unit whose last run's wall time reached
    ``overrun_ratio`` of its period, or whose CPU time was ``spin_cpu_ratio`` of that wall time (cio-delivery spent
    3 min 59 s CPU of a 4 min 33 s run every 5 min and delivered 0)."""
    c = cfg["units"]
    lint, out = [], []
    periods = c.get("periods_s") or {}
    for u in units or []:
        name = str(u.get("unit") or "")
        if not any(fnmatch(name, g) for g in c.get("lint_globs") or []):
            continue
        if u.get("type") == "oneshot" and str(u.get("timeout_start")) in ("infinity", "0"):
            lint.append(name)
        wall, cpu, period = u.get("last_wall_s"), u.get("last_cpu_s"), periods.get(name)
        if period and wall and float(wall) >= float(c["overrun_ratio"]) * float(period):
            spin = bool(cpu) and float(cpu) >= float(c["spin_cpu_ratio"]) * float(wall)
            out.append(
                finding(
                    "unit_overrun",
                    name,
                    since=None,
                    now=now,
                    severity="P2",
                    heal="code",
                    lane=(lane_for(name, cfg) or {}).get("lane"),
                    evidence={"wall_s": wall, "cpu_s": cpu, "period_s": period, "cpu_bound": spin},
                )
            )
    if lint:
        out.append(
            finding(
                "unit_no_timeout",
                f"{len(lint)} oneshot units without a start timeout",
                since=None,
                now=now,
                severity="P3",
                heal="page",
                evidence={"units": sorted(lint), "why": "TimeoutStartUSec=infinity: a hang never ends"},
            )
        )
    return out


def proc_extra_findings(procs: Mapping[int, Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """Classes 3-6 at process level. ``procs`` rows also carry ppid, cpu_s, cwd and ``deleted_open`` (list of
    {path, size}). Never kills: a runaway orphan is ``reaper`` (process_reaper with a measured rule, or the
    operator); zombies need their parent reaped."""
    c = cfg["processes"]
    out: list[dict] = []
    zombies: dict[int, list[int]] = {}
    for pid, p in sorted(procs.items()):
        age = _age_min(p.get("started"), now) or 0.0
        cmd, cpu = str(p.get("args") or ""), float(p.get("cpu_s") or 0.0)
        ratio = cpu / (age * 60.0) if age > 0 else 0.0
        if str(p.get("stat") or "").startswith("Z"):
            zombies.setdefault(int(p.get("ppid") or 0), []).append(pid)
            continue
        orphan = int(p.get("ppid") or 0) == 1 and "(deleted)" in str(p.get("cwd") or "")
        if orphan and age >= float(c["orphan_min_age_h"]) * 60 and ratio >= float(c["orphan_cpu_ratio"]):
            out.append(
                finding(
                    "orphan_runaway",
                    f"pid {pid}",
                    since=p.get("started"),
                    now=now,
                    severity="P2",
                    heal="reaper",
                    evidence={
                        "pid": pid,
                        "command": cmd[:200],
                        "cwd": p.get("cwd"),
                        "cpu_ratio": round(ratio, 2),
                        "why": "parent gone, worktree deleted",
                    },
                )
            )
        elif (
            any(re.search(m, cmd) for m in c.get("command_patterns") or [])
            and age >= float(c["spin_min"])
            and ratio >= float(c["spin_cpu_ratio"])
        ):
            out.append(
                finding(
                    "cpu_spin",
                    f"pid {pid}",
                    since=p.get("started"),
                    now=now,
                    severity="P2",
                    heal="code",
                    lane=(lane_for(cmd, cfg) or {}).get("lane"),
                    evidence={"pid": pid, "command": cmd[:200], "cpu_ratio": round(ratio, 2)},
                )
            )
        big = [d for d in p.get("deleted_open") or [] if int(d.get("size") or 0) >= int(c["deleted_open_bytes"])]
        if big:
            out.append(
                finding(
                    "deleted_open_space",
                    f"pid {pid}",
                    since=p.get("started"),
                    now=now,
                    severity="P2",
                    heal="reaper",
                    evidence={
                        "pid": pid,
                        "command": cmd[:200],
                        "files": big[:5],
                        "bytes": sum(int(d["size"]) for d in big),
                    },
                )
            )
    for parent, kids in sorted(zombies.items()):
        if len(kids) >= int(c["zombie_min"]):
            out.append(
                finding(
                    "zombie",
                    f"parent pid {parent}",
                    since=None,
                    now=now,
                    severity="P3",
                    heal="page",
                    evidence={
                        "parent": parent,
                        "zombies": kids,
                        "parent_command": str((procs.get(parent) or {}).get("args") or "")[:200],
                    },
                )
            )
    return out


# ---------------------------------------------------------------- sweep classes 9, 10, 18 (n8n ledger)
def ledger_findings(
    probes: Mapping[str, int],
    poison: Iterable[Mapping[str, Any]],
    unverifiable: Iterable[Mapping[str, Any]],
    cfg: Mapping[str, Any],
    now: datetime,
    open_breakers: Iterable[str],
) -> list[dict]:
    """``probes``: lane -> runs started after its breaker opened (0 = nobody ever retried: class 9). ``poison``:
    {lane_id, slot_key, attempts} dead letters of one item over and over (class 10). ``unverifiable``: {lane_id,
    count} runs that exited 0 with reason ``output_unverifiable`` — a verifier bug, not a lane failure (class 18)."""
    c = cfg["breakers"]
    out: list[dict] = []
    for lane in sorted(open_breakers):
        if int(probes.get(lane, 0)) == 0:
            out.append(
                finding(
                    "breaker_no_probe",
                    lane,
                    since=None,
                    now=now,
                    severity="P2",
                    heal="page",
                    lane=lane,
                    evidence={"probes_since_open": 0, "why": "breaker never half-open probed"},
                )
            )
    for row in poison or []:
        if int(row.get("attempts") or 0) >= int(c["poison_min"]):
            out.append(
                finding(
                    "poison_item",
                    f"{row['lane_id']}:{row['slot_key']}",
                    since=None,
                    now=now,
                    severity="P2",
                    heal="code",
                    lane=str(row["lane_id"]),
                    evidence={
                        "slot_key": row["slot_key"],
                        "dead_letters": row["attempts"],
                        "last_reason": row.get("last_reason"),
                    },
                )
            )
    for row in unverifiable or []:
        out.append(
            finding(
                "verifier_blind",
                str(row["lane_id"]),
                since=None,
                now=now,
                severity="P2",
                heal="code",
                lane=str(row["lane_id"]),
                evidence={
                    "exit0_output_unverifiable": row["count"],
                    "why": "exit 0 judged a failure: fix the output contract, not the lane",
                },
            )
        )
    return out


# ---------------------------------------------------------------- sweep classes 13, 14, 16, 17, stale locks
def missed_window_findings(windows: Iterable[Mapping[str, Any]], now: datetime, trading_day: bool) -> list[dict]:
    """windows: {lane, due (datetime today), grace_min, signal_at}. On a trading day, a lane whose signal is older
    than today's due time once due + grace has passed missed its market window (class 13)."""
    if not trading_day:
        return []
    out = []
    for w in windows or []:
        due = w["due"]
        if now < due + timedelta(minutes=float(w["grace_min"])):
            continue
        at = w.get("signal_at")
        if at is None or at < due:
            out.append(
                finding(
                    "missed_window",
                    w["lane"],
                    since=due,
                    now=now,
                    severity=str(w.get("severity", "P1")),
                    heal="page",
                    lane=w["lane"],
                    evidence={"due": _iso(due), "signal_at": _iso(at) if at else None},
                )
            )
    return out


def claim_findings(claims: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """Class 14: claim-board claims still ``active`` whose heartbeat is older than ``stale_hours``. One P3 summary
    (``agent_claim.py takeover`` or close them)."""
    c = cfg["claims"]
    stale = []
    for cl in claims or []:
        hb = cl.get("heartbeat_at")
        if cl.get("status") == "active" and (
            hb is None or (now - hb).total_seconds() / 3600 >= float(c["stale_hours"])
        ):
            stale.append(
                {
                    "claim_id": cl.get("claim_id"),
                    "branch": cl.get("branch"),
                    "age_hours": round((now - hb).total_seconds() / 3600, 1) if hb else None,
                }
            )
    if not stale:
        return []
    return [
        finding(
            "stuck_claim",
            f"{len(stale)} claim-board claims",
            since=None,
            now=now,
            severity="P3",
            heal="page",
            evidence={"claims": stale[: int(c.get("summary_max", 40))], "count": len(stale)},
        )
    ]


def heal_loop_findings(counts: Mapping[str, int], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """Class 16: the same heal tried ``loop_min`` times in 24 h without the problem going away (this monitor's own
    heals, and other healers' 'remediation ineffective' rows). The heal is suppressed for that item."""
    lim = int(cfg["heals"]["loop_min"])
    return [
        finding(
            "heal_loop",
            key,
            since=None,
            now=now,
            severity="P1",
            heal="code",
            lane=(lane_for(key, cfg) or {}).get("lane"),
            evidence={"attempts_24h": n, "why": "heal repeats without effect: needs a code fix"},
        )
        for key, n in sorted(counts.items())
        if n >= lim
    ]


def precursor_findings(res: Mapping[str, Any], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """Class 17: disk %, swap %, Postgres in recovery — what preceded the 10-30 outage."""
    c = cfg["resources"]
    out = []
    for mount, pct in sorted((res.get("disk_pct") or {}).items()):
        if pct >= float(c["disk_pct"]):
            out.append(
                finding(
                    "resource_precursor",
                    f"disk {mount}",
                    since=None,
                    now=now,
                    severity="P1" if pct >= float(c["disk_pct_p1"]) else "P2",
                    heal="page",
                    evidence={"used_pct": pct},
                )
            )
    sw = res.get("swap_pct")
    if sw is not None and sw >= float(c["swap_pct"]):
        out.append(
            finding(
                "resource_precursor",
                "swap",
                since=None,
                now=now,
                severity="P2",
                heal="page",
                evidence={"used_pct": sw, "top": res.get("swap_top")},
            )
        )
    if res.get("pg_in_recovery"):
        out.append(
            finding(
                "resource_precursor",
                "postgres in recovery",
                since=None,
                now=now,
                severity="P1",
                heal="page",
                evidence={"pg_is_in_recovery": True},
            )
        )
    return out


def stale_lock_findings(locks: Iterable[Mapping[str, Any]], now: datetime) -> list[dict]:
    """pid-file locks ({path, pid, pid_alive, held, mtime}) whose recorded pid is dead and that no process holds:
    the §28.14 stale-lock reconcile archives them (runtime/self_heal_fixer.lock, pid dead 62 h on 10-31)."""
    return [
        finding(
            "stale_lock",
            str(lk["path"]),
            since=lk.get("mtime"),
            now=now,
            severity="P3",
            heal="reconcile_lock",
            evidence={"pid": lk["pid"], "pid_alive": False, "held": False},
        )
        for lk in locks or []
        if lk.get("pid") and not lk.get("pid_alive") and not lk.get("held")
    ]


def quarantine_findings(rows: Iterable[Mapping[str, Any]], now: datetime) -> list[dict]:
    """Items held by scripts/lib/poison_quarantine.py: each is a poison item the lane now skips — a code defect for
    the Claude Code fixer (the quarantine kept the lane running; this keeps the item from being forgotten)."""
    return [
        finding(
            "poison_item",
            f"{r['lane']}:{r['item']}",
            since=r.get("at"),
            now=now,
            severity="P2",
            heal="code",
            lane=str(r["lane"]),
            evidence={
                "quarantined": True,
                "consecutive_failures": r.get("consecutive_failures"),
                "reason": r.get("reason"),
            },
        )
        for r in rows or []
    ]
