"""Do CIO, Hermes and Advisory read the SAME memory ids for one subject in one window?

Agentic-memory tranche 2, Slice 4 (D2 acceptance G8, 2026-09-25). A measurement,
not a change of behaviour: MEMORY_BEHAVIOR_INFLUENCE stays 0 and nothing here
touches a provider. It reads three existing, append-only stores of durable
``mem_…`` ids and reports, per subject_guid in a window, which agents read
which ids and how many ids they share.

Sources (all read-only JSONL):

* CIO — persistent wakes ``wakes.jsonl``: ``agent_id``, ``subject_guid``,
  ``memory_fact_ids`` (the facts loaded before deciding), ``produced_at``.
  Today every wake is ``cio``; other agents in ``KNOWN_AGENTS`` are counted
  if they ever appear.
* Hermes — ``hermes_research_requests.jsonl`` ``HERMES_RESEARCH_REQUESTED`` rows:
  ``subject_guid`` and ``prompt_context.memory_context.{supporting,counter}[].memory_id``.
  Honesty note carried in the report: these are the memory retrievals CIO plan
  enrichment placed in Hermes's prompt, not reads logged by a Hermes process.
* Advisory — ``aif_memory_retrievals.jsonl`` rows whose ``query`` is the desk's
  literal ``"advisory desk operator truth"``: ``symbols[]`` + ``memory_ids[]``.
  Attributed to a subject_guid through an injected symbol→guid mapping (the
  identity registry, lookup only). Rows whose ``query`` is not a string are the
  shadow measure's own replay (19,908 of them on 2026-09-24) and are excluded.

The report says plainly when a source is absent, when no subject is read by
more than one agent, and when the three-way intersection is empty. It never
invents agreement. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

SCHEMA = "CrossAgentMemoryAgreement@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
ADVISORY_QUERY = "advisory desk operator truth"
HERMES_EVENT = "HERMES_RESEARCH_REQUESTED"
AGENTS = ("cio", "hermes", "advisory")
DEFAULT_WINDOW_HOURS = 24.0


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _in_window(ts: Any, start: datetime, end: datetime) -> bool:
    dt = _parse(ts)
    return dt is not None and start <= dt <= end


def iter_jsonl(path: Path | str) -> Iterable[dict[str, Any]]:
    """Stream a JSONL file (the retrievals log is ~150 MB). Bad lines skipped."""
    p = Path(path)
    if not p.is_file():
        return
    with p.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


# ── per-source readers → (agent, subject_guid, memory_ids, ts) ────────────────

def cio_reads(wakes: Iterable[dict[str, Any]], *, start: datetime, end: datetime) -> list[tuple[str, str, set[str], str]]:
    out = []
    for w in wakes:
        ts = w.get("produced_at") or w.get("schedule_slot_utc")
        if not _in_window(ts, start, end):
            continue
        ids = {str(x) for x in (w.get("memory_fact_ids") or []) if x}
        sg = str(w.get("subject_guid") or "")
        agent = str(w.get("agent_id") or "cio")
        if sg and ids:
            out.append((agent, sg, ids, str(ts)))
    return out


def hermes_reads(requests: Iterable[dict[str, Any]], *, start: datetime, end: datetime) -> list[tuple[str, str, set[str], str]]:
    out = []
    for r in requests:
        if str(r.get("event") or r.get("event_type") or "") != HERMES_EVENT:
            continue
        pc = r.get("prompt_context") or {}
        ts = r.get("created_ts") or (pc.get("as_of") if isinstance(pc, dict) else None)
        if not _in_window(ts, start, end):
            continue
        mc = (pc.get("memory_context") if isinstance(pc, dict) else None) or {}
        ids: set[str] = set()
        for key in ("supporting", "counter"):
            for m in (mc.get(key) or []) if isinstance(mc, dict) else []:
                mid = m.get("memory_id") if isinstance(m, dict) else None
                if mid:
                    ids.add(str(mid))
        sg = str(r.get("subject_guid") or "")
        if sg and ids:
            out.append(("hermes", sg, ids, str(ts)))
    return out


def advisory_reads(retrievals: Iterable[dict[str, Any]], *, start: datetime, end: datetime,
                   guid_for_symbol: Callable[[str], Optional[str]]) -> tuple[list[tuple[str, str, set[str], str]], dict[str, int]]:
    """Desk retrieval rows → per-symbol subject reads. Excludes the measure's own replay."""
    out = []
    stats = defaultdict(int)
    for r in retrievals:
        q = r.get("query")
        if not isinstance(q, str):
            stats["excluded_measure_replay"] += 1
            continue
        if q != ADVISORY_QUERY:
            stats["other_queries"] += 1
            continue
        ts = r.get("at")
        if not _in_window(ts, start, end):
            continue
        ids = {str(x) for x in (r.get("memory_ids") or []) if x}
        if not ids:
            stats["advisory_empty"] += 1
            continue
        for sym in (r.get("symbols") or []):
            sg = guid_for_symbol(str(sym).upper()) if sym else None
            if not sg:
                stats["advisory_symbol_unresolved"] += 1
                continue
            out.append(("advisory", sg, ids, str(ts)))
    return out, dict(stats)


# ── agreement ──────────────────────────────────────────────────────────────

def compute_agreement(reads: Iterable[tuple[str, str, set[str], str]], *, now: datetime,
                      window_hours: float, sources_present: dict[str, bool],
                      extra_stats: Optional[dict[str, int]] = None,
                      notes: Optional[list[str]] = None) -> dict[str, Any]:
    by_subject: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    reads_per_agent = defaultdict(int)
    for agent, sg, ids, _ts in reads:
        by_subject[sg][agent] |= set(ids)
        reads_per_agent[agent] += 1
    subjects = []
    n_multi = n_pair_shared = n_three = 0
    for sg, per_agent in sorted(by_subject.items()):
        agents = sorted(per_agent)
        sets = [per_agent[a] for a in agents]
        shared_all = set.intersection(*sets) if len(sets) >= 2 else set()
        pairwise = {}
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                pairwise[f"{agents[i]}&{agents[j]}"] = len(per_agent[agents[i]] & per_agent[agents[j]])
        row = {
            "subject_guid": sg,
            "agents": agents,
            "ids_by_agent": {a: len(per_agent[a]) for a in agents},
            "pairwise_shared": pairwise,
            "shared_by_all_present": len(shared_all),
            "three_way_shared": len(shared_all) if len(agents) >= 3 else 0,
            "shared_sample": sorted(shared_all)[:5],
        }
        subjects.append(row)
        if len(agents) >= 2:
            n_multi += 1
            if any(v > 0 for v in pairwise.values()):
                n_pair_shared += 1
        if len(agents) >= 3 and shared_all:
            n_three += 1
    agents_present = sorted(a for a in AGENTS if reads_per_agent.get(a))
    if not any(sources_present.values()):
        verdict = "UNAVAILABLE"
    elif n_three > 0:
        verdict = "THREE_WAY_SHARED"
    elif n_pair_shared > 0:
        verdict = "PAIRWISE_SHARED_ONLY"
    elif n_multi > 0:
        verdict = "MULTI_AGENT_NO_SHARED_IDS"
    else:
        verdict = "NO_SUBJECT_READ_BY_MORE_THAN_ONE_AGENT"
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.isoformat(),
        "window": {"hours": window_hours, "start": (now - timedelta(hours=window_hours)).isoformat(),
                   "end": now.isoformat()},
        "sources_present": dict(sources_present),
        "agents_present": agents_present,
        "reads_per_agent": dict(reads_per_agent),
        "subjects_total": len(by_subject),
        "subjects_read_by_2plus_agents": n_multi,
        "subjects_with_pairwise_shared_ids": n_pair_shared,
        "subjects_with_three_way_shared_ids": n_three,
        "verdict": verdict,
        "g8_closure": n_three > 0,
        "subjects": subjects[:200],
        "stats": dict(extra_stats or {}),
        "notes": list(notes or []),
        "memory_behavior_influence": 0,
        "financial_action": False,
    }


def default_guid_for_symbol() -> Callable[[str], Optional[str]]:
    """Identity-registry lookup (never mint); None when the registry is unavailable."""
    try:
        from scripts.lib import identity_registry as reg

        doc = reg.load_cached()

        def _lookup(sym: str) -> Optional[str]:
            ent = reg.lookup_symbol(doc, sym) or {}
            return str(ent.get("subject_guid") or ent.get("security_guid") or "") or None

        return _lookup
    except Exception:  # noqa: BLE001
        return lambda _s: None


def measure(*, wakes_path: Path | str, hermes_requests_path: Path | str,
            retrievals_path: Path | str, guid_for_symbol: Callable[[str], Optional[str]] | None = None,
            now: Optional[datetime] = None, window_hours: float = DEFAULT_WINDOW_HOURS) -> dict[str, Any]:
    """Read the three stores and report agreement for the trailing window. Fail-soft."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(hours=window_hours)
    lookup = guid_for_symbol or default_guid_for_symbol()
    present = {"cio_wakes": Path(wakes_path).is_file(),
               "hermes_requests": Path(hermes_requests_path).is_file(),
               "advisory_retrievals": Path(retrievals_path).is_file()}
    reads: list[tuple[str, str, set[str], str]] = []
    stats: dict[str, int] = {}
    notes = [
        "cio ids = memory_fact_ids loaded by the persistent wake (durable aif_memory store)",
        "hermes ids = prompt_context.memory_context retrievals placed in the research request by CIO plan enrichment; no Hermes process logs its own reads",
        "advisory ids = durable-provider retrievals with the desk's query, attributed to a subject_guid via the identity registry (lookup only)",
        "the shadow measure's own replay rows (non-string query) are excluded",
        "M2 production memory holds versions, not read receipts; it is not a source here",
    ]
    try:
        reads += cio_reads(iter_jsonl(wakes_path), start=start, end=now)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"cio_wakes unreadable: {type(exc).__name__}")
    try:
        reads += hermes_reads(iter_jsonl(hermes_requests_path), start=start, end=now)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"hermes_requests unreadable: {type(exc).__name__}")
    try:
        adv, stats = advisory_reads(iter_jsonl(retrievals_path), start=start, end=now, guid_for_symbol=lookup)
        reads += adv
    except Exception as exc:  # noqa: BLE001
        notes.append(f"advisory_retrievals unreadable: {type(exc).__name__}")
    return compute_agreement(reads, now=now, window_hours=window_hours, sources_present=present,
                             extra_stats=stats, notes=notes)


__all__ = ["SCHEMA", "measure", "compute_agreement", "cio_reads", "hermes_reads", "advisory_reads",
           "iter_jsonl", "default_guid_for_symbol"]
