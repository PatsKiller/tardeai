#!/usr/bin/env python3
"""report_n8n_cutover_outcomes.py — one reconciled, timestamped n8n cutover measurement packet (2026-10-16).

Operator, 2026-10-16: one packet that proves OUTCOMES, not activity. This generator joins, read-only:

* the live crontab (``crontab -l``; hashed, parsed; command text is never written to the packet),
* ``config/lane_registry.json``, ``config/lane_cutover_policy.json``, ``config/n8n_effect_keys.json``,
  ``config/n8n_run_allowlist.json``, ``config/n8n_fabric_processes.json``,
* ``docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv`` (the disposition table),
* the relay live-lane list (``~/.config/tradeai/n8n-live-lanes.env``; ONLY the value of
  ``TRADEAI_N8N_RELAY_LIVE_LANES`` is parsed, every other line is ignored and nothing from the file is printed except
  lane names),
* run receipts ``<state>/data/runtime/n8n_runs/*.json`` and the coordination ledger
  ``<state>/data/governance/n8n_coordination_ledger.sqlite`` (sqlite ``mode=ro`` + ``PRAGMA query_only``),
* the relay log, diagnoses, failure-diagnosis state, supervisor breaches and recoveries,
* ``communication_events`` / ``communication_deliveries`` (Postgres, SELECT only, ``readonly`` session) and the router
  ledger ``notification_intent_receipts.jsonl``,
* ``gh pr view`` and ``git merge-base --is-ancestor`` for the PR table,

and writes ``REPORT.md`` plus JSON/CSV files into ``--out`` (default
``docs/ops/measurements/n8n-cutover-<UTC timestamp>/``). It writes nowhere else, sends nothing, calls no broker and
no provider, never edits the crontab, never prints a credential value, a message body or a chat id.

    ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/report_n8n_cutover_outcomes.py \\
        [--since 2026-10-15T04:00:00Z] [--out docs/ops/measurements/n8n-cutover-<ts>]

The counting functions are pure (fixtures in tests/test_report_n8n_cutover_outcomes_20261016.py).
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SCHEMA = "N8nCutoverOutcomes@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
NO_CONSUMER_REASON = (
    "Operator measurement packet generator (docs/ops/measurements/n8n-cutover-<ts>/); a human and Agent A read "
    "REPORT.md and its JSON/CSV. Nothing imports this module at runtime."
)

DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
DEFAULT_CURRENT = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
DEFAULT_LIVE_LANES_ENV = Path.home() / ".config" / "tradeai" / "n8n-live-lanes.env"
DISPOSITION_CSV = ROOT / "docs" / "implementation" / "n8n-maturity" / "LANE_DISPOSITION_20261015.csv"
LIVE_LANES_KEY = "TRADEAI_N8N_RELAY_LIVE_LANES"
#: The operator N8N Cutover Decision (AGENTS.md §23.25) was taken 2026-10-15; the default window starts at that
#: day's America/New_York midnight.
DEFAULT_SINCE = "2026-10-15T04:00:00+00:00"
PR_RANGE = tuple(range(1808, 1830))
UNKNOWN = "UNKNOWN"

# ── counting definitions (printed verbatim in REPORT.md) ──────────────────────────────────────────────────────────
DEFINITIONS = {
    "disposition_row": (
        "One row of LANE_DISPOSITION_20261015.csv: one active crontab line at build time (source=crontab) or one "
        "registry lane with no crontab line (source=registry_*). The 267 MIGRATE_N8N rows are 267 rows, not 267 "
        "jobs: several rows can name one lane, and one lane can be a family slot runner for many rows."
    ),
    "active_cron_line": (
        "An uncommented, non-assignment line of the CURRENT `crontab -l` (same rule as "
        "lane_registry.discover_cron). A commented line is not a job."
    ),
    "unique_lane": (
        "A distinct lane_id (config/lane_registry.json, plus relay live-list names). A crontab line is attributed to "
        "the single best-ranked registry match (n8n_lane_disposition.match_rows); lines with no match are UNMAPPED."
    ),
    "business_process": (
        "Two levels, reported separately: (a) a WS2 family (disposition family_id, e.g. F44) = one business "
        "function implemented by one or more lanes; (b) a fabric process (config/n8n_fabric_processes.json, e.g. "
        "hermes-learning) = an ordered set of step lanes run as one n8n workflow."
    ),
    "n8n_primary": (
        "The lane is on the relay live list (or is a registry scheduler.kind=n8n ACTIVE lane) AND no active cron "
        "line RUNS it (no active line, or every active line is effect-claim wrapped and stood down)."
    ),
    "scheduler_ownership (S)": (
        "n8n primary AND the cron copy is gone: either no active cron line plus a commented line tagged "
        "`RETIRED <date> n8n-cutover` / `N8N-ONLY TEST` (or a native n8n row), or EVERY active cron line runs "
        "scripts/effect_claim_cron.sh switched on for the lane (TRADEAI_EFFECT_CLAIM=<lane>) and the wrapper's LAST "
        "event for it in the window is skipped_effect / skipped_ownership_unknown (logs/effect_claim_events.jsonl: "
        "the cron copy fired and ran nothing). A wrapped line with no event yet, or whose last event ran the "
        "command, is NOT ownership."
    ),
    "execution (E)": ">=1 live RUN_DONE receipt for the lane in the window.",
    "useful_output (U)": ">=1 live RUN_DONE whose output verdict is produced or empty_allowed.",
    "MIGRATED_PROVEN": (
        "S AND E AND U (2026-10-16 architect review: a completed live run alone is not proof). N8N_NATIVE is the "
        "same bar for a lane with no cron history (registry kind n8n, no retirement tag, no cron line); a native row "
        "WITH a retirement tag is a migration. n8n-live lanes are also reported by S/E/U combination (e.g. S1E1U0 = "
        "owns + ran, output unverified). A skip on a scheduled fire of the line is told apart from an off-schedule "
        "(manual / install verification) skip."
    ),
    "parallel": (
        "Relay-live AND >=1 live n8n receipt in the window AND an active cron line still RUNS the lane (unwrapped, "
        "or wrapped but its last wrapper event ran the command / no event yet). LIVE_LISTED_IDLE = the same with "
        "ZERO live n8n receipts in the window (n8n is permitted, not firing)."
    ),
    "protection_mode": (
        "Effect protection qualified by ledger health and wrapper policy. FAIL_CLOSED = handover manifest names n8n, "
        "every active cron line is wrapped, and the SERVED wrapper fails closed (knows skipped_ownership_unknown): "
        "the cron copy cannot take effect even with the ledger unreadable. LEDGER_HEALTHY_ONLY = owner n8n and every "
        "line wrapped, but the served wrapper fails OPEN on an unreadable ledger (or the manifest lacks the "
        "process): protected only while the ledger answers. NO_CRON_COPY = handed over, no active cron line. "
        "UNPROTECTED_CRON_UNWRAPPED = handed over, >=1 active line unwrapped. NOT_HANDED_OVER = neither store says "
        "n8n. A manifest/ledger disagreement is reported, never reconciled (AGENTS §0 rule 5)."
    ),
    "cron_stood_down": (
        "A skipped_effect (owner n8n) or skipped_ownership_unknown (fail-closed) event in "
        "logs/effect_claim_events.jsonl: the wrapped cron line fired and ran nothing."
    ),
    "event_trigger_state": (
        "Per config/lane_registry.json dispatch.triggers entry: LIVE_FIRING (>=1 live `e:` receipt in window), "
        "LIVE_ARMED_NOT_FIRED, SHADOW_FIRING (dispatch dry_run, >=1 dry `e:` receipt), SHADOW_NOT_FIRED, INACTIVE. "
        "clock_fallback = every clock that still fires the lane (dispatch.cron d: slots, active crontab lines)."
    ),
    "useful_live_output": "A live RUN_DONE receipt whose output_verdict.verdict == 'produced'.",
    "verified_empty": "A live RUN_DONE receipt whose output_verdict.verdict == 'empty_allowed' (declared, reasoned empty).",
    "unverified_ok": (
        "A live RUN_DONE receipt with exit 0 but no evaluated output verdict (missing, no_rule or "
        "declared_not_enforced). Exit 0 is NOT evidence of work (AGENTS §0 rule 8); counted, never called useful."
    ),
    "failure": "A receipt in RUN_FAILED or RUN_TIMEOUT, or a live RUN_DONE with output verdict empty_violation/unverifiable.",
    "refusal": "A relay_log.jsonl row with state REFUSED for the lane (the run never started).",
    "lock_skip": "A receipt in RUN_SKIPPED_LOCK (another holder had the lane's flock).",
    "ambiguous_effect": "An effect_claims row in CLAIMED or UNKNOWN (the effect may or may not have happened).",
    "worker_seconds": "Sum of receipt duration_s.",
    "incident_episode": (
        "A distinct (lane, failure class) with >=1 event in the window, failure class = breach kind / diagnosis "
        "event_type (NO_OUTPUT, UNGOVERNED, STALE_2X, ...) or run:<reason> for failed receipts. Every further event of "
        "the same episode is a DUPLICATE event."
    ),
    "verified_recovery": (
        "The OUTPUT condition recovered: a CLEARED breach row after the last OPEN one, or the lane's declared output "
        "signal (file mtime / JSON key) is now newer than the last breach's detection, or (run failures) a later "
        "receipt of the same lane+mode is RUN_DONE with output verdict produced/empty_allowed (dry_run: RUN_DONE). "
        "A REQUESTED / shadow remediation row is NOT a heal; a lower alert count is NOT recovery."
    ),
    "provenance": (
        "Scheduler + lane named by the Telegram provenance footer `· via <n8n|cron|systemd> <lane>` (PR #1817) or "
        "run_id / source_job on the communication_events row. Anything else is UNKNOWN, never guessed."
    ),
    "deployed": "The PR's merge commit is an ancestor of the served SHA (git merge-base --is-ancestor).",
    "proven": (
        "A qualifying LIVE receipt exists: for a lane associated with the PR (a changed script is the lane's "
        "registry match, or the PR changed the lane's row in lane_registry/n8n_effect_keys/n8n_run_allowlist), a live "
        "RUN_DONE whose code_sha contains the merge commit and whose output verdict is produced/empty_allowed. "
        "PR #1817 is proven by a communication_events row carrying an `· via n8n` footer."
    ),
}

#: Independent P1 / dead-man backstops the cutover must NOT absorb (DD12 plan §3; AGENTS §23.25 F07 rule).
BACKSTOPS = (
    ("incident-notifier", "platform", "On-host P1 path: sends every fan-in P1 at once (uncapped, through quiet hours)."),
    ("autonomy-watchdog", "platform", "Host watchdog: autonomy loop liveness (own systemd timer)."),
    ("portfolio-server-watchdog", "platform", "Restarts the :7777 API when it stops answering (F07)."),
    ("postgres-main-watchdog", "platform", "Detects/recovers postgres-main down (installed after the 09-18 ENOSPC crash)."),
    ("n8n-lab-watchdog", "platform", "Host-side probe of the n8n lab /healthz every 5 min: watches the watcher."),
    ("supervisor-breach-detector", "platform", "Writes supervisor_breaches.jsonl (NO_OUTPUT/STALE) independent of n8n."),
    ("health-tick", "platform", "One systemd 5-min timer running the host health/monitor cadence table (F07)."),
    ("process-reaper", "platform", "Kills hung / piled-up batch jobs (F07)."),
    ("offbox-deadman", "operator", "DD12 outside dead-man (scripts/offbox_deadman.py): built, NOT activated (operator packet)."),
)

_ISO_FIXES = (("Z", "+00:00"),)


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────────────
def parse_ts(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds") if d else None


def et_midnight_utc(now: datetime) -> datetime:
    """America/New_York midnight of ``now``'s ET date, as UTC."""
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        et = now.astimezone(ZoneInfo("America/New_York"))
        return et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return (now - timedelta(hours=4)).replace(hour=4, minute=0, second=0, microsecond=0)


# ── live-lane list (names only) ───────────────────────────────────────────────────────────────────────────────────
def parse_live_lanes(text: str) -> list[str]:
    """Lane names from the ``TRADEAI_N8N_RELAY_LIVE_LANES=`` line only; every other line is ignored unread."""
    names: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("export "):
            s = s[len("export "):].strip()
        if not s.startswith(LIVE_LANES_KEY + "="):
            continue
        value = s.split("=", 1)[1].strip().strip('"').strip("'")
        for tok in re.split(r"[\s,]+", value):
            if tok and re.fullmatch(r"[A-Za-z0-9._:-]+", tok) and tok not in names:
                names.append(tok)
    return names


# ── crontab ───────────────────────────────────────────────────────────────────────────────────────────────────────
_N8N_CUTOVER_RE = re.compile(r"RETIRED\s+(\d{4}-\d{2}-\d{2})\s+n8n-cutover\s+(\S+)\s")
_N8N_ONLY_RE = re.compile(r"N8N-ONLY TEST\s+(\d{4}-\d{2}-\d{2})")
_RETIRED_TAG_RE = re.compile(r"RETIRED\s+(\d{4}-\d{2}-\d{2})\s+(\S+)")
CONSOLIDATION_TOKENS = ("c1-manifest", "b-family", "(folded")
_SCHED_BODY_RE = re.compile(r"((?:@\w+)|(?:[\d*/,\-]+\s+){4}[\d*/,\-]+)\s+\S")


def classify_commented_line(line: str) -> Optional[dict[str, Any]]:
    """A commented crontab line that records a migration/consolidation/retirement, else None.

    kind: N8N_CUTOVER (``# RETIRED <date> n8n-cutover <lane> ...``), N8N_ONLY_TEST (``# N8N-ONLY TEST <date>``),
    CONSOLIDATED (``# RETIRED <date> c1-manifest|b-family ...`` / ``(folded ...``), RETIRED_OTHER (any other dated
    RETIRED tag). ``body`` is the commented job text after the tag, for lane matching only (never written out)."""
    s = line.strip()
    if not s.startswith("#"):
        return None
    m = _N8N_CUTOVER_RE.search(s)
    if m:
        return {"kind": "N8N_CUTOVER", "date": m.group(1), "lane_id": m.group(2), "body": s[m.end():]}
    m = _N8N_ONLY_RE.search(s)
    if m:
        return {"kind": "N8N_ONLY_TEST", "date": m.group(1), "lane_id": "", "body": s[m.end():]}
    m = _RETIRED_TAG_RE.search(s)
    if m:
        token = m.group(2)
        kind = "CONSOLIDATED" if any(token.startswith(t) for t in CONSOLIDATION_TOKENS) else "RETIRED_OTHER"
        return {"kind": kind, "date": m.group(1), "lane_id": "", "body": s[m.end():], "token": token}
    return None


def lane_matcher(registry: Mapping[str, Any]):
    """Callable(line text) -> best lane_id or '' using n8n_lane_disposition's substring + rank rule."""
    from n8n_lane_disposition import match_rows, registry_matchers  # noqa: PLC0415

    matchers = registry_matchers(dict(registry))

    def best(text: str, schedule: str = "", tag: str = "") -> str:
        rows = match_rows({"line": text, "schedule": schedule, "tag": tag}, matchers)
        return rows[0]["lane_id"] if rows else ""

    return best


_WRAP_RE = re.compile(r"TRADEAI_EFFECT_CLAIM=([A-Za-z0-9._:-]+)\s+bash\s+\S*effect_claim_cron\.sh\s+([A-Za-z0-9._:-]+)")


def wrapped_lane_of(line: str) -> str:
    """The lane an active cron line is effect-claim WRAPPED for, else ''.

    Wrapped = the line runs scripts/effect_claim_cron.sh AND switches it on for that lane with
    ``TRADEAI_EFFECT_CLAIM=<lane>`` (the wrapper is a byte-for-byte pass-through otherwise). Only the lane name is
    returned; command text never leaves this function."""
    m = _WRAP_RE.search(line or "")
    return m.group(2) if m and m.group(1) == m.group(2) else ""


def parse_cron(text: str, best_lane) -> dict[str, Any]:
    """Active lines (attributed to one lane each) and tagged commented lines (attributed to a lane)."""
    from n8n_lane_disposition import parse_crontab  # noqa: PLC0415

    _env, jobs = parse_crontab(text or "")
    active = []
    for j in jobs:
        active.append({"line_no": j["line_no"], "schedule": j["schedule"],
                       "lane_id": best_lane(j["line"], j["schedule"], j["tag"]) or "",
                       "wrapped_lane": wrapped_lane_of(j["line"])})
    commented = []
    for n, line in enumerate((text or "").splitlines(), 1):
        c = classify_commented_line(line)
        if not c:
            continue
        lane = c["lane_id"] or best_lane(c["body"]) or ""
        commented.append({"line_no": n, "kind": c["kind"], "date": c["date"], "lane_id": lane,
                          "token": c.get("token", "")})
    return {"active": active, "commented": commented}


# ── receipts → per-lane outcomes ──────────────────────────────────────────────────────────────────────────────────
OUTCOME_KEYS = (
    "live_runs", "dry_runs", "useful_live_output", "verified_empty", "unverified_ok", "failures", "lock_skips",
    "live_worker_s", "dry_worker_s",
)


def receipt_class(r: Mapping[str, Any]) -> str:
    """One of useful / empty / unverified_ok / failure / lock_skip / dry_done / other."""
    state = str(r.get("state") or "")
    mode = str(r.get("mode") or "")
    ov = r.get("output_verdict") or {}
    verdict = ov.get("verdict") if isinstance(ov, Mapping) else None
    if state == "RUN_SKIPPED_LOCK" or r.get("lock_skipped") is True:
        return "lock_skip"
    if state in ("RUN_FAILED", "RUN_TIMEOUT"):
        return "failure"
    if state == "RUN_DONE":
        if mode != "live":
            return "dry_done"
        if verdict == "produced":
            return "useful"
        if verdict == "empty_allowed":
            return "empty"
        if verdict in ("empty_violation", "unverifiable"):
            return "failure"
        return "unverified_ok"
    return "other"


def in_window(r: Mapping[str, Any], since: datetime, until: datetime) -> bool:
    t = parse_ts(r.get("started_at")) or parse_ts(r.get("finished_at"))
    return bool(t and since <= t <= until)


def count_outcomes(receipts: Iterable[Mapping[str, Any]], since: datetime, until: datetime) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {k: 0 for k in OUTCOME_KEYS})
    for r in receipts:
        if not in_window(r, since, until):
            continue
        lane = str(r.get("lane_id") or UNKNOWN)
        row = out[lane]
        live = r.get("mode") == "live"
        row["live_runs" if live else "dry_runs"] += 1
        row["live_worker_s" if live else "dry_worker_s"] += float(r.get("duration_s") or 0.0)
        cls = receipt_class(r)
        if cls == "useful":
            row["useful_live_output"] += 1
        elif cls == "empty":
            row["verified_empty"] += 1
        elif cls == "unverified_ok":
            row["unverified_ok"] += 1
        elif cls == "failure":
            row["failures"] += 1
        elif cls == "lock_skip":
            row["lock_skips"] += 1
    for row in out.values():
        row["live_worker_s"] = round(row["live_worker_s"], 1)
        row["dry_worker_s"] = round(row["dry_worker_s"], 1)
    return dict(out)


def count_refusals(relay_rows: Iterable[Mapping[str, Any]], since: datetime, until: datetime) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for r in relay_rows:
        if r.get("state") != "REFUSED":
            continue
        t = parse_ts(r.get("at"))
        if not t or not (since <= t <= until):
            continue
        out[str(r.get("lane_id") or "(no lane)")][str(r.get("reason") or UNKNOWN)] += 1
    return dict(out)


def count_effect_claims(claims: Iterable[Mapping[str, Any]], since: datetime, until: datetime) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for c in claims:
        t = parse_ts(c.get("claimed_at"))
        if not t or not (since <= t <= until):
            continue
        out[str(c.get("process"))][str(c.get("state"))] += 1
    return dict(out)


def disposition_totals(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Rows vs unique lanes per disposition: N disposition rows are not N jobs."""
    return {
        "rows": len(rows),
        "by_disposition": dict(Counter(r.get("disposition") for r in rows)),
        "by_source": dict(Counter(r.get("source") for r in rows)),
        "unique_lanes": len({r["lane_id"] for r in rows if r.get("lane_id")}),
        "unique_lanes_by_disposition": {d: len({r["lane_id"] for r in rows if r.get("disposition") == d and r.get("lane_id")})
                                        for d in sorted({str(r.get("disposition")) for r in rows})},
    }


# ── cron-side effect-claim wrapper events (logs/effect_claim_events.jsonl) ────────────────────────────────────────
#: The wrapper stood the cron copy down: nothing ran. skipped_effect = owner n8n; skipped_ownership_unknown = a
#: handed-over lane whose ownership could not be established (fail closed, PR 1 of the 2026-10-16 architect review).
SKIP_EVENTS = ("skipped_effect", "skipped_ownership_unknown")
#: The wrapper ran the command (claimed or not).
RAN_EVENTS = ("run_unclaimed_cron_claim_false", "run_unclaimed_ledger_unreachable", "completed_unclaimed",
              "completed_claimed")


#: Minutes after a scheduled fire within which a wrapper event still counts as that fire (cron start + python).
SCHEDULED_SLACK_MIN = 2
CRON_TZ = "America/New_York"


def cron_fires_at(expr: str, t: datetime, tz: str = CRON_TZ) -> Optional[bool]:
    """Did the 5-field cron ``expr`` fire within SCHEDULED_SLACK_MIN minutes before ``t`` (host wall clock ``tz``,
    Vixie DOM/DOW OR rule)? None when the expression is not a parseable 5-field schedule (e.g. @reboot)."""
    from scripts.lib import cron_schedule  # noqa: PLC0415

    try:
        minutes, hours, doms, months, dows, dom_r, dow_r = cron_schedule.parse(expr)
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        local = t.astimezone(ZoneInfo(tz)).replace(second=0, microsecond=0)
    except Exception:  # noqa: BLE001
        return None
    for back in range(SCHEDULED_SLACK_MIN + 1):
        x = local - timedelta(minutes=back)
        cron_dow = (x.weekday() + 1) % 7
        day_ok = (x.day in doms or cron_dow in dows) if (dom_r and dow_r) else (x.day in doms and cron_dow in dows)
        if x.minute in minutes and x.hour in hours and x.month in months and day_ok:
            return True
    return False


def count_effect_events(
    rows: Iterable[Mapping[str, Any]], since: datetime, until: datetime,
    schedules: Optional[Mapping[str, Iterable[str]]] = None,
) -> dict[str, dict[str, Any]]:
    """Per wrapper lane: event counts in the window and the LAST event (by ts). Only lane/event/ts/detail-flag are
    kept; the detail text is not copied into the packet.

    With ``schedules`` (wrapper lane -> cron expressions of its active lines), each skip is also classed
    ``scheduled_skips`` (the event falls on a fire of the line's schedule: the cron copy stood down AT ITS SLOT) or
    ``offschedule_skips`` (a manual / verification invocation: the wrapper skipped when run, not a scheduled
    stand-down)."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = parse_ts(r.get("ts"))
        if not t or not (since <= t <= until):
            continue
        lane = str(r.get("lane") or "")
        if not lane:
            continue
        ev = str(r.get("event") or UNKNOWN)
        e = out.setdefault(lane, {"counts": Counter(), "last_event": None, "last_at": None,
                                  "manifest_ledger_disagree": 0, "scheduled_skips": 0, "offschedule_skips": 0})
        e["counts"][ev] += 1
        if ev in SKIP_EVENTS and schedules is not None:
            fired = [cron_fires_at(x, t) for x in (schedules.get(lane) or [])]
            if any(f is True for f in fired):
                e["scheduled_skips"] += 1
            else:
                e["offschedule_skips"] += 1
        if "manifest_ledger_disagree" in str(r.get("detail") or ""):
            e["manifest_ledger_disagree"] += 1
        if e["last_at"] is None or t >= e["last_at"]:
            e["last_at"], e["last_event"] = t, ev
    return out


def cron_copy_standing_down(lines: Iterable[Mapping[str, Any]], events: Mapping[str, Mapping[str, Any]]) -> bool:
    """True when EVERY given active cron line is wrapped and the wrapper's last event in the window for that line's
    lane is a skip (the cron copy fired and ran nothing). No lines -> False (nothing to stand down)."""
    lines = list(lines)
    if not lines:
        return False
    for a in lines:
        w = a.get("wrapped_lane") or ""
        if not w:
            return False
        e = events.get(w) or {}
        if e.get("last_event") not in SKIP_EVENTS:
            return False
    return True


# ── migration state per lane ──────────────────────────────────────────────────────────────────────────────────────
STATUSES = (
    "MIGRATED_PROVEN", "N8N_NATIVE", "N8N_PRIMARY_UNPROVEN", "PARALLEL", "LIVE_LISTED_IDLE", "CRON_PRIMARY",
    "CONSOLIDATED", "RETIRED", "HELD", "RETAINED_F07", "RETAINED_SYSTEMD", "OTHER",
)


def lane_states(
    *,
    registry_rows: Mapping[str, Mapping[str, Any]],
    live_lanes: Iterable[str],
    cron: Mapping[str, Any],
    families: Mapping[str, str],
    dispositions: Mapping[str, str],
    holds: Mapping[str, str],
    outcomes: Mapping[str, Mapping[str, Any]],
    effect_events: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, dict[str, Any]]:
    """One row per unique lane with exactly one status (see STATUSES / DEFINITIONS), plus the three SEPARATE
    measures (2026-10-16 architect review): scheduler ownership, execution, useful output.

    * ``sched_n8n`` - n8n is primary (relay live list or a native n8n row) AND the cron copy is gone: no active cron
      line plus a retirement tag (``RETIRED <date> n8n-cutover`` / ``N8N-ONLY TEST``) or a native row, OR every
      active cron line is effect-claim wrapped and the wrapper's last event for it in the window is a skip
      (``skipped_effect`` / ``skipped_ownership_unknown``: the cron copy fired and ran nothing).
    * ``executed`` - >=1 live RUN_DONE receipt in the window.
    * ``useful`` - >=1 live RUN_DONE with output verdict produced or empty_allowed.

    MIGRATED_PROVEN needs all three. A wrapped cron line that stands down is not PARALLEL (the cron copy runs
    nothing); a wrapped line that still RUNS the command (owner not n8n, ledger unreachable) is."""
    live = set(live_lanes)
    events = effect_events or {}
    active_by_lane: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for a in cron.get("active") or []:
        if a.get("lane_id"):
            active_by_lane[a["lane_id"]].append(a)
    commented_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cron.get("commented") or []:
        if c.get("lane_id"):
            commented_by_lane[c["lane_id"]].append(c)
    lanes = set(registry_rows) | live | set(active_by_lane) | set(commented_by_lane)
    out: dict[str, dict[str, Any]] = {}
    for lane in sorted(lanes):
        reg = registry_rows.get(lane) or {}
        sched = reg.get("scheduler") or {}
        kind = str(sched.get("kind") or ("none" if reg else "unregistered"))
        state = str(reg.get("state") or ("UNREGISTERED" if not reg else ""))
        fam = str(families.get(lane) or "")
        o = outcomes.get(lane) or {}
        active_rows = active_by_lane.get(lane, [])
        active = sorted(int(a["line_no"]) for a in active_rows)
        wrapped = [a for a in active_rows if a.get("wrapped_lane")]
        wrapped_lanes = sorted({str(a["wrapped_lane"]) for a in wrapped})
        standing_down = cron_copy_standing_down(active_rows, events)
        tags = commented_by_lane.get(lane, [])
        n8n_tag = [t for t in tags if t["kind"] in ("N8N_CUTOVER", "N8N_ONLY_TEST")]
        consolidated = [t for t in tags if t["kind"] == "CONSOLIDATED"]
        native = kind == "n8n" and state == "ACTIVE"
        relay_live = lane in live
        n8n_live = relay_live or native
        live_done = int(o.get("useful_live_output", 0)) + int(o.get("verified_empty", 0)) + int(o.get("unverified_ok", 0))
        useful_n = int(o.get("useful_live_output", 0)) + int(o.get("verified_empty", 0))
        if not n8n_live:
            sched_n8n, sched_how = False, ""
        elif active:
            sched_n8n = standing_down
            sched_how = "cron_wrapped_skipping" if standing_down else ""
        elif n8n_tag:
            sched_n8n, sched_how = True, "cron_retired_tag"
        elif native:
            sched_n8n, sched_how = True, "n8n_native_row"
        else:
            sched_n8n, sched_how = False, ""
        executed, useful = live_done > 0, useful_n > 0
        combo = f"S{int(sched_n8n)}E{int(executed)}U{int(useful)}"
        cron_runs = bool(active) and not standing_down
        if lane in holds:
            status = "HELD"
        elif fam.startswith("F07"):
            status = "RETAINED_F07"
        elif kind == "systemd" and not n8n_live:
            status = "RETAINED_SYSTEMD"
        elif n8n_live and cron_runs:
            status = "PARALLEL" if int(o.get("live_runs", 0)) else "LIVE_LISTED_IDLE"
        elif n8n_live:
            if sched_n8n and executed and useful:
                # proven either way; N8N_NATIVE only when the lane has no cron history (born on n8n)
                status = "N8N_NATIVE" if sched_how == "n8n_native_row" else "MIGRATED_PROVEN"
            else:
                status = "N8N_PRIMARY_UNPROVEN"
        elif active:
            status = "CRON_PRIMARY"
        elif consolidated:
            status = "CONSOLIDATED"
        elif state == "RETIRED" or dispositions.get(lane) == "RETIRE":
            status = "RETIRED"
        else:
            status = "OTHER"
        why: list[str] = []
        if status == "N8N_PRIMARY_UNPROVEN":
            if not sched_n8n:
                why.append("no scheduler-ownership evidence (no n8n-cutover / N8N-ONLY tag and no wrapped cron line "
                           "that stood down)")
            if not executed:
                why.append("no live RUN_DONE in window")
            elif not useful:
                why.append("live RUN_DONE but no useful output verdict (produced / empty_allowed)")
        out[lane] = {
            "lane_id": lane,
            "status": status,
            "registry_state": state,
            "scheduler_kind": kind,
            "family_id": fam,
            "disposition": dispositions.get(lane, ""),
            "relay_live": relay_live,
            "active_cron_lines": len(active),
            "active_cron_line_nos": " ".join(str(n) for n in active),
            "active_cron_lines_wrapped": len(wrapped),
            "cron_copy_standing_down": standing_down,
            "wrapper_skip_events": sum(int((events.get(w) or {}).get("counts", {}).get(k, 0))
                                       for w in wrapped_lanes for k in SKIP_EVENTS),
            "wrapper_last_event": " ".join(str((events.get(w) or {}).get("last_event") or "-") for w in wrapped_lanes),
            "wrapper_scheduled_skips": sum(int((events.get(w) or {}).get("scheduled_skips", 0)) for w in wrapped_lanes),
            "wrapper_offschedule_skips": sum(int((events.get(w) or {}).get("offschedule_skips", 0))
                                             for w in wrapped_lanes),
            "n8n_cutover_tags": " ".join(f"{t['kind']}@{t['date']}:L{t['line_no']}" for t in n8n_tag),
            "consolidation_tags": " ".join(f"{t.get('token')}@{t['date']}" for t in consolidated),
            "live_run_done": live_done,
            "live_useful_or_empty": useful_n,
            "sched_n8n": sched_n8n,
            "sched_evidence": sched_how,
            "executed": executed,
            "useful": useful,
            "measure_combo": combo if n8n_live else "",
            "dry_runs": int(o.get("dry_runs", 0)),
            "unproven_reason": "; ".join(why),
        }
    return out


#: Human labels for the S/E/U combinations (scheduler ownership / execution / useful output).
COMBO_LABELS = {
    "S1E1U1": "PROVEN: n8n owns the schedule, ran live, produced useful output",
    "S1E1U0": "n8n owns + ran live, output unverified (exit 0 is not evidence)",
    "S1E0U0": "n8n owns the schedule, no live RUN_DONE in window",
    "S0E1U1": "ran live with useful output, but the cron copy still runs / is not retired",
    "S0E1U0": "ran live (unverified output), the cron copy still runs / is not retired",
    "S0E0U0": "relay-live only: no ownership evidence, no live run",
}


def measure_combinations(lanes: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """n8n-live lanes (relay live list or native; HELD / F07 / systemd-retained excluded) by S/E/U combination."""
    out: dict[str, list[str]] = defaultdict(list)
    for lane, r in lanes.items():
        if r.get("measure_combo") and r["status"] not in ("HELD", "RETAINED_F07", "RETAINED_SYSTEMD"):
            out[r["measure_combo"]].append(lane)
    return {k: sorted(v) for k, v in sorted(out.items(), key=lambda kv: kv[0], reverse=True)}


def family_ownership(lanes: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A family is n8n-owned when every non-retired lane is n8n primary and no lane is cron/parallel."""
    by_fam: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in lanes.values():
        if row.get("family_id"):
            by_fam[row["family_id"]].append(row)
    out = []
    n8n_ok = {"MIGRATED_PROVEN", "N8N_NATIVE"}
    for fam, rows in sorted(by_fam.items()):
        live_rows = [r for r in rows if r["status"] not in ("RETIRED",)]
        c = Counter(r["status"] for r in live_rows)
        fully = bool(live_rows) and all(r["status"] in n8n_ok for r in live_rows)
        any_n8n = any(r["status"] in n8n_ok | {"N8N_PRIMARY_UNPROVEN", "PARALLEL", "LIVE_LISTED_IDLE"} for r in live_rows)
        out.append({
            "family_id": fam,
            "lanes": len(live_rows),
            "fully_n8n_owned": fully,
            "has_any_n8n": any_n8n,
            "status_counts": dict(sorted(c.items())),
            "cron_or_parallel_lanes": sorted(
                r["lane_id"] for r in live_rows if r["status"] in ("CRON_PRIMARY", "PARALLEL", "LIVE_LISTED_IDLE")),
        })
    return out


def fabric_process_ownership(
    processes: Mapping[str, Any], lanes: Mapping[str, Mapping[str, Any]], outcomes: Mapping[str, Mapping[str, Any]],
    cron_active_lanes: set[str],
) -> list[dict[str, Any]]:
    out = []
    for name, p in sorted((processes or {}).items()):
        steps = p.get("steps") or {}
        step_rows = []
        for sid, s in steps.items():
            lane = s.get("lane_id")
            o = outcomes.get(lane) or {}
            step_rows.append({
                "step": sid, "lane_id": lane, "blocked": s.get("blocked"),
                "live_runs": int(o.get("live_runs", 0)), "dry_runs": int(o.get("dry_runs", 0)),
                "useful_or_empty_live": int(o.get("useful_live_output", 0)) + int(o.get("verified_empty", 0)),
            })
        runners = sorted((p.get("runner_lanes") or {}).values())
        runner_cron = [r for r in runners if r in cron_active_lanes]
        all_live = all(sr["live_runs"] > 0 for sr in step_rows if not sr["blocked"])
        out.append({
            "process": name, "workflow_id": p.get("workflow_id"), "mode": p.get("mode"),
            "runner_lanes": runners, "runner_lanes_with_active_cron": runner_cron,
            "steps": step_rows,
            "fully_n8n_owned": bool(step_rows) and all_live and not runner_cron,
            "why_not": (
                "" if (all_live and not runner_cron) else
                "; ".join(x for x in (
                    f"cron stage runner still active: {', '.join(runner_cron)}" if runner_cron else "",
                    "step(s) without a live run in window: " + ", ".join(sr["step"] for sr in step_rows
                                                                       if not sr["blocked"] and sr["live_runs"] == 0)
                    if not all_live else "",
                ) if x)
            ),
        })
    return out


# ── incidents ─────────────────────────────────────────────────────────────────────────────────────────────────────
def signal_time(signal: Mapping[str, Any], state_root: Path) -> Optional[datetime]:
    """Current output time of a file_mtime / json_key signal; None when unreadable or another kind."""
    try:
        path = Path(str(signal.get("path") or ""))
        if not str(path):
            return None
        p = path if path.is_absolute() else state_root / path
        kind = signal.get("kind")
        if kind == "file_mtime":
            return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) if p.exists() else None
        if kind == "json_key":
            d = json.loads(p.read_text())
            return parse_ts(d.get(signal.get("key"))) if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None
    return None


def incident_episodes(
    *,
    breaches: Iterable[Mapping[str, Any]],
    diagnoses: Iterable[Mapping[str, Any]],
    receipts: Iterable[Mapping[str, Any]],
    since: datetime,
    until: datetime,
    signal_now=None,
) -> list[dict[str, Any]]:
    """Distinct (lane, failure class) episodes with duplicates and recovery verdicts. ``signal_now(signal)`` -> dt."""
    ev: dict[tuple[str, str], dict[str, Any]] = {}

    def bump(lane: str, cls: str, t: datetime, source: str) -> dict[str, Any]:
        e = ev.setdefault((lane, cls), {"lane_id": lane, "failure_class": cls, "events": 0, "sources": Counter(),
                                        "first_at": t, "last_at": t, "last_open": None, "cleared_after": False,
                                        "last_signal": None, "run_mode": None})
        e["events"] += 1
        e["sources"][source] += 1
        e["first_at"] = min(e["first_at"], t)
        e["last_at"] = max(e["last_at"], t)
        return e

    for b in breaches:
        t = parse_ts(b.get("detected_at"))
        if not t or not (since <= t <= until):
            continue
        lane, kind = str(b.get("lane_id")), str(b.get("kind"))
        if b.get("state") == "CLEARED":
            e = ev.get((lane, kind))
            if e and e["last_open"] and t >= e["last_open"]:
                e["cleared_after"] = True
            continue
        e = bump(lane, kind, t, "breach")
        if not e["last_open"] or t >= e["last_open"]:
            e["last_open"] = t
            e["cleared_after"] = False
            sig = (b.get("evidence") or {}).get("signal")
            e["last_signal"] = sig if isinstance(sig, Mapping) else None
    for d in diagnoses:
        t = parse_ts(d.get("at"))
        if not t or not (since <= t <= until):
            continue
        bump(str(d.get("lane")), str(d.get("event_type")), t, "diagnosis")
    rec_list = [r for r in receipts if in_window(r, since, until)]
    rec_list.sort(key=lambda r: str(r.get("started_at") or ""))
    for r in rec_list:
        if receipt_class(r) != "failure":
            continue
        t = parse_ts(r.get("started_at"))
        reason = str(r.get("reason") or (r.get("output_verdict") or {}).get("verdict") or r.get("state"))
        e = bump(str(r.get("lane_id")), f"run:{reason}", t, f"receipt_{r.get('mode')}")
        e["run_mode"] = r.get("mode")
    out = []
    for (lane, cls), e in sorted(ev.items()):
        verdict, how = "UNRESOLVED", ""
        if cls.startswith("run:"):
            later = [r for r in rec_list if r.get("lane_id") == lane and r.get("mode") == e["run_mode"]
                     and (parse_ts(r.get("started_at")) or since) > e["last_at"]]
            ok = [r for r in later if receipt_class(r) in ("useful", "empty", "dry_done")]
            if ok:
                verdict, how = "VERIFIED_RECOVERED", f"later {e['run_mode']} receipt {ok[0].get('run_id')}"
            elif any(receipt_class(r) == "unverified_ok" for r in later):
                verdict, how = "RAN_AGAIN_UNVERIFIED", "later live exit 0 without an output verdict"
        elif e["cleared_after"]:
            verdict, how = "VERIFIED_RECOVERED", "CLEARED breach row after the last OPEN"
        elif e["last_signal"] and signal_now is not None:
            now_t = signal_now(e["last_signal"])
            if now_t and e["last_open"] and now_t > e["last_open"]:
                verdict, how = ("VERIFIED_RECOVERED",
                                f"output signal now {_iso(now_t)} > last breach detection {_iso(e['last_open'])}")
            elif now_t is None:
                verdict, how = "UNRESOLVED", "output signal unreadable/unsupported kind"
        out.append({
            "lane_id": lane, "failure_class": cls, "events": e["events"], "duplicate_events": e["events"] - 1,
            "sources": dict(e["sources"]), "first_at": _iso(e["first_at"]), "last_at": _iso(e["last_at"]),
            "recovery": verdict, "recovery_evidence": how,
        })
    return out


# ── notifications ─────────────────────────────────────────────────────────────────────────────────────────────────
_FOOTER_RE = re.compile(r"· via (n8n|cron|systemd) ([A-Za-z0-9.\-]+)")


def provenance_of(row: Mapping[str, Any]) -> tuple[str, str]:
    """(scheduler, lane) from the footer, else run_id (d:<lane>:...) / source_job, else (UNKNOWN, UNKNOWN)."""
    m = _FOOTER_RE.search(str(row.get("body") or ""))
    if m:
        return m.group(1), m.group(2)
    run_id = str(row.get("run_id") or "")
    if run_id.startswith("d:") and run_id.count(":") >= 3:
        return "n8n", run_id.split(":")[1]
    if row.get("source_job"):
        return UNKNOWN, str(row["source_job"])
    return UNKNOWN, UNKNOWN


def summarize_notifications(events: Iterable[Mapping[str, Any]], router_rows: Iterable[Mapping[str, Any]],
                            intents: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ev = list(events)
    prov = Counter()
    by_prod = defaultdict(Counter)
    chain = Counter()
    for e in ev:
        sched, lane = provenance_of(e)
        prov[f"{sched}:{lane}" if sched != UNKNOWN or lane != UNKNOWN else "UNKNOWN"] += 1
        by_prod[f"{e.get('producer')}|{e.get('message_class')}"][str(e.get("delivery_status") or "NO_DELIVERY_ROW")] += 1
        chain[(sched, str(e.get("delivery_status") or "NO_DELIVERY_ROW"))] += 1
    router = Counter()
    router_prod = defaultdict(Counter)
    for r in router_rows:
        router[str(r.get("decision"))] += 1
        router_prod[str(r.get("producer") or UNKNOWN)][str(r.get("decision"))] += 1
    it = Counter((str(i.get("tier")), str(i.get("state"))) for i in intents)
    return {
        "communication_events_outbound": len(ev),
        "attribution": {
            "attributed": sum(v for k, v in prov.items() if k != "UNKNOWN" and not k.startswith("UNKNOWN:")),
            "unknown": sum(v for k, v in prov.items() if k == "UNKNOWN" or k.startswith("UNKNOWN:")),
            "by_source": dict(prov.most_common()),
        },
        "by_scheduler_and_delivery": {f"{a}|{b}": n for (a, b), n in sorted(chain.items())},
        "by_producer_class_delivery": {k: dict(v) for k, v in sorted(by_prod.items())},
        "router_decisions": dict(router),
        "router_by_producer": {k: dict(v) for k, v in sorted(router_prod.items())},
        "n8n_comms_intents_by_tier_state": {f"{a}|{b}": n for (a, b), n in sorted(it.items())},
    }


# ── effect protection ─────────────────────────────────────────────────────────────────────────────────────────────
#: Qualified effect-protection modes (2026-10-16 architect review). Counted separately in the packet.
PROTECTION_MODES = (
    "FAIL_CLOSED", "LEDGER_HEALTHY_ONLY", "NO_CRON_COPY", "UNPROTECTED_CRON_UNWRAPPED", "NOT_HANDED_OVER",
)


def manifest_ledger_agreement(ledger_owner: str, manifest_owner: str) -> str:
    """AGREE / DISAGREE (both name a different owner) / MANIFEST_MISSING / LEDGER_MISSING / NEITHER.
    Reported, never reconciled (AGENTS §0 rule 5)."""
    if ledger_owner and manifest_owner:
        return "AGREE" if ledger_owner == manifest_owner else "DISAGREE"
    if ledger_owner:
        return "MANIFEST_MISSING"
    if manifest_owner:
        return "LEDGER_MISSING"
    return "NEITHER"


def effect_protection(
    keys: Mapping[str, Mapping[str, Any]], owners: Mapping[str, Mapping[str, Any]], cron_text: str,
    cron: Mapping[str, Any], claims: Mapping[str, Counter], *,
    manifest: Optional[Mapping[str, Mapping[str, Any]]] = None,
    served_wrapper_fail_closed: bool = False,
    ledger_ok: bool = True,
    effect_events: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """One row per keyed lane. ``protection`` is the claim-level view (unchanged since #1827); ``protection_mode``
    qualifies it with ledger health and the wrapper policy:

    * FAIL_CLOSED - handed over (manifest owner n8n), EVERY active cron line of the lane runs the effect-claim
      wrapper switched on for the lane, and the SERVED wrapper is the fail-closed version (it knows
      ``skipped_ownership_unknown``): the cron copy cannot run the effect even when the ledger is unreadable.
    * LEDGER_HEALTHY_ONLY - handed over (ledger owner n8n) and every active line is wrapped, but the served wrapper
      fails OPEN when the ledger is unreadable, or the manifest does not name the process n8n: the cron copy stands
      down only while the ledger answers.
    * NO_CRON_COPY - handed over and no active cron line fires the lane (nothing on cron to double-fire).
    * UNPROTECTED_CRON_UNWRAPPED - handed over but >=1 active cron line is not wrapped: both can take effect.
    * NOT_HANDED_OVER - neither the ledger nor the manifest names n8n as owner."""
    from n8n_lane_disposition import parse_crontab  # noqa: PLC0415

    _env, jobs = parse_crontab(cron_text or "")
    line_by_no = {j["line_no"]: j["line"] for j in jobs}
    manifest = manifest or {}
    events = effect_events or {}
    active_by_lane: dict[str, list[int]] = defaultdict(list)
    for a in cron.get("active") or []:
        if a.get("lane_id"):
            active_by_lane[a["lane_id"]].append(a["line_no"])
        w = a.get("wrapped_lane") or wrapped_lane_of(line_by_no.get(a.get("line_no"), ""))
        if w and w != a.get("lane_id") and a["line_no"] not in active_by_lane[w]:
            active_by_lane[w].append(a["line_no"])
    out = []
    for lane, k in sorted(keys.items()):
        process = k.get("process") or lane
        own = owners.get(process) or {}
        lines = sorted(active_by_lane.get(lane, []))
        armed = [n for n in lines if "effect_claim" in line_by_no.get(n, "")
                 or f"TRADEAI_EFFECT_CLAIM={lane}" in line_by_no.get(n, "")
                 or "PIPELINE_EFFECT_CLAIM=1" in line_by_no.get(n, "")]
        cron_wrapped = [n for n in lines if wrapped_lane_of(line_by_no.get(n, ""))]
        n8n_claim = bool(k.get("n8n_claim"))
        cron_claim_cfg = bool(k.get("cron_claim"))
        c = claims.get(process) or Counter()
        if not own:
            level = "NOT_ARMED (no owner row: every claim refused effect_no_owner)" if n8n_claim else "STAGED (no owner row)"
        elif n8n_claim and (not lines or len(armed) == len(lines)):
            level = "SINGLE_OWNER_CLAIMING" if c.get("DONE") else "ARMED_NOT_YET_EXERCISED"
        elif n8n_claim and lines:
            level = "N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect)"
        else:
            level = "OWNER_ROW_ONLY"
        ledger_owner = str(own.get("owner") or "")
        m = manifest.get(process) or {}
        manifest_owner = str(m.get("owner") or "") if isinstance(m, Mapping) else ""
        handed_over = ledger_owner == "n8n" or manifest_owner == "n8n"
        agreement = manifest_ledger_agreement(ledger_owner, manifest_owner)
        if not handed_over:
            mode, why = "NOT_HANDED_OVER", f"ledger owner {ledger_owner or 'none'}, manifest {manifest_owner or 'absent'}"
        elif not lines:
            mode, why = "NO_CRON_COPY", "no active cron line fires the lane"
        elif len(cron_wrapped) < len(lines):
            mode, why = "UNPROTECTED_CRON_UNWRAPPED", f"{len(lines) - len(cron_wrapped)} of {len(lines)} active cron lines not effect_claim_cron.sh-wrapped"
        elif served_wrapper_fail_closed and manifest_owner == "n8n" and agreement != "DISAGREE":
            mode, why = "FAIL_CLOSED", "served wrapper fails closed; manifest names n8n"
        else:
            reasons = []
            if not served_wrapper_fail_closed:
                reasons.append("served wrapper fails OPEN on an unreadable ledger")
            if manifest_owner != "n8n":
                reasons.append("handover manifest does not name n8n")
            if agreement == "DISAGREE":
                reasons.append("manifest and ledger DISAGREE")
            mode, why = "LEDGER_HEALTHY_ONLY", "; ".join(reasons)
        ev = events.get(lane) or {}
        evc = ev.get("counts") or {}
        out.append({
            "lane_id": lane, "process": process, "owner": own.get("owner", ""), "epoch": own.get("epoch", ""),
            "manifest_owner": manifest_owner, "manifest_ledger": agreement, "handed_over": handed_over,
            "n8n_claim": n8n_claim, "cron_claim_config": cron_claim_cfg,
            "active_cron_lines": len(lines), "active_cron_lines_wrapped": len(armed),
            "active_cron_lines_cron_wrapped": len(cron_wrapped),
            "claims_done": c.get("DONE", 0), "claims_released": c.get("RELEASED", 0), "claims_failed": c.get("FAILED", 0),
            "claims_ambiguous": c.get("CLAIMED", 0) + c.get("UNKNOWN", 0),
            "late_write_fenced": bool(k.get("late_write_fenced")), "protection": level,
            "protection_mode": mode, "protection_mode_why": why,
            "ledger_readable_at_capture": bool(ledger_ok),
            "skipped_effect": int(evc.get("skipped_effect", 0)),
            "skipped_ownership_unknown": int(evc.get("skipped_ownership_unknown", 0)),
            "wrapper_ran": sum(int(evc.get(x, 0)) for x in ("run_unclaimed_cron_claim_false",
                                                              "run_unclaimed_ledger_unreachable", "completed_claimed")),
            "manifest_ledger_disagree_events": int(ev.get("manifest_ledger_disagree", 0)),
        })
    return out


def served_wrapper_policy(current: Path) -> dict[str, Any]:
    """Whether the SERVED release's scripts/effect_claim_cron.sh fails closed for a handed-over lane (it names the
    ``skipped_ownership_unknown`` event). Read-only: the file is grepped for the event name, never executed."""
    path = Path(os.path.realpath(current)) / "scripts" / "effect_claim_cron.sh"
    try:
        text = path.read_text()
    except OSError as e:
        return {"path": str(path), "readable": False, "fail_closed": False, "error": type(e).__name__}
    return {"path": str(path), "readable": True, "fail_closed": "skipped_ownership_unknown" in text,
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


def load_handover_manifest(path: Path) -> dict[str, Any]:
    """The durable handover manifest (N8nHandoverManifest@v1) the owner-switch path writes. Absent = {} + present
    False; malformed = error (reported, never repaired)."""
    res: dict[str, Any] = {"path": str(path), "present": False, "processes": {}}
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError:
        return res
    except Exception as e:  # noqa: BLE001
        res.update(present=True, error=f"{type(e).__name__}")
        return res
    res["present"] = True
    if not isinstance(doc, dict) or doc.get("schema") != "N8nHandoverManifest@v1" or not isinstance(doc.get("processes"), dict):
        res["error"] = "schema_mismatch"
        return res
    res["updated_at"] = doc.get("updated_at")
    res["processes"] = {str(k): v for k, v in doc["processes"].items() if isinstance(v, dict)}
    return res


# ── event-driven chain ────────────────────────────────────────────────────────────────────────────────────────────
def event_chain(
    registry_rows: Mapping[str, Mapping[str, Any]], receipts: Iterable[Mapping[str, Any]], cron: Mapping[str, Any],
    outcomes: Mapping[str, Mapping[str, Any]], since: datetime, until: datetime,
) -> list[dict[str, Any]]:
    """One row per ``dispatch.triggers`` entry in config/lane_registry.json (the only declared n8n event triggers).

    ``trigger_state``: LIVE_FIRING (>=1 live ``e:`` receipt in window), LIVE_ARMED_NOT_FIRED (dispatch mode live,
    no live e: receipt), SHADOW_FIRING (dispatch mode dry_run, >=1 dry e: receipt), SHADOW_NOT_FIRED, INACTIVE (lane
    not ACTIVE or dispatch off). A receipt cannot say WHICH of a lane's triggers fired, so e: counts are per lane.
    ``clock_fallback`` lists every clock that still fires the lane: the dispatch cron (d: slots) and active cron
    lines (wrapped lines are marked)."""
    e_counts: dict[str, Counter] = defaultdict(Counter)
    last_e: dict[str, datetime] = {}
    for r in receipts:
        if not str(r.get("run_id") or "").startswith("e:") or not in_window(r, since, until):
            continue
        lane = str(r.get("lane_id") or "")
        e_counts[lane][str(r.get("mode"))] += 1
        t = parse_ts(r.get("started_at")) or parse_ts(r.get("finished_at"))
        if t and (lane not in last_e or t > last_e[lane]):
            last_e[lane] = t
    active_by_lane: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for a in cron.get("active") or []:
        if a.get("lane_id"):
            active_by_lane[a["lane_id"]].append(a)
    out = []
    for lane, row in sorted(registry_rows.items()):
        d = row.get("dispatch") or {}
        trig = d.get("triggers") or []
        if not trig:
            continue
        mode = str(d.get("mode") or "off")
        ec = e_counts.get(lane) or Counter()
        if row.get("state") != "ACTIVE" or mode not in ("live", "dry_run"):
            st = "INACTIVE"
        elif ec.get("live"):
            st = "LIVE_FIRING"
        elif mode == "live":
            st = "LIVE_ARMED_NOT_FIRED"
        elif ec.get("dry_run"):
            st = "SHADOW_FIRING"
        else:
            st = "SHADOW_NOT_FIRED"
        fallback = [f"dispatch.cron {c}" for c in (d.get("cron") or [])]
        for a in active_by_lane.get(lane, []):
            fallback.append(f"crontab L{a['line_no']}" + (" (wrapped)" if a.get("wrapped_lane") else ""))
        for t in trig:
            src = str(t.get("source") or "")
            upstream = str(t.get("lane_id") or t.get("domain") or "")
            uo = (outcomes.get(upstream) or {}) if src == "run_done" else {}
            out.append({
                "lane_id": lane, "trigger_source": src, "upstream": upstream,
                "require_verdict": ",".join(t.get("require_verdict") or []),
                "dispatch_mode": mode, "trigger_state": st,
                "e_live_receipts": ec.get("live", 0), "e_dry_receipts": ec.get("dry_run", 0),
                "last_e_receipt_at": _iso(last_e.get(lane)),
                "upstream_live_useful": (int(uo.get("useful_live_output", 0)) + int(uo.get("verified_empty", 0))
                                         if src == "run_done" else ""),
                "clock_fallback": "; ".join(fallback) or "none",
                "has_clock_fallback": bool(fallback),
            })
    return out


# ── PR table ──────────────────────────────────────────────────────────────────────────────────────────────────────
def pr_proof(
    *, merge_sha: str, lanes: Iterable[str], receipts: Iterable[Mapping[str, Any]], contains,
) -> tuple[str, str]:
    """(PROVEN|PARTIAL|UNPROVEN, evidence). ``contains(ancestor, descendant)`` -> bool."""
    lanes = sorted(set(lanes))
    if not lanes:
        return "UNPROVEN", "no lane associated with the PR's changes"
    proven: dict[str, str] = {}
    for r in receipts:
        lane = r.get("lane_id")
        if lane not in lanes or lane in proven or r.get("mode") != "live":
            continue
        if receipt_class(r) not in ("useful", "empty"):
            continue
        sha = str(r.get("code_sha") or "")
        if sha and contains(merge_sha, sha):
            proven[lane] = str(r.get("run_id"))
    if len(proven) == len(lanes):
        return "PROVEN", f"{len(proven)}/{len(lanes)} lanes have a qualifying live receipt"
    if proven:
        return "PARTIAL", f"{len(proven)}/{len(lanes)} lanes proven; missing: {', '.join(l for l in lanes if l not in proven)}"
    return "UNPROVEN", f"0/{len(lanes)} lanes have a live produced/empty_allowed receipt at a SHA containing the merge"


def burn_down(lanes: Mapping[str, Mapping[str, Any]], migrations_by_date: Mapping[str, int], *, today: str,
              allowlisted: set[str], p1_last: Iterable[str], holds: Mapping[str, str]) -> dict[str, Any]:
    """Cohorts of what is left, owners and a linear projection from the observed migration rate."""
    p1 = set(p1_last)
    cohorts: dict[str, list[str]] = defaultdict(list)
    for lane, r in lanes.items():
        st = r["status"]
        if st == "PARALLEL":
            cohorts["C1_parallel_retire_cron_copy" if lane not in p1 else "C1p_parallel_p1_last"].append(lane)
        elif st in ("N8N_PRIMARY_UNPROVEN", "LIVE_LISTED_IDLE"):
            cohorts["C2_live_listed_unproven"].append(lane)
        elif st == "CRON_PRIMARY" and r.get("disposition") in ("MIGRATE_N8N", "CONSOLIDATE", "STAY_HOST", ""):
            if lane in p1:
                cohorts["C5_p1_last"].append(lane)
            elif r.get("dry_runs", 0) > 0:
                cohorts["C3_shadow_proven_ready_for_live"].append(lane)
            elif lane in allowlisted:
                cohorts["C4a_allowlisted_no_shadow_run"].append(lane)
            else:
                cohorts["C4b_not_onboarded"].append(lane)
        elif st == "CRON_PRIMARY" and r.get("disposition") == "RETIRE":
            cohorts["C7_retire_pending"].append(lane)
        elif st == "HELD":
            cohorts["C6_operator_hold"].append(lane)
    owners = {
        "C1_parallel_retire_cron_copy": "operator (crontab edit under config-write grant; cutover packet by Agent A)",
        "C1p_parallel_p1_last": "operator, after cron_overlap_trading_days=1 post first live RUN_DONE (policy p1_last)",
        "C2_live_listed_unproven": "Agent A (relay-live but no live RUN_DONE in window: find why; fix or delist)",
        "C3_shadow_proven_ready_for_live": "Agent A (canary packet + effect key) -> operator (relay live list + crontab)",
        "C4a_allowlisted_no_shadow_run": "Agent A (dispatch block / shadow wave so a dry run exists)",
        "C4b_not_onboarded": "Agent A (allowlist + health contract PR per lane)",
        "C5_p1_last": "operator (policy p1_last: last cohort, cron kept one trading day after proof)",
        "C6_operator_hold": "operator (holds in config/lane_cutover_policy.json)",
        "C7_retire_pending": "operator (disposition RETIRE but the cron line is still active: retire packet)",
    }
    remaining = sum(len(v) for k, v in cohorts.items() if k != "C6_operator_hold")
    days = sorted(migrations_by_date)
    recent = [migrations_by_date[d] for d in days[-3:]] if days else []
    rate = (sum(recent) / 3.0) if recent else 0.0
    projection = None
    if rate > 0:
        cal_days = remaining / rate
        projection = (datetime.fromisoformat(today) + timedelta(days=round(cal_days * 7 / 5 + 0.4999))).date().isoformat()
    return {
        "cohorts": {k: sorted(v) for k, v in sorted(cohorts.items())},
        "cohort_sizes": {k: len(v) for k, v in sorted(cohorts.items())},
        "owners": owners,
        "remaining_lanes_excluding_holds": remaining,
        "observed_migrations_by_date": dict(sorted(migrations_by_date.items())),
        "rate_lanes_per_trading_day": round(rate, 2),
        "projected_completion": projection,
        "assumptions": [
            "rate = mean of n8n-cutover/N8N-ONLY tagged cron retirements over the last 3 dates that had any "
            "(a calendar date with zero retirements is not in the denominator), so the rate is optimistic",
            "one migrating lane needs: allowlist + dry run + live canary + effect key/owner + cron retirement",
            "trading days only (5 of 7); holds, F07 and registry_systemd are excluded (retained by directive)",
            "no new lanes are added; open PRs in the section 9 table merge and deploy without rework",
        ],
        "holds": dict(holds),
    }


# ── loaders (read-only) ───────────────────────────────────────────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 60, cwd: Optional[Path] = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd or ROOT))
        return p.returncode, p.stdout, p.stderr
    except Exception as e:  # noqa: BLE001
        return 127, "", f"{type(e).__name__}: {e}"


def load_receipts(state_root: Path) -> list[dict[str, Any]]:
    out = []
    for f in glob.glob(str(state_root / "data" / "runtime" / "n8n_runs" / "*.json")):
        try:
            d = json.loads(Path(f).read_text())
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict):
            d.pop("env_allowlist", None)
            d.pop("stdout_tail", None)
            d.pop("stderr_tail", None)
            out.append(d)
    return out


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        with path.open() as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except FileNotFoundError:
        pass
    return out


def ledger_rows(state_root: Path, since: datetime) -> dict[str, Any]:
    path = state_root / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    res: dict[str, Any] = {"path": str(path), "ok": False}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=1")
        cur = con.cursor()
        cur.execute("BEGIN")
        s = _iso(since)
        res["runs_by_state_mode"] = [dict(r) for r in cur.execute(
            "SELECT state, mode, COUNT(*) AS n FROM runs WHERE COALESCE(started_at, requested_at) >= ? "
            "GROUP BY state, mode ORDER BY state, mode", (s,))]
        res["effect_claims"] = [dict(r) for r in cur.execute(
            "SELECT effect_key, process, slot, state, scheduler, epoch, run_id, claimed_at, finished_at, detail "
            "FROM effect_claims")]
        res["effect_owners"] = {r["process"]: dict(r) for r in cur.execute(
            "SELECT process, owner, epoch, switched_at, note FROM effect_owners")}
        res["dead_letters_open"] = [dict(r) for r in cur.execute(
            "SELECT slot_key, lane_id, mode, last_reason, dead_at FROM dead_letters WHERE released_at IS NULL "
            "AND dead_at >= ? ORDER BY dead_at", (s,))]
        res["breakers"] = [dict(r) for r in cur.execute(
            "SELECT lane_id, opened_at, consecutive, released_at FROM breakers")]
        res["comms_intents"] = [dict(r) for r in cur.execute(
            "SELECT intent_id, domain, kind, tier, workflow_id, state, count, first_at, last_at FROM comms_intents "
            "WHERE last_at >= ?", (s,))]
        cur.execute("ROLLBACK")
        con.close()
        res["ok"] = True
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return res


def comms_rows(day_start: datetime) -> dict[str, Any]:
    """Today's OUTBOUND communication_events (+ delivery status). SELECT only, readonly session."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"ok": False, "error": "refusing a DB connection under pytest", "rows": []}
    try:
        import psycopg2  # noqa: PLC0415
        import psycopg2.extras  # noqa: PLC0415

        kw: dict[str, Any] = {
            "host": os.environ.get("DB_HOST", "localhost"),
            "dbname": os.environ.get("DB_NAME", "trade_ai"),
            "user": os.environ.get("DB_USER", "trade_ai"),
            "connect_timeout": 10,
            "cursor_factory": psycopg2.extras.RealDictCursor,
        }
        if os.environ.get("DB_PORT"):
            kw["port"] = os.environ["DB_PORT"]
        conn = psycopg2.connect(**kw)  # password: libpq (~/.pgpass / PGPASSWORD); never read or printed here
        conn.set_session(readonly=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT e.event_id, e.producer, e.message_class, e.created_at, e.run_id, e.source_job, "
            "       substring(e.sanitized_body from '· via [^\\n]*') AS body, "
            "       e.provider_settlement_state, "
            "       (SELECT string_agg(DISTINCT d.status, ',') FROM communication_deliveries d "
            "         WHERE d.event_id = e.event_id) AS delivery_status "
            "FROM communication_events e WHERE e.direction = 'OUTBOUND' AND e.created_at >= %s "
            "ORDER BY e.created_at", (day_start,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.rollback()
        conn.close()
        return {"ok": True, "rows": rows}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}", "rows": []}


def served_sha(current: Path) -> dict[str, Any]:
    target = os.path.realpath(current)
    name = os.path.basename(target)
    prefix = name.split("-", 1)[0]
    rc, out, _ = _run(["git", "rev-parse", "--verify", "--quiet", f"{prefix}^{{commit}}"])
    return {"release_dir": target, "short": prefix, "sha": out.strip() if rc == 0 else UNKNOWN}


def is_ancestor(a: str, b: str, cache: dict) -> bool:
    key = (a, b)
    if key not in cache:
        rc, _, _ = _run(["git", "merge-base", "--is-ancestor", a, b])
        cache[key] = rc == 0
    return cache[key]


def _fabric_lane_view(d: Mapping[str, Any]) -> dict[str, Any]:
    """lane -> its process definition, so a changed process associates every step and runner lane."""
    out: dict[str, Any] = {}
    for _name, p in (d.get("processes") or {}).items():
        lanes = [s.get("lane_id") for s in (p.get("steps") or {}).values()] + list((p.get("runner_lanes") or {}).values())
        for lane in lanes:
            if lane:
                out[lane] = p
    return out


def pr_lanes(number: int, merge_sha: str, files: list[str], registry_rows: Mapping[str, Any]) -> list[str]:
    """Lanes associated with a PR: changed scripts that are a lane's match, and lane rows the PR changed."""
    lanes: set[str] = set()
    for f in files:
        if f.startswith("scripts/") and f.endswith((".py", ".sh")) and "/lib/" not in f:
            base = f.split("/", 1)[1]
            for lane, row in registry_rows.items():
                s = row.get("scheduler") or {}
                if row.get("state") == "ACTIVE" and (base in str(s.get("match") or "") or base in str(s.get("command_text") or "")):
                    lanes.add(lane)
    for cfg, getter in (
        ("config/lane_registry.json", lambda d: {r["lane_id"]: r for r in d.get("lanes", [])}),
        ("config/n8n_effect_keys.json", lambda d: dict(d.get("lanes") or {})),
        ("config/n8n_run_allowlist.json", lambda d: {r.get("lane_id"): r for r in d.get("lanes", []) if isinstance(r, dict)}),
        ("config/n8n_fabric_processes.json", _fabric_lane_view),
    ):
        if cfg not in files or not merge_sha:
            continue
        rc1, before, _ = _run(["git", "show", f"{merge_sha}^1:{cfg}"])
        rc2, after, _ = _run(["git", "show", f"{merge_sha}:{cfg}"])
        if rc1 or rc2:
            continue
        try:
            b, a = getter(json.loads(before)), getter(json.loads(after))
        except Exception:  # noqa: BLE001
            continue
        for lane in set(a) | set(b):
            if a.get(lane) != b.get(lane) and lane:
                lanes.add(lane)
    return sorted(lanes)


# ── report ────────────────────────────────────────────────────────────────────────────────────────────────────────
def write_csv(path: Path, rows: list[Mapping[str, Any]], cols: Optional[list[str]] = None) -> None:
    cols = cols or (list(rows[0].keys()) if rows else ["empty"])
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v) for k, v in r.items()})


def md_table(rows: list[Mapping[str, Any]], cols: list[str]) -> str:
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")).replace("|", "/").replace("\n", " ") for c in cols) + " |")
    return "\n".join(out) + "\n"


def build(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    since = parse_ts(args.since) or parse_ts(DEFAULT_SINCE)
    until = now
    state_root = Path(args.state_root)
    unmeasured: list[str] = []

    rc, cron_text, err = _run(["crontab", "-l"], timeout=30)
    if rc != 0:
        unmeasured.append(f"crontab -l failed ({err.strip()[:80]}): cron state empty")
        cron_text = ""
    cron_sha = hashlib.sha256(cron_text.encode()).hexdigest()
    served = served_sha(Path(args.current))
    _rc, head, _ = _run(["git", "rev-parse", "HEAD"])
    checkout_sha = head.strip() or UNKNOWN

    registry = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    registry_rows = {r["lane_id"]: r for r in registry.get("lanes", [])}
    policy_path = ROOT / "config" / "lane_cutover_policy.json"
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
    if not policy:
        unmeasured.append("config/lane_cutover_policy.json absent: holds/p1_last empty")
    if policy and not (Path(served["release_dir"]) / "config" / "lane_cutover_policy.json").exists():
        unmeasured.append(
            "config/lane_cutover_policy.json is read from this checkout (main); the served release does not contain "
            "it, so its holds / p1_last are merged policy, not yet the enforced dispatch gate")
    holds = dict(policy.get("holds") or {})
    p1_last = list(policy.get("p1_last") or [])
    effect_cfg = json.loads((ROOT / "config" / "n8n_effect_keys.json").read_text()).get("lanes") or {}
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    allowlisted = {r.get("lane_id") for r in allow.get("lanes", []) if isinstance(r, dict)}
    fabric = json.loads((ROOT / "config" / "n8n_fabric_processes.json").read_text()).get("processes") or {}

    disp_rows = list(csv.DictReader(DISPOSITION_CSV.open())) if DISPOSITION_CSV.exists() else []
    families: dict[str, str] = dict(policy.get("families") or {})
    dispositions: dict[str, str] = {}
    for r in disp_rows:
        if r.get("lane_id"):
            if r.get("family_id") and not families.get(r["lane_id"]):
                families[r["lane_id"]] = r["family_id"]
            dispositions.setdefault(r["lane_id"], r.get("disposition") or "")
    disp_totals = disposition_totals(disp_rows)

    try:
        live_lanes = parse_live_lanes(Path(args.live_lanes_env).read_text())
    except Exception as e:  # noqa: BLE001
        live_lanes = []
        unmeasured.append(f"relay live-lane list unreadable ({type(e).__name__}): relay_live=false for every lane")

    best = lane_matcher(registry)
    cron = parse_cron(cron_text, best)
    receipts = load_receipts(state_root)
    outcomes = count_outcomes(receipts, since, until)
    relay = load_jsonl(state_root / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl")
    refusals = count_refusals(relay, since, until)
    led = ledger_rows(state_root, since)
    if not led.get("ok"):
        unmeasured.append(f"coordination ledger unreadable: {led.get('error')}")
    claims = count_effect_claims(led.get("effect_claims") or [], since, until)
    events_path = Path(args.effect_events) if getattr(args, "effect_events", "") else state_root / "logs" / "effect_claim_events.jsonl"
    effect_event_rows = load_jsonl(events_path)
    if not events_path.exists():
        unmeasured.append(f"{events_path} absent: no wrapper events (no cron line can count as stood down)")
    wrap_schedules: dict[str, list[str]] = defaultdict(list)
    for a in cron["active"]:
        if a.get("wrapped_lane"):
            wrap_schedules[a["wrapped_lane"]].append(a["schedule"])
    effect_events = count_effect_events(effect_event_rows, since, until, schedules=wrap_schedules)
    wrapper_times = sorted(t for t in (parse_ts(r.get("ts")) for r in effect_event_rows) if t)
    manifest_path = Path(getattr(args, "handover_manifest", "") or os.environ.get("TRADEAI_N8N_HANDOVER_MANIFEST")
                         or state_root / "data" / "governance" / "n8n_handover_manifest.json")
    manifest = load_handover_manifest(manifest_path)
    if manifest.get("error"):
        unmeasured.append(f"handover manifest unreadable ({manifest['error']}): reported, not repaired")
    wrapper_policy = served_wrapper_policy(Path(args.current))

    lanes = lane_states(registry_rows=registry_rows, live_lanes=live_lanes, cron=cron, families=families,
                        dispositions=dispositions, holds=holds, outcomes=outcomes, effect_events=effect_events)
    for lane, row in lanes.items():
        o = outcomes.get(lane) or {}
        for k in OUTCOME_KEYS:
            row[k] = o.get(k, 0)
        row["refusals"] = sum((refusals.get(lane) or Counter()).values())
        row["refusal_reasons"] = dict(refusals.get(lane) or {})
        c = claims.get(lane) or Counter()
        row["ambiguous_effects"] = c.get("CLAIMED", 0) + c.get("UNKNOWN", 0)
        row["on_p1_last"] = lane in p1_last

    status_counts = Counter(r["status"] for r in lanes.values())
    active_lines = cron["active"]
    mapped = [a for a in active_lines if a["lane_id"]]
    commented_kinds = Counter(c["kind"] for c in cron["commented"])
    migrations_by_date = Counter(c["date"] for c in cron["commented"] if c["kind"] in ("N8N_CUTOVER", "N8N_ONLY_TEST"))

    migration = {
        "active_cron_lines": len(active_lines),
        "active_cron_lines_mapped_to_a_lane": len(mapped),
        "active_cron_lines_unmapped": len(active_lines) - len(mapped),
        "unique_lanes_with_active_cron": len({a["lane_id"] for a in mapped}),
        "commented_lines_by_kind": dict(commented_kinds),
        "unique_lanes_by_status": {s: status_counts.get(s, 0) for s in STATUSES},
        "relay_live_list_size": len(live_lanes),
        "relay_live_lanes": live_lanes,
        "migrated_proven": sorted(l for l, r in lanes.items() if r["status"] == "MIGRATED_PROVEN"),
        "n8n_native": sorted(l for l, r in lanes.items() if r["status"] == "N8N_NATIVE"),
        "n8n_primary_unproven": sorted(l for l, r in lanes.items() if r["status"] == "N8N_PRIMARY_UNPROVEN"),
        "parallel": sorted(l for l, r in lanes.items() if r["status"] == "PARALLEL"),
        "live_listed_idle": sorted(l for l, r in lanes.items() if r["status"] == "LIVE_LISTED_IDLE"),
        "consolidated": sorted(l for l, r in lanes.items() if r["status"] == "CONSOLIDATED"),
        "measure_combinations": measure_combinations(lanes),
        "measures": {
            "n8n_live_lanes_measured": sum(len(v) for v in measure_combinations(lanes).values()),
            "scheduler_ownership_n8n": sum(1 for r in lanes.values() if r.get("sched_n8n")),
            "  via_cron_retired_tag": sum(1 for r in lanes.values() if r.get("sched_evidence") == "cron_retired_tag"),
            "  via_cron_wrapped_skipping": sum(1 for r in lanes.values()
                                                if r.get("sched_evidence") == "cron_wrapped_skipping"),
            "  via_n8n_native_row": sum(1 for r in lanes.values() if r.get("sched_evidence") == "n8n_native_row"),
            "execution_live_run_done": sum(1 for r in lanes.values() if r.get("measure_combo") and r.get("executed")),
            "useful_output": sum(1 for r in lanes.values() if r.get("measure_combo") and r.get("useful")),
            "proven_S_E_U": sum(1 for r in lanes.values() if r.get("measure_combo") == "S1E1U1"
                                and r["status"] in ("MIGRATED_PROVEN", "N8N_NATIVE")),
            "owned_but_no_live_run_S1E0": sum(1 for r in lanes.values() if str(r.get("measure_combo")).startswith("S1E0")
                                              and r["status"] not in ("HELD", "RETAINED_F07", "RETAINED_SYSTEMD")),
        },
        "wrapped_cron_lines": sum(1 for a in active_lines if a.get("wrapped_lane")),
        "stood_down_skips_scheduled": sum(int(e.get("scheduled_skips", 0)) for e in effect_events.values()),
        "stood_down_skips_offschedule": sum(int(e.get("offschedule_skips", 0)) for e in effect_events.values()),
        "wrapped_cron_lines_standing_down": sum(
            1 for a in active_lines if a.get("wrapped_lane")
            and (effect_events.get(a["wrapped_lane"]) or {}).get("last_event") in SKIP_EVENTS),
    }

    # retained exceptions
    retained = []
    for lane, r in sorted(lanes.items()):
        if r["status"] == "RETAINED_F07":
            retained.append({"lane_id": lane, "class": "F07", "reason": "AGENTS §23.25 / directive 2026-10-15: F07 "
                             "host daemons, watchdogs and guards stay on the host", "owner": "platform"})
        elif r["status"] == "RETAINED_SYSTEMD" and r["registry_state"] == "ACTIVE":
            retained.append({"lane_id": lane, "class": "registry_systemd", "reason": "directive 2026-10-15: every "
                             "registry_systemd row stays (DEFERRED-I2)", "owner": registry_rows.get(lane, {}).get("owner", "")})
        elif r["status"] == "HELD":
            retained.append({"lane_id": lane, "class": "hold", "reason": holds.get(lane, ""), "owner": "operator"})
    backstops = []
    for lane, owner, purpose in BACKSTOPS:
        reg = registry_rows.get(lane) or {}
        s = reg.get("scheduler") or {}
        lr = lanes.get(lane) or {}
        backstops.append({
            "lane_id": lane, "owner": owner, "purpose": purpose,
            "registry_state": reg.get("state", "UNREGISTERED"), "scheduler": f"{s.get('kind', '-')}:{s.get('expression', '')}",
            "status": lr.get("status", "UNREGISTERED"), "active_cron_lines": lr.get("active_cron_lines", 0),
            "relay_live": lr.get("relay_live", False),
        })

    fam_rows = family_ownership(lanes)
    cron_active_lanes = {a["lane_id"] for a in mapped}
    fabric_rows = fabric_process_ownership(fabric, lanes, outcomes, cron_active_lanes)

    # incidents
    breaches = load_jsonl(state_root / "data" / "runtime" / "supervisor_breaches.jsonl")
    diagnoses = load_jsonl(state_root / "data" / "runtime" / "n8n_diagnoses" / "diagnoses.jsonl")
    recoveries = [r for r in load_jsonl(state_root / "data" / "runtime" / "supervisor_recoveries.jsonl")
                  if (parse_ts(r.get("ts")) or since) >= since]
    episodes = incident_episodes(breaches=breaches, diagnoses=diagnoses, receipts=receipts, since=since, until=until,
                                 signal_now=lambda s: signal_time(s, state_root))
    try:
        fd_state = json.loads((state_root / "data" / "runtime" / "n8n_failure_diagnosis_state.json").read_text())
    except Exception:  # noqa: BLE001
        fd_state = {}
        unmeasured.append("n8n_failure_diagnosis_state.json unreadable")
    fd_window = [v for v in (fd_state.get("diagnosed") or {}).values() if (parse_ts(v.get("at")) or since) >= since]
    incidents = {
        "episodes": len(episodes),
        "events": sum(e["events"] for e in episodes),
        "duplicate_events": sum(e["duplicate_events"] for e in episodes),
        "by_recovery": dict(Counter(e["recovery"] for e in episodes)),
        "by_class": dict(Counter("run_receipt_failure" if e["failure_class"].startswith("run:")
                                 else e["failure_class"] for e in episodes)),
        "remediation_rows_requested_not_heals": {
            "supervisor_recoveries_in_window": len(recoveries),
            "executed_true": sum(1 for r in recoveries if r.get("executed") is True),
            "modes": dict(Counter(str(r.get("mode")) for r in recoveries)),
            "diagnoses_with_remediation_run_id": sum(1 for d in diagnoses if d.get("remediation_run_id")
                                                     and (parse_ts(d.get("at")) or since) >= since),
        },
        "diagnoses_in_window_by_outcome": dict(Counter(str(d.get("outcome")) for d in diagnoses
                                                       if (parse_ts(d.get("at")) or since) >= since)),
        "failure_diagnosis_state": {
            "diagnosed_in_window": len(fd_window),
            "diagnosed_by_action": dict(Counter(str(v.get("action_id")) for v in fd_window)),
            "pending": len(fd_state.get("pending") or {}),
            "lane_last_remediation": len(fd_state.get("lane_last_remediation") or {}),
        },
        "dead_letters_unreleased_in_window": led.get("dead_letters_open") or [],
    }

    # notifications (today ET)
    day_start = et_midnight_utc(now)
    comm = comms_rows(day_start)
    if not comm.get("ok"):
        unmeasured.append(f"communication_events not readable: {comm.get('error')}")
    router_today = [r for r in load_jsonl(state_root / "data" / "runtime" / "notification_intent_receipts.jsonl")
                    if (parse_ts(r.get("ts")) or since) >= day_start]
    intents_today = [i for i in (led.get("comms_intents") or []) if (parse_ts(i.get("last_at")) or since) >= day_start]
    notif = summarize_notifications(comm.get("rows") or [], router_today, intents_today)
    notif["day_start_utc"] = _iso(day_start)
    notif["router_ledger"] = "data/runtime/notification_intent_receipts.jsonl (NotificationIntentRoute@v1)"
    notif["join_note"] = (
        "No shared key joins a router receipt to a communication_events row (router rows carry producer + decision, "
        "events carry one generic chokepoint producer name); the chain is reported as per-stage counts. "
        "Per-message intent->delivery linkage is UNKNOWN except where the provenance footer names the lane."
    )
    try:
        budget = json.loads((state_root / "data" / "runtime" / "telegram_daily_send_budget.json").read_text())
        notif["telegram_daily_send_budget_today"] = budget.get(now.astimezone().date().isoformat(), UNKNOWN) \
            if isinstance(budget, dict) else UNKNOWN
    except Exception:  # noqa: BLE001
        notif["telegram_daily_send_budget_today"] = UNKNOWN
    try:
        idem = json.loads((state_root / "data" / "runtime" / "telegram_send_idempotency.json").read_text())
        ts0 = day_start.timestamp()
        today_keys = [k for k, v in idem.items() if isinstance(v, dict) and float(v.get("ts") or 0) >= ts0]
        notif["telegram_send_idempotency_today_by_prefix"] = dict(Counter(k.split(":", 1)[0] for k in today_keys))
    except Exception:  # noqa: BLE001
        notif["telegram_send_idempotency_today_by_prefix"] = UNKNOWN

    # effect protection
    effect_rows = effect_protection(effect_cfg, led.get("effect_owners") or {}, cron_text, cron, claims,
                                    manifest=manifest.get("processes") or {},
                                    served_wrapper_fail_closed=bool(wrapper_policy.get("fail_closed")),
                                    ledger_ok=bool(led.get("ok")), effect_events=effect_events)
    ev_totals: Counter = Counter()
    for e in effect_events.values():
        ev_totals.update(e["counts"])
    effect_summary = {
        "by_protection_mode": {m: sum(1 for r in effect_rows if r["protection_mode"] == m) for m in PROTECTION_MODES},
        "protected_fail_closed": sorted(r["lane_id"] for r in effect_rows if r["protection_mode"] == "FAIL_CLOSED"),
        "protected_only_while_ledger_healthy": sorted(
            r["lane_id"] for r in effect_rows if r["protection_mode"] == "LEDGER_HEALTHY_ONLY"),
        "manifest_ledger": dict(Counter(r["manifest_ledger"] for r in effect_rows)),
        "manifest_ledger_disagree": sorted(r["lane_id"] for r in effect_rows if r["manifest_ledger"] == "DISAGREE"),
        "ledger_readable_at_capture": bool(led.get("ok")),
        "served_wrapper": wrapper_policy,
        "handover_manifest": {k: v for k, v in manifest.items() if k != "processes"}
        | {"processes": len(manifest.get("processes") or {})},
        "wrapper_events_path": str(events_path),
        "wrapper_events_in_window": dict(ev_totals),
        "wrapper_first_event_at": _iso(wrapper_times[0]) if wrapper_times else None,
        "wrapper_last_event_at": _iso(wrapper_times[-1]) if wrapper_times else None,
        "lanes_stood_down": sorted(l for l, e in effect_events.items()
                                   if any(e["counts"].get(k) for k in SKIP_EVENTS)),
        "lanes_wrapper_ran_command": sorted(l for l, e in effect_events.items()
                                            if any(e["counts"].get(k) for k in RAN_EVENTS)),
    }
    chain = event_chain(registry_rows, receipts, cron, outcomes, since, until)

    # PRs
    pr_rows = []
    anc_cache: dict = {}
    gh_ok = True
    for n in PR_RANGE:
        rc, out, err = _run(["gh", "pr", "view", str(n), "--json", "number,title,state,mergedAt,mergeCommit,files"], 60)
        if rc != 0:
            gh_ok = False
            pr_rows.append({"pr": n, "merged": UNKNOWN, "deployed": UNKNOWN, "proven": UNKNOWN,
                            "evidence": f"gh failed: {err.strip()[:80]}"})
            continue
        p = json.loads(out)
        merge_sha = ((p.get("mergeCommit") or {}).get("oid") or "") if p.get("state") == "MERGED" else ""
        files = [f.get("path") for f in p.get("files") or []]
        deployed = bool(merge_sha and served["sha"] != UNKNOWN and is_ancestor(merge_sha, served["sha"], anc_cache))
        lanes_for_pr = pr_lanes(n, merge_sha, files, registry_rows) if merge_sha else []
        if not merge_sha:
            proven, ev = "UNPROVEN", "not merged"
        elif n == 1817:
            n8n_footer = [r for r in comm.get("rows") or [] if provenance_of(r)[0] == "n8n" and _FOOTER_RE.search(str(r.get("body") or ""))]
            any_footer = [r for r in comm.get("rows") or [] if _FOOTER_RE.search(str(r.get("body") or ""))]
            proven = "PROVEN" if n8n_footer else ("PARTIAL" if any_footer else "UNPROVEN")
            ev = (f"{len(any_footer)} outbound rows today carry a footer, {len(n8n_footer)} name n8n"
                  if comm.get("ok") else "communication_events unreadable")
        else:
            proven, ev = pr_proof(merge_sha=merge_sha, lanes=lanes_for_pr, receipts=receipts,
                                  contains=lambda a, b: is_ancestor(a, b, anc_cache))
            if not deployed:
                ev = "NOT DEPLOYED (merge commit not in served SHA); " + ev
        pr_rows.append({
            "pr": n, "title": p.get("title", "")[:100], "state": p.get("state"),
            "merged": bool(merge_sha), "merge_sha": merge_sha[:10], "merged_at": p.get("mergedAt"),
            "deployed": deployed, "proven": proven, "evidence": ev,
            "associated_lanes": " ".join(lanes_for_pr),
        })
    if not gh_ok:
        unmeasured.append("gh pr view failed for at least one PR: merged/deployed/proven UNKNOWN there")

    bd = burn_down(lanes, migrations_by_date, today=now.date().isoformat(), allowlisted=allowlisted,
                   p1_last=p1_last, holds=holds)

    totals = Counter()
    for lane, o in outcomes.items():
        for k in OUTCOME_KEYS:
            totals[k] += o.get(k, 0)
    refusal_totals = Counter()
    for c in refusals.values():
        refusal_totals.update(c)
    run_summary = {
        "receipts_in_window": sum(o["live_runs"] + o["dry_runs"] for o in outcomes.values()),
        "lanes_with_receipts": len(outcomes),
        "lanes_with_live_receipts": sum(1 for o in outcomes.values() if o["live_runs"]),
        **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in totals.items()},
        "refusals": sum(refusal_totals.values()),
        "refusals_by_reason": dict(refusal_totals.most_common()),
        "ambiguous_effects": sum(c.get("CLAIMED", 0) + c.get("UNKNOWN", 0) for c in claims.values()),
        "effect_claims_by_state": dict(sum((Counter(c) for c in claims.values()), Counter())),
        "ledger_runs_by_state_mode": led.get("runs_by_state_mode"),
    }

    packet = {
        "schema": SCHEMA, "authority": AUTHORITY, "generated_at": _iso(now),
        "window": {"since": _iso(since), "until": _iso(until), "notifications_day_start": _iso(day_start)},
        "served": served, "checkout_sha": checkout_sha, "crontab_sha256": cron_sha, "definitions": DEFINITIONS,
        "disposition": disp_totals, "migration": migration, "retained": retained, "backstops": backstops,
        "families": fam_rows, "fabric_processes": fabric_rows, "lanes": lanes, "run_summary": run_summary,
        "incidents": incidents, "episodes": episodes, "notifications": notif, "effect_protection": effect_rows,
        "effect_summary": effect_summary, "event_chain": chain,
        "capture": {"captured_at_utc": _iso(now), "captured_at_et": _et(now),
                    "context": list(getattr(args, "context", None) or [])},
        "prs": pr_rows, "burn_down": bd, "unmeasured": unmeasured,
        "sources": {
            "registry": "config/lane_registry.json", "policy": "config/lane_cutover_policy.json" if policy else None,
            "disposition_csv": str(DISPOSITION_CSV.relative_to(ROOT)), "receipts": "<state>/data/runtime/n8n_runs/*.json",
            "ledger": "<state>/data/governance/n8n_coordination_ledger.sqlite (mode=ro)",
            "relay_log": "<state>/data/runtime/n8n_relay/relay_log.jsonl",
            "live_lanes": "~/.config/tradeai/n8n-live-lanes.env (TRADEAI_N8N_RELAY_LIVE_LANES names only)",
        },
    }
    packet["comparison"] = compare_packets(Path(args.compare), packet) if getattr(args, "compare", "") else None
    return packet


def _et(d: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        return d.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:  # noqa: BLE001
        return UNKNOWN


COMPARE_RUN_KEYS = ("live_runs", "dry_runs", "useful_live_output", "verified_empty", "unverified_ok", "failures",
                    "lock_skips", "refusals", "ambiguous_effects")
COMPARE_MIGRATION_KEYS = ("active_cron_lines", "unique_lanes_with_active_cron", "relay_live_list_size")


def compare_packets(prev_dir: Path, cur: Mapping[str, Any]) -> dict[str, Any]:
    """What changed against an earlier packet (its summary.json + lanes.csv). Definitions may differ between the two
    packets: a lane that left MIGRATED_PROVEN is listed with its CURRENT status and reason, so a definition change is
    never read as a regression of the lane."""
    try:
        prev = json.loads((prev_dir / "summary.json").read_text())
        prev_lanes = {r["lane_id"]: r for r in csv.DictReader((prev_dir / "lanes.csv").open())}
    except Exception as e:  # noqa: BLE001
        return {"prev_dir": str(prev_dir), "error": f"{type(e).__name__}: {str(e)[:120]}"}
    pm, cm = prev.get("migration") or {}, cur["migration"]
    ps, cs = pm.get("unique_lanes_by_status") or {}, cm["unique_lanes_by_status"]
    prs, crs = prev.get("run_summary") or {}, cur["run_summary"]
    cur_lanes = cur["lanes"]
    prev_proven = {l for l, r in prev_lanes.items() if r.get("status") == "MIGRATED_PROVEN"}
    now_proven = {l for l, r in cur_lanes.items() if r["status"] == "MIGRATED_PROVEN"}
    moved = []
    for lane in sorted(set(prev_lanes) | set(cur_lanes)):
        a = (prev_lanes.get(lane) or {}).get("status", "")
        b = (cur_lanes.get(lane) or {}).get("status", "")
        if a != b:
            moved.append({"lane_id": lane, "prev_status": a or "(absent)", "status": b or "(absent)",
                          "why_now": (cur_lanes.get(lane) or {}).get("unproven_reason", "")})
    return {
        "prev_dir": (str(prev_dir.resolve().relative_to(ROOT)) if prev_dir.resolve().is_relative_to(ROOT)
                     else str(prev_dir)),
        "prev_generated_at": prev.get("generated_at"),
        "prev_served": (prev.get("served") or {}).get("short"),
        "cur_served": cur["served"].get("short"),
        "prev_crontab_sha256": prev.get("crontab_sha256"),
        "crontab_changed": prev.get("crontab_sha256") != cur.get("crontab_sha256"),
        "status": {s: {"prev": int(ps.get(s, 0)), "now": int(cs.get(s, 0))} for s in STATUSES
                   if int(ps.get(s, 0)) or int(cs.get(s, 0))},
        "migration": {k: {"prev": pm.get(k), "now": cm.get(k)} for k in COMPARE_MIGRATION_KEYS},
        "run_summary": {k: {"prev": prs.get(k), "now": crs.get(k)} for k in COMPARE_RUN_KEYS},
        "proven_kept": sorted(prev_proven & now_proven),
        "proven_added": sorted(now_proven - prev_proven),
        "proven_dropped": [{"lane_id": l, "status": (cur_lanes.get(l) or {}).get("status", "(absent)"),
                            "why_now": (cur_lanes.get(l) or {}).get("unproven_reason", "")}
                           for l in sorted(prev_proven - now_proven)],
        "status_moves": moved,
    }


def render(p: Mapping[str, Any]) -> str:
    m, rs, inc, n, bd = p["migration"], p["run_summary"], p["incidents"], p["notifications"], p["burn_down"]
    es = p["effect_summary"]
    L: list[str] = []
    L.append(f"# n8n cutover outcomes — {p['generated_at']}\n")
    L.append(f"**Status:** MEASUREMENT (read-only snapshot; a later packet supersedes it)  \n"
             f"**Date:** {p['generated_at']}  \n**Authority:** {p['authority']}\n")
    L.append(f"Schema `{p['schema']}` · authority `{p['authority']}` · generator `scripts/report_n8n_cutover_outcomes.py` (read-only).\n")
    L.append("## 1. Header\n")
    L.append(md_table([
        {"item": "served SHA", "value": f"`{p['served']['sha']}` ({os.path.basename(p['served']['release_dir'])})"},
        {"item": "config / registry read from checkout", "value": f"`{p.get('checkout_sha', UNKNOWN)}` (not the served release)"},
        {"item": "measurement window (UTC)", "value": f"{p['window']['since']} → {p['window']['until']}"},
        {"item": "notifications window (today, ET midnight)", "value": p["window"]["notifications_day_start"]},
        {"item": "sha256(crontab -l)", "value": f"`{p['crontab_sha256']}`"},
        {"item": "captured at", "value": f"{p['capture']['captured_at_utc']} ({p['capture']['captured_at_et']})"},
        {"item": "served effect-claim wrapper", "value": (
            f"{'FAIL-CLOSED' if es['served_wrapper'].get('fail_closed') else 'FAIL-OPEN on an unreadable ledger'} "
            f"(`{es['served_wrapper'].get('path')}`)")},
        {"item": "wrapper events (window)", "value": (
            f"{es['wrapper_events_in_window'] or 'none'}; first event {es['wrapper_first_event_at'] or '-'}, "
            f"last {es['wrapper_last_event_at'] or '-'}")},
        {"item": "handover manifest", "value": (
            f"{'present' if es['handover_manifest'].get('present') else 'ABSENT'} "
            f"({es['handover_manifest'].get('processes', 0)} processes) `{es['handover_manifest'].get('path')}`")},
        {"item": "coordination ledger readable at capture", "value": es["ledger_readable_at_capture"]},
    ], ["item", "value"]))
    for c in p["capture"].get("context") or []:
        L.append(f"- Context (operator-supplied): {c}")
    L.append("\n### Counting definitions\n")
    for k, v in p["definitions"].items():
        L.append(f"- **{k}** — {v}")
    d = p["disposition"]
    L.append(f"\nDisposition table: **{d['rows']} rows** ({d['by_source']}), **{d['unique_lanes']} unique lanes**. "
             f"Rows by disposition {d['by_disposition']}; unique lanes by disposition {d['unique_lanes_by_disposition']}. "
             f"So {d['by_disposition'].get('MIGRATE_N8N', 0)} MIGRATE_N8N rows = "
             f"{d['unique_lanes_by_disposition'].get('MIGRATE_N8N', 0)} unique lanes, not jobs.\n")

    L.append("## 2. Migration state\n")
    L.append(md_table([
        {"measure": "active cron lines (now)", "n": m["active_cron_lines"]},
        {"measure": "  … attributed to a lane", "n": m["active_cron_lines_mapped_to_a_lane"]},
        {"measure": "  … unmapped (no registry match)", "n": m["active_cron_lines_unmapped"]},
        {"measure": "unique lanes with ≥1 active cron line (remaining cron primaries)", "n": m["unique_lanes_with_active_cron"]},
        {"measure": "commented cron lines by tag", "n": m["commented_lines_by_kind"]},
        {"measure": "relay live list (lanes n8n may run LIVE)", "n": m["relay_live_list_size"]},
    ], ["measure", "n"]))
    L.append("\nUnique lanes by status (each lane exactly once):\n")
    L.append(md_table([{"status": k, "lanes": v} for k, v in m["unique_lanes_by_status"].items()], ["status", "lanes"]))
    L.append("\n### Three separate measures (n8n-live lanes)\n")
    L.append("S = scheduler ownership, E = execution (live RUN_DONE), U = useful output (produced / empty_allowed). "
             "Proven = S and E and U.\n")
    L.append(md_table([{"measure": k, "lanes": v} for k, v in m["measures"].items()], ["measure", "lanes"]))
    L.append(f"\nWrapped active cron lines: {m['wrapped_cron_lines']}; of those, last wrapper event is a skip "
             f"(stood down): {m['wrapped_cron_lines_standing_down']}. Skip events on a scheduled fire of the line: "
             f"{m['stood_down_skips_scheduled']}; off-schedule (manual / install verification, not a slot): "
             f"{m['stood_down_skips_offschedule']}. S1E0 lanes (n8n owns the schedule, no live n8n RUN_DONE in the "
             f"window): {m['measures']['owned_but_no_live_run_S1E0']}. For these the wrapped cron copy stands down at "
             "its next slot, so the effect now depends on n8n firing it, and there is no live n8n RUN_DONE in the "
             "window yet to show that it does.\n")
    L.append("\nLanes by combination:\n")
    L.append(md_table([{"combo": k, "meaning": COMBO_LABELS.get(k, ""), "lanes": len(v), "lane_ids": ", ".join(v)}
                       for k, v in m["measure_combinations"].items()], ["combo", "meaning", "lanes", "lane_ids"]))
    L.append(f"\n**Migrated (proven: S+E+U)** ({len(m['migrated_proven'])}): {', '.join(m['migrated_proven']) or '—'}\n")
    L.append(f"\n**n8n-native** ({len(m['n8n_native'])}): {', '.join(m['n8n_native']) or '—'}\n")
    L.append(f"\n**PARALLEL — cron + n8n live both firing** ({len(m['parallel'])}): {', '.join(m['parallel']) or '—'}\n")
    L.append(f"\n**LIVE_LISTED_IDLE — relay-live, cron line active, 0 live n8n runs in window** "
             f"({len(m['live_listed_idle'])}): {', '.join(m['live_listed_idle']) or '—'}\n")
    unp = [p["lanes"][l] for l in m["n8n_primary_unproven"]]
    L.append(f"\n**n8n primary but UNPROVEN** ({len(unp)}):\n")
    L.append(md_table(unp, ["lane_id", "measure_combo", "unproven_reason", "sched_evidence", "n8n_cutover_tags",
                            "wrapper_scheduled_skips", "wrapper_offschedule_skips", "live_run_done",
                            "live_useful_or_empty", "refusals"]))
    L.append(f"\n**Consolidated on host (stage runner, still cron)** ({len(m['consolidated'])}) — listed in lanes.csv.\n")
    L.append("\n### Retained exceptions\n")
    rc = Counter(r["class"] for r in p["retained"])
    L.append(f"F07 lanes: {rc.get('F07', 0)}; registry_systemd ACTIVE lanes: {rc.get('registry_systemd', 0)}; holds: "
             f"{rc.get('hold', 0)} (full list in retained.csv).\n")
    L.append(md_table([r for r in p["retained"] if r["class"] == "hold"], ["lane_id", "reason", "owner"]))
    L.append("\nIndependent P1 / dead-man backstops (must stay independent of n8n):\n")
    L.append(md_table(p["backstops"], ["lane_id", "owner", "purpose", "registry_state", "scheduler", "status", "relay_live"]))

    L.append("\n## 3. Business processes fully owned by n8n\n")
    full = [f for f in p["families"] if f["fully_n8n_owned"]]
    L.append(f"WS2 families fully n8n-owned: **{len(full)} of {len(p['families'])}** "
             f"({', '.join(f['family_id'] for f in full) or 'none'}). Families with some n8n but not all "
             f"(top 15 by lanes):\n")
    part = sorted([f for f in p["families"] if f["has_any_n8n"] and not f["fully_n8n_owned"]], key=lambda f: -f["lanes"])[:15]
    L.append(md_table([{**f, "cron_or_parallel": len(f["cron_or_parallel_lanes"])} for f in part],
                      ["family_id", "lanes", "status_counts", "cron_or_parallel"]))
    L.append("\nFabric processes:\n")
    L.append(md_table(p["fabric_processes"], ["process", "workflow_id", "mode", "fully_n8n_owned", "why_not"]))

    L.append("\n## 4. Run outcomes (window)\n")
    L.append(md_table([
        {"measure": k, "n": rs[k]} for k in (
            "receipts_in_window", "lanes_with_receipts", "lanes_with_live_receipts", "live_runs", "dry_runs",
            "useful_live_output", "verified_empty", "unverified_ok", "failures", "lock_skips", "refusals",
            "ambiguous_effects", "live_worker_s", "dry_worker_s")
    ], ["measure", "n"]))
    L.append(f"\nRefusals by reason: {rs['refusals_by_reason']}\n\nEffect claims by state: {rs['effect_claims_by_state']}\n")
    L.append(f"\nLedger cross-check (runs table, same window): {rs['ledger_runs_by_state_mode']}\n")
    live_rows = sorted([r for r in p["lanes"].values() if r["live_runs"]], key=lambda r: -r["live_runs"])
    L.append("\nPer lane with live runs:\n")
    L.append(md_table(live_rows, ["lane_id", "status", "live_runs", "useful_live_output", "verified_empty",
                                  "unverified_ok", "failures", "lock_skips", "refusals", "ambiguous_effects",
                                  "live_worker_s", "dry_runs"]))

    L.append("\n## 5. Incidents (window)\n")
    L.append(md_table([
        {"measure": "distinct episodes (lane × failure class)", "n": inc["episodes"]},
        {"measure": "events", "n": inc["events"]},
        {"measure": "duplicate events", "n": inc["duplicate_events"]},
        {"measure": "episodes by recovery verdict", "n": inc["by_recovery"]},
        {"measure": "episodes by class", "n": inc["by_class"]},
        {"measure": "remediation rows (REQUESTED / shadow — NOT heals)", "n": inc["remediation_rows_requested_not_heals"]},
        {"measure": "diagnoses by outcome", "n": inc["diagnoses_in_window_by_outcome"]},
        {"measure": "failure-diagnosis state", "n": inc["failure_diagnosis_state"]},
        {"measure": "unreleased dead letters in window", "n": len(inc["dead_letters_unreleased_in_window"])},
    ], ["measure", "n"]))
    rec = [e for e in p["episodes"] if e["recovery"] == "VERIFIED_RECOVERED"]
    L.append(f"\nVerified recoveries ({len(rec)}):\n")
    L.append(md_table(rec, ["lane_id", "failure_class", "events", "last_at", "recovery_evidence"]))
    L.append("\nUnresolved episodes are listed in episodes.csv.\n")

    L.append("\n## 6. Notifications (today, ET)\n")
    L.append(md_table([
        {"stage": "n8n comms intents (coordination ledger)", "counts": n["n8n_comms_intents_by_tier_state"]},
        {"stage": "router decisions (notification_intent_receipts)", "counts": n["router_decisions"]},
        {"stage": "communication_events OUTBOUND", "counts": n["communication_events_outbound"]},
        {"stage": "scheduler × delivery status", "counts": n["by_scheduler_and_delivery"]},
        {"stage": "attribution", "counts": {"attributed": n["attribution"]["attributed"], "UNKNOWN": n["attribution"]["unknown"]}},
        {"stage": "telegram idempotency keys today (by prefix)", "counts": n["telegram_send_idempotency_today_by_prefix"]},
        {"stage": "telegram daily send budget today", "counts": n["telegram_daily_send_budget_today"]},
    ], ["stage", "counts"]))
    L.append(f"\nAttribution by source: {n['attribution']['by_source']}\n\n{n['join_note']}\n")

    L.append("\n## 7. Effect protection (qualified by ledger health and wrapper policy)\n")
    L.append(md_table([{"protection_mode": k, "keyed lanes": v} for k, v in es["by_protection_mode"].items()],
                      ["protection_mode", "keyed lanes"]))
    L.append(f"\n**Protected fail-closed** ({len(es['protected_fail_closed'])}): "
             f"{', '.join(es['protected_fail_closed']) or '—'}\n")
    L.append(f"\n**Protected only while the ledger is healthy** ({len(es['protected_only_while_ledger_healthy'])}): "
             f"{', '.join(es['protected_only_while_ledger_healthy']) or '—'}\n")
    L.append(f"\nManifest vs ledger owner: {es['manifest_ledger']}. Disagreements (reported, never reconciled): "
             f"{', '.join(es['manifest_ledger_disagree']) or 'none'}.\n")
    L.append(f"\nCron copy stood down (skipped_effect / skipped_ownership_unknown in window): "
             f"{len(es['lanes_stood_down'])} lanes: {', '.join(es['lanes_stood_down']) or '—'}\n")
    L.append(f"\nWrapper RAN the command (owner not n8n, or ledger unreachable): "
             f"{len(es['lanes_wrapper_ran_command'])} lanes: {', '.join(es['lanes_wrapper_ran_command']) or '—'}\n")
    lv = Counter(r["protection"].split(" ")[0] for r in p["effect_protection"])
    L.append(f"\nClaim-level view (unchanged since #1827): {dict(lv)}. SINGLE_OWNER_CLAIMING = owner n8n, the "
             "executor claimed DONE keys in the window, every active cron line wrapped; \"cannot run twice\" holds "
             "only for runs through the n8n executor or the wrapper (a manual run outside both is not fenced). "
             "late_write_fenced is false for every key (no lane calls assert_fence yet).\n")
    L.append(md_table([r for r in p["effect_protection"] if r["owner"] or r["n8n_claim"] or r["manifest_owner"]],
                      ["lane_id", "owner", "manifest_owner", "manifest_ledger", "active_cron_lines",
                       "active_cron_lines_cron_wrapped", "skipped_effect", "skipped_ownership_unknown", "wrapper_ran",
                       "claims_done", "claims_ambiguous", "protection_mode", "protection_mode_why"]))

    L.append("\n### Event-driven chain (config/lane_registry.json dispatch.triggers)\n")
    ch = p["event_chain"]
    L.append(f"{len(ch)} declared triggers on {len({r['lane_id'] for r in ch})} lanes; by state "
             f"{dict(Counter(r['trigger_state'] for r in ch))}; with a clock fallback still firing: "
             f"{sum(1 for r in ch if r['has_clock_fallback'])}. Whether the tradeai-event-router workflow is active in "
             "n8n is not read here (no n8n API call); the e: receipts are the evidence that a trigger fired. The five "
             "registry scheduler.kind=event rows (openclaw reminders, cio-situation-detector) are emitted outside n8n "
             "and are not part of this chain.\n")
    L.append(md_table(ch, ["lane_id", "trigger_source", "upstream", "dispatch_mode", "trigger_state",
                           "e_live_receipts", "e_dry_receipts", "last_e_receipt_at", "upstream_live_useful",
                           "clock_fallback"]))

    L.append("\n## 8. Next cohorts and burn-down\n")
    L.append(md_table([{"cohort": k, "lanes": v, "owner": bd["owners"].get(k, "")} for k, v in bd["cohort_sizes"].items()],
                      ["cohort", "lanes", "owner"]))
    L.append(f"\nRemaining (excl. holds): **{bd['remaining_lanes_excluding_holds']}** lanes. Observed tagged migrations "
             f"by date: {bd['observed_migrations_by_date']}. Rate {bd['rate_lanes_per_trading_day']} lanes/trading day "
             f"→ projected completion **{bd['projected_completion'] or 'not projectable (rate 0)'}**.\n\nAssumptions:\n")
    for a in bd["assumptions"]:
        L.append(f"- {a}")
    L.append("\nOpen PRs carrying blockers: see section 9 (state OPEN).\n")

    L.append(f"\n## 9. PRs #{PR_RANGE[0]}–#{PR_RANGE[-1]}: merged / deployed / proven\n")
    L.append(md_table(p["prs"], ["pr", "state", "merged", "deployed", "proven", "evidence", "title"]))

    cmp_ = p.get("comparison")
    if cmp_:
        L.append(f"\n## 10. Changes since {cmp_.get('prev_dir')}\n")
        if cmp_.get("error"):
            L.append(f"Comparison unavailable: {cmp_['error']}\n")
        else:
            L.append(f"Previous packet {cmp_['prev_generated_at']} (served {cmp_['prev_served']}) -> this packet "
                     f"(served {cmp_['cur_served']}); crontab changed: {cmp_['crontab_changed']}. The definition of "
                     "MIGRATED_PROVEN changed between the two (now S+E+U; then tag + any live RUN_DONE), and wrapped "
                     "cron lines that stood down no longer count as PARALLEL.\n")
            L.append(md_table([{"status": k, "prev": v["prev"], "now": v["now"], "delta": v["now"] - v["prev"]}
                               for k, v in cmp_["status"].items()], ["status", "prev", "now", "delta"]))
            L.append("\n" + md_table([{"measure": k, **v} for k, v in {**cmp_["migration"], **cmp_["run_summary"]}.items()],
                                     ["measure", "prev", "now"]))
            L.append(f"\nProven kept ({len(cmp_['proven_kept'])}): {', '.join(cmp_['proven_kept']) or '—'}\n")
            L.append(f"\nProven added ({len(cmp_['proven_added'])}): {', '.join(cmp_['proven_added']) or '—'}\n")
            L.append(f"\nProven dropped ({len(cmp_['proven_dropped'])}):\n")
            L.append(md_table(cmp_["proven_dropped"], ["lane_id", "status", "why_now"]))
            L.append(f"\nAll status moves ({len(cmp_['status_moves'])}):\n")
            L.append(md_table(cmp_["status_moves"], ["lane_id", "prev_status", "status", "why_now"]))

    L.append("\n## Not measured / caveats\n")
    for u in p["unmeasured"] or ["(none)"]:
        L.append(f"- {u}")
    L.append("- Lane attribution of a crontab line is a substring match against registry rows; a line no row matches "
             "is counted UNMAPPED, never guessed.")
    L.append("- Receipts carry no output verdict until a lane emits produced_count and opts in (output_receipt v2); "
             "those live runs are `unverified_ok`, not useful output.")
    L.append("\nFiles: summary.json, lanes.csv, families.csv, retained.csv, episodes.csv, effect_protection.csv, "
             "event_chain.csv, prs.csv, notifications.json, burn_down.json.\n")
    return "\n".join(L) + "\n"


def write_packet(p: Mapping[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "REPORT.md").write_text(render(p))
    summary = {k: v for k, v in p.items()
               if k not in ("lanes", "episodes", "effect_protection", "families", "retained", "event_chain")}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True, default=str) + "\n")
    lane_cols = ["lane_id", "status", "registry_state", "scheduler_kind", "family_id", "disposition", "relay_live",
                 "on_p1_last", "active_cron_lines", "active_cron_line_nos", "n8n_cutover_tags", "consolidation_tags",
                 "active_cron_lines_wrapped", "cron_copy_standing_down", "wrapper_skip_events", "wrapper_last_event",
                 "wrapper_scheduled_skips", "wrapper_offschedule_skips",
                 "measure_combo", "sched_n8n", "sched_evidence", "executed", "useful", "live_useful_or_empty",
                 *OUTCOME_KEYS, "refusals", "refusal_reasons", "ambiguous_effects", "unproven_reason"]
    write_csv(out / "lanes.csv", list(p["lanes"].values()), lane_cols)
    write_csv(out / "families.csv", list(p["families"]))
    write_csv(out / "retained.csv", list(p["retained"]) + [{**b, "class": "backstop"} for b in p["backstops"]],
              ["lane_id", "class", "reason", "owner", "purpose", "registry_state", "scheduler", "status"])
    write_csv(out / "episodes.csv", list(p["episodes"]))
    write_csv(out / "effect_protection.csv", list(p["effect_protection"]))
    write_csv(out / "event_chain.csv", list(p["event_chain"]))
    write_csv(out / "prs.csv", list(p["prs"]))
    (out / "notifications.json").write_text(json.dumps(p["notifications"], indent=1, sort_keys=True, default=str) + "\n")
    (out / "burn_down.json").write_text(json.dumps(p["burn_down"], indent=1, sort_keys=True, default=str) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--since", default=DEFAULT_SINCE, help="window start, ISO-8601 (default: directive day ET midnight)")
    ap.add_argument("--out", default="", help="output dir (default docs/ops/measurements/n8n-cutover-<UTC ts>)")
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT") or str(DEFAULT_STATE_ROOT))
    ap.add_argument("--current", default=str(DEFAULT_CURRENT))
    ap.add_argument("--live-lanes-env", default=str(DEFAULT_LIVE_LANES_ENV))
    ap.add_argument("--effect-events", default="", help="wrapper event log (default <state>/logs/effect_claim_events.jsonl)")
    ap.add_argument("--handover-manifest", default="",
                    help="handover manifest (default $TRADEAI_N8N_HANDOVER_MANIFEST or "
                         "<state>/data/governance/n8n_handover_manifest.json)")
    ap.add_argument("--compare", default="", help="an earlier packet dir to diff against (summary.json + lanes.csv)")
    ap.add_argument("--context", action="append", default=[],
                    help="operator-supplied context line printed in the header (repeatable), e.g. the wrapper install time")
    a = ap.parse_args(argv)
    p = build(a)
    out = Path(a.out) if a.out else ROOT / "docs" / "ops" / "measurements" / (
        "n8n-cutover-" + p["generated_at"].replace("-", "").replace(":", "").replace("+0000", "Z"))
    write_packet(p, out)
    print(json.dumps({"out": str(out), "unmeasured": p["unmeasured"],
                      "status": p["migration"]["unique_lanes_by_status"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
