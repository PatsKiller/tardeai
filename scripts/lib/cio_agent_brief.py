#!/usr/bin/env python3
"""What the agent actually did today, in the operator's language.

The system completed hundreds of workflows, admitted hundreds of memories and
wrote hundreds of lesson candidates, and the operator saw none of it. Silence and
a stopped system look identical from the outside, which is the failure this whole
programme keeps finding. This is the artifact that tells them apart.

REPORTING ONLY. It changes no decision, no ranking, no position. Every line
carries its provenance class per CLAUDE.md:

    D deterministic · T template · M model-assisted, gated
    A agent-originated · S snapshot-derived

Two rules this module exists to keep:

  * **If nothing changed, say nothing changed.** That sentence is the most
    valuable one in the brief, and a brief that quietly omits an empty section
    reads as a brief with nothing to report.
  * **Never blur research-derived and outcome-derived lessons.** A lesson from a
    research result is a claim about evidence; a lesson from a resolved outcome
    is a claim about what actually happened to money. Today every lesson is the
    former, and saying so is the honest limit of the system's learning.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import collections
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "CIOAgentBrief@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_WINDOW_HOURS = 24.0


def _state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
    except Exception:
        from lib.canonical_store_registry import production_state_root  # type: ignore
    return Path(production_state_root())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _within(value: Any, since: datetime) -> bool:
    d = _ts(value)
    return bool(d and d >= since)


# ── sections ───────────────────────────────────────────────────────────────

def looked_at(rows: list[dict[str, Any]], since: datetime) -> dict[str, Any]:
    """D — research requests raised, by situation type and trigger."""
    raised = [r for r in rows
              if r.get("event") in ("HERMES_RESEARCH_REQUESTED", "HERMES_RESEARCH_ENQUEUE")
              and _within(r.get("ts") or r.get("created_ts"), since)]
    by_situation = collections.Counter(
        str(r.get("situation_type") or "unspecified") for r in raised)
    self_raised = sum(1 for r in raised if str(r.get("reason") or "").startswith("situation.raised"))
    operator_forced = sum(1 for r in raised if r.get("operator_forced") is True)
    return {
        "class": "D",
        "requests_raised": len(raised),
        "self_raised": self_raised,
        "operator_forced": operator_forced,
        "by_situation": dict(by_situation.most_common(6)),
    }


def came_back(rows: list[dict[str, Any]], since: datetime) -> dict[str, Any]:
    """D — completed results and how the critic judged them."""
    done = [r for r in rows if r.get("event") == "HERMES_LOOP_COMPLETED"
            and _within(r.get("ts") or r.get("updated_ts"), since)]
    verdicts = collections.Counter(
        str(r.get("critique_verdict") or "unrecorded") for r in done)
    return {
        "class": "D",
        "completed": len(done),
        "critique_verdicts": dict(verdicts.most_common(5)),
    }


def changed_because(records: list[dict[str, Any]], since: datetime) -> dict[str, Any]:
    """D — named records whose cognition fields moved, with before/after.

    The cognition fields are the four CLAUDE.md permits memory to move. A field
    that did not move is not reported as movement.
    """
    COG = ("next_research_question", "next_eligible_at", "notify_priority", "cc_narrative")
    by_subject: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in records:
        k = str(r.get("subject_key") or "")
        if k:
            by_subject[k].append(r)

    changes: list[dict[str, Any]] = []
    for subject, seq in by_subject.items():
        seq = sorted(seq, key=lambda r: str(r.get("updated_ts") or ""))
        for prev, cur in zip(seq, seq[1:]):
            if not _within(cur.get("updated_ts"), since):
                continue
            for f in COG:
                a, b = prev.get(f), cur.get(f)
                if a == b:
                    continue
                a, b = _substantive(a), _substantive(b)
                if a == b:
                    # Only a timestamp moved inside the value. Reporting that as
                    # "a field changed" is the register problem this brief exists
                    # to avoid: the first live render called 98 fields moved when
                    # nearly all of them were cc_narrative as_of churn.
                    continue
                changes.append({
                    "subject_key": subject,
                    "field": f,
                    "before": _short(_headline(a)),
                    "after": _short(_headline(b)),
                    "at": str(cur.get("updated_ts") or "")[:19],
                })
    return {"class": "D", "changed": len(changes), "changes": changes[:8]}


# Keys whose movement is bookkeeping, not a change the operator should be told
# about. `as_of` moves on every rewrite whether or not anything was decided.
_NOISE_KEYS = {"as_of", "updated_ts", "written_at", "generated_at", "writer"}


def _headline(v: Any) -> Any:
    """The readable part of a value. A whole cc_narrative dict on a phone is
    noise; `what` is the sentence the operator would actually read."""
    if isinstance(v, dict):
        for k in ("what", "statement", "question", "text"):
            if v.get(k):
                return v[k]
        return _substantive(v)
    return v


def _substantive(v: Any) -> Any:
    """The part of a value whose change is worth reporting."""
    if isinstance(v, dict):
        return {k: _substantive(x) for k, x in sorted(v.items())
                if k not in _NOISE_KEYS}
    return v


def _short(v: Any, n: int = 120) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[: n - 1] + "…"
    if isinstance(v, dict):
        return {k: _short(x, 60) for k, x in list(v.items())[:3]}
    return v


def learned(lessons: list[dict[str, Any]], since: datetime) -> dict[str, Any]:
    """D — lesson candidates, provenance stated, never blurred.

    research-derived: a claim about evidence.
    outcome-derived : a claim about what actually happened to money.
    """
    fresh = [r for r in lessons if _within(r.get("created_ts") or r.get("review_at"), since)]

    def split(pool):
        research = [r for r in pool if r.get("hermes_result_id")]
        outcome = [r for r in pool
                   if (r.get("supporting_outcome_ids") or r.get("correlated_outcome_ids"))]
        return len(research), len(outcome)

    w_research, w_outcome = split(fresh)
    t_research, t_outcome = split(lessons)
    stages = collections.Counter(
        str(r.get("promotion_stage") or r.get("status")) for r in lessons)
    return {
        "class": "D",
        # Window and lifetime are reported separately and never conflated. The
        # first draft printed "0 written" beside all-time counts, which reads as
        # 336 lessons written today.
        "written_in_window": len(fresh),
        "window_research_derived": w_research,
        "window_outcome_derived": w_outcome,
        "total": len(lessons),
        "total_research_derived": t_research,
        "total_outcome_derived": t_outcome,
        "stages": dict(stages.most_common(4)),
    }


def acted_on_memory(root: Path) -> dict[str, Any]:
    """D — what the record changed about what the agent did.

    Read from the durable artifact the SCHEDULED dispatcher writes, not
    recomputed here: recomputing would report what the record *would* have
    changed, which is a different claim from what it *did* change on a schedule.
    An absent artifact means the consult is not running, and the brief says so
    rather than printing a zero that looks like "nothing to report".
    """
    p = Path(root) / "data" / "cio" / "wake_record_consult.json"
    if not p.exists():
        return {"state": "NOT_RUNNING", "provenance": "D",
                "note": "no wake_record_consult artifact — the scheduled wake is "
                        "not consulting the record, or has not run since deploy"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"state": "UNREADABLE", "provenance": "D", "note": str(e)}
    return {
        "state": "RUNNING", "provenance": "D",
        "as_of": doc.get("as_of"),
        "unattended": doc.get("unattended"),
        "wakes_considered": doc.get("wakes_considered"),
        "subject_resolved": doc.get("subject_resolved"),
        "decisions_changed_by_record": doc.get("decisions_changed_by_record"),
        "skipped_cadence_not_due": doc.get("skipped_cadence_not_due"),
        "no_subject": doc.get("no_subject"),
        "changed": doc.get("changed") or [],
    }


def could_not_do(root: Path) -> dict[str, Any]:
    """D — lanes starved, domains unstamped, purposes blocked. Not buried."""
    out: dict[str, Any] = {"class": "D", "lanes": [], "unstamped_domains": [],
                           "blocked_purposes": [], "errors": []}
    try:
        from scripts.lib.pipeline_liveness import default_lanes, evaluate
        rep = evaluate(default_lanes())
        out["lanes"] = [
            {"lane": l["lane"], "status": l["status"],
             "produced": l.get("produced"), "attempted": l.get("attempted")}
            for l in rep.lanes if l["status"] != "LIVE"
        ]
    except Exception as e:
        out["errors"].append(f"lanes: {type(e).__name__}")
    try:
        from scripts.lib.cio_domain_registry import CIODomainRegistry, VALID_RUN_PURPOSES
        from scripts.lib.cio_financial_snapshot import build_canonical_snapshot
        d = build_canonical_snapshot()._domains
        out["unstamped_domains"] = sorted(
            k for k, v in d.items() if v.get("freshness_unverified"))
        st = {k: v.get("state") for k, v in d.items()}
        reg = CIODomainRegistry.load()
        BLOCK = {"DATA_UNAVAILABLE", "STALE", "ERROR", "CONFLICTED"}
        out["blocked_purposes"] = sorted(
            p for p in VALID_RUN_PURPOSES
            if any(st.get(r, "DATA_UNAVAILABLE") in BLOCK
                   for r in reg.run_purpose_requirements(p).required_domains))
    except Exception as e:
        out["errors"].append(f"domains: {type(e).__name__}")
    return out


# ── assembly ───────────────────────────────────────────────────────────────

def build_brief(*, window_hours: float = DEFAULT_WINDOW_HOURS,
                root: Path | str | None = None) -> dict[str, Any]:
    r = Path(root) if root else _state_root()
    cio = r / "data" / "cio"
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)

    reqs = _read_jsonl(cio / "hermes_research_requests.jsonl")
    records = _read_jsonl(cio / "cio_instrument_records.jsonl")
    lessons = _read_jsonl(cio / "lesson_candidates.jsonl")

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_action": False,
        "as_of": now.isoformat(),
        "window_hours": window_hours,
        "state_root": str(r),
        "looked_at": looked_at(reqs, since),
        "came_back": came_back(reqs, since),
        "changed_because": changed_because(records, since),
        "learned": learned(lessons, since),
        "acted_on_memory": acted_on_memory(r),
        "could_not_do": could_not_do(r),
    }


def render_telegram(brief: dict[str, Any]) -> str:
    """T — fixed prose around D values. Labelled as such at the foot."""
    L, C = brief["looked_at"], brief["came_back"]
    CH, LE, CN = brief["changed_because"], brief["learned"], brief["could_not_do"]
    AM = brief.get("acted_on_memory") or {}
    lines: list[str] = [
        "*🧠 Agent brief — what I did*",
        f"_{brief['as_of'][:16]}Z · last {brief['window_hours']:g}h · advisory only_",
        "",
    ]

    lines.append(f"*Looked at* — raised {L['requests_raised']} research requests "
                 f"({L['self_raised']} self-raised, {L['operator_forced']} operator-forced)")
    for sit, n in list(L["by_situation"].items())[:4]:
        lines.append(f"  • {sit}: {n}")
    lines.append("")

    v = ", ".join(f"{k} {n}" for k, n in C["critique_verdicts"].items()) or "none"
    lines.append(f"*Came back* — {C['completed']} completed · critic: {v}")
    lines.append("")

    if CH["changed"] == 0:
        lines.append("*Changed because of it* — nothing changed.")
    else:
        lines.append(f"*Changed because of it* — {CH['changed']} field(s) moved")
        for c in CH["changes"][:4]:
            lines.append(f"  • {c['subject_key']} · {c['field']}")
            lines.append(f"      was: {c['before']}")
            lines.append(f"      now: {c['after']}")
    lines.append("")

    # M5 — what memory changed about what the agent DID, not what it read.
    if AM.get("state") == "NOT_RUNNING":
        lines.append("*Acted on memory* — the scheduled wake is not consulting "
                     "the record. This is a fault, not a quiet day.")
    elif AM.get("state") == "UNREADABLE":
        lines.append(f"*Acted on memory* — consult artifact unreadable: "
                     f"{AM.get('note')}")
    else:
        n = AM.get("decisions_changed_by_record") or 0
        lines.append(f"*Acted on memory* — {AM.get('wakes_considered')} wakes, "
                     f"{AM.get('subject_resolved')} with a subject, "
                     f"{n} decision(s) changed by the record")
        for c in (AM.get("changed") or [])[:3]:
            lines.append(f"  • {c.get('subject_key')}: "
                         f"{c.get('without_record')} → {c.get('with_record')}")
        if n == 0:
            lines.append("  • the record changed nothing today — it was read "
                         "and nothing in it applied")
    lines.append("")

    if LE["written_in_window"] == 0:
        lines.append("*Learned* — no new lesson candidate in window.")
    else:
        lines.append(f"*Learned* — {LE['written_in_window']} new lesson candidate(s)"
                     f" · research-derived {LE['window_research_derived']}"
                     f" · outcome-derived {LE['window_outcome_derived']}")
    lines.append(f"  • lifetime: {LE['total']} "
                 f"({LE['total_research_derived']} research-derived, "
                 f"{LE['total_outcome_derived']} outcome-derived)")
    if LE["total_outcome_derived"] == 0:
        lines.append("  • none comes from a resolved outcome — these are claims "
                     "about evidence, not about money")
    lines.append("")

    starved = [l for l in CN["lanes"] if l["status"] != "LIVE"]
    if starved or CN["unstamped_domains"] or CN["blocked_purposes"]:
        lines.append("*Could not do*")
        for l in starved[:3]:
            lines.append(f"  • lane {l['lane']}: {l['status']} "
                         f"({l.get('produced')}/{l.get('attempted')})")
        if CN["unstamped_domains"]:
            lines.append(f"  • {len(CN['unstamped_domains'])} domain(s) never age-checked: "
                         + ", ".join(CN["unstamped_domains"][:4]))
        if CN["blocked_purposes"]:
            lines.append(f"  • {len(CN['blocked_purposes'])} run purpose(s) blocked")
        lines.append("")

    lines.append("_All counts deterministic (class D). Prose is template (class T)._")
    lines.append("_No judgment was exercised in this brief. Advisory only — no orders placed._")
    return "\n".join(lines)
