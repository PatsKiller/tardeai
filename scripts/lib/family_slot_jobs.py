"""family_slot_jobs.py — the top-5 same-script cron families as ONE parameterised job each (slot table).

n8n-maturity B families (b-family-designs/RANKING.md, 2026-10-11): fourteen crontab lines ran five scripts in
different modes on different schedules, and 87 of their weekly fires were refused by a gate the schedule could
have known about (non_trading_hours_gate.sh in the session, llm_priority_guard.sh 06-12 ET, the DeepSeek
official UTC peak). Each family is now one registry lane and one entry (`scripts/run_family_slot.py --family
<lane>`). The entry derives the mode(s) from the clock through the slot table below and runs EXACTLY the old
crontab command of that mode: same argv, same env (the crontab env is passed through untouched), same lock
(the lock is inside the command), same log (opened in append mode, as `>> log 2>&1` did).

The gates moved inside: the slot table only schedules the minutes the gates allow, so the scheduler stops firing
into a refusal. The gate wrappers stay INSIDE each mode's command as safety nets (holidays, early closes, a
changed LLM_GUARD_* window); `gate_allows` models them so the tests and `--audit-week` can prove a new fire
is never a predicted refusal.

A crontab line can carry only one minute/hour/day-of-week set, so a family still needs one crontab line per
distinct field set (`Family.cron_lines`); every line runs the same command. `tests/test_family_slot_jobs_20261011.py`
proves, minute by minute over an EDT and an EST week, that the union of `cron_lines` equals the union of the slot
table (no fire that matches no slot, no slot no line fires) and that every old line's effective run is one mode
run of the new job, except the documented deltas (`Family.deltas`).

Stdlib only (plus scripts/lib/cron_schedule.py). No broker, no order, no send: MBI_BEHAVIOR = 0. This module
never runs a command; scripts/run_family_slot.py does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

try:
    from scripts.lib import cron_schedule
except ImportError:  # scripts/ on sys.path, repo root not
    from lib import cron_schedule  # type: ignore[no-redef]

SCHEMA = "FamilySlotRun@v1"
ENTRY = "scripts/run_family_slot.py"
ENTRY_LOG = "logs/run_family_slot.log"
#: Cron starts a job within seconds of its minute; a fire later than this is not attributed to a slot.
DEFAULT_TOLERANCE_MIN = 10
TZ_NAME = "America/New_York"

#: Gate names a mode's command carries (the wrapper scripts are in the command; these model them).
GATE_NON_TRADING_HOURS = "non_trading_hours_gate"      # scripts/non_trading_hours_gate.sh
GATE_LLM_PRIORITY = "llm_priority_guard"               # scripts/llm_priority_guard.sh (06:00-11:59 ET Mon-Fri)
GATE_DEEPSEEK_OFFICIAL = "deepseek_offpeak_official"   # run_with_deepseek_offpeak.sh --official
GATES = (GATE_NON_TRADING_HOURS, GATE_LLM_PRIORITY, GATE_DEEPSEEK_OFFICIAL)


@dataclass(frozen=True)
class Mode:
    """One retired crontab line, as a mode of the family job."""

    name: str
    #: The old line's command between `cd <root> && ` and ` >> <log> 2>&1`, verbatim; `{root}` stands for the
    #: literal served path the old line named (the new line `cd $PROJ`s to the same path). `$PY`, `$PROJ` and
    #: `$HOME` stay shell variables: cron's environment expands them exactly as it did for the old line.
    command: str
    log: str
    replaces_lane: str
    old_schedule: str
    gates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Slot:
    cron: str
    modes: tuple[str, ...]


@dataclass(frozen=True)
class Family:
    lane_id: str
    design_id: str
    modes: tuple[Mode, ...]
    slots: tuple[Slot, ...]
    #: The crontab lines that replace the retired ones (one per distinct cron field set; same command each).
    cron_lines: tuple[str, ...]
    #: Deliberate behaviour differences from the retired lines (tested, documented).
    deltas: tuple[str, ...] = ()
    #: Modes the family can run (`--mode`) that no slot schedules yet.
    unscheduled_modes: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    def mode(self, name: str) -> Mode:
        for m in self.modes:
            if m.name == name:
                return m
        raise KeyError(f"{self.lane_id}: unknown mode {name!r}")


_TOPIC_SYNTH = (
    "bash {root}/scripts/non_trading_hours_gate.sh bash -c 'bash {root}/scripts/llm_priority_guard.sh && "
    "flock -n /tmp/topic_synth.lock $PY scripts/topic_research_synthesizer.py --max 15 --apply'"
)
_TOPIC_REGROUND = (
    'bash "$HOME/.config/tradeai/bin/run_with_deepseek_offpeak.sh" --official -- bash '
    "{root}/scripts/non_trading_hours_gate.sh flock -n /tmp/topic_reground.lock $PY "
    "scripts/topic_research_synthesizer.py --reground --max 20 --apply"
)
_RESEARCH = (
    "env LLM_GLOBAL_DAILY_USD_CAP=2.00 flock -n /tmp/research_sched.lock env RESEARCH_SKIP_GATE=1 $PY "
    "{root}/scripts/research_scheduler.py --mode %s --apply --budget %d"
)
_CATALYST = (
    "bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_%s.lock $PY scripts/catalyst_momentum_engine.py "
    "--band %s --apply%s"
)
_TOPIC_INGEST = (
    "bash {root}/scripts/non_trading_hours_gate.sh timeout 30m $PY scripts/topic_ingestion.py "
    "--use-llm-queries --max-topics 14"
)
_CIO_DETECTOR = (
    "flock -n /tmp/cio_event_detector.lock python3 -c 'from scripts.lib.cio_event_detector import "
    "run_cio_event_detector_once; r=run_cio_event_detector_once(); print(\"Wakes:\", r.get(\"wakes_created\", 0))'"
)


FAMILIES: tuple[Family, ...] = (
    Family(
        lane_id="topic-research-synthesizer",
        design_id="B3",
        modes=(
            Mode("synth", _TOPIC_SYNTH, "logs/topic_research_synth.log",
                 "topic-research-synthesizer-at-20-x", "20 * * * *",
                 (GATE_NON_TRADING_HOURS, GATE_LLM_PRIORITY)),
            Mode("reground", _TOPIC_REGROUND, "logs/topic_research_synth.log",
                 "topic-research-synthesizer-reground", "50 21 * * *",
                 (GATE_DEEPSEEK_OFFICIAL, GATE_NON_TRADING_HOURS)),
        ),
        slots=(
            Slot("20 0-3,16-23 * * 1-5", ("synth",)),   # the weekday hours the session gate allows
            Slot("20 * * * 0,6", ("synth",)),           # weekend: allowed all day
            Slot("20 21 * * 5,6", ("reground",)),       # Fri/Sat nights: the only ones off the UTC peak
        ),
        cron_lines=("20 0-3,16-23 * * 1-5", "20 * * * 0,6"),
        deltas=(
            "reground runs at 21:20 Fri/Sat right after that slot's synth (same invocation, its own lock "
            "/tmp/topic_reground.lock, same log) instead of 21:50; Sun-Thu 21:50 were PEAK_SKIP no-ops",
            "a weekday market holiday no longer gets the 04:20, 05:20 and 12:20-15:20 synth runs the session gate "
            "allowed (the priority guard still defers 06-11), nor an early-close day its 13:20-15:20 runs: ~70 runs a "
            "year (design B3 risk, accepted: low value; a topic event trigger is the long-term answer)",
        ),
    ),
    Family(
        lane_id="research-scheduler",
        design_id="B7",
        modes=(
            Mode("holdings", _RESEARCH % ("holdings", 70), "logs/research_scheduler.log",
                 "research-scheduler-holdings", "5 9 * * 1-5"),
            Mode("priority", "bash {root}/scripts/llm_priority_guard.sh && " + _RESEARCH % ("priority", 40),
                 "logs/research_scheduler.log", "research-scheduler-priority-hourly", "0 10-16 * * 1-5",
                 (GATE_LLM_PRIORITY,)),
            Mode("watchlist", _RESEARCH % ("watchlist", 50), "logs/research_scheduler.log",
                 "research-scheduler-watchlist-2030", "30 20 * * 1-5"),
            Mode("incubator", _RESEARCH % ("incubator", 30), "logs/research_scheduler.log",
                 "research-scheduler-incubator-sun-1900", "0 19 * * 0"),
        ),
        slots=(
            Slot("5 9 * * 1-5", ("holdings",)),
            Slot("0 12-16 * * 1-5", ("priority",)),     # 10:00/11:00 were always DEFERRED by the guard
            Slot("30 20 * * 1-5", ("watchlist",)),
            Slot("0 19 * * 0", ("incubator",)),
        ),
        cron_lines=("5 9 * * 1-5", "0 12-16 * * 1-5", "30 20 * * 1-5", "0 19 * * 0"),
        deltas=(
            "the guard's DEFERRED echo (priority mode) now lands in logs/research_scheduler.log instead of cron "
            "mail (the old line redirected only the scheduler); with the 12-16 slots the guard never defers",
        ),
        notes=("holdings (09:05) stays unguarded on purpose: T1 holdings research inside the guard window",),
    ),
    Family(
        lane_id="catalyst-momentum-engine",
        design_id="B8",
        modes=(
            Mode("premarket_scalp", _CATALYST % ("premarket", "premarket_scalp", " --generate-proposals"),
                 "logs/catalyst_momentum_engine.log", "catalyst-momentum-engine-premarket", "*/30 4-9 * * 1-5"),
            Mode("market_swing", _CATALYST % ("swing", "market_swing", " --generate-proposals"),
                 "logs/catalyst_momentum_engine.log", "catalyst-momentum-engine-market", "30 9-15 * * 1-5"),
            Mode("overnight", _CATALYST % ("overnight", "overnight", ""),
                 "logs/catalyst_momentum_engine.log", "catalyst-momentum-engine-overnight", "0 18,22 * * *"),
        ),
        slots=(
            Slot("*/30 4-8 * * 1-5", ("premarket_scalp",)),
            Slot("0 9 * * 1-5", ("premarket_scalp",)),
            Slot("30 9-15 * * 1-5", ("market_swing",)),
        ),
        cron_lines=("0 4-9 * * 1-5", "30 4-15 * * 1-5"),
        deltas=(
            "no premarket_scalp pass at 09:30: it collided with the 09:30 market_swing pass under a different "
            "lock after the open (both logged 10-09 09:30); the swing band is the in-session band",
        ),
        unscheduled_modes=("overnight",),
        notes=(
            "overnight (L381, 0 18,22 * * *) stays on its own crontab line: it is the dispatcher shadow lane "
            "catalyst-momentum-engine-overnight (wave D3, config/n8n_run_allowlist.json); folding it needs the "
            "D3 shadow-row decision first. The mode exists so a manual `--mode overnight` run is the same command.",
        ),
    ),
    Family(
        lane_id="topic-ingestion",
        design_id="B2",
        modes=(
            Mode("after_close", _TOPIC_INGEST, "logs/topic_ingestion.log", "topic-ingestion-cron-lines", "45 20 * * 1-5",
                 (GATE_NON_TRADING_HOURS,)),
            Mode("weekend_overnight",
                 'bash "$HOME/.config/tradeai/bin/run_with_deepseek_offpeak.sh" --official -- ' + _TOPIC_INGEST,
                 "logs/topic_ingestion.log", "topic-ingestion-cron-lines", "45 2 * * *",
                 (GATE_DEEPSEEK_OFFICIAL, GATE_NON_TRADING_HOURS)),
        ),
        slots=(
            Slot("45 20 * * 1-5", ("after_close",)),
            Slot("45 2 * * 0,6", ("weekend_overnight",)),  # weekday 02:45 ET is inside the UTC peak (PEAK_SKIP)
        ),
        cron_lines=("45 20 * * 1-5", "45 2 * * 0,6"),
    ),
    Family(
        lane_id="cio-event-detector",
        design_id="B1",
        modes=(
            Mode("daily", _CIO_DETECTOR, "logs/cio_detector.log", "run-cio-event-detector-once-at-0-5",
                 "0 5 * * 1-5"),
            Mode("weekly", _CIO_DETECTOR, "logs/cio_detector_weekly.log", "run-cio-event-detector-once-at-0-8",
                 "0 8 * * 0"),
            Mode("monthly", _CIO_DETECTOR, "logs/cio_detector_monthly.log", "run-cio-event-detector-once-at-0-9",
                 "0 9 1 * *"),
        ),
        slots=(
            Slot("0 5 * * 1-5", ("daily",)),
            Slot("0 8 * * 0", ("weekly",)),
            Slot("0 9 1 * *", ("monthly",)),
        ),
        cron_lines=("0 5 * * 1-5", "0 8 * * 0", "0 9 1 * *"),
        deltas=(
            "adds `flock -n /tmp/cio_event_detector.lock` (design B1): the three slots never overlap today, so "
            "the lock only turns a hung run into a skipped one instead of two concurrent detectors",
        ),
        notes=(
            "the 05:00/09:00 (or 08:00/09:00) runs on the 1st are NOT duplicates: the detector computes due "
            "schedule slots against its clock (cio_event_detector._compute_due_slots), so it is not de-duplicated",
            "the interpreter stays bare `python3` exactly as the retired lines (side finding, not changed here)",
        ),
    ),
)

BY_LANE = {f.lane_id: f for f in FAMILIES}


def family(lane_id: str) -> Family:
    try:
        return BY_LANE[lane_id]
    except KeyError:
        raise KeyError(f"unknown family {lane_id!r}; known: {sorted(BY_LANE)}") from None


# ── cron matching (local wall clock, the crontab's own time) ──────────────────────────────────────────────


def cron_matches(expr: str, t: datetime) -> bool:
    """Does the 5-field cron expression fire at the local wall-clock minute ``t`` (Vixie DOM/DOW OR rule)?"""
    minutes, hours, doms, months, dows, dom_r, dow_r = cron_schedule.parse(expr)
    if t.minute not in minutes or t.hour not in hours or t.month not in months:
        return False
    cron_dow = (t.weekday() + 1) % 7
    if dom_r and dow_r:
        return t.day in doms or cron_dow in dows
    return t.day in doms and cron_dow in dows


def slot_modes_at(fam: Family, t: datetime) -> tuple[str, ...]:
    """Modes scheduled at exactly the minute ``t`` (table order, no duplicates)."""
    out: list[str] = []
    for slot in fam.slots:
        if cron_matches(slot.cron, t):
            out.extend(m for m in slot.modes if m not in out)
    return tuple(out)


def resolve(fam: Family, now: datetime, tolerance_min: int = DEFAULT_TOLERANCE_MIN
            ) -> Optional[tuple[datetime, tuple[str, ...]]]:
    """(slot minute, modes) for the latest slot minute in [now - tolerance, now]; None when there is none.

    Cron cannot fire early, so only a slot at or before ``now`` counts. A fire outside every slot is refused by
    the caller (exit 2) rather than given a guessed mode.
    """
    base = now.replace(second=0, microsecond=0, tzinfo=None)
    for delta in range(0, max(0, int(tolerance_min)) + 1):
        t = base - timedelta(minutes=delta)
        modes = slot_modes_at(fam, t)
        if modes:
            return t, modes
    return None


def render(mode: Mode, root: str) -> str:
    return mode.command.replace("{root}", str(root).rstrip("/"))


def crontab_command(fam: Family) -> str:
    return f"cd $PROJ && $PY {ENTRY} --family {fam.lane_id} >> {ENTRY_LOG} 2>&1"


def crontab_lines(fam: Family) -> list[str]:
    return [f"{expr} {crontab_command(fam)}" for expr in fam.cron_lines]


def registry_match(fam: Family) -> str:
    """The `scheduler.match` substring. Unique to this family's lines: no family id is a prefix of another's
    (tested), so `--family <id>` cannot hit a sibling family's line."""
    return f"{ENTRY} --family {fam.lane_id}"


# ── gate model (what the wrapper scripts inside the command decide) ───────────────────────────────────────


def _aware_et(t: datetime) -> datetime:
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(TZ_NAME)
    return t.replace(tzinfo=zone) if t.tzinfo is None else t.astimezone(zone)


def gate_allows(gate: str, t: datetime) -> bool:
    """Model of one gate wrapper at local time ``t`` (naive = America/New_York, the host and crontab zone).

    non_trading_hours_gate: market_session.current_market_session in afterhours|closed|weekend|holiday.
    llm_priority_guard: DEFERS Mon-Fri 06:00 <= h < 12:00 ET (LLM_GUARD_START/END_HOUR defaults).
    deepseek_offpeak_official: deepseek_offpeak.is_deepseek_peak_utc refuses 01-04Z and 06-10Z Mon-Fri UTC.
    """
    et = _aware_et(t)
    if gate == GATE_NON_TRADING_HOURS:
        try:
            from market_session import current_market_session  # scripts/ on sys.path
        except ImportError:
            from scripts.market_session import current_market_session  # type: ignore[no-redef]
        return current_market_session(et) in ("afterhours", "closed", "weekend", "holiday")
    if gate == GATE_LLM_PRIORITY:
        return not (et.weekday() <= 4 and 6 <= et.hour < 12)
    if gate == GATE_DEEPSEEK_OFFICIAL:
        try:
            from scripts.lib.deepseek_offpeak import is_deepseek_peak_utc
        except ImportError:
            from lib.deepseek_offpeak import is_deepseek_peak_utc  # type: ignore[no-redef]
        return not is_deepseek_peak_utc(et.astimezone(timezone.utc))
    raise KeyError(f"unknown gate {gate!r}")


def mode_allowed(mode: Mode, t: datetime) -> bool:
    return all(gate_allows(g, t) for g in mode.gates)


# ── week arithmetic (fires/week, audit) ───────────────────────────────────────────────────────────────────


def minutes_of_week(monday: datetime) -> Iterable[datetime]:
    start = monday.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    for i in range(7 * 24 * 60):
        yield start + timedelta(minutes=i)


def fires_in_week(exprs: Iterable[str], monday: datetime) -> list[datetime]:
    """Minutes in the week starting ``monday`` at which ANY of ``exprs`` fires (one fire per line per minute
    counted separately: two lines at the same minute are two scheduler fires)."""
    exprs = list(exprs)
    out: list[datetime] = []
    for t in minutes_of_week(monday):
        out.extend(t for e in exprs if cron_matches(e, t))
    return out


def audit_week(fam: Family, monday: datetime) -> dict:
    """Fires/week old vs new and predicted gate refusals, for one family and one calendar week."""
    old_exprs = []
    for m in fam.modes:
        if m.name in fam.unscheduled_modes:
            continue
        if m.old_schedule not in old_exprs:
            old_exprs.append(m.old_schedule)
    old_fires = 0
    old_refused = 0
    for t in minutes_of_week(monday):
        for m in fam.modes:
            if m.name in fam.unscheduled_modes or not cron_matches(m.old_schedule, t):
                continue
            old_fires += 1
            if not mode_allowed(m, t):
                old_refused += 1
    new_fires = len(fires_in_week(fam.cron_lines, monday))
    new_refused = 0
    for t in minutes_of_week(monday):
        for name in slot_modes_at(fam, t):
            if not mode_allowed(fam.mode(name), t):
                new_refused += 1
    return {
        "family": fam.lane_id, "design_id": fam.design_id, "week_of": monday.date().isoformat(),
        "old_lines": len(old_exprs), "new_lines": len(fam.cron_lines),
        "old_fires": old_fires, "old_predicted_refusals": old_refused,
        "new_fires": new_fires, "new_predicted_refusals": new_refused,
        "fires_saved": old_fires - new_fires,
    }
