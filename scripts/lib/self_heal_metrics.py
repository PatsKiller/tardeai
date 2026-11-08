"""Self-heal metrics (LQ-20261107-1235, P1): funnel, false-fix rate, cost per accepted fix, MTTR.

Pure functions plus one append-only JSONL writer. No DB, no network, no broker. The file
``runtime/self_heal/metrics.jsonl`` holds one row per job transition::

    {"job_id", "lane", "state", "at" (ISO-8601), "cost_usd" (float or null = unknown), "incident_at" (opt.)}

``state`` is a fixer state (fix_requested ... incident_resolved) or one of the metrics-only events
``insufficient_evidence`` (the job was refused for want of evidence) and ``recurred`` (the incident came
back after a fix; it makes that job a false fix when it lands within 7 days of the heal).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

DEFAULT_PATH = Path("runtime/self_heal/metrics.jsonl")
HEALED = frozenset({"output_recovered", "incident_resolved"})
FALSE_FIX_WINDOW = timedelta(days=7)
RECURRED = "recurred"


def parse_ts(value: Any) -> Optional[datetime]:
    """ISO string -> aware UTC datetime; anything unparseable -> None (never guessed)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def row_from_job(job: Mapping[str, Any], state: str, now: datetime, cost_usd: Optional[float] = None) -> dict:
    """The metrics row for one transition of a SelfHealFixJob. Cost stays None when not reported."""
    return {
        "job_id": job.get("job_id"),
        "lane": job.get("lane"),
        "state": state,
        "at": now.isoformat(),
        "cost_usd": cost_usd,
        "incident_at": job.get("created_at"),
    }


def append_row(row: Mapping[str, Any], path: Path = DEFAULT_PATH) -> Path:
    """Append one row (append-only; never rewrites or truncates)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(row), sort_keys=True, default=str) + "\n")
    return path


def read_rows(path: Path = DEFAULT_PATH) -> list[dict]:
    """Rows from the JSONL file; a missing file is [] and a torn/garbage line is skipped, not fatal."""
    path = Path(path)
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def summarize(rows: Iterable[Mapping[str, Any]], now: datetime) -> dict:
    """Funnel counts (distinct jobs that ever reached each stage) plus false_fix_7d, cost_per_accepted, mttr_h.

    * ``admitted`` jobs seen at all; ``insufficient_evidence`` refused for evidence; ``ready_local`` /
      ``accepted`` (= fix_ready_local or later) / ``deployed`` / ``output_recovered``.
    * ``false_fix_7d``: {healed, false, rate}: healed in the 7 days to ``now`` and recurred within 7 days of the
      heal. rate is None when nothing healed (no denominator).
    * ``cost_per_accepted``: known cost of jobs that were accepted / accepted jobs; None when no accepted job
      has a known cost. Unknown cost is never counted as zero (``cost_unknown_jobs`` says how many).
    * ``mttr_h``: mean hours from incident to heal over healed jobs with both times; None otherwise.
    """
    by_job: dict[Any, dict] = {}
    for r in rows:
        jid = r.get("job_id")
        at = parse_ts(r.get("at"))
        if jid is None or at is None:
            continue
        j = by_job.setdefault(jid, {"states": {}, "cost": None, "incident_at": None})
        j["states"].setdefault(r.get("state"), at)
        j["states"][r.get("state")] = min(j["states"][r.get("state")], at)
        c = r.get("cost_usd")
        if isinstance(c, (int, float)) and not isinstance(c, bool) and c >= 0:
            j["cost"] = float(c) if j["cost"] is None else max(j["cost"], float(c))  # cost_usd is cumulative
        inc = parse_ts(r.get("incident_at"))
        if inc and (j["incident_at"] is None or inc < j["incident_at"]):
            j["incident_at"] = inc

    def reached(j: dict, names: frozenset) -> bool:
        return any(s in j["states"] for s in names)

    accepted_set = frozenset({"fix_ready_local", "fix_pr_opened", "fix_deployed", "output_recovered", "incident_resolved"})
    deployed_set = frozenset({"fix_deployed", "output_recovered", "incident_resolved"})
    jobs = list(by_job.values())
    accepted = [j for j in jobs if reached(j, accepted_set)]
    known = [j["cost"] for j in accepted if j["cost"] is not None]

    window_start = now - FALSE_FIX_WINDOW
    healed_win = false_n = 0
    mttrs: list[float] = []
    for j in jobs:
        heals = [t for s, t in j["states"].items() if s in HEALED]
        if not heals:
            continue
        healed_at = min(heals)
        if j["incident_at"] and healed_at >= j["incident_at"]:
            mttrs.append((healed_at - j["incident_at"]).total_seconds() / 3600.0)
        if window_start <= healed_at <= now:
            healed_win += 1
            rec = j["states"].get(RECURRED)
            if rec and healed_at <= rec <= healed_at + FALSE_FIX_WINDOW:
                false_n += 1
    return {
        "admitted": len(jobs),
        "insufficient_evidence": sum(1 for j in jobs if "insufficient_evidence" in j["states"]),
        "ready_local": sum(1 for j in jobs if reached(j, accepted_set)),
        "accepted": len(accepted),
        "deployed": sum(1 for j in jobs if reached(j, deployed_set)),
        "output_recovered": sum(1 for j in jobs if reached(j, HEALED)),
        "false_fix_7d": {"healed": healed_win, "false": false_n, "rate": (false_n / healed_win) if healed_win else None},
        "cost_per_accepted": (sum(known) / len(accepted)) if accepted and known else None,
        "cost_unknown_jobs": len(accepted) - len(known),
        "mttr_h": (sum(mttrs) / len(mttrs)) if mttrs else None,
    }
