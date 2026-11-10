"""ANCHOR: STATUS_CONSISTENCY_LQ1803_20261110 — one document may not say two different things about one run's health.

LQ-20261107-1803 (operator, 2026-11-10, P0 SEV-1). ``data/runtime/source-litmus-vs-yahoo_last.json`` finished
2026-11-10T12:46:37Z carrying ``status: ok``, ``outcome: ok``, ``exit: 1`` and ``summary.verdict: BLOCK`` at once.
The Jobs page reads ``status``/``ok_at``, not the verdict, so a BLOCK rendered as healthy — a silent failure.

The operator's addendum (20261110T1725Z) makes the rule general: for EVERY ``runtime/*_last.json`` /
health-producing writer, ``verdict``, ``status``, ``outcome``, ``health`` and the display state must agree, and a
contradictory combination is **downgraded to the worse state (never upgraded) and logged**.

This module is the single place that decides what "the worse state" is:

* every health field is mapped to a rank — ``ok < unknown < warn < blocked < failed``;
* the document's ``status`` is the run's own health line, so it may never rank below a ``warn``/``blocked``/
  ``failed`` claim the same document makes;
* ``outcome`` may not claim ``ok`` for a run the status calls ``degraded``/``blocked``/``failed`` (it takes that
  field's word: ``degraded`` / ``blocked`` / ``error``);
* a non-zero exit code is a failure claim too — except where a **blocking verdict explains it** (source-litmus
  exits 1 by design to tell systemd the run found BLOCK, ``SuccessExitStatus=0 1``; the verdict, not the exit
  code, is the cause, so the state is ``blocked``, not ``failed``);
* the worse rank is written as the canonical word ``degraded`` / ``blocked`` / ``failed``, the fields that
  disagree are recorded in an additive ``status_consistency`` block, and one line goes to stderr.

Deliberately out of scope (and why):

* ``summary.status`` is NOT read. Since 2026-11-06 (``tests/test_receipt_honesty_20261106.py``) a *subject*
  status lives under ``subject_status`` and must not grade the run; ``summary.verdict`` IS read because it
  states a verdict, which is one of the five fields the operator named.
* an ``unknown`` claim (``unverified`` / ``pending`` / ``not_measured``) is reported but never rewrites a status:
  it is a claim of ignorance, not a health claim, and rewriting 300 receipts to say "unknown" is not a fix.
* a word outside the vocabulary gets no opinion (``None``): an unknown word must never invent a downgrade.
  Unknown beats wrong; a reported gap beats a wrong rewrite.
* ``exit`` is only ever used to *lower* a status, never to raise one.

``reconcile`` is pure: it returns ``(doc, contradictions)`` and never touches disk. The writer
(``scripts/lib/lane_last_receipt.build_receipt``) calls it before writing; ``scripts/sweep_status_contradictions.py``
calls ``scan`` over the live runtime directory and reports, read-only.

MBI_BEHAVIOR = 0. No broker, no send, no DB. Stdlib only.
"""
from __future__ import annotations

import sys
from typing import Any, Mapping

SCHEMA = "StatusConsistency@v1"

OK, UNKNOWN, WARN, BLOCKED, FAILED = "ok", "unknown", "warn", "blocked", "failed"
RANK = {OK: 0, UNKNOWN: 1, WARN: 2, BLOCKED: 3, FAILED: 4}
#: The word written when a rank wins the reconciliation. ``degraded`` is the Jobs page's own adjective for work
#: that was written but is not healthy; ``blocked`` keeps source-litmus's word (the check ran, the subject is not
#: fit for use); ``failed`` is the run itself.
CANONICAL = {WARN: "degraded", BLOCKED: "blocked", FAILED: "failed"}
#: The word ``outcome`` takes when a rank wins. ``outcome`` keeps the receipt contract's own four words plus the one
#: this ticket adds (``ok``/``empty``/``error``/``blocked``/``degraded``): a failed run stays ``error``, as every
#: existing receipt writes it.
OUTCOME_WORD = {WARN: "degraded", BLOCKED: "blocked", FAILED: "error"}
#: The minimum rank a claim needs before it may rewrite a status (see the module docstring).
DOWNGRADING = (WARN, BLOCKED, FAILED)

#: Word -> rank. One table: the same adjective means the same thing whichever field carries it. A word absent
#: here returns ``None`` (no opinion).
WORDS = {
    # ok
    "ok": OK, "okay": OK, "pass": OK, "passed": OK, "success": OK, "succeeded": OK, "done": OK,
    "complete": OK, "completed": OK, "reconciled": OK, "stored": OK, "healthy": OK, "green": OK,
    "clear": OK, "nominal": OK, "fine": OK, "live": OK, "no_action": OK, "not_needed": OK, "run_done": OK,
    # unknown: a claim of ignorance, not of health
    "unknown": UNKNOWN, "unmeasured": UNKNOWN, "not_measured": UNKNOWN, "unverified": UNKNOWN,
    "not_evaluated": UNKNOWN, "pending": UNKNOWN, "unavailable": UNKNOWN,
    # warn
    "warn": WARN, "warning": WARN, "degraded": WARN, "partial": WARN, "drift": WARN, "stale": WARN,
    "rate_limited": WARN, "throttled": WARN, "retrying": WARN, "flaky": WARN,
    # blocked: the run did its job and the thing it guards is not fit for use
    "block": BLOCKED, "blocked": BLOCKED,
    # failed
    "fail": FAILED, "failed": FAILED, "error": FAILED, "errored": FAILED, "critical": FAILED,
    "unhealthy": FAILED, "red": FAILED, "breach": FAILED, "breached": FAILED, "crashed": FAILED,
    "crash": FAILED, "timeout": FAILED, "timed_out": FAILED, "run_failed": FAILED, "dead": FAILED,
    "down": FAILED, "refused": FAILED,
}

#: Top-level fields that state the document's health. ``state`` is read only for the n8n executor's RUN_*
#: lifecycle words, never for a business ``state`` such as ``summary.state: completed``.
FIELDS = ("status", "outcome", "verdict", "health", "overall_status", "display", "display_state")
RUN_STATES = {"RUN_DONE": OK, "RUN_FAILED": FAILED, "RUN_TIMEOUT": FAILED, "RUN_REFUSED": FAILED,
              "RUN_SKIPPED_LOCK": WARN}
#: ``summary`` keys that state a verdict. ``subject_status`` is NOT here: it is a subject outcome by contract.
SUMMARY_VERDICT_KEYS = ("verdict",)
#: Exit codes that do not, by themselves, claim success. 75 = EX_TEMPFAIL (a lock-busy skip): the run did not
#: run, so it cannot be "ok", but it is not a failure either.
EXIT_CODES = {0: None, 75: WARN}


def _rank(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    word = value.strip().lower().replace("-", "_")
    return WORDS.get(word) if word else None


def _exit_rank(doc: Mapping[str, Any]) -> str | None:
    code = doc.get("exit", doc.get("exit_code"))
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return EXIT_CODES.get(code, FAILED)


def claims(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every health claim the document makes, worst first. ``[]`` when it makes none."""
    out: list[dict[str, Any]] = []

    def add(field: str, value: Any, rank: str | None) -> None:
        if rank is not None:
            out.append({"field": field, "value": value, "rank": rank})

    for field in FIELDS:
        value = doc.get(field)
        if isinstance(value, Mapping):
            # a structured verdict block (active-trader's motion verdict) states its band/status inside
            inner = value.get("status", value.get("band"))
            add(f"{field}.status", inner, _rank(inner))
            continue
        add(field, value, _rank(value))
    state = doc.get("state")
    if isinstance(state, str) and state.strip().upper() in RUN_STATES:
        add("state", state, RUN_STATES[state.strip().upper()])
    summary = doc.get("summary")
    if isinstance(summary, Mapping):
        for key in SUMMARY_VERDICT_KEYS:
            value = summary.get(key)
            if isinstance(value, str):
                add(f"summary.{key}", value, _rank(value))
    return sorted(out, key=lambda c: RANK[c["rank"]], reverse=True)


def scan(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only: what the document claims, what contradicts its ``status``/``outcome``, and what ``reconcile``
    would write. Never mutates ``doc``."""
    found = claims(doc)
    status = doc.get("status")
    status_rank = _rank(status)
    worst = found[0]["rank"] if found else None
    exit_rank = _exit_rank(doc)
    if exit_rank is not None:
        # A blocking verdict explains a non-zero exit: the lane exits non-zero *because* the verdict is BLOCK.
        if any(c["rank"] == BLOCKED for c in found):
            exit_rank = BLOCKED if RANK[exit_rank] > RANK[BLOCKED] else exit_rank
        if worst is None or RANK[exit_rank] > RANK[worst]:
            worst = exit_rank
    proposed_status, proposed_outcome = status, doc.get("outcome")
    downgrade: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []
    if worst is not None and status_rank is not None and RANK[worst] > RANK[status_rank]:
        offenders = [c for c in found if RANK[c["rank"]] > RANK[status_rank]]
        if exit_rank is not None and RANK[exit_rank] > RANK[status_rank]:
            offenders.append({"field": "exit", "value": doc.get("exit", doc.get("exit_code")), "rank": exit_rank})
        if worst in CANONICAL:
            proposed_status = CANONICAL[worst]
            downgrade = offenders
        else:  # an unknown claim is reported, never rewritten
            advisories = offenders
    elif worst is not None and status_rank is None and RANK[worst] > RANK[OK]:
        # A document that makes a warn/blocked/failed claim but states no ``status`` at all: nothing to reconcile
        # against, and inventing a status for a file we do not know is a run receipt would be an upgrade. Reported.
        advisories = [c for c in found if RANK[c["rank"]] > RANK[OK]]
        if exit_rank is not None and RANK[exit_rank] > RANK[OK]:
            advisories.append({"field": "exit", "value": doc.get("exit", doc.get("exit_code")), "rank": exit_rank})
    # ``outcome`` states what the run's output was. It is rewritten whenever the worse claim is a health claim
    # (degraded/blocked/failed), because "outcome: ok" beside any of those is the same silent-failure claim as
    # "status: ok". Never raised, only lowered.
    if downgrade and downgrade[0]["rank"] in (WARN, BLOCKED, FAILED):
        want = downgrade[0]["rank"]
        rank_out = _rank(proposed_outcome)
        if rank_out is None or RANK[rank_out] < RANK[want]:
            proposed_outcome = OUTCOME_WORD[want]
            if not any(c["field"] == "outcome" for c in downgrade):
                downgrade.append({"field": "outcome", "value": doc.get("outcome"), "rank": want})
    return {
        "schema": SCHEMA,
        "status": status, "status_rank": status_rank,
        "outcome": doc.get("outcome"), "outcome_rank": _rank(proposed_outcome),
        "claims": found, "worst_rank": worst,
        "contradictions": downgrade, "advisories": advisories,
        "proposed_status": proposed_status, "proposed_outcome": proposed_outcome,
        "consistent": not downgrade and proposed_status == status and proposed_outcome == doc.get("outcome"),
    }


def consistent(doc: Mapping[str, Any]) -> bool:
    """True when the document's fields agree (nothing to downgrade)."""
    return bool(scan(doc)["consistent"])


def reconcile(doc: Mapping[str, Any], *, lane_id: str | None = None, log: bool = True) -> tuple[dict, list[dict]]:
    """Return ``(doc, contradictions)`` with a contradictory ``status``/``outcome`` downgraded to the worse rank.

    Downgrade only: a claim may lower the status and never raise it, and the source fields are never rewritten —
    the verdict is the evidence the run produced. When something was downgraded the document carries an additive
    ``status_consistency`` block naming the fields that disagreed, and one line goes to stderr.
    """
    result = scan(doc)
    out = dict(doc)
    if not result["contradictions"]:
        return out, []
    out["status"] = result["proposed_status"]
    out["outcome"] = result["proposed_outcome"]
    out["status_consistency"] = {
        "schema": SCHEMA,
        "downgraded": True,
        "from": result["status"],
        "to": result["proposed_status"],
        "fields": [{k: c[k] for k in ("field", "value", "rank")} for c in result["contradictions"]],
    }
    if log:
        name = lane_id or str(doc.get("lane_id") or doc.get("script") or "receipt")
        detail = ", ".join(f"{c['field']}={c['value']!r} ({c['rank']})" for c in result["contradictions"])
        print(f"[{name}] status_consistency: status {result['status']!r} -> {result['proposed_status']!r} "
              f"— worse claim wins: {detail}", file=sys.stderr)
    return out, result["contradictions"]
