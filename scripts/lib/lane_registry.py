#!/usr/bin/env python3
"""lane_registry.py — declare what is supposed to be producing, then check it.

A production lane was disabled on 2026-06-01 and nothing reported its absence
for three months. The liveness monitor exists, works, and runs every 15 minutes.
It simply had no way to know that lane was supposed to exist: it learns its
lanes from hardcoded tuples (`EXTERNAL_AUTO_LANES`, `EXTERNAL_MANUAL_LANES`)
plus a handful of bespoke collectors. It can see a lane producing poorly. It
cannot see a lane producing nothing because nobody told it the lane was there.

Detection generalises; prevention does not. A guard against commented-out crons
would not catch a renamed script, a masked systemd unit, or a queue that quietly
stopped being read. What catches all of those is a declaration of what *should*
be producing, compared against what *is* — the same shape as the dark-contract
gate, which is the working precedent here.

Two rules this module exists to enforce:

  * **A lane is verified by a durable artifact, never by an exit code.** Exit
    code 0 has been wrong about this system three times. `output_signal` names
    the thing that would not exist if the lane had not run.
  * **RETIRED and PAUSED are declared states, not absences.** A retired lane
    keeps its row; its silence is expected and is reported as expected. The
    failure being fixed is that "off" was indistinguishable from "gone".

READ_ONLY_ADVISORY. No LLM calls, no broker mutation, no scheduler mutation —
this module reads schedulers and never writes them.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "LaneRegistry@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = ROOT / "config" / "lane_registry.json"


def state_root() -> Path:
    """Where the running system WRITES, which is not where this code lives.

    Output signals are durable artifacts produced by scheduled jobs. Those jobs
    run from the deployed tree and write under the canonical state root; this
    module may be imported from a worktree, a release directory or the dev tree.
    Resolving a relative output path against the CODE tree therefore asks "did
    this job write into the checkout I happen to be running from", which is a
    different question and is almost always answered no.

    Measured 2026-09-05: run from a worktree, this reported 28 of 65 lanes
    SILENT, including `research-lane-health` — the lane producing the very
    report — and `warm-caches`, whose cron entry had fired minutes earlier. Both
    artifacts existed, dated that same day, under the state root. The verdicts
    were not observations of silence; they were observations of the wrong
    directory.

    `observe_signal` is careful to distinguish UNVERIFIABLE from SILENT because
    "conflating the two is how a monitor starts lying". That reasoning has a
    premise this restores: that we looked where the writer writes.
    """
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
            return Path(production_state_root())
        except Exception:
            return Path.home() / "trade-ai-releases" / "persistent-state"

# ── states ─────────────────────────────────────────────────────────────────

STATE_ACTIVE = "ACTIVE"
STATE_RETIRED = "RETIRED"
STATE_PAUSED = "PAUSED"
STATE_NEVER_SCHEDULED = "NEVER_SCHEDULED"
STATES = (STATE_ACTIVE, STATE_RETIRED, STATE_PAUSED, STATE_NEVER_SCHEDULED)

# States whose silence is expected rather than a finding.
SILENCE_EXPECTED = (STATE_RETIRED, STATE_PAUSED, STATE_NEVER_SCHEDULED)

# ── verdicts ───────────────────────────────────────────────────────────────

LIVE = "LIVE"
SLOW = "SLOW"
SILENT = "SILENT"
EXPECTED_SILENT = "EXPECTED_SILENT"
UNDECLARED = "UNDECLARED"
ORPHANED = "ORPHANED"
UNVERIFIABLE = "UNVERIFIABLE"

FINDING_VERDICTS = (SILENT, UNDECLARED, ORPHANED)

# A reason we could not establish. Never invent one; an honest UNKNOWN is the
# correct entry and is itself a finding worth reporting.
REASON_UNKNOWN = "UNKNOWN"

# ESTABLISHED — the cause is proven from evidence quoted in reason_evidence.
# CORRELATED  — strong evidence, causation NOT proven. Do not treat as covered.
# UNKNOWN     — genuinely not established. An honest entry, and itself a finding.
REASON_CONFIDENCE = ("ESTABLISHED", "CORRELATED", "UNKNOWN")


# ── loading and validation ─────────────────────────────────────────────────

def load_registry(path: Optional[Path] = None) -> dict[str, Any]:
    p = Path(path) if path else REGISTRY_PATH
    if not p.exists():
        return {"schema": SCHEMA, "lanes": [], "undeclared_baseline": []}
    return json.loads(p.read_text(encoding="utf-8"))


def validate_row(row: dict[str, Any]) -> list[str]:
    """Structural problems with one registry row. Empty list means valid.

    These are the CI gate's rules, expressed once so the gate and the monitor
    cannot disagree about what a valid row is.
    """
    errs: list[str] = []
    lane_id = str(row.get("lane_id") or "")
    if not lane_id:
        errs.append("lane_id is required")
    if not row.get("owner"):
        errs.append(f"{lane_id}: owner is required")

    state = str(row.get("state") or "")
    if state not in STATES:
        errs.append(f"{lane_id}: state must be one of {STATES}, got {state!r}")

    # The field that matters: a durable artifact, not an exit code.
    sig = row.get("output_signal")
    if not isinstance(sig, dict) or not sig.get("kind"):
        errs.append(
            f"{lane_id}: output_signal is required and must name the durable "
            "artifact that proves the lane ran (a file, a row, a store key) — "
            "an exit code is not an output signal")
    elif sig.get("kind") not in OUTPUT_SIGNAL_KINDS:
        errs.append(f"{lane_id}: output_signal.kind {sig.get('kind')!r} unknown")

    if state != STATE_ACTIVE:
        if not row.get("state_reason"):
            errs.append(f"{lane_id}: state_reason is required when state != ACTIVE")
        if not row.get("state_since"):
            errs.append(f"{lane_id}: state_since is required when state != ACTIVE")
    # How well is the reason established? Added 2026-08-30 after working the
    # 26 UNKNOWN lanes down to 6: most had a recoverable cause, but "superseded"
    # has been asserted falsely in this repo before, so a reason now has to say
    # whether it was proven or merely correlated.
    if state != STATE_ACTIVE:
        conf = row.get("reason_confidence")
        if conf not in REASON_CONFIDENCE:
            errs.append(f"{lane_id}: reason_confidence must be one of "
                        f"{REASON_CONFIDENCE}, got {conf!r}")
    if state == STATE_PAUSED and not row.get("review_by"):
        errs.append(f"{lane_id}: review_by is required when state == PAUSED "
                    "(a paused lane the operator is never asked about again is a "
                    "retired lane with better manners)")

    sched = row.get("scheduler")
    if not isinstance(sched, dict) or sched.get("kind") not in SCHEDULER_KINDS:
        errs.append(f"{lane_id}: scheduler.kind must be one of {SCHEDULER_KINDS}")
    elif sched.get("kind") != "none" and not sched.get("expression"):
        errs.append(f"{lane_id}: scheduler.expression is required for "
                    f"kind={sched.get('kind')}")

    if state == STATE_ACTIVE and not row.get("expected_cadence_hours"):
        errs.append(f"{lane_id}: expected_cadence_hours is required when ACTIVE")
    return errs


SCHEDULER_KINDS = ("cron", "systemd", "none")
OUTPUT_SIGNAL_KINDS = ("file_mtime", "json_key", "db_max", "none")


def validate_registry(reg: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    seen: set[str] = set()
    for row in reg.get("lanes") or []:
        errs.extend(validate_row(row))
        lid = str(row.get("lane_id") or "")
        if lid in seen:
            errs.append(f"{lid}: duplicate lane_id")
        seen.add(lid)
    return errs


# ── observing the durable artifact ─────────────────────────────────────────

def _mtime_utc(p: Path) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return None


def _parse_ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    for cut in (None, 19, 10):
        try:
            d = datetime.fromisoformat(s if cut is None else s[:cut])
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def observe_signal(sig: dict[str, Any], *, root: Optional[Path] = None,
                   db_query: Any = None) -> dict[str, Any]:
    """When did this lane last produce? Returns {last_output_at, detail}.

    Never raises. An unreadable signal returns ``last_output_at=None`` with the
    reason in ``detail`` — a lane whose signal cannot be read is reported
    UNVERIFIABLE, which is a different thing from a lane that is silent, and
    conflating the two is how a monitor starts lying.
    """
    # Durable OUTPUT paths resolve against the state root, never the code tree.
    # An explicit root= still wins, which is what the tests use.
    root = Path(root) if root else state_root()
    kind = str((sig or {}).get("kind") or "none")
    try:
        if kind == "file_mtime":
            p = Path(str(sig.get("path") or ""))
            if not p.is_absolute():
                p = root / p
            ts = _mtime_utc(p)
            # An absent file IS readable: we looked and there was nothing. That is
            # silence, not unverifiability.
            return {"last_output_at": ts, "readable": True,
                    "detail": str(p) + ("" if ts else " (absent)")}

        if kind == "json_key":
            p = Path(str(sig.get("path") or ""))
            if not p.is_absolute():
                p = root / p
            if not p.exists():
                return {"last_output_at": None, "readable": True,
                        "detail": f"{p} (absent)"}
            doc = json.loads(p.read_text(encoding="utf-8"))
            cur: Any = doc
            for part in str(sig.get("key") or "").split("."):
                if not part:
                    continue
                cur = cur.get(part) if isinstance(cur, dict) else None
            ts = _parse_ts(cur)
            return {"last_output_at": ts, "readable": True,
                    "detail": f"{p}#{sig.get('key')}={cur!r}"}

        if kind == "db_max":
            # Validate the DECLARATION before checking whether we can execute
            # it. Ordering these the other way round meant a malformed table
            # name was never reported in any context without a live connection,
            # which is most of them.
            table = str(sig.get("table") or "")
            col = str(sig.get("column") or "created_at")
            if not _SAFE_IDENT.match(table) or not _SAFE_IDENT.match(col):
                return {"last_output_at": None, "readable": False,
                        "detail": f"unsafe identifier {table}.{col}"}
            where = sig.get("where")
            if where and not _SAFE_WHERE.match(str(where)):
                return {"last_output_at": None, "readable": False,
                        "detail": f"unsafe where clause {where!r}"}
            if db_query is None:
                # We could not look. Reporting SILENT here would be a lie about a
                # store that may be perfectly healthy.
                return {"last_output_at": None, "readable": False,
                        "detail": "no db_query supplied"}
            sql = f"SELECT max({col}) FROM {table}"
            if where:
                sql += f" WHERE {where}"
            rows = db_query(sql)
            if rows is None:
                return {"last_output_at": None, "readable": False,
                        "detail": sql + " (query unavailable)"}
            val = rows[0][0] if rows and rows[0] else None
            return {"last_output_at": _parse_ts(val), "readable": True, "detail": sql}
    except Exception as e:                    # never let a signal read break a cycle
        return {"last_output_at": None, "readable": False,
                "detail": f"{type(e).__name__}: {e}"}
    return {"last_output_at": None, "readable": False,
            "detail": "no output signal declared"}


_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_WHERE = re.compile(r"^[A-Za-z0-9_ '\"=<>!.:%+\-()]*$")


# ── discovering what is actually scheduled ─────────────────────────────────

def discover_cron(text: Optional[str] = None) -> list[dict[str, Any]]:
    """Active (uncommented) crontab entries. A commented line is NOT a job."""
    if text is None:
        try:
            text = subprocess.run(["crontab", "-l"], capture_output=True,
                                  text=True, timeout=30).stdout
        except Exception:
            text = ""
    out: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" in s.split()[0] and not s[0].isdigit() and not s.startswith("*"):
            continue                          # CRON_TZ=... / PATH=... assignment
        out.append({"kind": "cron", "expression": s})
    return out


def discover_commented_cron(text: Optional[str] = None) -> list[dict[str, Any]]:
    """Commented-out entries, with whatever reason text they carry.

    This is the class that produced the unanswerable question: a commented line
    tagged only `PHASE102-RETIRED` records that something was turned off and
    nothing about why.
    """
    if text is None:
        try:
            text = subprocess.run(["crontab", "-l"], capture_output=True,
                                  text=True, timeout=30).stdout
        except Exception:
            text = ""
    out: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s.startswith("#"):
            continue
        body = s.lstrip("#").strip()
        if not re.match(r"^([A-Z0-9_]+\s+)?[\d*/,\-]+\s+[\d*/,\-]+\s+", body):
            # Not a schedule expression; look for an explicit retirement tag.
            if not _RETIRE_TAG.search(body):
                continue
        out.append({"kind": "cron_commented", "expression": body,
                    "tags": sorted(set(_RETIRE_TAG.findall(body)))})
    return out


_RETIRE_TAG = re.compile(
    r"(PHASE\d+-RETIRED|R9_DISABLED[A-Z_]*|RETIRED\s+\d{4}-\d{2}-\d{2}"
    r"|OFFPEAK_SOAK|DISABLED)")


def discover_systemd() -> list[dict[str, Any]]:
    """User timers, enabled and disabled alike. A disabled timer is a lane that
    was turned off — exactly the state this registry exists to make reportable."""
    out: list[dict[str, Any]] = []
    try:
        r = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "--type=timer", "--no-legend"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return out
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].endswith(".timer"):
            continue
        out.append({"kind": "systemd", "expression": parts[0],
                    "enabled_state": parts[1]})
    return out


def discover_all(*, cron_text: Optional[str] = None,
                 include_systemd: bool = True) -> dict[str, Any]:
    return {
        "cron": discover_cron(cron_text),
        "cron_commented": discover_commented_cron(cron_text),
        "systemd": discover_systemd() if include_systemd else [],
    }


# ── evaluating one lane ────────────────────────────────────────────────────

def _scheduler_present(row: dict[str, Any], found: dict[str, Any]) -> bool:
    """Does this lane's declared scheduler still exist?

    ORPHANED — a registry row whose scheduler is gone — is the verdict that
    would have caught the June retirement within one cadence period.
    """
    sched = row.get("scheduler") or {}
    kind, expr = sched.get("kind"), str(sched.get("expression") or "")
    if kind == "none":
        return False
    if kind == "systemd":
        return any(u["expression"] == expr for u in found.get("systemd") or [])
    if kind == "cron":
        marker = str(sched.get("match") or expr)
        return any(marker in c["expression"] for c in found.get("cron") or [])
    return False


def _within_declared_days(row: dict[str, Any], now: datetime) -> bool:
    """Weekend and market-closed cadences are declared, not inferred.

    A weekday-only lane must not alarm on a Sunday; a quiet system reports QUIET
    rather than paging.
    """
    days = row.get("active_days")
    if not days:
        return True
    # 0=Mon .. 6=Sun, matching datetime.weekday()
    return now.weekday() in set(int(d) for d in days)


def evaluate_lane(row: dict[str, Any], *, now: Optional[datetime] = None,
                  found: Optional[dict[str, Any]] = None,
                  root: Optional[Path] = None,
                  db_query: Any = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    found = found if found is not None else {"cron": [], "systemd": []}
    state = str(row.get("state") or STATE_ACTIVE)
    lane_id = str(row.get("lane_id") or "")

    obs = observe_signal(row.get("output_signal") or {}, root=root, db_query=db_query)
    last = obs["last_output_at"]
    cadence_h = float(row.get("expected_cadence_hours") or 0) or None
    age_h = round((now - last).total_seconds() / 3600.0, 2) if last else None

    sched_ok = _scheduler_present(row, found)
    in_window = _within_declared_days(row, now)

    # Order matters. A declared-off lane is never a finding, whatever its
    # scheduler or its silence — that is the whole point of declaring it.
    if state in SILENCE_EXPECTED:
        verdict = EXPECTED_SILENT
    elif not sched_ok:
        verdict = ORPHANED
    elif str((row.get("output_signal") or {}).get("kind")) == "none":
        verdict = UNVERIFIABLE
    elif not obs.get("readable", True):
        # We could not read the signal. This module's own docstring says reporting
        # that as SILENT is "how a monitor starts lying" -- but until now only
        # kind=="none" reached UNVERIFIABLE, so an unreachable database reported
        # every store SILENT. A false SILENT is worse than no verdict: it spends the
        # attention that a real one needs.
        verdict = UNVERIFIABLE
    elif last is None:
        verdict = SILENT if in_window else EXPECTED_SILENT
    elif cadence_h is None:
        verdict = LIVE
    elif age_h is not None and age_h <= cadence_h:
        verdict = LIVE
    elif age_h is not None and age_h <= 2 * cadence_h:
        verdict = SLOW
    else:
        verdict = SILENT if in_window else EXPECTED_SILENT

    return {
        "lane": lane_id,
        "lane_id": lane_id,
        "owner": row.get("owner"),
        "state": state,
        "state_reason": row.get("state_reason"),
        "state_since": row.get("state_since"),
        "review_by": row.get("review_by"),
        "verdict": verdict,
        "ok": verdict not in FINDING_VERDICTS,
        "firing": [verdict] if verdict in FINDING_VERDICTS else [],
        "scheduler": row.get("scheduler"),
        "scheduler_present": sched_ok,
        "expected_cadence_hours": cadence_h,
        "last_output_at": last.isoformat() if last else None,
        "output_age_hours": age_h,
        "output_signal_detail": obs["detail"],
        "in_declared_window": in_window,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
    }


def find_undeclared(reg: dict[str, Any], found: dict[str, Any]) -> list[dict[str, Any]]:
    """Scheduled jobs with no registry row, minus the inherited-debt baseline.

    The baseline is what makes the gate adoptable: green on day one, and it can
    only shrink. Same precedent as the dark-contract gate and the CI test
    coverage gate.
    """
    declared: set[str] = set()
    for row in reg.get("lanes") or []:
        sched = row.get("scheduler") or {}
        if sched.get("expression"):
            declared.add(str(sched["expression"]))
        if sched.get("match"):
            declared.add(str(sched["match"]))
    baseline = set(reg.get("undeclared_baseline") or [])

    out: list[dict[str, Any]] = []
    for unit in found.get("systemd") or []:
        expr = unit["expression"]
        if expr in declared or expr in baseline:
            continue
        out.append({"kind": "systemd", "expression": expr,
                    "enabled_state": unit.get("enabled_state")})
    for job in found.get("cron") or []:
        expr = job["expression"]
        if expr in baseline or any(d in expr for d in declared if d):
            continue
        out.append({"kind": "cron", "expression": expr})
    return out


# ── the report the monitor appends ─────────────────────────────────────────

def collect_lane_registry_report(*, now: Optional[datetime] = None,
                                 registry_path: Optional[Path] = None,
                                 root: Optional[Path] = None,
                                 cron_text: Optional[str] = None,
                                 db_query: Any = None,
                                 include_systemd: bool = True) -> dict[str, Any]:
    """One lane row for `research_lane_health`, summarising every declared lane.

    Shaped exactly like the existing collectors (`lane`, `ok`, `firing`) so it
    slots into `collect_report` without changing how anything downstream reads
    the report. This EXTENDS the monitor that already works; it is not a second
    monitor.
    """
    now = now or datetime.now(timezone.utc)
    reg = load_registry(registry_path)
    found = discover_all(cron_text=cron_text, include_systemd=include_systemd)

    rows = [evaluate_lane(r, now=now, found=found, root=root, db_query=db_query)
            for r in (reg.get("lanes") or [])]
    undeclared = find_undeclared(reg, found)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    if undeclared:
        counts[UNDECLARED] = len(undeclared)

    findings = [r for r in rows if r["verdict"] in FINDING_VERDICTS]
    firing = sorted({r["verdict"] for r in findings} | ({UNDECLARED} if undeclared else set()))

    return {
        "lane": "lane-registry",
        "ok": not firing,
        "firing": firing,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "declared": len(rows),
        "verdict_counts": counts,
        # A quiet system reports QUIET rather than paging.
        "summary": "QUIET" if not firing else ", ".join(
            f"{v}={counts.get(v, 0)}" for v in firing),
        "findings": findings,
        "undeclared": undeclared,
        "lanes": rows,
        "registry_path": str(registry_path or REGISTRY_PATH),
    }


# ── alert suppression: escalate on change, not on continuation ─────────────

def changed_findings(current: dict[str, Any], previous: Optional[dict[str, Any]]
                     ) -> list[dict[str, Any]]:
    """Only lanes whose verdict CHANGED since the last cycle.

    A lane silent for many cycles produces one alert, not one per cycle. A
    monitor that alerts every cycle gets muted, and a muted monitor is worse
    than none because it still looks like coverage.
    """
    prev = {}
    for r in ((previous or {}).get("lanes") or []):
        prev[str(r.get("lane_id") or r.get("lane"))] = r.get("verdict")
    out = []
    for r in current.get("lanes") or []:
        lid = str(r.get("lane_id") or r.get("lane"))
        if r["verdict"] in FINDING_VERDICTS and prev.get(lid) != r["verdict"]:
            out.append(r)
    return out
