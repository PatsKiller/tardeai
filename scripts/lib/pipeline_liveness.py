"""PipelineLiveness@v1 — detect lanes that have stopped producing.

The CIO evidence gate blocked 54 of 55 runs for 17 continuous days and nothing
raised an alarm. Every block was recorded faithfully; no monitor watched the
record. That is the general failure mode of a scheduled pipeline: a lane that is
broken and a lane that legitimately has nothing to do look identical from the
outside, because both emit nothing.

So the probe here is deliberately NOT error-log parsing. It measures **absence of
throughput**: for each lane, how many successful outputs landed inside a rolling
window, against the minimum that lane should produce. A lane whose inputs arrive
but whose outputs do not is the exact shape of the bug that went unseen — which
is why `attempted` is tracked separately from `produced`. Silence with no
attempts is quiet; silence *despite* attempts is a fault.

Read-only. Writes nothing, sends nothing, and holds no authority: it reports.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "PipelineLiveness@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# Statuses a probe can return.
LIVE = "LIVE"                    # produced at or above its floor
STARVED = "STARVED"              # attempted work, produced nothing — the 17-day shape
QUIET = "QUIET"                  # no attempts and no output; nothing to conclude
NO_ELIGIBLE_INPUT = "NO_ELIGIBLE_INPUT"  # work arrived, but none of it could ever produce this output
UNKNOWN = "UNKNOWN"              # source unreadable; explicitly not "healthy"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    """Best-effort timestamp parse. Unreadable is None, never 'now'.

    Defaulting an unparseable timestamp to now would make every stale record
    look fresh, which is how a silent lane reports healthy.
    """
    if not value:
        return None
    raw = str(value).strip()
    try:
        if raw.upper().endswith(" ET"):
            from zoneinfo import ZoneInfo
            naive = datetime.strptime(raw[:-3].strip(), "%Y-%m-%d %H:%M:%S")
            return naive.replace(tzinfo=ZoneInfo("America/New_York"))
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, KeyError):
        return None


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    rows = []
    try:
        with Path(path).open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue  # one bad line must not blind the whole probe
    except OSError:
        return []
    return rows


@dataclass
class Lane:
    """One monitored lane.

    `produced` counts successful outputs; `attempted` counts work that entered
    the lane. Separating them is the whole point: 55 runs entered and 1 produced
    is a fault, while 0 entered and 0 produced is a quiet weekend.
    """
    name: str
    window_hours: float
    min_expected: int
    describe: str
    probe: Callable[[datetime], tuple[int, int, str]]  # -> (produced, attempted, source)


@dataclass
class LivenessReport:
    lanes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def findings(self) -> list[dict[str, Any]]:
        # NO_ELIGIBLE_INPUT is a finding too: a lane that can never produce is
        # still a gap the operator should see. It is reported under its own
        # status so the ACTION differs -- wire a producer, not unblock a queue.
        return [l for l in self.lanes
                if l["status"] in (STARVED, UNKNOWN, NO_ELIGIBLE_INPUT)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "financial_action": False,
            "observed_at": _now().replace(microsecond=0).isoformat(),
            "lanes": self.lanes,
            "findings": self.findings,
            "ok": not self.findings,
        }


def evaluate(lanes: list[Lane], now: datetime | None = None) -> LivenessReport:
    now = now or _now()
    report = LivenessReport()
    for lane in lanes:
        try:
            result = lane.probe(now - timedelta(hours=lane.window_hours))
            # A probe may report a fourth value: how many of those attempts were
            # ELIGIBLE to produce this lane's output. Three-value probes keep
            # their existing meaning -- every attempt counts as eligible.
            if len(result) == 4:
                produced, attempted, source, eligible = result
            else:
                produced, attempted, source = result
                eligible = attempted
        except Exception as exc:  # a broken probe is UNKNOWN, never LIVE
            report.lanes.append({
                "lane": lane.name,
                "status": UNKNOWN,
                "detail": f"probe failed: {type(exc).__name__}",
                "window_hours": lane.window_hours,
                "describe": lane.describe,
            })
            continue

        if produced >= lane.min_expected and produced > 0:
            status = LIVE
        elif attempted > 0 and eligible == 0:
            # Work arrived, but none of it was of a class this lane's output can
            # be made from. Calling that STARVED tells the operator to go
            # unblock a queue that is not blocked, and a standing false alarm is
            # one that gets ignored -- this system has already produced one
            # ("Hermes starved", 2026-07-23, false). The gap is real but
            # different: nothing is producing eligible input.
            status = NO_ELIGIBLE_INPUT
        elif attempted > 0:
            status = STARVED
        elif produced >= lane.min_expected:
            status = LIVE
        else:
            status = QUIET

        report.lanes.append({
            "lane": lane.name,
            "status": status,
            "produced": produced,
            "attempted": attempted,
            "eligible": eligible,
            "min_expected": lane.min_expected,
            "window_hours": lane.window_hours,
            "source": source,
            "describe": lane.describe,
        })
    return report


# ── Probes over the real stores ────────────────────────────────────────────

def _state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state"


def _probe_cio_runs(since: datetime) -> tuple[int, int, str]:
    """Runs that got past the evidence gate, vs runs that were created.

    This is the probe that would have fired on 2026-08-10: 55 created, 1 not
    blocked, for 17 days.
    """
    path = _state_root() / "data" / "cio" / "cio_runs.jsonl"
    rows = read_jsonl(path)
    created = blocked = 0
    for row in rows:
        ts = _parse_ts(row.get("occurred_at"))
        if not ts or ts < since:
            continue
        kind = row.get("event_type")
        if kind == "CIO_RUN_CREATED":
            created += 1
        elif kind == "CIO_RUN_BLOCKED":
            blocked += 1
    return max(created - blocked, 0), created, str(path)


def _probe_lineage_completions(since: datetime) -> tuple[int, int, str]:
    """Workflows reaching complete_to_checkpoint, vs envelopes written."""
    path = _state_root() / "data" / "cio" / "cio_workflow_lineage.jsonl"
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        if row.get("record_type") == "envelope" and row.get("workflow_id"):
            latest[str(row["workflow_id"])] = row
    written = complete = 0
    for env in latest.values():
        ts = _parse_ts(env.get("updated_at") or env.get("created_at"))
        if not ts or ts < since:
            continue
        written += 1
        if env.get("complete_to_checkpoint"):
            complete += 1
    return complete, written, str(path)


def _receipt_is_promotable(row: dict[str, Any]) -> bool:
    """Could THIS candidate ever have reached ADMITTED?

    Governance admits only OPERATOR_EXPLICIT_PREFERENCE, AGENT_COMMITMENT and
    CASE_SUMMARY as ACTIVE; RESEARCH_REFERENCE, EPISODIC and PROCEDURAL_HINT are
    context and are deliberately never policy. A receipt for the latter reading
    CANDIDATE is the system working, not a blockage.

    Receipts written before this field existed carry no memory_type. They are
    resolved against the memory store by memory_id rather than guessed at; a
    receipt that cannot be resolved counts as NOT promotable, so an unknown can
    never manufacture the appearance of eligible input.
    """
    explicit = row.get("promotable")
    if isinstance(explicit, bool):
        return explicit
    mtype = str(row.get("memory_type") or "") or _store_memory_type(row.get("memory_id"))
    if not mtype:
        return False
    try:
        from scripts.lib.agent_memory_governance import ADMIT_ACTIVE_TYPES
    except Exception:
        return False
    return mtype in ADMIT_ACTIVE_TYPES


_STORE_TYPES: dict[str, str] | None = None


def _store_memory_type(memory_id: Any) -> str:
    """memory_id -> memory_type, folded once from the durable store."""
    global _STORE_TYPES
    if not memory_id:
        return ""
    if _STORE_TYPES is None:
        _STORE_TYPES = {}
        path = _state_root() / "data" / "cio" / "aif_memory.jsonl"
        for rec in read_jsonl(path):
            mid = rec.get("memory_id") or rec.get("id")
            if mid:
                _STORE_TYPES[str(mid)] = str(rec.get("memory_type") or "")
    return _STORE_TYPES.get(str(memory_id), "")


def _probe_memory_admissions(since: datetime) -> tuple[int, int, str, int]:
    """Memories that actually became usable, vs candidates offered.

    `accepted: true` only means the candidate was taken in -- 396 of 403 are
    accepted while just 2 carry `display_status: ADMITTED`. Counting `accepted`
    would report this lane healthy at a 0.5% promotion rate, which is precisely
    the blindness this module exists to remove. ADMITTED is the output that
    matters: a memory stuck at CANDIDATE influences nothing.
    """
    path = _state_root() / "data" / "cio" / "aif_memory_admissions.jsonl"
    offered = admitted = eligible = 0
    for row in read_jsonl(path):
        ts = _parse_ts(row.get("admitted_at"))
        if not ts or ts < since:
            continue
        offered += 1
        if str(row.get("display_status") or "").upper() == "ADMITTED":
            admitted += 1
        if _receipt_is_promotable(row):
            eligible += 1
    return admitted, offered, str(path), eligible


def default_lanes() -> list[Lane]:
    """Lanes whose silence has already cost something, or would."""
    return [
        Lane(
            name="cio_runs_reaching_synthesis",
            window_hours=float(24),
            min_expected=1,
            describe="CIO runs that got past the evidence gate",
            probe=_probe_cio_runs,
        ),
        Lane(
            name="lineage_completions",
            window_hours=float(24),
            min_expected=1,
            describe="workflows reaching complete_to_checkpoint",
            probe=_probe_lineage_completions,
        ),
        Lane(
            name="memory_admissions",
            window_hours=float(72),
            min_expected=1,
            describe="candidate memories promoted to ADMITTED",
            probe=_probe_memory_admissions,
        ),
    ]
