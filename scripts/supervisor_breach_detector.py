#!/usr/bin/env python3
"""supervisor_breach_detector.py — Breach@v1 detection over heartbeats, SLA rows and output signals (06 §5).

Wave 1 tranche 2 body: DETECT and RECORD. It walks every ACTIVE lane in config/lane_registry.json,
reads its SLA row (data/runtime/supervisor_sla_seed.json, or intelligence.sla when present), its
heartbeat (file fallback via supervisor_heartbeat.read_all, or intelligence.heartbeat), and its
registered output signal (lane_registry.observe_signal), and raises:

  UNGOVERNED         no SLA row
  SILENT             last beat older than max_silence_s (only when the lane has ever beaten)
  NO_OUTPUT          output signal older than 3 × cadence (or unreadable) for an ACTIVE lane
  MEMORY_UNREACHABLE last beat says memory_context_ok = false on a fail-closed lane
  STALE_OUTPUT       (W1-9, 2026-10-11) a registry ``freshness_contracts`` entry — a store table/file the
                     freshness monitors and job_coverage_monitor watch — is older than its max_age_hours
  INPUT_STARVATION   (W1-9) a pipeline_liveness lane is STARVED / NO_ELIGIBLE_INPUT / UNKNOWN
                     (the checks of pipeline_liveness_report.py)

STALE_OUTPUT and INPUT_STARVATION are RECORD_ONLY_KINDS: recorded on the ledger, never handed to L1–L5 (not
even as shadow receipts) or L3. Both are "slow checks", evaluated at most every 30 min (--slow-checks).

It writes an append-only data/runtime/supervisor_breaches.jsonl (one row per NEW breach id; a breach
id is stable per lane × kind × day, so a repeat is a re-observation, not a new row) and
data/runtime/supervisor_breach_detector_latest.json (the lane's own output signal). Ladder actions
L1–L5 are NOT executed here: L1 restarts need the sudoers allowlist review (11 S-6) and land in
Wave 2; escalation to the health agent (L3) is available with --enqueue-escalations and is off by default.

Dry-run by default (prints, writes nothing); --write records. ``--dry-run`` (n8n refactor 2026-10-10) is
the explicit spelling of the default and WINS over --write/--heal/--ladder/--enqueue-escalations: the
write block is not reachable from it (AGENTS.md §6).

Exit (2026-10-10): 0 when the run completed — breaches are FINDINGS, not a failed run. 1 when a --write
step failed (L3 enqueue, L1/L2 self-heal, L4/L5 ladder used to be printed to stderr and exit 0). The
lane receipt ``supervisor_breach_detector_latest.json`` is now written LAST and carries ``ok_at`` (advanced
only when every step succeeded) and ``steps_failed``.
Approval: pkg-20260927-cogx-w1-d9e1 item 2. Authority: READ_ONLY_ADVISORY. Never touches a broker.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

PROJ = Path(__file__).resolve().parents[1]
NO_CONSUMER_REASON = (
    "Breach@v1 rows are read by report_platform_conformance (monitoring standard) and by the Command "
    "Center supervisor panel (Wave 2); lane supervisor-breach-detector is declared NEVER_SCHEDULED "
    "until the pkg-20260927-cogx-w1-d9e1 service grant installs its timer"
)
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

SCHEMA = "Breach@v1"
KINDS = (
    "SILENT",
    "HUNG",
    "BACKLOG",
    "FAILING",
    "NO_OUTPUT",
    "MEMORY_UNREACHABLE",
    "SLO_MISS",
    "UNGOVERNED",
    "STALE_OUTPUT",
    "INPUT_STARVATION",
)
#: W1-9 monitor fold (2026-10-11): kinds that are DETECT + RECORD only. They never reach the L1/L2 self-heal or
#: the L4/L5 ladder (not even its shadow receipts); the fan-in reads them from the ledger like any other row.
RECORD_ONLY_KINDS = ("STALE_OUTPUT", "INPUT_STARVATION")
#: The slow checks (freshness contracts run ~30 SELECT max() queries; input starvation folds ~210 MB of CIO
#: JSONL) are evaluated at most once per this many seconds — today's monitors run every 30-40 min — not on
#: every 2-minute tick. The last evaluation time is kept in SLOW_CHECKS_STATE (written only under --write).
SLOW_CHECK_EVERY_S = {"freshness_contracts": 1800, "input_starvation": 1800}
SLOW_CHECKS_STATE = "supervisor_slow_checks_last.json"
SCHEDULE_TZ = ZoneInfo("America/New_York")
#: cron_schedule.last_fire_at_or_before lookback; parity with cron_last_fire.last_fire(max_days=400) for monthly lanes.
CRON_LOOKBACK_DAYS = 400


def _parse(ts):
    if not ts:
        return None
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def breach_id(lane_id: str, kind: str, day: str) -> str:
    return "br_" + hashlib.sha256(f"{lane_id}|{kind}|{day}".encode()).hexdigest()[:16]


def _parse_any(ts):
    return _parse(ts)


def _cron_fields(expr: str) -> str | None:
    """The schedule part of a registry cron ``expression`` (first 5 fields; ``@`` aliases and names mapped).

    Delegates to the shared extractor ``cron_schedule.cron_fields`` so the detector, ``cron_last_fire``, the
    job coverage monitor, scheduler operations and source clocks read a schedule the same way (#1616 moved
    here, 2026-10-09 breach triage). ``@reboot`` returns ``"@reboot"``; anything unreadable returns None.
    """
    from cron_schedule import cron_fields  # type: ignore

    return cron_fields(expr)


def _last_cron_fire(fields: str, ref: _dt.datetime) -> tuple[_dt.datetime, str] | None:
    """(most recent fire <= ref in UTC, basis) for one 5-field schedule, or None (no fire in the lookback)."""
    try:
        # 2026-10-09 (n8n maturity B5 follow-up): the DST-safe API. A spring-forward gap fire lands on the
        # first valid minute and a fall-back fold fires once (fold 0), so neither transition hour moves the
        # deadline past a run that really happened. None (no fire inside the lookback) = unknown -> cadence rule.
        from cron_schedule import last_fire_at_or_before  # type: ignore

        fire = last_fire_at_or_before(fields, ref, str(SCHEDULE_TZ), lookback_days=CRON_LOOKBACK_DAYS)
        return (fire.at.astimezone(_dt.timezone.utc), f"cron:{fields}") if fire is not None else None
    except Exception:  # noqa: BLE001 — a field cron_schedule rejects (e.g. out of range): the legacy parser
        pass
    try:
        import cron_last_fire  # type: ignore

        local_ref = ref.astimezone(SCHEDULE_TZ)
        lf = cron_last_fire.last_fire(fields, local_ref.replace(tzinfo=None))
        if lf is not None:
            return lf.replace(tzinfo=local_ref.tzinfo).astimezone(_dt.timezone.utc), f"cron_legacy:{fields}"
    except Exception:  # noqa: BLE001 — fall back to the cadence rule
        pass
    return None


def _expected_since(lane: dict, now: _dt.datetime, max_run_s: float = 900.0) -> tuple[_dt.datetime | None, str]:
    """When should this lane have produced by? Returns (deadline, basis).

    cron lanes: the most recent scheduled fire ≤ now (each `` + ``-joined schedule's first 5 fields, see
    cron_schedule.cron_fields; the latest over all of them), so a weekday-only or market-hours lane is not
    judged over a weekend (2026-09-27 triage: 6 false breaches).
    Other lanes, ``@reboot`` lanes and cron lanes with no fire inside the lookback: 3 × cadence (min 15 min);
    inactive days are not due days.
    """
    sched = lane.get("scheduler") or {}
    expr = str(sched.get("expression") or "")
    # registry-ops-crons 2026-10-09: `due_schedules` (a subset of the crontab schedule) names the fires whose
    # output is due, e.g. premarket_watch.py writes no heartbeat after 09:29 while its line fires to 09:55.
    due = sched.get("due_schedules")
    if isinstance(due, list) and due and all(isinstance(x, str) and x.strip() for x in due):
        expr = " + ".join(x.strip() for x in due)
    cad_h = lane.get("expected_cadence_hours")
    if sched.get("kind") == "cron":
        # the most recent fire that has had max_run to finish: a run still in progress is not a miss
        ref = now - _dt.timedelta(seconds=max_run_s)
        # A lane run by several crontab lines stores them joined by " + "; the deadline is the latest fire
        # over all of them (cron_schedule.cron_schedules), not just the first line's.
        from cron_schedule import cron_schedules  # type: ignore

        fires = [
            f for f in (_last_cron_fire(fields, ref) for fields in cron_schedules(expr) if fields != "@reboot") if f
        ]
        if fires:
            return max(fires, key=lambda f: f[0])
    if not cad_h:
        return None, "no_cadence"
    limit_s = max(3 * float(cad_h) * 3600, 900)
    days = lane.get("active_days")
    if isinstance(days, (list, tuple)) and days:
        # These lane schedules are in Eastern market time. Extending a 45 min
        # cadence by two days still flags Friday's last output on Sunday night;
        # no output is due on an inactive day, regardless of the clock hour.
        if now.astimezone(SCHEDULE_TZ).weekday() not in days:
            return None, "inactive_day:America/New_York"
    return now - _dt.timedelta(seconds=limit_s), f"cadence:{cad_h}h×3"


def detect(
    *, lanes: list[dict], sla_by_lane: dict[str, dict], heartbeats: dict[str, dict], observe, now: _dt.datetime
) -> list[dict]:
    """Pure: returns Breach@v1 rows. ``observe(sig)`` returns {last_output_at, readable}."""
    day = now.strftime("%Y-%m-%d")
    out: list[dict] = []

    def add(lane, kind, evidence, level=1):
        out.append(
            {
                "schema": SCHEMA,
                "breach_id": breach_id(lane["lane_id"], kind, day),
                "lane_id": lane["lane_id"],
                "silo_id": None,
                "kind": kind,
                "detected_at": now.isoformat(),
                "evidence": evidence,
                "level": level,
                "state": "OPEN",
                "recovery": [],
                "authority": "READ_ONLY_ADVISORY",
            }
        )

    for lane in lanes:
        if lane.get("state") != "ACTIVE":
            continue
        lid = lane.get("lane_id")
        fd = _parse(lane.get("first_due"))
        if fd and now < fd:
            continue  # declared not-yet-due (e.g. a monthly report installed mid-month)
        sla = sla_by_lane.get(lid)
        if not sla:
            add(
                lane,
                "UNGOVERNED",
                {
                    "note": "no SLA row",
                    "cmd": "python3 scripts/seed_supervisor_sla.py --json-out data/runtime/supervisor_sla_seed.json",
                },
            )
            continue
        hb = heartbeats.get(lid)
        if hb and sla.get("max_silence_s"):
            lb = _parse(hb.get("last_beat"))
            if lb and (now - lb).total_seconds() > float(sla["max_silence_s"]):
                add(
                    lane,
                    "SILENT",
                    {
                        "last_beat": hb.get("last_beat"),
                        "max_silence_s": sla["max_silence_s"],
                        "boot_id": hb.get("boot_id"),
                    },
                )
            if hb.get("memory_context_ok") is False and sla.get("memory_context_required") == "fail-closed":
                add(
                    lane,
                    "MEMORY_UNREACHABLE",
                    {"degraded_reasons": hb.get("degraded_reasons"), "last_beat": hb.get("last_beat")},
                    level=2,
                )
        sig = lane.get("output_signal") or {}
        if sig.get("kind") in (None, "none"):
            continue
        max_run = float(sla.get("max_run_s") or 900)
        deadline, basis = _expected_since(lane, now, max_run)
        if deadline is None:
            continue
        obs = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (observe(sig) or {}).items()}
        lo = _parse(obs.get("last_output_at"))
        if obs.get("readable") is False:
            add(
                lane,
                "NO_OUTPUT",
                {
                    "signal": sig,
                    "observed": obs,
                    "basis": basis,
                    "note": "signal unreadable (UNVERIFIABLE, reported as NO_OUTPUT)",
                },
            )
        elif lo is None:
            add(lane, "NO_OUTPUT", {"signal": sig, "observed": obs, "basis": basis, "note": "never produced"})
        elif lo < deadline:
            add(
                lane,
                "NO_OUTPUT",
                {
                    "signal": sig,
                    "last_output_at": obs.get("last_output_at"),
                    "expected_by": deadline.isoformat(),
                    "basis": basis,
                },
            )
    return out


# ── W1-9 monitor fold (2026-10-11): store freshness and input starvation ─────────────────────────────────


def _is_trading_day(day: _dt.date) -> bool:
    """market_session's calendar (weekends + NYSE holidays); weekday-only when it cannot be imported."""
    try:
        from market_session import is_trading_day  # type: ignore

        return bool(is_trading_day(_dt.datetime(day.year, day.month, day.day, 12, 0, tzinfo=SCHEDULE_TZ)))
    except Exception:  # noqa: BLE001
        return day.weekday() < 5


def _trading_day_limit_h(max_age_h: float, now: _dt.datetime, *, cap_days: int = 14) -> float:
    """max_age_h extended by 24 h for every non-trading day the window reaches into (America/New_York days).

    The window grows until it stops reaching a new non-trading day: Monday 06:00 with 26 h reaches Sunday, then
    Saturday, then stops at Friday (74 h). That is at least as lenient as pipeline_freshness_monitor's
    "consecutive closed days ending today" grace and system_freshness_monitor's weekday_only skip, so the fold
    can only report later than today's monitors, never earlier.
    """
    limit = float(max_age_h)
    local_now = now.astimezone(SCHEDULE_TZ)
    counted: set[_dt.date] = set()
    for _ in range(cap_days + 1):
        start = (local_now - _dt.timedelta(hours=limit)).date()
        d, extra = local_now.date(), 0
        while d >= start:
            if d not in counted and not _is_trading_day(d):
                counted.add(d)
                extra += 1
            d -= _dt.timedelta(days=1)
        if not extra or len(counted) >= cap_days:
            break
        limit += 24.0 * extra
    return limit


def _freshness_deadline(
    contract: dict, lane: dict | None, sla: dict | None, now: _dt.datetime
) -> tuple[_dt.datetime, str]:
    """(oldest acceptable output time, basis label) for one freshness contract."""
    max_age = float(contract["max_age_hours"])
    basis = contract.get("basis")
    if basis == "trading_days":
        lim = _trading_day_limit_h(max_age, now)
        return now - _dt.timedelta(hours=lim), f"trading_days:{max_age:g}h→{lim:g}h"
    if basis == "lane_due" and lane is not None and (lane.get("scheduler") or {}).get("kind") == "cron":
        # job_coverage_monitor: allowed = max(cadence, idle + min(cadence, 1 h)) where idle = hours since the
        # last due fire, i.e. the output must postdate min(now - cadence, last fire - min(cadence, 1 h)).
        fire, fbasis = _expected_since(lane, now, float((sla or {}).get("max_run_s") or 900))
        if fire is not None and fbasis.startswith("cron"):
            by_fire = fire - _dt.timedelta(hours=min(max_age, 1.0))
            return min(now - _dt.timedelta(hours=max_age), by_fire), f"lane_due:{fbasis}|{max_age:g}h"
    return now - _dt.timedelta(hours=max_age), f"wall_clock:{max_age:g}h"


def detect_freshness(
    *, contracts: list[dict], lanes: list[dict], sla_by_lane: dict[str, dict], observe, now: _dt.datetime
) -> list[dict]:
    """Pure: STALE_OUTPUT Breach@v1 rows from the registry's freshness_contracts.

    A contract tied to a lane is only judged while that lane is ACTIVE (a retired producer stops raising).
    An unreadable signal is reported (UNVERIFIABLE, as for NO_OUTPUT); an absent row/file is "never produced".
    Detect + record only: the rows carry the contract's severity and never enter the ladder.
    """
    day = now.strftime("%Y-%m-%d")
    by_id = {l.get("lane_id"): l for l in lanes}
    out: list[dict] = []
    for c in contracts or []:
        lid = c.get("lane_id")
        lane = by_id.get(lid) if lid else None
        if lid and (lane is None or lane.get("state") != "ACTIVE"):
            continue
        fd = _parse((lane or {}).get("first_due"))
        if fd and now < fd:
            continue
        deadline, basis = _freshness_deadline(c, lane, sla_by_lane.get(lid) if lid else None, now)
        obs = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (observe(c["signal"]) or {}).items()}
        lo = _parse(obs.get("last_output_at"))
        if obs.get("readable") is False:
            note = "signal unreadable (UNVERIFIABLE, reported as STALE_OUTPUT)"
        elif lo is None:
            note = "never produced"
        elif lo < deadline:
            note = "stale"
        else:
            continue
        owner = str(lid or f"freshness:{c['key']}")
        out.append(
            {
                "schema": SCHEMA,
                "breach_id": breach_id(owner, f"STALE_OUTPUT:{c['key']}", day),
                "lane_id": owner,
                "silo_id": None,
                "kind": "STALE_OUTPUT",
                "detected_at": now.isoformat(),
                "evidence": {
                    "contract": c["key"],
                    "signal": c["signal"],
                    "observed": obs,
                    "expected_by": deadline.isoformat(),
                    "basis": basis,
                    "severity": c.get("severity"),
                    "source": c.get("source"),
                    "replaces": c.get("replaces"),
                    "note": note,
                },
                "level": 1,
                "state": "OPEN",
                "recovery": [],
                "authority": "READ_ONLY_ADVISORY",
            }
        )
    return out


#: PipelineLiveness@v1 statuses that are findings (scripts/lib/pipeline_liveness.py LivenessReport.findings).
STARVATION_STATUSES = ("STARVED", "NO_ELIGIBLE_INPUT", "UNKNOWN")


def detect_input_starvation(*, liveness: dict, now: _dt.datetime) -> list[dict]:
    """Pure: INPUT_STARVATION Breach@v1 rows from a PipelineLiveness@v1 document (pipeline_liveness_report's checks).

    STARVED = work entered the lane and nothing came out; NO_ELIGIBLE_INPUT = work arrived but none of it could
    produce this output; UNKNOWN = the source could not be read (not evidence of a live lane). One row per
    liveness lane × status × day. Detect + record only.
    """
    day = now.strftime("%Y-%m-%d")
    out: list[dict] = []
    for ln in (liveness or {}).get("lanes") or []:
        status = str(ln.get("status") or "")
        if status not in STARVATION_STATUSES:
            continue
        owner = f"liveness:{ln.get('lane')}"
        ev = {
            k: ln.get(k)
            for k in (
                "status",
                "produced",
                "attempted",
                "eligible",
                "min_expected",
                "window_hours",
                "source",
                "describe",
                "detail",
            )
            if ln.get(k) is not None
        }
        ev["origin"] = "scripts/lib/pipeline_liveness.py (pipeline-liveness-report)"
        out.append(
            {
                "schema": SCHEMA,
                "breach_id": breach_id(owner, f"INPUT_STARVATION:{status}", day),
                "lane_id": owner,
                "silo_id": None,
                "kind": "INPUT_STARVATION",
                "detected_at": now.isoformat(),
                "evidence": ev,
                "level": 2 if status == "STARVED" else 1,
                "state": "OPEN",
                "recovery": [],
                "authority": "READ_ONLY_ADVISORY",
            }
        )
    return out


def _evaluate_liveness(state_root: Path | None) -> dict:
    """Run pipeline_liveness's default probes (read-only) against ``state_root`` (default: production state root)."""
    if str(PROJ) not in sys.path:
        sys.path.insert(0, str(PROJ))
    from scripts.lib import pipeline_liveness as pl  # type: ignore

    orig = pl._state_root
    try:
        if state_root is not None:
            pl._state_root = lambda: Path(state_root)
        return pl.evaluate(pl.default_lanes()).to_dict()
    finally:
        pl._state_root = orig


def _slow_checks_due(runtime_dir: Path, now: _dt.datetime, mode: str) -> tuple[dict[str, bool], dict]:
    """Which slow checks run this tick: mode always/never, or auto = last evaluation older than its interval."""
    try:
        state = json.loads((runtime_dir / SLOW_CHECKS_STATE).read_text(encoding="utf-8"))
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        state = {}
    due: dict[str, bool] = {}
    for name, every in SLOW_CHECK_EVERY_S.items():
        if mode in ("always", "never"):
            due[name] = mode == "always"
            continue
        last = _parse(state.get(name))
        due[name] = last is None or (now - last).total_seconds() >= every
    return due, state


def _read_only_db_query():
    """A `db_query(sql) -> rows` for db_max signals, read-only, fail-soft (None when no DSN).
    2026-09-27 triage: without it every db_max lane read as NO_OUTPUT ("no db_query supplied")."""
    try:
        import db_adapter  # type: ignore

        conn = db_adapter._get_conn()
    except Exception:  # noqa: BLE001
        return None

    def q(sql: str):
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN READ ONLY")
                cur.execute(sql)
                rows = cur.fetchall()
            conn.rollback()
            return rows
        except Exception:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None

    return q


L1_MAX_PER_WINDOW = 2  # 06 §5 L1: 2 attempts per 10 min per lane
L1_WINDOW_S = 600
L1_KINDS = ("SILENT", "NO_OUTPUT", "HUNG")


def _recovery_budget(path: Path, now) -> dict[str, int]:
    """Compatibility wrapper over the shared owner; existing Recovery@v1 history is unchanged."""
    from lib import recovery_attempt_budget as budget

    return budget.counts(path, now, limit=L1_MAX_PER_WINDOW, window_s=L1_WINDOW_S, namespace=budget.SUPERVISOR)


def _recovery_row(path: Path, row: dict) -> None:
    from lib import recovery_attempt_budget as budget

    budget.append(path, row)


def _reserve_recovery(path: Path, row: dict, now, *, live: bool) -> tuple[bool, str]:
    from lib import recovery_attempt_budget as budget

    return budget.reserve(
        path, row, now, limit=L1_MAX_PER_WINDOW, window_s=L1_WINDOW_S, namespace=budget.SUPERVISOR, live=live
    )


def _self_heal_l1_l2(
    rows: list[dict], lanes: list[dict], sla_by_lane: dict, now, runtime_dir: Path, *, live: bool
) -> dict:
    """L1: `systemctl --user restart <unit>` for a systemd-scheduled lane in breach (class A: its unit is the lane
    registry's own scheduler expression; system units and cron lanes are never touched — S-W4-1 sudoers is for
    those). L2: `systemctl --user start <alternate>` when the SLA row declares one. Every decision is a
    Recovery@v1 row (data/runtime/supervisor_recoveries.jsonl); shadow rows carry executed=false."""
    import subprocess
    from lib import recovery_attempt_budget as budget

    by_id = {l.get("lane_id"): l for l in lanes}
    rec_p = runtime_dir / "supervisor_recoveries.jsonl"
    out = {
        "l1_candidates": 0,
        "l1_executed": 0,
        "l2_candidates": 0,
        "l2_executed": 0,
        "mode": "live" if live else "shadow",
    }
    rec_p.parent.mkdir(parents=True, exist_ok=True)
    for r in rows:
        lane = by_id.get(r.get("lane_id")) or {}
        sched = lane.get("scheduler") or {}
        unit = str(sched.get("expression") or "") if sched.get("kind") == "systemd" else ""
        alt = (sla_by_lane.get(r.get("lane_id")) or {}).get("alternate")
        if r.get("kind") not in L1_KINDS:
            continue
        row = {
            "schema": "Recovery@v1",
            "ts": now.isoformat(),
            "breach_id": r.get("breach_id"),
            "lane_id": r.get("lane_id"),
            "kind": r.get("kind"),
            "mode": out["mode"],
            "executed": False,
            "attempted": False,
            "business_recovered": False,
        }
        if unit and unit.endswith((".timer", ".service")) and lane.get("state") == "ACTIVE":
            out["l1_candidates"] += 1
            svc = unit[: -len(".timer")] + ".service" if unit.endswith(".timer") else unit
            row.update({"level": 1, "action": f"systemctl --user restart {svc}"})
            argv, counter = ["systemctl", "--user", "restart", svc], "l1_executed"
        elif alt:
            out["l2_candidates"] += 1
            row.update({"level": 2, "action": f"systemctl --user start {alt}"})
            argv, counter = ["systemctl", "--user", "start", str(alt)], "l2_executed"
        else:
            continue
        allowed, status = _reserve_recovery(rec_p, row, now, live=live)
        if status != "known":
            out["budget_status"] = "unavailable"
            break
        if not live or not allowed:
            continue
        row.update(attempted=True, attempt_reserved=True)
        try:
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            row.update(
                executed=True, rc=cp.returncode, action_succeeded=cp.returncode == 0, stderr=(cp.stderr or "")[:200]
            )
            out[counter] += 1
        except Exception as exc:  # noqa: BLE001 - still an attempted, budgeted action; never recovery evidence
            row.update(action_succeeded=False, error=f"{type(exc).__name__}:{str(exc)[:120]}")
        try:
            with budget.journal_lock(rec_p):
                _recovery_row(rec_p, row)
        except (OSError, ValueError):
            # The durable reservation still consumes the attempt if result recording is unavailable.
            out["budget_status"] = "unavailable"
            break
    return out


L4_AFTER_S = 3 * 3600  # a breach still OPEN this long after detection pages the operator (06 §5 L4)
L5_RECURRENCES = 3  # the same lane × kind three times in 7 days → orchestration-change proposal (06 §5 L5)


def _ladder_l4_l5(rows: list[dict], sla_by_lane: dict, now, runtime_dir: Path, *, live: bool) -> dict:
    """L4: one page per breach_id (edge-triggered through alert_transition) when a breach stays OPEN past
    L4_AFTER_S and the lane's ladder_max allows it. L5: a Recovery/orchestration proposal row when a
    lane × kind recurs L5_RECURRENCES times in 7 days. Shadow = receipts only; live = page + proposal."""
    led = runtime_dir / "supervisor_breaches.jsonl"
    history: list[dict] = []
    try:
        with led.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        history = []
    week_ago = (now - _dt.timedelta(days=7)).isoformat()
    recur: dict[tuple, int] = {}
    first_seen: dict[str, str] = {}
    for h in history:
        if str(h.get("detected_at") or "") >= week_ago:
            recur[(h.get("lane_id"), h.get("kind"))] = recur.get((h.get("lane_id"), h.get("kind")), 0) + 1
        first_seen.setdefault(h.get("breach_id"), h.get("detected_at"))
    out = {
        "l4_candidates": 0,
        "l4_paged": 0,
        "l5_candidates": 0,
        "l5_proposed": 0,
        "mode": "live" if live else "shadow",
    }
    receipts = runtime_dir / "supervisor_ladder_receipts.jsonl"
    receipts.parent.mkdir(parents=True, exist_ok=True)
    try:
        import alert_transition as at  # type: ignore
    except Exception:  # noqa: BLE001
        at = None
    for r in rows:
        lane = r.get("lane_id")
        kind = r.get("kind")
        ladder_max = int((sla_by_lane.get(lane) or {}).get("ladder_max") or 3)
        since = first_seen.get(r.get("breach_id")) or r.get("detected_at")
        try:
            age_s = (now - _dt.datetime.fromisoformat(str(since).replace("Z", "+00:00"))).total_seconds()
        except (ValueError, TypeError):
            age_s = 0
        rec = {
            "schema": "SupervisorLadderReceipt@v1",
            "ts": now.isoformat(),
            "breach_id": r.get("breach_id"),
            "lane_id": lane,
            "kind": kind,
            "age_s": int(age_s),
            "ladder_max": ladder_max,
            "recurrences_7d": recur.get((lane, kind), 0),
            "mode": out["mode"],
        }
        if ladder_max >= 4 and age_s >= L4_AFTER_S:
            out["l4_candidates"] += 1
            rec["level"] = 4
            fire = True
            if (
                live and at is not None
            ):  # shadow never touches the transition state (an evaluate persists the observation)
                try:
                    tr = at.evaluate(
                        f"supervisor:{r.get('breach_id')}",
                        "BREACH",
                        path=runtime_dir / "supervisor_ladder_transitions.json",
                        extra={"kind": kind},
                    )
                    fire = bool(
                        getattr(tr, "notify", True)
                    )  # edge-triggered: one page per breach, re-alert after MIN_REALERT_MINUTES
                    rec["transition"] = getattr(tr, "action", None)
                    tr.commit()
                except Exception:  # noqa: BLE001
                    fire = True
            rec["would_page"] = fire
            if live and fire:
                try:
                    from telegram_alert import send_telegram  # type: ignore

                    send_telegram(
                        f"STOP HEALTH — supervisor L4: lane {lane} {kind} OPEN for {int(age_s // 3600)}h (breach {r.get('breach_id')}); L1–L3 did not recover it",
                        priority="P1",
                        producer="supervisor_breach_detector",
                    )
                    rec["paged"] = True
                    out["l4_paged"] += 1
                except Exception as exc:  # noqa: BLE001
                    rec["paged"] = False
                    rec["error"] = type(exc).__name__
        if recur.get((lane, kind), 0) >= L5_RECURRENCES and ladder_max >= 5:
            out["l5_candidates"] += 1
            rec["level"] = max(rec.get("level", 0), 5)
            proposal = {
                "schema": "OrchestrationProposal@v1",
                "ts": now.isoformat(),
                "lane_id": lane,
                "kind": kind,
                "recurrences_7d": recur.get((lane, kind), 0),
                "proposal": "declare an alternate lane or change the schedule / owner (06 §5 L5)",
                "requires": "ApprovalPackage item (operator-only, AGENTS §17)",
                "state": "PROPOSED" if live else "SHADOW",
            }
            rec["proposal"] = proposal
            if live:
                with (runtime_dir.parent / "governance" / "orchestration_proposals.jsonl").open(
                    "a", encoding="utf-8"
                ) as fh:
                    fh.write(json.dumps(proposal, sort_keys=True) + "\n")
                out["l5_proposed"] += 1
        if rec.get("level"):
            with receipts.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(PROJ), help="code root (lane registry, silos)")
    ap.add_argument("--state-root", help="persistent-state root for output signals (default: production)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument(
        "--dry-run", action="store_true", help="detect and print only; overrides --write and every live flag"
    )
    ap.add_argument(
        "--enqueue-escalations",
        action="store_true",
        help="L3: append to the health agent's escalation queue (off by default)",
    )
    ap.add_argument(
        "--ladder",
        action="store_true",
        help="L4/L5 live: page the operator / write the orchestration proposal (default: shadow receipts only)",
    )
    ap.add_argument(
        "--heal",
        action="store_true",
        help="L1/L2 live: restart the lane's --user unit / start its alternate (default: shadow Recovery rows)",
    )
    ap.add_argument(
        "--slow-checks",
        choices=("auto", "always", "never"),
        default="auto",
        help="freshness contracts (STALE_OUTPUT) and input starvation (INPUT_STARVATION): auto = at most "
        "every 30 min (SLOW_CHECK_EVERY_S), always = this tick, never = skip",
    )
    a = ap.parse_args()
    if a.dry_run and (a.write or a.heal or a.ladder or a.enqueue_escalations):
        print("--dry-run given: ignoring --write/--heal/--ladder/--enqueue-escalations", file=sys.stderr)
    if a.dry_run:
        a.write = a.heal = a.ladder = a.enqueue_escalations = False
    root = Path(a.root)
    env = os.environ
    now = _dt.datetime.now(_dt.timezone.utc)
    import lane_registry  # type: ignore
    import supervisor_heartbeat as hbmod  # type: ignore

    reg = lane_registry.load_registry(root / "config" / "lane_registry.json")
    from approval_package import governance_dir  # type: ignore

    runtime_dir = (
        governance_dir(root, env).parent / "runtime"
    )  # state root's data/runtime (a persistent symlink in releases)
    seed_p = runtime_dir / "supervisor_sla_seed.json"
    seed_rows = json.loads(seed_p.read_text()).get("rows", []) if seed_p.exists() else []
    # 2026-10-16: lanes registered after the seed was written get their registry-derived SLA row (was: UNGOVERNED).
    from seed_supervisor_sla import merged_sla_rows  # type: ignore

    sla_by_lane = merged_sla_rows(seed_rows, reg.get("lanes", []))
    heartbeats = {h.get("lane_id"): h for h in hbmod.read_all(root=root, env=env)}
    state_root = Path(a.state_root) if a.state_root else None
    db_query = _read_only_db_query()
    observe = (
        (lambda sig: lane_registry.observe_signal(sig, root=state_root, db_query=db_query))
        if state_root
        else (lambda sig: lane_registry.observe_signal(sig, db_query=db_query))
    )
    rows = detect(lanes=reg.get("lanes", []), sla_by_lane=sla_by_lane, heartbeats=heartbeats, observe=observe, now=now)
    # W1-9 monitor fold: the slow checks, throttled (see SLOW_CHECK_EVERY_S). A failed slow check is reported on
    # the summary and never stops the lane checks above.
    due, slow_state = _slow_checks_due(runtime_dir, now, a.slow_checks)
    slow: dict[str, dict] = {}
    if due["freshness_contracts"]:
        try:
            fr = detect_freshness(
                contracts=reg.get("freshness_contracts") or [],
                lanes=reg.get("lanes", []),
                sla_by_lane=sla_by_lane,
                observe=observe,
                now=now,
            )
            rows.extend(fr)
            slow["freshness_contracts"] = {
                "evaluated": True,
                "contracts": len(reg.get("freshness_contracts") or []),
                "breaches": len(fr),
            }
        except Exception as exc:  # noqa: BLE001
            slow["freshness_contracts"] = {"evaluated": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    else:
        slow["freshness_contracts"] = {"evaluated": False, "last_evaluated_at": slow_state.get("freshness_contracts")}
    if due["input_starvation"]:
        try:
            st = detect_input_starvation(liveness=_evaluate_liveness(state_root), now=now)
            rows.extend(st)
            slow["input_starvation"] = {"evaluated": True, "breaches": len(st)}
        except Exception as exc:  # noqa: BLE001
            slow["input_starvation"] = {"evaluated": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    else:
        slow["input_starvation"] = {"evaluated": False, "last_evaluated_at": slow_state.get("input_starvation")}
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    summary = {
        "schema": "BreachDetectorRun@v1",
        "as_of": now.isoformat(),
        "active_lanes": sum(1 for l in reg.get("lanes", []) if l.get("state") == "ACTIVE"),
        "sla_rows": len(sla_by_lane),
        "heartbeats": len(heartbeats),
        "breaches": len(rows),
        "by_kind": by_kind,
        "ladder": "detect+record only (L1–L5 not executed in Wave 1)",
        "slow_checks": slow,
        "authority": "READ_ONLY_ADVISORY",
    }
    print(json.dumps(summary, indent=1))
    for r in rows[:15]:
        print(f"  {r['kind']:<18} {r['lane_id']}")
    if len(rows) > 15:
        print(f"  … {len(rows) - 15} more")
    if a.write:
        led = runtime_dir / "supervisor_breaches.jsonl"
        led.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        if led.exists():
            for line in led.read_text().splitlines():
                try:
                    seen.add(json.loads(line).get("breach_id"))
                except (json.JSONDecodeError, AttributeError):
                    pass
        new = [r for r in rows if r["breach_id"] not in seen]
        with led.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
        evaluated = [k for k, v in slow.items() if v.get("evaluated")]
        if evaluated:
            st_p = runtime_dir / SLOW_CHECKS_STATE
            st_tmp = st_p.with_suffix(".json.tmp")
            st_tmp.write_text(json.dumps({**slow_state, **{k: now.isoformat() for k in evaluated}}, indent=1) + "\n")
            os.replace(st_tmp, st_p)
        # RECORD_ONLY_KINDS (W1-9) never reach L1/L2 or the L4/L5 ladder, not even as shadow receipts.
        ladder_input = [r for r in rows if r.get("kind") not in RECORD_ONLY_KINDS]
        latest = runtime_dir / "supervisor_breach_detector_latest.json"
        steps_failed: list[str] = []
        # item 10 (pkg-20260928-wave-2-enforcement-35c4): upsert the beat into intelligence.heartbeat when reachable
        _conn = None
        try:
            import db_adapter  # type: ignore

            _conn = db_adapter._get_conn()
            with _conn.cursor() as _c:
                _c.execute("SET app.tenant_id = 'tradeai:tenant:primary'")
        except Exception:  # noqa: BLE001
            _conn = None
        hb_row = hbmod.beat(
            "supervisor-breach-detector",
            conn=_conn,
            success=True,
            output_signal=True,
            work_done=len(rows),
            root=root,
            env=env,
        )
        print(f"heartbeat: file + pg={hb_row.get('pg')}")
        print(f"wrote {len(new)} new breach rows; latest → {latest}")
        if a.enqueue_escalations and new:
            try:
                import health_agent  # type: ignore

                # Wave 4 O-W4-5 finding: this call passed one argument to enqueue_escalations(policy, findings_flat)
                # and rows without `severity`, so the TypeError was swallowed as "L3 unavailable" and nothing was
                # ever enqueued. Now the policy is loaded and each breach carries a severity + component.
                pol = {}
                try:
                    pol = health_agent.load_policy() if hasattr(health_agent, "load_policy") else {}
                except Exception:  # noqa: BLE001
                    pol = {}
                findings = [
                    {
                        "source": "supervisor-breach-detector",
                        "breach_id": r["breach_id"],
                        "lane_id": r["lane_id"],
                        "kind": r["kind"],
                        "component": f"lane:{r['lane_id']}",
                        "type": f"breach_{str(r['kind']).lower()}",
                        "severity": "high" if r.get("level", 1) >= 2 else "medium",
                        "message": f"{r['kind']} on lane {r['lane_id']}",
                        "evidence": r.get("evidence"),
                    }
                    for r in new
                    if r.get("kind") not in RECORD_ONLY_KINDS
                ]
                health_agent.enqueue_escalations(pol, findings)
                print(f"L3: {len(findings)} escalation(s) enqueued")
            except Exception as exc:  # noqa: BLE001
                print(f"L3 enqueue unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
                steps_failed.append(f"l3:{type(exc).__name__}")
        # Wave 5 O-W5-3: self-healing L1 (systemctl --user restart of the lane's own unit) and L2 (start the SLA row's
        # alternate). SHADOW unless --heal: what WOULD be restarted is a Recovery@v1 row with executed=false.
        try:
            heal = _self_heal_l1_l2(
                ladder_input, reg.get("lanes", []), sla_by_lane, now, runtime_dir, live=bool(getattr(a, "heal", False))
            )
            print(f"self-heal L1/L2: {heal}")
            if heal.get("budget_status") == "unavailable":
                steps_failed.append("self_heal:budget_unavailable")
        except Exception as exc:  # noqa: BLE001
            print(f"self-heal skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
            steps_failed.append(f"self_heal:{type(exc).__name__}")
        # Wave 4 O-W4-5: ladder L4 (operator page) and L5 (orchestration-change proposal). SHADOW unless --ladder:
        # what WOULD be paged / proposed is recorded on data/runtime/supervisor_ladder_receipts.jsonl.
        try:
            ladder_rows = _ladder_l4_l5(
                ladder_input, sla_by_lane, now, runtime_dir, live=bool(getattr(a, "ladder", False))
            )
            print(f"ladder L4/L5: {ladder_rows}")
        except Exception as exc:  # noqa: BLE001
            print(f"ladder skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
            steps_failed.append(f"ladder:{type(exc).__name__}")
        # The lane's output signal, written last so it can say whether every step held.
        try:
            prev_ok = json.loads(latest.read_text(encoding="utf-8")).get("ok_at")
        except (OSError, ValueError, AttributeError):
            prev_ok = None
        doc = {
            **summary,
            "new_rows": len(new),
            "steps_failed": steps_failed,
            "ok_at": now.isoformat() if not steps_failed else prev_ok,
        }
        tmp = latest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n")
        os.replace(tmp, latest)
        return 1 if steps_failed else 0
    else:
        print("dry run: nothing written (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
