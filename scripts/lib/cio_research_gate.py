"""ResearchNeedDecision@v2 — routing gate: free-first, residual, then paid.

`research_need_decision.py` (v1) answers *how much* research a symbol needs
(NO_RESEARCH_NEEDED / REFRESH / TARGETED / DEEP). It is unchanged and still
used by closed_loop_maturity and symbol_thesis_research.

This module answers the different question: *what should actually run now*, if
anything. It routes to one of seven outcomes and is the only place that may
authorise a paid call.

    skip | reuse | corpus_hit | flash | pro | openai | grok_critique

Law, in order:

    not material                  -> skip
    cost cap hit                  -> skip until next_eligible_at (NOT a bug)
    prior execution_language      -> skip, fail closed, no next paid gate
    cadence not due               -> skip
    VALID on-disk row inside TTL  -> reuse
    corpus closes the dimension   -> corpus_hit          (no model call)
    unresolved paid artifact      -> grok_critique       (before any attach)
    flash PARTIAL/truncated       -> pro                 (same research_id)
    pro unresolved + material     -> openai
    otherwise                     -> flash

Deterministic. No network, no model call, no clock beyond `now`. The worker
decides nothing; it executes what this returns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

GATE_VERSION = "ResearchNeedDecision@v2"
AUTHORITY = "READ_ONLY_ADVISORY"
FINANCIAL_ACTION = False

DECISIONS = (
    "skip", "reuse", "corpus_hit", "flash", "pro", "openai", "grok_critique",
)
PAID_DECISIONS = frozenset({"flash", "pro", "openai", "grok_critique"})

# Outcome classes carried forward from the previous attempt on a research_id.
OUTCOMES = (
    "VALID", "PARTIAL", "FAIL", "execution_language", "truncated",
    "cost_cap", "stale",
)

# Cadence TTLs in hours. Documented and overridable via `ttl_overrides` so the
# operator can retune without a code change.
TTL_HOURS: dict[str, int] = {
    "held_core_thesis": 24 * 7,      # 7d unless a material event fires
    "new_position_if": 24 * 7,       # 7d or first-seen
    "watch_block": 0,                # never — watch BLOCK gets no LLM at all
    "s6_concentration": 0,           # threshold cross / defer expiry only
    "earnings_calendar": 0,          # event-driven, see EARNINGS_EVENT_DAYS
    "corpus_refresh": 24 * 7,        # weekly max
    "default": 24 * 3,
}
EARNINGS_EVENT_DAYS = 5

# Job kinds that may never reach a model, whatever else is true.
NO_LLM_KINDS = frozenset({"watch_block"})


def _utc(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def ttl_for(kind: str, overrides: Optional[dict[str, int]] = None) -> int:
    table = dict(TTL_HOURS)
    table.update(overrides or {})
    return int(table.get(kind, table["default"]))


def _decision(name: str, reason: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema": GATE_VERSION,
        "decision": name,
        "reason": reason,
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "free_sources_tried": [],
        "prior_artifact_ids": [],
        "prior_outcome": None,
        "next_eligible_at": None,
        "research_id": None,
        "workflow_id": None,
    }
    out.update(extra)
    return out


def _source_index_verdict(inp: dict[str, Any],
                          now: datetime) -> Optional[str]:
    """Delegate the freshness/unchanged axis to the gate that already owns it.

    `research_source_index.decide()` is the existing source-hash skip gate
    (SKIP_FRESH / SKIP_UNCHANGED / RESEARCH_TRIGGERED / RESEARCH_EXECUTED) with
    its own class SLAs in `freshness_days_for`. This module deliberately does
    NOT re-implement that: two freshness laws over one question drift apart, and
    the drift is invisible until someone diffs them by hand.

    Returns its verdict string, or None when the caller supplied no source_id
    (then the local TTL table applies as a fallback).
    """
    source_id = inp.get("source_id")
    if not source_id:
        return None
    try:
        from scripts.lib.research_source_index import decide as _sdecide
    except Exception:
        return None
    try:
        return _sdecide(
            str(source_id),
            str(inp.get("content_hash") or ""),
            triggered=bool(inp.get("event_fired")),
            now=now,
            root=inp.get("root"),
        )
    except Exception:
        return None


def _librarian_filter(corpus: dict[str, Any], now: datetime,
                      root: Any = None) -> dict[str, Any]:
    """Apply SourceLibrarian@v1 shelf life to a corpus verdict, fail-open.

    Fail-open on purpose: if the librarian cannot be consulted, the corpus
    keeps whatever verdict it already had. A staleness gate that fails CLOSED
    would silently route every corpus_hit to a paid call the moment its store
    was unreadable — the exact failure mode this ladder exists to prevent.
    """
    if not corpus:
        return corpus
    try:
        from scripts.lib.cio_research_librarian import filter_corpus
    except Exception:                                            # noqa: BLE001
        return corpus
    try:
        return filter_corpus(corpus, now=now,
                             root=Path(root) if root else None)
    except Exception:                                            # noqa: BLE001
        return corpus


def _has_execution_language(text: Any) -> bool:
    """Reuse the one shared imperative matcher. Never a second word list."""
    if not text:
        return False
    try:
        from scripts.lib.execution_language import find_imperative
    except Exception:
        return False
    if find_imperative is None:
        return False
    try:
        return bool(find_imperative(text))
    except Exception:
        return False


def decide(inp: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Route one research job. See module docstring for the ordering."""
    now = _utc(now)
    kind = str(inp.get("kind") or "default")
    research_id = inp.get("research_id")
    workflow_id = inp.get("workflow_id")
    plan_id = inp.get("plan_id")
    symbol = str(inp.get("symbol") or inp.get("entity") or "").upper() or None
    ttl_over = inp.get("ttl_overrides") or {}
    base = {"research_id": research_id, "workflow_id": workflow_id,
            "plan_id": plan_id, "symbol": symbol, "kind": kind,
            "as_of": now.isoformat()}

    prior_outcome = inp.get("prior_outcome")
    prior_ids = list(inp.get("prior_artifact_ids") or [])
    tried: list[str] = []

    # --- watch BLOCK and other no-LLM kinds ------------------------------
    if kind in NO_LLM_KINDS:
        return _decision("skip", "kind_never_uses_llm", **base,
                         prior_outcome=prior_outcome)

    # --- materiality ------------------------------------------------------
    if not bool(inp.get("material")):
        return _decision("skip", "not_material", **base,
                         prior_outcome=prior_outcome)

    # --- cost cap: a budget stop, not a failure ---------------------------
    # Recorded as its own reason so a capped day never reads as a broken
    # worker in the counters.
    if bool(inp.get("cost_cap_hit")):
        return _decision("skip", "cost_cap", **base,
                         prior_outcome="cost_cap",
                         next_eligible_at=(inp.get("cost_cap_resets_at")
                                           or (now + timedelta(days=1)).isoformat()))

    # --- execution language: fail closed ---------------------------------
    # A prior artifact that told the operator to do something does not get a
    # retry at a more expensive gate. It stops here.
    if prior_outcome == "execution_language" or _has_execution_language(
            inp.get("prior_text")):
        return _decision("skip", "execution_language_fail_closed", **base,
                         prior_outcome="execution_language",
                         prior_artifact_ids=prior_ids,
                         next_eligible_at=None)

    # --- cadence ----------------------------------------------------------
    nxt = _parse(inp.get("next_eligible_at"))
    if nxt and now < nxt:
        return _decision("skip", "cadence_not_due", **base,
                         prior_outcome=prior_outcome,
                         next_eligible_at=nxt.isoformat())

    ttl_h = ttl_for(kind, ttl_over)
    event_forced = bool(inp.get("event_fired"))
    days_to_event = inp.get("days_to_event")
    if days_to_event is not None and int(days_to_event) <= EARNINGS_EVENT_DAYS:
        event_forced = True

    # Event-driven kinds (ttl 0) are only eligible when their event fires.
    if ttl_h == 0 and not event_forced:
        return _decision("skip", "event_driven_kind_no_event", **base,
                         prior_outcome=prior_outcome)

    # --- reuse: defer to the source-hash gate when the caller has a source --
    verdict = _source_index_verdict(inp, now)
    if verdict in {"SKIP_UNCHANGED", "SKIP_FRESH"} and not event_forced:
        tried.append("research_source_index")
        return _decision("reuse", "source_index_" + verdict.lower(), **base,
                         free_sources_tried=tried,
                         prior_artifact_ids=prior_ids,
                         prior_outcome="VALID",
                         source_index_verdict=verdict)

    # --- reuse: a VALID row inside TTL (fallback when no source_id) --------
    last_ok = _parse(inp.get("last_valid_at"))
    if last_ok and not event_forced and ttl_h > 0:
        age_h = (now - last_ok).total_seconds() / 3600.0
        if age_h < ttl_h:
            tried.append("hermes_research_results")
            return _decision("reuse", "valid_on_disk_within_ttl", **base,
                             free_sources_tried=tried,
                             prior_artifact_ids=prior_ids,
                             prior_outcome="VALID",
                             next_eligible_at=(last_ok + timedelta(hours=ttl_h)).isoformat())

    # --- corpus: free before paid ----------------------------------------
    # Wave 3A: a stale-or-changed source must not be closed by the corpus.
    # `RESEARCH_EXECUTED` means the source hash moved or its SLA lapsed — the
    # entity-level facts changed, and an entity-agnostic almanac fact cannot
    # speak to that. Closing it here would let new information be answered with
    # old context and skip the research that would have caught it.
    corpus = inp.get("corpus") or {}
    if verdict == "RESEARCH_EXECUTED" and corpus.get("closes"):
        tried.append("corpus_index")
        corpus = dict(corpus)
        corpus["closes"] = False
        corpus["reason"] = "source_index_stale_corpus_may_not_close"
    # Slice D: a graded source has a shelf life. SourceLibrarian@v1 drops any
    # source_ref whose grade-derived `stale_after_days` has lapsed, and
    # un-closes the corpus when nothing eligible survives. It has an opinion
    # ONLY about sources carrying a grade and a last_seen, so an ungraded
    # corpus behaves exactly as it did before.
    corpus = _librarian_filter(corpus, now, inp.get("root"))
    if corpus.get("closes"):
        tried.append("corpus_index")
        return _decision("corpus_hit", corpus.get("reason") or "corpus_closed_gap",
                         **base,
                         free_sources_tried=tried,
                         source_refs=corpus.get("source_refs") or [],
                         max_influence_pct=corpus.get("max_influence_pct"),
                         standalone_sell=False,
                         creates_trim=False,
                         prior_outcome=prior_outcome,
                         next_eligible_at=(now + timedelta(hours=ttl_h or 168)).isoformat())
    if corpus:
        tried.append("corpus_index")

    # --- critique gate: any paid artifact is critiqued before attach ------
    if inp.get("unreviewed_paid_artifact"):
        return _decision("grok_critique", "paid_artifact_needs_critique_before_attach",
                         **base,
                         free_sources_tried=tried,
                         prior_artifact_ids=prior_ids,
                         prior_outcome=prior_outcome)

    # --- escalation ladder ------------------------------------------------
    if prior_outcome in {"PARTIAL", "truncated"}:
        return _decision("pro", "flash_partial_escalates_to_pro", **base,
                         free_sources_tried=tried,
                         prior_artifact_ids=prior_ids,
                         prior_outcome=prior_outcome)

    if prior_outcome == "FAIL" and inp.get("pro_attempted"):
        return _decision("openai", "pro_unresolved_and_material", **base,
                         free_sources_tried=tried,
                         prior_artifact_ids=prior_ids,
                         prior_outcome=prior_outcome)

    if prior_outcome == "VALID":
        # Fresh VALID that fell outside TTL and has no critique yet.
        if not inp.get("critique_verdict"):
            return _decision("grok_critique", "valid_artifact_awaiting_critique",
                             **base, free_sources_tried=tried,
                             prior_artifact_ids=prior_ids,
                             prior_outcome="VALID")

    return _decision("flash", "free_sources_exhausted_first_pass", **base,
                     free_sources_tried=tried,
                     prior_artifact_ids=prior_ids,
                     prior_outcome=prior_outcome,
                     next_eligible_at=(now + timedelta(hours=ttl_h or 168)).isoformat())


def schedule_surface(decisions: list[dict[str, Any]], *, cap: int = 10,
                     now: Optional[datetime] = None) -> dict[str, Any]:
    """Read-only ops block: what is queued, and what was skipped and why.

    Ops, not notify. Nothing here is sent anywhere; it exists so a quiet day is
    legible as a quiet day rather than as a broken worker.
    """
    now = _utc(now)
    eligible = [d for d in decisions if d.get("decision") in PAID_DECISIONS]
    eligible.sort(key=lambda d: str(d.get("next_eligible_at") or ""))
    skipped: dict[str, int] = {}
    for d in decisions:
        if d.get("decision") == "skip":
            r = str(d.get("reason") or "unknown")
            skipped[r] = skipped.get(r, 0) + 1
    by_decision: dict[str, int] = {}
    for d in decisions:
        k = str(d.get("decision"))
        by_decision[k] = by_decision.get(k, 0) + 1
    return {
        "schema": "ResearchScheduleSurface@v1",
        "as_of": now.isoformat(),
        "authority": AUTHORITY,
        "financial_action": False,
        "considered": len(decisions),
        "next_eligible": [
            {"symbol": d.get("symbol"), "plan_id": d.get("plan_id"),
             "decision": d.get("decision"), "reason": d.get("reason"),
             "kind": d.get("kind"),
             "skip_reason": (d.get("reason") if d.get("decision") == "skip"
                             else None),
             "next_eligible_at": d.get("next_eligible_at")}
            for d in eligible[:cap]
        ],
        # Wave 3B ops block: what was skipped and why, capped alongside the
        # eligible list. Ops only — a test asserts this block is never routed
        # to Telegram.
        "skipped_sample": [
            {"symbol": d.get("symbol"), "plan_id": d.get("plan_id"),
             "skip_reason": d.get("reason"), "kind": d.get("kind")}
            for d in decisions if d.get("decision") == "skip"
        ][:cap],
        "next_eligible_total": len(eligible),
        "skipped_by_reason": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
        "by_decision": by_decision,
        "note": ("claimed=0 is healthy when nothing is eligible; a peek that "
                 "finds no work is not a failed run."),
    }
