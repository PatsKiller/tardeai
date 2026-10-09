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
import sqlite3
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
    elif sched.get("kind") == SCHEDULER_N8N and not sched.get("match"):
        # The workflow id alone cannot prove the host is clean: `match` keeps the retired cron
        # command text (or timer unit) so the double-scheduler conflict stays detectable.
        errs.append(f"{lane_id}: scheduler.match is required for kind=n8n (the retired cron "
                    "command text or timer unit, kept for host-conflict detection)")

    if state == STATE_ACTIVE and not row.get("expected_cadence_hours"):
        errs.append(f"{lane_id}: expected_cadence_hours is required when ACTIVE")

    # active_days is 0=Mon..6=Sun ints (docs/ops/LANE_REGISTRY_AND_RETIREMENT_CONVENTION.md).
    # A string like "Mon-Fri" iterates characters → int('M') and took down
    # collect_lane_registry_report entirely (stance observe lanes, 2026-09-20).
    days = row.get("active_days")
    if days is not None:
        if isinstance(days, str) or not isinstance(days, (list, tuple)):
            errs.append(
                f"{lane_id}: active_days must be a list of weekday ints 0-6 "
                f"(0=Mon..6=Sun), not {type(days).__name__} {days!r}"
            )
        else:
            for d in days:
                try:
                    di = int(d)
                except (TypeError, ValueError):
                    errs.append(
                        f"{lane_id}: active_days entries must be ints 0-6, "
                        f"got {d!r}"
                    )
                    break
                if di < 0 or di > 6:
                    errs.append(
                        f"{lane_id}: active_days entry {di} out of range 0-6"
                    )
                    break
    return errs


#: "event" is for a lane nothing schedules — another lane emits it. It has no
#: scheduler that could go missing, so it cannot earn ORPHANED, and its liveness
#: is judged purely on output freshness against its declared cadence. That is a
#: stronger signal for such a lane than scheduler presence, not a weaker one: if
#: the emitter stops, the lane goes SLOW and then SILENT on schedule.
#:
#: Added 2026-09-05 because cio-situation-detector was declared kind="cron" with
#: the prose expression "emitted from the reactive cycle / heartbeat hooks".
#: Matched against crontab it was never found, so the lane reported ORPHANED
#: permanently while its output was 0.21h old against a 24h cadence.
#: "n8n" (2026-10-08, scheduler-of-record program): the lane is fired by an n8n workflow through
#: the coordination gateway's run operation. Shape:
#:
#:   scheduler: {kind: "n8n", expression: "<n8n workflow id>",
#:               match: "<retired cron command text or timer unit>", cadence: "<cron expr>"}
#:
#: `expression` is the workflow id (what the monitor labels "n8n:<id>"); `match` is kept so
#: n8n_lane_host_conflict can flag the cron line / timer still being live beside the workflow
#: (CRON_PRESENT_WHILE_SCHEDULER_N8N / TIMER_ENABLED_WHILE_SCHEDULER_N8N). Scheduler presence is
#: proven by the run ledger / RunReceipt, never by n8n's own UI: a RUN_DONE (or RUN_SKIPPED_LOCK)
#: row for the lane within expected_cadence_hours, see `n8n_last_run`.
SCHEDULER_N8N = "n8n"
SCHEDULER_KINDS = ("cron", "systemd", "event", "none", SCHEDULER_N8N)
OUTPUT_SIGNAL_KINDS = ("file_mtime", "json_key", "db_max", "systemd_result", "none")


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

        if kind == "systemd_result":
            # A oneshot service whose only per-run artifact is its journal: last SUCCESSFUL exit.
            # Found 2026-09-27: cio-delivery and advisory-lessons-reflect write files only when they
            # have work, so a file signal reads "silent" on a healthy idle worker.
            import subprocess as _sp
            unit = str(sig.get("unit") or "")
            if not unit:
                return {"last_output_at": None, "readable": False, "detail": "systemd_result needs unit"}
            try:
                out = _sp.run(["systemctl", "--user", "show", unit, "-p", "Result", "-p", "ExecMainExitTimestamp"],
                              capture_output=True, text=True, timeout=10).stdout
            except Exception as exc:  # noqa: BLE001
                return {"last_output_at": None, "readable": False, "detail": f"systemctl failed: {type(exc).__name__}"}
            props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
            if props.get("Result") != "success":
                return {"last_output_at": None, "readable": True, "detail": f"{unit} Result={props.get('Result')!r}"}
            raw = props.get("ExecMainExitTimestamp", "").strip()
            try:
                from datetime import datetime as _dtc
                ts = _dtc.strptime(" ".join(raw.split()[1:3]), "%Y-%m-%d %H:%M:%S").astimezone(timezone.utc) if raw else None
            except Exception:  # noqa: BLE001
                ts = None
            return {"last_output_at": ts, "readable": bool(ts), "detail": f"{unit} success at {raw or 'unknown'}"}
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
        entry = {"kind": "cron_commented", "expression": body,
                 "tags": sorted(set(_RETIRE_TAG.findall(body)))}
        cut = n8n_cutover_tag(body)
        if cut:
            entry["retired_lane_id"] = cut["lane_id"]
            entry["retired_on"] = cut["date"]
        out.append(entry)
    return out


_RETIRE_TAG = re.compile(
    r"(PHASE\d+-RETIRED|R9_DISABLED[A-Z_]*|RETIRED\s+\d{4}-\d{2}-\d{2}"
    r"|n8n-cutover|OFFPEAK_SOAK|DISABLED)")

#: `# RETIRED <date> n8n-cutover <lane_id> <original line>` — written by
#: scripts/pipelines/cutover/_cutover.py --lane when a cron lane moves to n8n. The line is
#: commented, never deleted (§0 rail 6); the tag names the lane so rollback can find exactly it.
N8N_CUTOVER_TAG = re.compile(r"RETIRED\s+(\d{4}-\d{2}-\d{2})\s+n8n-cutover\s+(\S+)\s")


def n8n_cutover_tag(line: str) -> Optional[dict[str, str]]:
    """{date, lane_id} when a crontab line carries the n8n-cutover retirement tag, else None."""
    m = N8N_CUTOVER_TAG.search(str(line or ""))
    if not m:
        return None
    return {"date": m.group(1), "lane_id": m.group(2)}


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
                 include_systemd: bool = True,
                 include_n8n: Optional[bool] = None) -> dict[str, Any]:
    out = {
        "cron": discover_cron(cron_text),
        "cron_commented": discover_commented_cron(cron_text),
        "systemd": discover_systemd() if include_systemd else [],
    }
    if include_n8n is None:
        include_n8n = os.environ.get(N8N_DISCOVERY_ENV, "") == "1"
    if include_n8n:
        try:
            out["n8n"] = discover_n8n_live()
        except Exception as exc:   # noqa: BLE001 — could-not-look is a note, never "nothing there"
            out["n8n_unavailable"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


# ── n8n as a scheduler source (AGENTS.md 3.0.0 §23.10 P17, audit C G10) ────────────────────────────
#
# An ACTIVE n8n workflow schedules host work exactly like a crontab line, so it is discovered the same
# way: one discovery row per active workflow, keyed by its id. It is declared when a registry row names
# that id as scheduler.expression (kind n8n) or when the id is one the workflow generator emitted
# (docs/implementation/n8n-parallel/workflows/generated/INDEX.json, live and shadow ids — the allowlist
# of known ids). Anything else is UNDECLARED_N8N_WORKFLOW and fails `check_lane_registry --fail-on-new`.
# The live read is a single SELECT through `docker exec` (scripts/lib/n8n_live_inventory.py); CI reads
# the committed snapshot instead. The lane monitor reads live only when TRADEAI_LANE_REGISTRY_N8N=1.

N8N_DISCOVERY_ENV = "TRADEAI_LANE_REGISTRY_N8N"
UNDECLARED_N8N_WORKFLOW = "UNDECLARED_N8N_WORKFLOW"


def discover_n8n_live(**kw: Any) -> list[dict[str, Any]]:
    try:
        from scripts.lib import n8n_live_inventory as inv
    except ImportError:                                   # imported as lib.lane_registry
        from lib import n8n_live_inventory as inv  # type: ignore
    return inv.discover_n8n(inv.read_active_workflows(**kw))


def discover_n8n_snapshot(path: Optional[Path] = None) -> list[dict[str, Any]]:
    try:
        from scripts.lib import n8n_live_inventory as inv
    except ImportError:
        from lib import n8n_live_inventory as inv  # type: ignore
    return inv.discover_n8n(inv.load_active_snapshot(path))


def n8n_known_workflow_ids(index_path: Optional[Path] = None) -> dict[str, str]:
    try:
        from scripts.lib import n8n_live_inventory as inv
    except ImportError:
        from lib import n8n_live_inventory as inv  # type: ignore
    return inv.known_workflow_ids(path=index_path)


# ── evaluating one lane ────────────────────────────────────────────────────

# ── n8n scheduler-of-record evidence ───────────────────────────────────────
#
# Shared contract with the run executor (scripts/n8n_run_executor.py, stream B): the ledger is
# `$TRADEAI_STATE_ROOT/data/governance/n8n_coordination_ledger.sqlite`, table `runs(run_id, lane_id,
# mode, state, requested_by, caller_id, requested_at, started_at, finished_at, exit_code,
# duration_s, receipt_json)`; receipts are `data/runtime/n8n_runs/<run_id>.json` (RunReceipt@v1:
# lane_id, mode, exit_code, finished_at, state). Read-only here, always.

N8N_LEDGER_REL = Path("data") / "governance" / "n8n_coordination_ledger.sqlite"
N8N_RUNS_REL = Path("data") / "runtime" / "n8n_runs"
N8N_RUN_STATES_PRESENT = ("RUN_DONE", "RUN_SKIPPED_LOCK")


def n8n_ledger_path(root: Optional[Path] = None) -> Path:
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    return (Path(root) if root else state_root()) / N8N_LEDGER_REL


def n8n_runs_dir(root: Optional[Path] = None) -> Path:
    return (Path(root) if root else state_root()) / N8N_RUNS_REL


def _n8n_last_run_from_ledger(lane_id: str, path: Path,
                              states: Iterable[str]) -> Optional[dict[str, Any]]:
    """Newest finished run for the lane in the given states, or None. Never raises, never writes."""
    if not path.is_file():
        return None
    st = tuple(states)                   # empty = any state
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            where = "lane_id = ? AND finished_at IS NOT NULL"
            if st:
                where += " AND state IN (%s)" % ",".join("?" * len(st))
            q = ("SELECT run_id, lane_id, mode, state, finished_at, exit_code FROM runs "
                 f"WHERE {where} ORDER BY finished_at DESC LIMIT 1")
            row = conn.execute(q, (lane_id, *st)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None                      # absent table / locked / not a db: fall back to receipts
    if row is None:
        return None
    return {"run_id": row["run_id"], "mode": row["mode"], "state": row["state"],
            "finished_at": row["finished_at"], "exit_code": row["exit_code"],
            "source": "ledger", "detail": str(path)}


def _n8n_last_run_from_receipts(lane_id: str, folder: Path,
                                states: Iterable[str]) -> Optional[dict[str, Any]]:
    st = set(states)
    best: Optional[dict[str, Any]] = None
    best_ts: Optional[datetime] = None
    if not folder.is_dir():
        return None
    for p in folder.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or str(doc.get("lane_id") or "") != lane_id:
            continue
        if st and str(doc.get("state") or "") not in st:
            continue
        ts = _parse_ts(doc.get("finished_at"))
        if ts is None:
            continue
        if best_ts is None or ts > best_ts:
            best_ts = ts
            best = {"run_id": doc.get("run_id") or p.stem, "mode": doc.get("mode"),
                    "state": doc.get("state"), "finished_at": doc.get("finished_at"),
                    "exit_code": doc.get("exit_code"), "source": "receipt", "detail": str(p)}
    return best


def n8n_last_run(lane_id: str, *, root: Optional[Path] = None,
                 states: Iterable[str] = N8N_RUN_STATES_PRESENT) -> Optional[dict[str, Any]]:
    """The newest finished n8n run for a lane: the ledger first, else the newest RunReceipt file.

    None when neither exists — the lane has no scheduler-of-record evidence and is ORPHANED.
    """
    states = tuple(states)
    hit = _n8n_last_run_from_ledger(lane_id, n8n_ledger_path(root), states)
    if hit is None:
        hit = _n8n_last_run_from_receipts(lane_id, n8n_runs_dir(root), states)
    return hit


def scheduler_label(sched: Optional[dict[str, Any]]) -> str:
    """`kind:expression` — what the lane monitor prints; an n8n lane reads `n8n:<workflow id>`."""
    sched = sched or {}
    kind = str(sched.get("kind") or "none")
    expr = str(sched.get("expression") or "")
    return f"{kind}:{expr}" if expr else kind


#: What the monitor prints for an n8n lane's scheduler presence. FRESH/ORPHANED is READ from
#: `scheduler_present`, which `_scheduler_present` decided against expected_cadence_hours; the
#: renderers below never re-derive it (observability gaps PR, 2026-10-08).
N8N_FRESH = "FRESH"


def n8n_last_run_label(last: Optional[dict[str, Any]]) -> str:
    """`mode/state finished_at` for the newest n8n run a report row carries, or the reason there is none."""
    if not last:
        return "no run (no ledger row, no RunReceipt)"
    return (f"{last.get('mode') or '?'}/{last.get('state') or '?'} "
            f"{last.get('finished_at') or '?'}")


def lane_scheduler_text(row: dict[str, Any]) -> str:
    """The scheduler column of a lane row from `evaluate_lane`.

    A cron/systemd lane reads `cron:<expr>`; an n8n lane reads `n8n:<workflow id>` plus its last
    run (mode/state/finished_at) and FRESH or ORPHANED — the cron expression it retired is not
    the scheduler any more, so printing it would be a lie about who fires the lane.
    """
    label = str(row.get("scheduler_label") or scheduler_label(row.get("scheduler")))
    if str((row.get("scheduler") or {}).get("kind") or "") != SCHEDULER_N8N:
        return label
    fresh = N8N_FRESH if row.get("scheduler_present") else ORPHANED
    cadence = row.get("expected_cadence_hours")
    within = f" within {cadence}h" if cadence else ""
    return f"{label} last {n8n_last_run_label(row.get('n8n_last_run'))} [{fresh}{within}]"


def format_lane_line(row: dict[str, Any]) -> str:
    """One text line per evaluated lane: id, verdict, scheduler (see `lane_scheduler_text`), output age."""
    age = row.get("output_age_hours")
    cadence = row.get("expected_cadence_hours")
    out = f"output {age}h" + (f"/{cadence}h" if cadence else "") if age is not None else "output none"
    return f"{str(row.get('lane_id') or row.get('lane') or ''):<36} {str(row.get('verdict') or ''):<16} {lane_scheduler_text(row)}  {out}"


def render_lane_table(rows: Iterable[dict[str, Any]]) -> str:
    """The lane-monitor text surface: every row from `collect_lane_registry_report()["lanes"]`."""
    return "\n".join(format_lane_line(r) for r in rows)


def _scheduler_present(row: dict[str, Any], found: dict[str, Any], *,
                       now: Optional[datetime] = None,
                       root: Optional[Path] = None) -> bool:
    """Does this lane's declared scheduler still exist?

    ORPHANED — a registry row whose scheduler is gone — is the verdict that
    would have caught the June retirement within one cadence period.
    """
    sched = row.get("scheduler") or {}
    kind, expr = sched.get("kind"), str(sched.get("expression") or "")
    if kind == "none":
        return False
    if kind == SCHEDULER_N8N:
        # n8n is not on this host; its UI is not evidence. The scheduler "exists" when the run
        # ledger (or a RunReceipt) shows it fired the lane within one cadence.
        last = n8n_last_run(str(row.get("lane_id") or ""), root=root)
        if last is None:
            return False
        ts = _parse_ts(last.get("finished_at"))
        if ts is None:
            return False
        cadence_h = float(row.get("expected_cadence_hours") or 0) or None
        if cadence_h is None:
            return True
        now = now or datetime.now(timezone.utc)
        return (now - ts) <= timedelta(hours=cadence_h)
    if kind == "systemd":
        return any(u["expression"] == expr for u in found.get("systemd") or [])
    if kind == "cron":
        marker = str(sched.get("match") or expr)
        return any(marker in c["expression"] for c in found.get("cron") or [])
    if kind == "event":
        # Hook-driven: nothing schedules it, another lane emits it. There is no
        # scheduler to be missing, so ORPHANED is not a verdict this lane can
        # earn and asking the question produces a permanent false positive.
        #
        # Measured 2026-09-05: cio-situation-detector was declared kind="cron"
        # with the expression "emitted from the reactive cycle / heartbeat
        # hooks" — prose, matched against crontab, never found. It reported
        # ORPHANED while its output was 0.21h old against a 24h cadence.
        #
        # This is not a hole. An event-driven lane is still judged on output
        # freshness, which is the ONLY meaningful liveness signal for it and a
        # stronger one than scheduler presence: if the emitter stops, the lane
        # goes SLOW and then SILENT on its declared cadence.
        return True
    return False


def _within_declared_days(row: dict[str, Any], now: datetime) -> bool:
    """Weekend and market-closed cadences are declared, not inferred.

    A weekday-only lane must not alarm on a Sunday; a quiet system reports QUIET
    rather than paging.

    ``active_days`` must be a list of ints 0=Mon..6=Sun. A string form such as
    ``"Mon-Fri"`` is invalid: iterating it yields characters and ``int('M')``
    raises — which previously aborted the whole lane-registry report.
    """
    days = row.get("active_days")
    if not days:
        return True
    if isinstance(days, str) or not isinstance(days, (list, tuple)):
        raise ValueError(
            f"active_days must be a list of weekday ints 0-6, got {days!r}"
        )
    # 0=Mon .. 6=Sun, matching datetime.weekday()
    return now.weekday() in {int(d) for d in days}


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

    sched_ok = _scheduler_present(row, found, now=now, root=root)
    try:
        in_window = _within_declared_days(row, now)
        days_err: Optional[str] = None
    except (TypeError, ValueError) as exc:
        # A bad declaration must not abort collect_lane_registry_report.
        # UNVERIFIABLE (not SILENT): we could not judge the window, not silence.
        in_window = True
        days_err = str(exc)

    # Order matters. A declared-off lane is never a finding, whatever its
    # scheduler or its silence — that is the whole point of declaring it.
    if state in SILENCE_EXPECTED:
        verdict = EXPECTED_SILENT
    elif days_err is not None:
        verdict = UNVERIFIABLE
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

    out = {
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
        "scheduler_label": scheduler_label(row.get("scheduler")),
        "scheduler_present": sched_ok,
        "expected_cadence_hours": cadence_h,
        "last_output_at": last.isoformat() if last else None,
        "output_age_hours": age_h,
        "output_signal_detail": obs["detail"],
        "in_declared_window": in_window,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
    }
    if days_err is not None:
        out["active_days_error"] = days_err
    if str((row.get("scheduler") or {}).get("kind")) == SCHEDULER_N8N:
        # Any-state newest run too, so a RUN_FAILED lane reads as "n8n fired and failed" in the
        # report rather than as a bare ORPHANED.
        out["n8n_last_run"] = n8n_last_run(lane_id, root=root, states=())
    return out


_BARE_CRON_SCHEDULE = re.compile(r"^\s*(?:[\d*/,\-]+\s+){4}[\d*/,\-]+\s*$")


def find_undeclared(reg: dict[str, Any], found: dict[str, Any], *,
                    n8n_known_ids: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
    """Scheduled jobs with no registry row, minus the inherited-debt baseline.

    The baseline is what makes the gate adoptable: green on day one, and it can
    only shrink. Same precedent as the dark-contract gate and the CI test
    coverage gate.

    n8n (P17): an active workflow id is declared by a kind-n8n row's expression or
    by the generated INDEX (``n8n_known_ids``; loaded from the committed INDEX when
    None). The inherited baseline does NOT apply to n8n — there is no n8n debt.
    """
    declared: set[str] = set()
    for row in reg.get("lanes") or []:
        sched = row.get("scheduler") or {}
        expr = str(sched.get("expression") or "")
        # Live-proof 2026-09-28 (LP-DEF-19): a bare cron schedule ("5 * * * *") is not a pattern — as a
        # substring it declared every line that happened to share the minute field and hid five
        # unregistered crons. A lane whose expression is only a schedule must name its script in `match`.
        if expr and not _BARE_CRON_SCHEDULE.match(expr):
            declared.add(expr)
        if sched.get("match"):
            declared.add(str(sched["match"]))
    baseline = set(reg.get("undeclared_baseline") or [])
    # Dated inherited tranches (2026-09-28): lines installed on the host by other work with no
    # lane row, recorded WITH provenance instead of growing the original baseline. Same contract:
    # they are debt, they only shrink, and a line is removed once it is declared as a lane.
    for tranche in reg.get("inherited_tranches") or []:
        baseline.update(str(x) for x in (tranche.get("lines") or []))

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
    n8n_rows = found.get("n8n") or []
    if n8n_rows:
        n8n_declared = {str((r.get("scheduler") or {}).get("expression") or "")
                        for r in reg.get("lanes") or []
                        if (r.get("scheduler") or {}).get("kind") == SCHEDULER_N8N}
        known = set(n8n_known_ids) if n8n_known_ids is not None else set(n8n_known_workflow_ids())
        for wf in n8n_rows:
            wid = str(wf.get("expression") or "")
            if wid and (wid in n8n_declared or wid in known):
                continue
            out.append({"kind": "n8n", "expression": wid, "name": str(wf.get("name") or ""),
                        "code": UNDECLARED_N8N_WORKFLOW})
    return out


#: An ACTIVE kind-n8n row whose workflow is not active in n8n (2026-10-09 audit: n8n-monitor-trade-ai and
#: n8n-monitor-dof were deactivated 13:04Z yet the registry still said ACTIVE and the gate printed "clean").
INACTIVE_N8N_WORKFLOW = "INACTIVE_N8N_WORKFLOW"


def find_inactive_n8n_rows(reg: dict[str, Any], found: dict[str, Any]) -> list[dict[str, Any]]:
    """ACTIVE kind-n8n rows whose workflow id is absent from the active-workflow discovery.

    Only meaningful when n8n was actually looked at (``"n8n" in found``); with no n8n source the
    answer is "not measured", never "all fine", so this returns [] and the caller reports the source.
    """
    if "n8n" not in found:
        return []
    active_ids = {str(wf.get("expression") or "") for wf in found.get("n8n") or []}
    out: list[dict[str, Any]] = []
    for row in reg.get("lanes") or []:
        sched = row.get("scheduler") or {}
        if row.get("state") != STATE_ACTIVE or sched.get("kind") != SCHEDULER_N8N:
            continue
        wid = str(sched.get("expression") or "")
        if wid not in active_ids:
            out.append({"lane_id": row.get("lane_id"), "expression": wid, "code": INACTIVE_N8N_WORKFLOW})
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
        # P17: whether n8n was looked at, and why not when it could not be (never "nothing there").
        "n8n_discovery": ("unavailable: " + found["n8n_unavailable"]) if found.get("n8n_unavailable")
                         else ("live" if "n8n" in found else "off"),
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


def lane_state_for_command(cmd: str, reg: dict[str, Any] | None = None) -> dict[str, Any]:
    """The registry lane that owns the script a command runs, and its state.

    R-15 (2026-09-26): the health agent's remediation allowlist could run
    `scripts/cio_decision_engine.py`, whose lane is PAUSED with an UNKNOWN reason.
    A remediation must not resurrect a paused or retired lane. Returns
    {"lane_id", "state", "matched"}; state None when no lane owns the script.
    """
    import re as _re
    reg = reg or load_registry()
    scripts = set(_re.findall(r"scripts/[\w/-]+\.(?:py|sh)", str(cmd or "")))
    for row in reg.get("lanes") or []:
        sched = row.get("scheduler") or {}
        blob = " ".join(str(sched.get(k) or "") for k in ("expression", "match")) + " " + str(row.get("entrypoint") or "")
        for sc in scripts:
            if sc in blob:
                return {"lane_id": row.get("lane_id"), "state": str(row.get("state") or "").upper(), "matched": sc}
    return {"lane_id": None, "state": None, "matched": None}


PAUSED_OR_RETIRED = frozenset({"PAUSED", "RETIRED", "NEVER_SCHEDULED"})


# ── N8N Maturity B5.2: dispatch/watch blocks live in lane_dispatch.py (design 02 §2); re-exported here ──
try:
    from scripts.lib.lane_dispatch import dispatch_eligible, dispatch_mode, parse_dispatch_block, parse_watch_block, validate_dispatch_block  # noqa: E402,F401
except ImportError:                                       # imported as lib.lane_registry
    from lib.lane_dispatch import dispatch_eligible, dispatch_mode, parse_dispatch_block, parse_watch_block, validate_dispatch_block  # type: ignore # noqa: E402,F401
