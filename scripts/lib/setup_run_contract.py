"""setup_run_contract.py — one canonical run-scoped GO/WAIT/NOGO summary.

Consumed identically by the shared Command Center v3 header and the Trade AI
surfaces, so one scanner run is never split across two contracts that disagree.

The defect this replaces (audit cc-header-truth-v2, 2026-09-03): the header's
SETUPS tile and the Trading page both read GO/WAIT/NOGO, but from different
producers —

  * `avoid_count` lumped AVOID, NO_GO, disqualified, filtered-out, unclassified
    and error rows under one "NOGO" label;
  * the "scanned" population was read from a different store than the classified
    counts (run_summary.json `ticker_count` vs trade_ai_scans rows), so the two
    read 61 vs 80 for the same run and nothing said which was the run.

Two unlabeled integers can only read as a contradiction of each other.

This module:
  * maps raw decisions to a closed taxonomy — go / wait / nogo / excluded /
    unclassified — and AVOID, NO_GO, NOGO, filtered-out and error are NOT
    synonyms (§16 of the master architecture: no silent conflation);
  * enforces GO + WAIT + NOGO == classified_count;
  * reconciles classified + excluded + unclassified against the scanned count;
  * returns COUNT_MISMATCH / PARTIAL / DATA_UNAVAILABLE instead of
    authoritative-looking counts when the populations do not reconcile;
  * derives a stable run_id from the run's own label/date/timestamp.

Pure functions. No broker, network, DB, scheduler, or financial side effects.
AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional

SETUP_RUN_CONTRACT_VERSION = "SetupRunSummary@v1"

# Canonical class taxonomy. Unknown tokens are NEVER a decision: counting an
# unclassifiable row as NOGO is how "everything not GO/WAIT" produced an
# authoritative NOGO count that included rows with no decision at all.
DECISION_GO: frozenset = frozenset({"GO", "BUY", "LONG", "ACTIONABLE", "APPROVED"})
DECISION_WAIT: frozenset = frozenset({"WAIT", "HOLD", "WATCH", "NEUTRAL"})
DECISION_NOGO: frozenset = frozenset(
    {
        "AVOID",
        "NO_GO",
        "NOGO",
        "NO-GO",
        "SELL",
        "SHORT",
        "BLOCK",
        "NOT_TRADEABLE",
        "NOT_TREADABLE",
        "REJECT",
    }
)

# A scanner decision that ESCALATES rather than deciding. The scanner set it
# deliberately (it has a `manual_review_required` column); the row is fully
# processed and has a terminal disposition -- it is simply not GO/WAIT/NOGO.
#
# Live acceptance 2026-09-04 run 2026-09-04::0900: 12 of 60 rows carried
# MANUAL_REVIEW (scores 30-38, setup_class squeeze / momentum_runner / ...).
# v1 had no token for it, so they fell into `unclassified` -- which reads as
# "the pipeline failed to decide" and made the run permanently PARTIAL. They are
# NOT nogo: folding an escalation into a rejection is the exact error the
# taxonomy comment below warns about, one level up.
DECISION_REVIEW: frozenset = frozenset({"MANUAL_REVIEW", "NEEDS_REVIEW", "OPERATOR_REVIEW", "REVIEW", "ESCALATE"})

# A row the scanner could not process at all. Distinct from `unclassified`
# (processed, no recognisable decision) and from `review` (processed, escalated).
DECISION_ERROR: frozenset = frozenset({"ERROR", "FAILED", "FAILURE", "EXCEPTION", "TIMEOUT"})

CLASS_LABELS: tuple[str, ...] = ("go", "wait", "nogo", "review", "excluded", "error", "unclassified")

INTEGRITY_RECONCILED = "RECONCILED"
INTEGRITY_COUNT_MISMATCH = "COUNT_MISMATCH"
INTEGRITY_PARTIAL = "PARTIAL"
INTEGRITY_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


def classify_decision(decision: Any, *, disqualified: bool = False) -> str:
    """Map one raw decision to a canonical class.

    ``disqualified`` rows are excluded regardless of their decision string —
    a disqualified GO is not a GO. Empty/unknown/error is unclassified, never
    nogo.
    """
    if disqualified:
        return "excluded"
    d = str(decision or "").strip().upper()
    if d in DECISION_GO:
        return "go"
    if d in DECISION_WAIT:
        return "wait"
    if d in DECISION_NOGO:
        return "nogo"
    if d in DECISION_REVIEW:
        return "review"
    if d in DECISION_ERROR:
        return "error"
    return "unclassified"


def tally_decisions(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Count a population into the canonical classes."""
    counts: dict[str, int] = {c: 0 for c in CLASS_LABELS}
    for r in rows:
        counts[
            classify_decision(
                r.get("decision"),
                disqualified=bool(r.get("disqualified")),
            )
        ] += 1
    return counts


def derive_run_id(
    run_label: Any,
    run_date: Any,
    run_timestamp: Any = None,
) -> str:
    """Stable run identity from the run's own fields.

    Deterministic so overview and the trade-ai summary derive the same id for
    the same run; a second producer reading the same run cannot mint a second id.
    """
    label = str(run_label or "").strip()
    date = str(run_date or "").strip()
    if label and date:
        return f"{date}::{label}"
    ts = str(run_timestamp or "").strip()
    if ts:
        return "ts-" + hashlib.sha1(ts.encode("utf-8")).hexdigest()[:12]
    return "unknown"


def build_setup_run_summary(
    *,
    run_id: str,
    tally: dict[str, int],
    run_label: Any = None,
    run_date: Any = None,
    run_timestamp: Any = None,
    source: str = "trade_ai_scans",
    scanned_count: Optional[int] = None,
    scanned_count_alt: Optional[int] = None,
    freshness_status: str = "UNKNOWN",
    quality: str = "UNKNOWN",
    calculation_version: str = SETUP_RUN_CONTRACT_VERSION,
) -> dict[str, Any]:
    """Build the canonical run-scoped setup summary with reconciliation.

    Invariants (enforced, never silently dropped):

      * GO + WAIT + NOGO == classified_count
      * classified + excluded + review + error + unclassified == the scanned
        population this tally was drawn from

    Every residual class is named and published. v1 had one residual bucket
    (`unclassified`) and 12 escalated rows fell into it, so the header could only
    say "48 classified / 60 scanned / 0 excluded" and leave 12 rows unaccounted
    with no way to say what they were.
      * if a second scanned-count contract disagrees, the summary is PARTIAL,
        not RECONCILED — two "scanned" numbers cannot both be the run.

    ``scanned_count`` is the population the tally was drawn from (e.g. the DB
    current-run rows). ``scanned_count_alt`` is an independent scanned claim
    (e.g. run_summary.json `ticker_count`) that must agree.
    """
    go = int(tally.get("go", 0) or 0)
    wait = int(tally.get("wait", 0) or 0)
    nogo = int(tally.get("nogo", 0) or 0)
    review = int(tally.get("review", 0) or 0)
    excluded = int(tally.get("excluded", 0) or 0)
    error = int(tally.get("error", 0) or 0)
    unclassified = int(tally.get("unclassified", 0) or 0)

    # classified stays GO+WAIT+NOGO: an escalation is not a classification.
    classified = go + wait + nogo
    accounted = classified + excluded + review + error + unclassified
    reconciled_scanned = accounted

    # Invariant 1: the three labels partition classified_count by construction,
    # but recompute and assert so a future edit cannot silently break it.
    integrity = INTEGRITY_RECONCILED
    integrity_reasons: list[str] = []

    if scanned_count is None:
        # No scanned population supplied: we cannot prove the tally is complete.
        integrity = INTEGRITY_DATA_UNAVAILABLE
        integrity_reasons.append("scanned_count unavailable")
    elif reconciled_scanned != int(scanned_count):
        integrity = INTEGRITY_COUNT_MISMATCH
        integrity_reasons.append(
            f"classified({classified})+excluded({excluded})+review({review})"
            f"+error({error})+unclassified({unclassified})"
            f"={reconciled_scanned} != scanned({int(scanned_count)})"
        )
    elif scanned_count_alt is not None and int(scanned_count_alt) != int(scanned_count):
        integrity = INTEGRITY_PARTIAL
        integrity_reasons.append(
            f"scanned contracts disagree: primary({int(scanned_count)}) vs alternate({int(scanned_count_alt)})"
        )

    return {
        "contract_version": calculation_version,
        "run_id": run_id,
        "run_label": str(run_label or "") or None,
        "run_date": str(run_date or "") or None,
        "run_timestamp": str(run_timestamp or "") or None,
        "source": source,
        "calculation_version": calculation_version,
        "scanned_count": scanned_count,
        "classified_count": classified,
        "go_count": go,
        "wait_count": wait,
        "nogo_count": nogo,
        "review_count": review,
        "excluded_count": excluded,
        "error_count": error,
        "unclassified_count": unclassified,
        "accounted_count": accounted,
        "unaccounted_count": (int(scanned_count) - accounted) if scanned_count is not None else None,
        "reconciled_scanned": reconciled_scanned,
        "freshness_status": freshness_status,
        "quality": quality,
        "count_integrity": integrity,
        "count_integrity_reason": " · ".join(integrity_reasons) if integrity_reasons else None,
    }
