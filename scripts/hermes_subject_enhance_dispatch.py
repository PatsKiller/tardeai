#!/usr/bin/env python3
"""hermes_subject_enhance_dispatch.py — one crontab line for the six hermes_subject_enhance subjects
(cron consolidation tranche C, rank 9).

Today (crontab lines 477-482, read 2026-10-07) six lines each call scripts/hermes_subject_enhance.py
with `--lanes grok,chatgpt --apply` on the paid OAuth lanes:

    */30 9-16 * * 1-5  flock -n /tmp/enh_scalp.lock   … --type scalp        --lanes grok,chatgpt --apply --limit 10
    */20 9-16 * * 1-5  flock -n /tmp/enh_prop.lock    … --type proposal     --lanes grok,chatgpt --apply
    20 */2 * * *       llm_priority_guard.sh && flock -n /tmp/enh_pos.lock    … --type position     --lanes grok,chatgpt --apply
    25 11,14 * * 1-5   llm_priority_guard.sh && flock -n /tmp/enh_sec.lock    … --type sector       --lanes grok,chatgpt --apply --limit 11
    40 16 * * 1-5      flock -n /tmp/enh_ct.lock      … --type closed_trade --lanes grok,chatgpt --apply --limit 12
    0 8,20 * * *       llm_priority_guard.sh && flock -n /tmp/enh_report.lock … --type report       --lanes grok,chatgpt --apply --limit 1

Whenever two of those minutes coincide (every :00 in 09-16 is scalp+proposal; :20 at even hours is
proposal+position; 16:40 is proposal+closed_trade) the subjects run CONCURRENTLY against the same two
OAuth lanes. This dispatcher keeps every cadence, window, minute phase, lock, guard and argv exactly as
above, but runs the subjects due at a firing ONE AFTER THE OTHER (table order), so no two subject
processes hit grok/chatgpt at once.

Due computation: a subject is due when one of its scheduled minutes falls inside the window
(watermark, now], where the watermark is the previous apply receipt's window_end (capped by
--max-lookback-min). A firing that had to wait for a long predecessor therefore still runs what came
due while it waited, and a firing that was skipped is caught up by the next one; a subject runs at most
once per firing however many of its minutes fell in the window (hermes_subject_enhance's own freshness
check already dedupes at the subject level).

Proposed crontab line (NOT installed by this PR; see docs/implementation/n8n-parallel/proposals/cron-tranche-c-lowrisk.md):

    0,20,25,30,40 * * * * cd $PROJ && $PY scripts/hermes_subject_enhance_dispatch.py --apply >> logs/hermes_subject_enhance_dispatch.log 2>&1  # TRADEAI_LANE hermes-subject-enhance-dispatch

That is the union of the six minute phases (0,20,25,30,40) over every hour (position runs at :20 of even
hours round the clock; report at 08:00 and 20:00). A firing at which nothing is due exits in milliseconds
with a NOTHING_DUE receipt and calls no LLM.

    python3 scripts/hermes_subject_enhance_dispatch.py                         # plan: what is due this minute
    python3 scripts/hermes_subject_enhance_dispatch.py --now 2026-10-07T09:00  # plan for a given minute
    python3 scripts/hermes_subject_enhance_dispatch.py --stats                 # weekly firings + same-minute collisions, today vs dispatched
    python3 scripts/hermes_subject_enhance_dispatch.py --apply                 # run the due subjects sequentially

Receipt: $TRADEAI_STATE_ROOT/data/runtime/hermes_subject_enhance_dispatch_last.json (HermesSubjectEnhanceDispatchReceipt@v1)
Env:     PY (interpreter for the subject runs; default sys.executable), TRADEAI_STATE_ROOT.

AUTHORITY: READ_ONLY_ADVISORY. The dispatcher sequences existing advisory jobs; it never touches orders,
stops, holdings or a broker. Lane registry: hermes-subject-enhance-dispatch (NEVER_SCHEDULED).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.atomic_json_store import atomic_write_json  # noqa: E402

SCHEMA = "HermesSubjectEnhanceDispatchReceipt@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
LANE = "hermes-subject-enhance-dispatch"
NO_CONSUMER_REASON = (
    "Cron consolidation tranche C (rank 9): the one-line sequential replacement for the six "
    "hermes_subject_enhance crontab lines (scalp, proposal, position, sector, closed_trade, report). "
    "Proposal only -- not installed; the operator installs the single line under a cron grant and deletes the "
    "six lines after two observed cycles. Its receipt is the lane's output_signal."
)

DISPATCH_LOCK = "/tmp/hermes_subject_enhance_dispatch.lock"
LOCK_CONFLICT_RC = 75             # flock -E 75: a held subject lock is typed, not a failure
WEEKDAYS = [0, 1, 2, 3, 4]        # cron 1-5 == Python weekday() Mon..Fri
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
LANES = "grok,chatgpt"
SUBJECT_SCRIPT = "scripts/hermes_subject_enhance.py"
SHARED_LOG = "logs/hermes_enh.log"
GUARD_SCRIPT = "scripts/llm_priority_guard.sh"

# Order == run order when several subjects fall due at the same minute.
DEFAULT_TABLE: list[dict[str, Any]] = [
    {"subject": "scalp", "today": "*/30 9-16 * * 1-5", "minutes": [0, 30], "hours": list(range(9, 17)), "dows": WEEKDAYS,
     "lock": "/tmp/enh_scalp.lock", "guard": False,
     "args": ["--type", "scalp", "--lanes", LANES, "--apply", "--limit", "10"]},
    {"subject": "proposal", "today": "*/20 9-16 * * 1-5", "minutes": [0, 20, 40], "hours": list(range(9, 17)), "dows": WEEKDAYS,
     "lock": "/tmp/enh_prop.lock", "guard": False,
     "args": ["--type", "proposal", "--lanes", LANES, "--apply"]},
    {"subject": "position", "today": "20 */2 * * *", "minutes": [20], "hours": list(range(0, 24, 2)), "dows": ALL_DAYS,
     "lock": "/tmp/enh_pos.lock", "guard": True,
     "args": ["--type", "position", "--lanes", LANES, "--apply"]},
    {"subject": "sector", "today": "25 11,14 * * 1-5", "minutes": [25], "hours": [11, 14], "dows": WEEKDAYS,
     "lock": "/tmp/enh_sec.lock", "guard": True,
     "args": ["--type", "sector", "--lanes", LANES, "--apply", "--limit", "11"]},
    {"subject": "closed_trade", "today": "40 16 * * 1-5", "minutes": [40], "hours": [16], "dows": WEEKDAYS,
     "lock": "/tmp/enh_ct.lock", "guard": False,
     "args": ["--type", "closed_trade", "--lanes", LANES, "--apply", "--limit", "12"]},
    {"subject": "report", "today": "0 8,20 * * *", "minutes": [0], "hours": [8, 20], "dows": ALL_DAYS,
     "lock": "/tmp/enh_report.lock", "guard": True,
     "args": ["--type", "report", "--lanes", LANES, "--apply", "--limit", "1"]},
]


def state_root(env: Optional[dict] = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def served_sha() -> Optional[str]:
    explicit = os.environ.get("TRADEAI_SERVED_SHA")
    if explicit:
        return explicit.strip()
    try:
        return (Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "GIT_SHA").read_text().strip()
    except OSError:
        return None


# ── due computation (pure) ────────────────────────────────────────────────────

def union_minutes(table: list[dict[str, Any]]) -> list[int]:
    """The minute phases the one cron line must fire on: the union of every subject's minutes."""
    return sorted({int(m) for s in table for m in s["minutes"]})


def matches(subject: dict[str, Any], t: datetime) -> bool:
    """Does this subject's crontab schedule match minute t (local time, same as cron)?"""
    return (t.minute in subject["minutes"] and t.hour in subject["hours"] and t.weekday() in subject["dows"])


def due_subjects(table: list[dict[str, Any]], now: datetime, since: Optional[datetime] = None,
                 max_lookback_min: int = 60) -> list[dict[str, Any]]:
    """Subjects with a scheduled minute in (since, now] (floored to minutes), table order, once each.

    since=None → just the current minute, which is what a cron firing that is on time sees.
    The lookback is capped so that a long outage does not replay a day of subjects at once.
    """
    end = now.replace(second=0, microsecond=0)
    if since is None:
        start = end - timedelta(minutes=1)
    else:
        start = since.replace(second=0, microsecond=0)
        floor = end - timedelta(minutes=max_lookback_min)
        if start < floor:
            start = floor
        if start >= end:
            start = end - timedelta(minutes=1)
    out = []
    for s in table:
        hit = []
        t = start + timedelta(minutes=1)
        while t <= end:
            if matches(s, t):
                hit.append(t.strftime("%H:%M"))
            t += timedelta(minutes=1)
        if hit:
            out.append({"subject": s["subject"], "matched_minutes": hit})
    return out


def weekly_firings(table: list[dict[str, Any]]) -> dict[str, Any]:
    """Firings per week today (one process per cron line match) vs under the dispatcher, and the
    same-minute collisions the six lines produce (two or more subjects starting in the same minute)."""
    per_subject = {s["subject"]: 0 for s in table}
    collisions = 0
    concurrent_pairs = 0
    dispatcher = 0
    fire_minutes = set(union_minutes(table))
    base = datetime(2026, 10, 5)          # a Monday; any week is the same
    t = base
    while t < base + timedelta(days=7):
        hits = [s["subject"] for s in table if matches(s, t)]
        for h in hits:
            per_subject[h] += 1
        if len(hits) >= 2:
            collisions += 1
            concurrent_pairs += len(hits) * (len(hits) - 1) // 2
        if t.minute in fire_minutes:
            dispatcher += 1
        t += timedelta(minutes=1)
    return {"today_lines": len(table), "today_subject_firings_per_week": sum(per_subject.values()),
            "per_subject": per_subject, "same_minute_collisions_per_week": collisions,
            "concurrent_subject_pairs_per_week": concurrent_pairs, "dispatcher_lines": 1,
            "dispatcher_firings_per_week": dispatcher, "dispatcher_minutes": sorted(fire_minutes),
            "dispatcher_subject_runs_per_week": sum(per_subject.values()), "dispatched_collisions_per_week": 0}


# ── execution ────────────────────────────────────────────────────────────────

def subject_argv(s: dict[str, Any], py: str) -> list[str]:
    inner = list(s["cmd"]) if s.get("cmd") else [py, SUBJECT_SCRIPT, *s["args"]]
    return ["flock", "-n", "-E", str(LOCK_CONFLICT_RC), s["lock"], *inner]


def guard_argv(s: dict[str, Any], root: Path) -> Optional[list[str]]:
    if not s.get("guard"):
        return None
    return list(s["guard_cmd"]) if s.get("guard_cmd") else ["bash", str(root / GUARD_SCRIPT)]


def run_subject(s: dict[str, Any], root: Path, env: dict[str, str], log_path: Path, timeout_s: Optional[float],
                matched: list[str]) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    row: dict[str, Any] = {"subject": s["subject"], "lock": s["lock"], "matched_minutes": matched,
                           "started_at": started.isoformat(), "rc": None, "outcome": None, "duration_s": None}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("ab") as fh:
            fh.write(f"[{started.isoformat()}] dispatch subject={s['subject']} start matched={','.join(matched)}\n".encode())
            fh.flush()
            g = guard_argv(s, root)
            if g is not None:
                gp = subprocess.run(g, cwd=str(root), env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=60)
                if gp.returncode != 0:            # exactly the crontab's `guard && job`: deferred to the next out-of-window tick
                    row["rc"] = gp.returncode
                    row["outcome"] = "DEFERRED_GUARD"
                    row["duration_s"] = round(time.monotonic() - t0, 3)
                    return row
            try:
                cp = subprocess.run(subject_argv(s, env.get("PY") or sys.executable), cwd=str(root), env=env,
                                    stdout=fh, stderr=subprocess.STDOUT, timeout=timeout_s or None)
                row["rc"] = cp.returncode
            except subprocess.TimeoutExpired:
                row["outcome"] = "TIMEOUT"
                fh.write(f"[{datetime.now(timezone.utc).isoformat()}] dispatch subject={s['subject']} TIMEOUT after {timeout_s}s\n".encode())
    except (OSError, subprocess.TimeoutExpired) as exc:
        row["outcome"] = "SPAWN_FAILED"
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["duration_s"] = round(time.monotonic() - t0, 3)
    if row["outcome"] is None:
        row["outcome"] = "RAN" if row["rc"] == 0 else ("LOCK_HELD" if row["rc"] == LOCK_CONFLICT_RC else "FAILED")
    return row


def load_table(path: Optional[str]) -> list[dict[str, Any]]:
    if not path:
        return [dict(s) for s in DEFAULT_TABLE]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("table") if isinstance(data, dict) else data
    out = []
    for s in rows or []:
        for k in ("subject", "minutes", "hours", "dows", "lock"):
            if k not in s:
                raise SystemExit(f"manifest subject needs {k}: {s}")
        if not (s.get("args") or s.get("cmd")):
            raise SystemExit(f"manifest subject needs args or cmd: {s}")
        out.append(dict(s))
    return out


def previous_window_end(receipt_path: Path) -> Optional[datetime]:
    try:
        prev = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if prev.get("schema") != SCHEMA or prev.get("mode") != "apply" or not prev.get("window_end"):
        return None
    try:
        return datetime.fromisoformat(prev["window_end"])
    except ValueError:
        return None


def _parse_local(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    t = datetime.fromisoformat(s)
    return t.replace(tzinfo=None) if t.tzinfo is None else t.astimezone().replace(tzinfo=None)


def acquire_dispatch_lock(path: str, wait_s: float):
    """Blocking with a bound: a firing waits for a long predecessor instead of dropping its subjects."""
    fh = open(path, "a+")
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.monotonic() >= deadline:
                fh.close()
                return None
            time.sleep(min(2.0, max(0.05, deadline - time.monotonic())))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the due hermes_subject_enhance subjects one after the other")
    ap.add_argument("--apply", action="store_true", help="run the due subjects (default: print the plan only)")
    ap.add_argument("--now", default=None, help="local minute to evaluate (ISO, e.g. 2026-10-07T09:00); default: now")
    ap.add_argument("--since", default=None, help="window start (ISO local); default: the previous apply receipt's window_end")
    ap.add_argument("--max-lookback-min", type=int, default=60)
    ap.add_argument("--subject-timeout-s", type=float, default=1800.0,
                    help="wall clock per subject run; 0 = none. NEW vs the crontab lines (which had none): a hung "
                         "subject must not hold the sequence forever")
    ap.add_argument("--lock-wait-s", type=float, default=900.0, help="how long a firing waits for the previous firing")
    ap.add_argument("--manifest", default=None, help="JSON {table:[…]} replacing the built-in due-table (tests)")
    ap.add_argument("--root", default=None, help="working directory for subject runs (default: this checkout)")
    ap.add_argument("--log", default=None, help=f"shared subject log (default: <root>/{SHARED_LOG})")
    ap.add_argument("--dispatch-lock", default=DISPATCH_LOCK)
    ap.add_argument("--receipt", default=None)
    ap.add_argument("--stats", action="store_true", help="print weekly firings/collisions today vs dispatched and exit")
    args = ap.parse_args(argv)

    table = load_table(args.manifest)
    if args.stats:
        print(json.dumps(weekly_firings(table), indent=1))
        return 0

    root = Path(args.root).resolve() if args.root else ROOT
    log_path = Path(args.log) if args.log else root / SHARED_LOG
    receipt_path = Path(args.receipt) if args.receipt else state_root() / "data" / "runtime" / "hermes_subject_enhance_dispatch_last.json"
    now = _parse_local(args.now) or datetime.now()
    since_src = "arg" if args.since else "none"
    since = _parse_local(args.since)
    if since is None and args.apply:
        since = previous_window_end(receipt_path)
        since_src = "receipt" if since else "none"
    due = due_subjects(table, now, since, args.max_lookback_min)
    end = now.replace(second=0, microsecond=0)
    window_start = (since if since else end - timedelta(minutes=1)).replace(second=0, microsecond=0)
    if window_start < end - timedelta(minutes=args.max_lookback_min):
        window_start = end - timedelta(minutes=args.max_lookback_min)
    by_name = {s["subject"]: s for s in table}

    if not args.apply:
        print(json.dumps({"schema": SCHEMA, "mode": "plan", "now": end.isoformat(), "window_start": window_start.isoformat(),
                          "window_end": end.isoformat(), "since_source": since_src, "union_minutes": union_minutes(table),
                          "due": [{**d, "lock": by_name[d["subject"]]["lock"], "guard": bool(by_name[d["subject"]].get("guard")),
                                   "cmd": subject_argv(by_name[d["subject"]], os.environ.get("PY") or sys.executable)} for d in due],
                          "receipt_would_be": str(receipt_path), "log_would_be": str(log_path)}, indent=1))
        return 0

    env = dict(os.environ)
    env.setdefault("PY", sys.executable)
    receipt: dict[str, Any] = {"schema": SCHEMA, "authority": AUTHORITY, "lane": LANE, "mode": "apply",
                               "as_of": datetime.now(timezone.utc).isoformat(), "now_local": end.isoformat(),
                               "window_start": window_start.isoformat(), "window_end": end.isoformat(),
                               "since_source": since_src, "served_sha": served_sha(), "root": str(root), "log": str(log_path),
                               "subject_timeout_s": args.subject_timeout_s or None, "lock_wait_s": args.lock_wait_s,
                               "due": due, "runs": [], "ok": False, "outcome": None}

    if not due:
        receipt["ok"], receipt["outcome"] = True, "NOTHING_DUE"
        atomic_write_json(receipt_path, receipt)
        print(json.dumps({"mode": "apply", "outcome": "NOTHING_DUE", "window": [receipt["window_start"], receipt["window_end"]]}))
        return 0

    lock_fh = acquire_dispatch_lock(args.dispatch_lock, args.lock_wait_s)
    if lock_fh is None:
        # Do NOT advance the watermark: the next firing's window still covers these minutes.
        receipt["window_end"] = window_start.isoformat()
        receipt["outcome"] = "LOCK_WAIT_TIMEOUT"
        atomic_write_json(receipt_path, receipt)
        print(json.dumps({"mode": "apply", "outcome": "LOCK_WAIT_TIMEOUT", "dispatch_lock": args.dispatch_lock,
                          "due": [d["subject"] for d in due]}))
        return 1
    try:
        for d in due:                                   # table order; continue on error
            receipt["runs"].append(run_subject(by_name[d["subject"]], root, env, log_path,
                                               args.subject_timeout_s or None, d["matched_minutes"]))
    finally:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
        finally:
            lock_fh.close()

    receipt["ok"] = all(r["outcome"] in ("RAN", "LOCK_HELD", "DEFERRED_GUARD") for r in receipt["runs"])
    receipt["outcome"] = "OK" if receipt["ok"] else "SUBJECT_FAILED"
    receipt["ended_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(receipt_path, receipt)
    print(json.dumps({"mode": "apply", "outcome": receipt["outcome"],
                      "runs": [(r["subject"], r["outcome"], r.get("rc"), r.get("duration_s")) for r in receipt["runs"]],
                      "receipt": str(receipt_path)}, default=str))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
