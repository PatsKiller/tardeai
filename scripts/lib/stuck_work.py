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
from datetime import datetime, timezone
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
)
#: heal keys: what may follow a finding. "page" = alert only; "repair_tail" / "restore_backup" = deterministic heal;
#: "code" = Claude Code fixer intake; "reaper" = needs a measured process_reaper rule (never killed here);
#: "restart" = systemctl --user restart, only for a unit on the stale_release allowlist (never a broker/server unit).
HEAL_KEYS = ("page", "repair_tail", "restore_backup", "code", "reaper", "restart")


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
        if stat.startswith("D") and age >= float(c["d_state_min"]):
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
    """``activating`` past ``activating_min`` (a oneshot that never finishes) or ``failed`` past ``failed_grace_min``.
    Units matched by ``ignore_globs`` (snap notifiers and the like) are never findings."""
    c = cfg["units"]
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
    """rows: {name, pending, last_done (datetime|None), stuck_processing, error}. Stalled = pending > 0 and nothing
    completed in ``stale_hours``; a query error is reported as unknown, never as zero."""
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
        if stalled or stuck:
            out.append(
                finding(
                    "queue_stalled",
                    r["name"],
                    since=last,
                    now=now,
                    severity=str(q.get("severity", "P2")),
                    heal=str(q.get("heal", "code")),
                    lane=q.get("lane"),
                    evidence={
                        "pending": pending,
                        "last_done": _iso(last) if last else None,
                        "idle_hours": round(idle_h, 1) if idle_h is not None else None,
                        "stuck_processing": stuck,
                    },
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
                    evidence={"status": r.get("status"), "error_count": r.get("error_count"), "stale_hours_cap": cap},
                )
            )
    return out


def lane_findings(rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """rows: {lane_id, cadence_hours, signal_at (datetime|None), signal, state_since}. Silent = signal older than cadence ×
    multiplier + margin. Only lanes on ``watched`` page; the rest are counted in one summary finding."""
    c = cfg["lanes"]
    watched = set(c.get("watched") or [])
    silent: list[dict] = []
    out: list[dict] = []
    for r in rows or []:
        cad = float(r.get("cadence_hours") or 0)
        if cad <= 0:
            continue
        limit_h = cad * float(c["cadence_multiplier"]) + float(c["margin_hours"])
        at = r.get("signal_at")
        age_h = None if at is None else (now - at).total_seconds() / 3600.0
        if age_h is not None and age_h < limit_h:
            continue
        since = r.get("state_since")
        if at is None and since is not None and (now - since).total_seconds() / 3600.0 < limit_h:
            continue  # a lane that became ACTIVE inside one cadence has not had the chance to signal yet
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
    if silent:
        out.append(
            finding(
                "lane_silent",
                f"{len(silent)} unwatched lanes",
                since=None,
                now=now,
                severity="P3",
                heal="page",
                evidence={"lanes": silent[: int(c.get("summary_max", 40))], "count": len(silent)},
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
    if f["heal"] == "repair_tail":
        return {
            "action": "repair_tail",
            "path": f["item"],
            "archive_dir": cfg["heals"]["archive_dir"],
            "drop": "final unparseable line only",
        }
    if f["heal"] == "restart":
        return {"action": "restart", "unit": f["item"], "path": f["item"]}
    if f["heal"] == "restore_backup":
        return {
            "action": "restore_backup",
            "path": f["item"],
            "from": f["evidence"]["backup"],
            "archive_dir": cfg["heals"]["archive_dir"],
        }
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
