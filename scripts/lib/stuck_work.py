"""Stuck-work detection and the safe deterministic heals — the pure core (no I/O, no subprocess, no sends).

Operator 2026-10-31 (verbatim): "validate all stuck agents and processes fix montior and make auto healings with
claude code". Born from the 2026-10-30 disk-full aftermath: the CIO wake pipeline self-deadlocked for 31 hours on a
half-written JSONL tail, ``tradeai-cio-reactive`` sat "activating" forever, zero-byte state files broke two units,
eight n8n breakers stayed open and the overnight LLM queue completed nothing — and no monitor said so.

``scripts/stuck_work_monitor.py`` collects raw facts (lslocks, ps, systemctl, files, read-only SQL, the n8n ledger
opened read-only, the lane registry) and hands them here. This module decides:

* ``StuckFinding@v1`` per item: class, item, since, evidence, severity, heal key;
* which findings may get a deterministic heal, and the plan for it (never the act). AGENTS.md §28.14 allows four
  deterministic fixes: an infra-flake rerun, a regenerated file, the disk re-pin and the stale-lock reconcile. Only
  the stale-lock reconcile is used here. The truncated-final-record JSONL repair and the zero-byte restore from a
  backup are NOT covered by §28.14: they are built and tested, but stay disabled until the operator ratifies a §28.14
  amendment that names them;
* which findings are code defects for the Claude Code fixer (``N8nCodeDefect@v1``, the contract
  ``scripts/self_heal_fixer.py`` consumes).

Never here: ending a process or restarting a unit. §28.1 names the four automations that may end a run; a stuck
process or a unit on an old release gets a page and, when it is a code defect, a fixer intake.
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
#: "reconcile_lock" = archive a pid-file lock whose pid is dead and that nobody holds (§28.14 stale-lock reconcile).
HEAL_KEYS = ("page", "repair_tail", "restore_backup", "code", "reaper", "reconcile_lock")


#: The heals that may actually run. A code constant (review round 2, 2026-10-31): ``heals_enabled`` alone can never turn
#: on a heal that AGENTS.md §28.14 does not name. §28.14's deterministic fixes include the stale-lock reconcile; the
#: tail repair and the zero-byte restore are built and tested but NOT ratified, so ``apply`` and ``do_heal`` refuse
#: them until a reviewed PR adds them here after the operator ratifies a §28.14 amendment naming them.
RATIFIED_HEALS = frozenset({"reconcile_lock"})

#: Units/lanes no automation here may ever act on (restart, heal, release). A code constant: config may ADD patterns
#: (``never_act_extra``), never remove these. Case-insensitive substring match. AGENTS.md §23.14 + review 2026-10-31.
NEVER_ACT = (
    "portfolio-server",
    "broker",
    "order",
    "stop",
    "position",
    "account",
    "paper",
    "scalp",
    "sender",
    "telegram",
    "secret",
    "guard",
    "deploy",
    "release",
    "retention",
    "agent-loop",
    "dof",
    "schwab",
    "alpaca",
    "moomoo",
    "execution",
    "active-trader",
    "options-lifecycle",
)


def never_act(name: str, cfg: Optional[Mapping[str, Any]] = None) -> bool:
    low = str(name or "").lower()
    extra = [str(x).lower() for x in ((cfg or {}).get("never_act_extra") or [])]
    return any(p in low for p in (*NEVER_ACT, *extra))


def cmd_key(cmd: str) -> str:
    """A stable identity for a command line: digits (pids, timestamps, hashes in argv) removed, then hashed."""
    norm = re.sub(r"[0-9]+", "#", " ".join(str(cmd or "").split()))[:400]
    return "cmd:" + hashlib.sha256(norm.encode()).hexdigest()[:12]


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
    key: Optional[str] = None,
) -> dict:
    """``key`` is the stable identity used for the once-a-day alert dedupe. It must never contain a count, a pid or a
    timestamp (review 2026-10-31: "32 other zero-byte files" and "pid 123" made a new alert every time they changed);
    it defaults to ``item`` only for items that are already stable (a path, a unit, a lane)."""
    if cls not in CLASSES:
        raise ValueError(f"unknown class {cls!r}")
    if heal not in HEAL_KEYS:
        raise ValueError(f"unknown heal key {heal!r}")
    stable = key if key is not None else item
    if re.search(r"\bpid [0-9]+|^[0-9]+ ", str(stable)):
        raise ValueError(f"unstable dedupe key {stable!r}: pass key= without counts or pids")
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
        "dedupe_key": f"{cls}|{stable}",
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
                    key=str(ln.get("lane") or path),
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
                    key=str(ln.get("lane") or cmd_key(cmd)),
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
                        key=str(w.get("lane") or cmd_key(cmd)),
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
def tail_state(data: bytes, *, whole_file: bool = False) -> dict:
    """The end of a JSONL store, split on b"\\n" only. Trailing blank lines are not damage. ``ok`` = the last
    non-blank record parses. ``repairable`` = the damage is confined to that one final record: every OTHER complete
    line in the window parses, and the file has at least two records. ``data`` is the file's last bytes; unless
    ``whole_file``, the first line of the window may be cut mid-record and is ignored."""
    body = data.rstrip(b"\n")
    if not body.strip():
        return {"empty": True, "ok": True, "repairable": False}
    lines = body.split(b"\n")
    while lines and not lines[-1].strip():
        lines.pop()
    last = lines[-1]
    try:
        json.loads(last)
        return {"ok": True, "ends_newline": data.endswith(b"\n"), "repairable": False}
    except ValueError:
        pass
    complete = lines[:-1] if whole_file else lines[1:-1]
    bad_before = 0
    for ln in complete:
        if not ln.strip():
            continue
        try:
            json.loads(ln)
        except ValueError:
            bad_before += 1
    enough = len(lines) >= 2
    return {
        "ok": False,
        "bad_bytes": len(last),
        "prev_ok": enough and bad_before == 0,
        "bad_complete_lines": bad_before,
        "line_count_ge_2": enough,
        "repairable": enough and bad_before == 0,
        "ends_newline": data.endswith(b"\n"),
    }


def file_findings(facts: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime) -> list[dict]:
    """``facts`` rows: {path, kind: jsonl|state, size, mtime, tail: tail_state(...), locked: bool, backup: path|None,
    backup_mtime}. A truncated final JSONL record is a repair candidate only when ``tail.repairable`` (every other
    complete line in the window parses, at least two records), no process holds the store or its lock, and the file
    has been quiet for ``quiet_min``. A zero-byte state file is a restore candidate only when it has been empty and
    unchanged for ``quiet_min``, no lock is held, and the newest valid backup is younger than ``backup_max_age_h``.
    Both heals stay disabled until an operator-ratified §28.14 amendment names them (config ``heals_enabled``)."""
    h = cfg["heals"]
    quiet = float(h["quiet_min"])
    out: list[dict] = []
    for f in facts or []:
        path, kind = str(f["path"]), f.get("kind")
        ln = lane_for(path, cfg) or {}
        age = _age_min(f.get("mtime"), now)
        settled = age is not None and age >= quiet
        if kind == "jsonl" and f.get("size") and not (f.get("tail") or {}).get("ok", True):
            t = f["tail"]
            why = (
                "store or its lock is held"
                if f.get("locked")
                else "damage beyond the final record"
                if not t.get("repairable")
                else f"written {age:.0f} min ago (< {quiet:.0f})"
                if not settled
                else None
            )
            out.append(
                finding(
                    "jsonl_truncated_tail",
                    path,
                    since=f.get("mtime"),
                    now=now,
                    severity="P1",
                    heal="page" if why else "repair_tail",
                    lane=ln.get("lane"),
                    evidence={
                        "bad_bytes": t.get("bad_bytes"),
                        "bad_complete_lines": t.get("bad_complete_lines"),
                        "locked": bool(f.get("locked")),
                        "why_not_auto": why,
                        "mtime": _iso(f["mtime"]) if f.get("mtime") else None,
                    },
                )
            )
        elif kind == "state" and f.get("size") == 0:
            bage = _age_min(f.get("backup_mtime"), now)
            fresh = bage is not None and bage <= float(h["backup_max_age_h"]) * 60
            why = (
                "no valid backup found"
                if not f.get("backup")
                else f"newest backup is {bage / 60:.0f} h old (> {h['backup_max_age_h']} h)"
                if not fresh
                else "file or its lock is held"
                if f.get("locked")
                else f"empty for {age:.0f} min only (< {quiet:.0f})"
                if not settled
                else None
            )
            out.append(
                finding(
                    "zero_byte_state",
                    path,
                    since=f.get("mtime"),
                    now=now,
                    severity="P1",
                    heal="page" if why else "restore_backup",
                    lane=ln.get("lane"),
                    evidence={
                        "backup": f.get("backup"),
                        "why_not_auto": why,
                        "mtime": _iso(f["mtime"]) if f.get("mtime") else None,
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
                    key=str(r["name"]),
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


def breaker_findings(
    rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], now: datetime, probes: Optional[Mapping[str, int]] = None
) -> list[dict]:
    """One finding per open breaker (the "never probed" fact is evidence on it, not a second alert). Page only: the
    breaker is a symptom; the lane's own failure is what a fix PR addresses, so it is never sent to the fixer."""
    c = cfg["breakers"]
    out: list[dict] = []
    for r in rows or []:
        opened = r.get("opened_at")
        age = _age_min(opened, now)
        if r.get("released_at") is None and age is not None and age >= float(c["open_hours"]) * 60:
            lane = str(r["lane_id"])
            n = None if probes is None else int(probes.get(lane, 0))
            out.append(
                finding(
                    "breaker_open",
                    lane,
                    since=opened,
                    now=now,
                    severity="P2",
                    heal="page",
                    lane=lane,
                    evidence={
                        "consecutive": r.get("consecutive"),
                        "probes_since_open": n,
                        "never_probed": n == 0,
                        "release_cmd": c["release_cmd"].replace("{lane}", lane),
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
                key="registry_drift",
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
                key="unwatched_lanes",
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
    """The deterministic heal for a finding, as a plan; the monitor re-checks every condition at act time and runs it
    only with ``heals_enabled`` and ``--apply``. repair_tail and restore_backup additionally need the operator's
    ratified §28.14 amendment naming them before heals_enabled may be set (config ``_heals_why``)."""
    arch = cfg["heals"]["archive_dir"]
    ev = f.get("evidence") or {}
    if f["heal"] == "repair_tail":
        return {
            "action": "repair_tail",
            "path": f["item"],
            "archive_dir": arch,
            "mtime": ev.get("mtime"),
            "drop": "final unparseable record only",
        }
    if f["heal"] == "restore_backup":
        return {
            "action": "restore_backup",
            "path": f["item"],
            "from": ev["backup"],
            "archive_dir": arch,
            "mtime": ev.get("mtime"),
        }
    if f["heal"] == "reconcile_lock":
        return {"action": "reconcile_lock", "path": f["item"], "pid": ev["pid"], "archive_dir": arch}
    return None


def truncate_offset(data: bytes) -> Optional[int]:
    """Byte length to keep: through the last newline that ends a parseable record, when the damage is only the
    final record and every other line parses (``data`` is the WHOLE file). None = not safe or nothing to do."""
    st = tail_state(data, whole_file=True)
    if st.get("ok") or not st.get("repairable"):
        return None
    cut = data.rstrip(b"\n").rfind(b"\n")
    return cut + 1 if cut >= 0 else None


def repaired_bytes(data: bytes) -> Optional[bytes]:
    """The store with only its final unparseable record removed (see ``truncate_offset``), or None."""
    off = truncate_offset(data)
    return None if off is None else data[:off]


def signature(f: Mapping[str, Any]) -> str:
    """Stable per defect: class + lane/item, no pid, no timestamp (a pid changes every run)."""
    base = f"{f['class']}|{f.get('lane') or re.sub(r'pid [0-9]+ on ', '', str(f['item']))}"
    return hashlib.sha256(base.encode()).hexdigest()[:12]


def fixer_defect(f: Mapping[str, Any], now: datetime, *, receipt: str) -> Optional[dict]:
    """A ``N8nCodeDefect@v1`` hand-off record for ``scripts/self_heal_fixer.py`` (store
    ``data/self_heal/fixer_defects.jsonl``). Contract with the fixer's train intake (#2129 ``train_incidents``): the
    record's TOP-LEVEL ``receipt`` is read as the failed run's receipt, so the evidence goes there
    (``stderr_tail`` = what the model reads), not only under ``code_defect.evidence``. Only heal == "code" with a known
    lane; the fixer applies its own refusal patterns on top."""
    if f["heal"] != "code" or not f.get("lane"):
        return None
    sig = signature(f)
    ev = dict(f.get("evidence") or {})
    tail = ev.get("journal_tail") or json.dumps({k: v for k, v in ev.items() if k != "journal_tail"}, default=str)
    return {
        "at": _iso(now),
        "source": "stuck-work-monitor",
        "receipt": {
            "schema": "StuckWorkEvidence@v1",
            "lane_id": f["lane"],
            "status": f["class"],
            "stderr_tail": f"{f['class']} {f['item']}: " + str(tail)[-3500:],
            "argv": [ev["command"]] if ev.get("command") else [],
            "monitor_receipt": receipt,
            "finding": dict(f),
        },
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
            "evidence": {"receipt": receipt, "incident_key": f["dedupe_key"]},
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
    KIND_UNKNOWN). ``units`` rows: {unit, pid, cwd (resolved)}. Flagged when the cwd is inside a release directory
    other than CURRENT's target (a cwd INSIDE the current release is current) for more than ``grace_min`` after the
    promote. PAGE ONLY: a restart ends a run, and AGENTS.md §28.1 names the only four automations that may — the real
    fix is the deploy script restarting every CURRENT-bound unit after a promote."""
    c = cfg["stale_release"]
    releases = os.path.expanduser(str(c["releases_dir"])).rstrip("/")
    if not current or promoted_at is None or (now - promoted_at).total_seconds() / 60.0 < float(c["grace_min"]):
        return []
    cur = current.rstrip("/")
    out: list[dict] = []
    for u in units or []:
        cwd, name = str(u.get("cwd") or "").rstrip("/"), str(u.get("unit") or "")
        if not cwd.startswith(releases + "/") or cwd == cur or cwd.startswith(cur + "/"):
            continue
        release = cwd[len(releases) + 1 :].split("/", 1)[0]
        out.append(
            finding(
                "stale_release",
                name,
                since=promoted_at,
                now=now,
                severity="P2",
                heal="page",
                lane=(lane_for(name, cfg) or {}).get("lane"),
                evidence={
                    "unit": name,
                    "pid": u.get("pid"),
                    "serving": release,
                    "current": cur.rsplit("/", 1)[-1],
                    "never_auto_act": never_act(name, cfg),
                    "why_not_auto": "a restart ends a run (§28.1); restart it after review, and add "
                    "it to the deploy script's CURRENT-bound unit list",
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
                key="oneshot_lint",
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
                    key=cmd_key(cmd),
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
                    key=cmd_key(cmd),
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
                    key=cmd_key(cmd),
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
                    key="zombie-parent:" + cmd_key(str((procs.get(parent) or {}).get("args") or "")),
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
    poison: Iterable[Mapping[str, Any]],
    unverifiable: Iterable[Mapping[str, Any]],
    cfg: Mapping[str, Any],
    now: datetime,
) -> list[dict]:
    """``poison``: {lane_id, slot_key, attempts} dead letters of one item over and over (class 10). ``unverifiable``:
    {lane_id, count} runs that exited 0 with reason ``output_unverifiable`` — a verifier bug, not a lane failure
    (class 18). (Breakers never probed: evidence on ``breaker_open``, not a separate alert.)"""
    c = cfg["breakers"]
    out: list[dict] = []
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
            key="claim_board",
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
