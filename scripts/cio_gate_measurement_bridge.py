#!/usr/bin/env python3
"""Bridge: feed existing CIO autonomous-run data into the 12-gate measurement framework.

P9 — GATE HONESTY (2026-09-16).

What this script used to do, and why it was wrong
-------------------------------------------------
Six of the twelve gates were **hardcoded literals** with no evidence read at
all (``g6 = 0.0``, ``g7 = 1.0``, ``g8 = 1.0``, ``g9 = 0.0``, ``g11 = True``,
``g12 = 0``), each justified by a prose argument in a comment rather than by a
row in a store.  A seventh, ``operator_usefulness``, reported an automated
Darwin grade average under a gate whose definition is *"Operator-rated
usefulness score"*.  And ``independent_review_coverage`` reused the **score**
count as though it were a **review** count, so it inherited Darwin's coverage
and reported 0.9512 for a population with zero independent reviews.

The result was a board showing 8/12 passing and ``gates_not_measured: 0`` — a
fully-measured, mostly-green agent that had in fact measured almost nothing.

The rule applied here
---------------------
A gate is measured only when a store exists whose rows answer it.  Absence of a
store is ``None`` — ``NOT_YET_MEASURED`` — never a passing value.  "No
violations were recorded" is not "no violations occurred" when nothing records
them; "the rollback tests exit 0" is not evidence (AGENTS.md §0 rule 8).

**The board shows FEWER passing gates after this change. That is the point.**

Unchanged by design: ``PROMOTION_AUTHORITY = "HUMAN_ONLY"`` and
``AUTOMATIC_PROMOTION_PERMITTED = False`` in
``scripts/agent_runtime/maturity_observability.py``.  Nothing here promotes
anything; ``evaluate_gates`` refuses promotion while any gate is unmeasured,
which is now the majority of them.

Run:   python scripts/cio_gate_measurement_bridge.py [--json]
       python scripts/cio_gate_measurement_bridge.py --write-measurements
       python scripts/cio_gate_measurement_bridge.py --update-catalog

Output:  JSON gate measurements on stdout; optionally a measurements file that
         ``evaluate_gates()`` consumes, and optionally the maturity catalog.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No provider call, no broker
call, no schedule. Installing a timer for this script is operator-only (§17).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "AgentGateMeasurement@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

SCHEDULED_ENTRYPOINT = (
    "INSTALLED, active — crontab `35 * * * *`, hourly at :35, from the rebuild "
    "tree with /run/user/$UID/tradeai/env loaded. Armed 2026-09-16 under operator "
    "APPROVE E3 (full package). Lane: goal-gate-bridge."
)

PROJECT_ROOT = Path(os.environ.get(
    "TRADE_AI_PROJECT_ROOT",
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
))

# Default location for the measurements file that ``evaluate_gates()`` reads.
MEASUREMENTS_RELPATH = ("data", "cio", "agent_gate_measurements.json")

# Sentinel returned instead of a number when no store answers a gate. Kept
# distinct from ``None``-as-missing-key so a caller can tell "I looked and there
# is nothing" from "I never looked".
NOT_MEASURED: None = None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").strip().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _action_id(action: Mapping[str, Any]) -> str:
    """The identity a review or score must name to count as covering this action.

    Measured 2026-09-16: 82 of 82 real actions carry ``payload.cio_action_id``
    (``pub-001``, ``pub-5633e578``, ...). The fallbacks exist for older rows.
    """
    payload = action.get("payload") or {}
    return str(
        payload.get("cio_action_id")
        or payload.get("action_id")
        or action.get("event_id")
        or ""
    )


def _real_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Advisory actions only: SUPERSEDED dedup merges and GENESIS are not artifacts."""
    return [
        a for a in actions
        if (a.get("payload") or {}).get("status") != "SUPERSEDED"
        and a.get("event_type") != "CIO_ACTION_LEDGER_GENESIS"
    ]


def _gate(
    measured_value: Any,
    threshold: Any,
    comparator: str,
    *,
    evidence: str,
    unmeasured_reason: str | None = None,
) -> dict[str, Any]:
    """One gate row. ``measured_value=None`` means NOT_YET_MEASURED, never PASS."""
    if measured_value is None:
        return {
            "measured_value": None,
            "threshold": threshold,
            "passing": False,
            "status": "NOT_YET_MEASURED",
            "evidence": evidence,
            "note": unmeasured_reason or "no store answers this gate",
        }
    if comparator == "bool":
        passing = bool(measured_value)
    elif comparator == "min":
        passing = float(measured_value) >= float(threshold)
    elif comparator == "max":
        passing = float(measured_value) <= float(threshold)
    else:                                                        # pragma: no cover
        raise ValueError(f"unknown comparator: {comparator}")
    return {
        "measured_value": measured_value,
        "threshold": threshold,
        "passing": passing,
        "status": "PASS" if passing else "FAIL",
        "evidence": evidence,
        "note": evidence,
    }


def _measure_alex(root: Path | None = None) -> dict[str, Any]:
    """Measure Alex's twelve gates from evidence, or report NOT_YET_MEASURED."""
    root = Path(root or PROJECT_ROOT)
    cio = root / "data" / "cio"
    now = datetime.now(timezone.utc)

    actions = _load_jsonl(cio / "cio_action_ledger.jsonl")
    snapshots = _load_jsonl(cio / "cio_heartbeat_snapshots.jsonl")
    scorecards = _load_jsonl(cio / "darwin_scorecards.jsonl")
    sentinel_reviews = _load_jsonl(cio / "sentinel_reviews.jsonl")
    handoffs = _load_jsonl(cio / "agent_handoff_queue.jsonl")
    challenges = _load_jsonl(cio / "hermes_challenge_queue.jsonl")
    notifications = _load_jsonl(cio / "operator_notification_outbox.jsonl")
    run_traces = _load_jsonl(cio / "agent_run_traces.jsonl")

    real_actions = _real_actions(actions)
    artifact_count = len(real_actions)
    action_ids = {_action_id(a) for a in real_actions if _action_id(a)}
    superseded_count = len([a for a in actions
                            if (a.get("payload") or {}).get("status") == "SUPERSEDED"])

    producer_agent_id = "alex"

    # ── Gate 1: min_artifact_population (≥100) ───────────────────────────
    g1 = _gate(
        artifact_count, 100, "min",
        evidence=(f"{artifact_count} advisory actions in cio_action_ledger.jsonl "
                  f"(SUPERSEDED dedup merges and GENESIS excluded)"),
    )

    # ── Gate 2: retrieval_provenance_completeness (100%) ─────────────────
    with_domains = sum(1 for a in real_actions
                       if (a.get("payload") or {}).get("domains")
                       or (a.get("payload") or {}).get("domain"))
    g2_value = (with_domains / artifact_count) if artifact_count else None
    g2 = _gate(
        round(g2_value, 4) if g2_value is not None else None, 1.0, "min",
        evidence=f"{with_domains}/{artifact_count} actions carry domain provenance",
        unmeasured_reason="no actions in the ledger to measure provenance over",
    )

    # ── Gate 3: independent_review_coverage (100%) ───────────────────────
    # An action is REVIEWED when a review row names that action id AND the
    # reviewer is not the producer. Measured 2026-09-16: the 144 real sentinel
    # rows carry artifact_ids belonging to guardian/ledger/steph artifacts, and
    # the 5 legacy rows that do name alex as producer carry no action id at all,
    # so ZERO Alex actions have an independent review.
    #
    # The previous implementation assigned this gate the Darwin SCORE count, so
    # it reported the scorer's coverage (0.9512) for a population with no
    # reviews. Review and score are separate gates precisely because they are
    # separate acts.
    reviewed_ids: set[str] = set()
    reviews_wrong_population = 0
    reviews_without_action_id = 0
    for r in sentinel_reviews:
        rid = str(r.get("artifact_id") or r.get("action_id") or "")
        reviewer = str(r.get("reviewer_agent_id") or r.get("reviewer") or "")
        reviewed_producer = str(r.get("producer_agent_id") or r.get("agent") or "")
        if not rid:
            reviews_without_action_id += 1
            continue
        if rid not in action_ids:
            reviews_wrong_population += 1
            continue
        if reviewer and reviewer == reviewed_producer:
            continue                       # self-review is not an independent review
        reviewed_ids.add(rid)
    g3_value = (len(reviewed_ids) / artifact_count) if artifact_count else None
    g3 = _gate(
        round(g3_value, 4) if g3_value is not None else None, 1.0, "min",
        evidence=(
            f"{len(reviewed_ids)}/{artifact_count} actions have an independent review. "
            f"{len(sentinel_reviews)} review rows exist but {reviews_wrong_population} "
            f"name artifacts outside Alex's action population and "
            f"{reviews_without_action_id} carry no artifact id at all"
        ),
        unmeasured_reason="no actions in the ledger to measure review coverage over",
    )

    # ── Gate 4: independent_score_coverage (100%) ────────────────────────
    # Independence enforced explicitly: scorer != producer, and scorer !=
    # reviewer (the gap the contracts layer permits and nothing checked here).
    scored_ids: set[str] = set()
    scores_self = 0
    scorer_equals_reviewer = 0
    for sc in scorecards:
        payload = sc.get("payload") or {}
        aid = str(payload.get("action_id") or payload.get("cio_action_id") or "")
        if not aid or aid not in action_ids:
            continue
        scorer = str(sc.get("scorer") or "")
        reviewer = str(sc.get("reviewer") or "")
        if scorer and scorer == producer_agent_id:
            scores_self += 1
            continue
        if scorer and reviewer and scorer == reviewer:
            scorer_equals_reviewer += 1
            continue
        scored_ids.add(aid)
    g4_value = (len(scored_ids) / artifact_count) if artifact_count else None
    g4 = _gate(
        round(g4_value, 4) if g4_value is not None else None, 1.0, "min",
        evidence=(
            f"{len(scored_ids)}/{artifact_count} actions independently scored "
            f"(scorer != producer '{producer_agent_id}', scorer != reviewer). "
            f"refused: {scores_self} self-scored, {scorer_equals_reviewer} scorer==reviewer"
        ),
        unmeasured_reason="no actions in the ledger to measure score coverage over",
    )

    # ── Gate 5: contradiction_rate (≤2%) ─────────────────────────────────
    # A rate needs a denominator. Alex's reviewed population is the set of Alex
    # actions that were actually reviewed — which is empty (gate 3). A rate over
    # reviews of OTHER agents' artifacts is not Alex's contradiction rate, and
    # dividing by "all review rows ever written" is what previously produced a
    # 0.0 PASS from a population this agent does not appear in.
    if reviewed_ids:
        contradictions = 0
        for r in sentinel_reviews:
            rid = str(r.get("artifact_id") or r.get("action_id") or "")
            if rid not in reviewed_ids:
                continue
            raw = r.get("contradictions")
            if isinstance(raw, (int, float)) and raw > 0:
                contradictions += 1
            elif isinstance(raw, (list, tuple)) and raw:
                contradictions += 1
            elif str(r.get("severity") or "").upper() in ("HIGH", "MEDIUM"):
                contradictions += 1
        g5_value = contradictions / len(reviewed_ids)
        g5_evidence = (f"{contradictions}/{len(reviewed_ids)} independently reviewed "
                       f"Alex actions carry a contradiction")
    else:
        g5_value = None
        g5_evidence = "sentinel_reviews.jsonl"
    g5 = _gate(
        round(g5_value, 4) if g5_value is not None else None, 0.02, "max",
        evidence=g5_evidence,
        unmeasured_reason=(
            "zero Alex actions have an independent review (gate 3), so the "
            "denominator is empty — a contradiction rate is not computable"
        ),
    )

    # ── Gate 6: unsupported_claim_rate (0%) ──────────────────────────────
    # WAS HARDCODED 0.0, argued from "the heartbeat is deterministic, so no
    # hallucination is possible". Determinism is an argument about the
    # PRODUCER; this gate measures whether each CLAIM carries retrieval
    # support. No store links a claim to the evidence supporting it, so the
    # rate is unknown — not zero.
    g6 = _gate(
        NOT_MEASURED, 0.0, "max",
        evidence="no claim→evidence-support ledger exists under data/cio",
        unmeasured_reason=(
            "was hardcoded 0.0 on the argument that a deterministic producer "
            "cannot hallucinate. That argues about the producer, not about "
            "claim support. Needs a per-claim retrieval-support store"
        ),
    )

    # ── Gate 7: stale_input_refusal_accuracy (100%) ──────────────────────
    # WAS HARDCODED 1.0, argued from "all data is collected fresh". A refusal
    # ACCURACY needs recorded refusal decisions to score: how many stale inputs
    # were correctly refused, out of how many stale inputs were presented.
    # Nothing records either number.
    g7 = _gate(
        NOT_MEASURED, 1.0, "min",
        evidence="no stale-input refusal receipts exist under data/cio",
        unmeasured_reason=(
            "was hardcoded 1.0 on the argument that inputs are collected fresh. "
            "Freshness of inputs is not accuracy of refusals; needs recorded "
            "refusal decisions with a known-stale control set"
        ),
    )

    # ── Gate 8: deadline_budget_adherence (100%) ─────────────────────────
    # WAS HARDCODED 1.0, citing a single log line ("elapsed_ms": 105). The
    # per-run store that would answer this, agent_run_traces.jsonl, records
    # workflow_metrics in which every field is the literal string "UNMEASURED"
    # (measured 2026-09-16 across 14,758 rows carrying the block).
    unmeasured_metric_rows = 0
    for t in run_traces:
        metrics = t.get("workflow_metrics")
        if isinstance(metrics, dict) and any(
            v == "UNMEASURED" for v in metrics.values()
        ):
            unmeasured_metric_rows += 1
    g8 = _gate(
        NOT_MEASURED, 1.0, "min",
        evidence=(f"agent_run_traces.jsonl: {len(run_traces)} rows, "
                  f"{unmeasured_metric_rows} carry workflow_metrics whose fields "
                  f"are the literal string 'UNMEASURED'"),
        unmeasured_reason=(
            "was hardcoded 1.0 from one log line. The per-run store records no "
            "elapsed, cost, model-call or deadline value to compare to a budget"
        ),
    )

    # ── Gate 9: duplicate_run_rate (0%) ──────────────────────────────────
    # WAS HARDCODED 0.0, argued from "SUPERSEDED merges prove idempotency".
    # SUPERSEDED counts duplicates that WERE caught. This gate measures the
    # ones that were NOT — which by construction nothing has counted.
    g9 = _gate(
        NOT_MEASURED, 0.0, "max",
        evidence=(f"{superseded_count} SUPERSEDED dedup merges recorded; no store "
                  f"records duplicates that escaped deduplication"),
        unmeasured_reason=(
            "was hardcoded 0.0 because caught duplicates were counted. The rate "
            "of UNCAUGHT non-idempotent duplicates is what this gate asks, and "
            "no store answers it"
        ),
    )

    # ── Gate 10: operator_usefulness (≥0.7) ──────────────────────────────
    # NOT previously hardcoded, but dishonest in the same way: it reported an
    # automated Darwin grade average under a gate defined as "Operator-rated
    # usefulness score". An automated proxy is not an operator rating. The
    # proxy is preserved alongside, clearly labelled, so the work is not lost.
    grade_map = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.4}
    grades = [str((sc.get("payload") or {}).get("grade") or "")
              for sc in scorecards
              if (sc.get("payload") or {}).get("grade")]
    darwin_proxy = (
        round(sum(grade_map.get(g, 0.4) for g in grades) / len(grades), 4)
        if grades else None
    )
    g10 = _gate(
        NOT_MEASURED, 0.7, "min",
        evidence="no operator rating store exists under data/cio",
        unmeasured_reason=(
            f"the gate is an OPERATOR rating; the available number is an "
            f"automated Darwin grade proxy ({darwin_proxy} over {len(grades)} "
            f"grades), which is not the operator's judgement"
        ),
    )
    g10["darwin_grade_proxy"] = darwin_proxy
    g10["darwin_grade_count"] = len(grades)

    # ── Gate 11: rollback_test_passed (bool) ─────────────────────────────
    # WAS HARDCODED True, citing "4 rollback tests pass". AGENTS.md §0 rule 8:
    # exit 0 is not evidence. A recorded rollback+replay receipt would be.
    g11 = _gate(
        NOT_MEASURED, True, "bool",
        evidence="no rollback/replay receipt exists under data/cio",
        unmeasured_reason=(
            "was hardcoded True by citing a test file. AGENTS.md §0 rule 8 — "
            "exit 0 is not evidence; needs a recorded rollback + replay receipt"
        ),
    )

    # ── Gate 12: authority_violations (0) ────────────────────────────────
    # WAS HARDCODED 0, argued from "the deny-list makes violations impossible".
    # A control existing is not the same as a control being observed to hold.
    # No violations ledger exists, so zero is unproven rather than true.
    g12 = _gate(
        NOT_MEASURED, 0, "max",
        evidence="no authority-violation ledger exists under data/cio",
        unmeasured_reason=(
            "was hardcoded 0 from the existence of a deny-list. An enforced "
            "control is not an observation; needs a violations ledger, which "
            "may legitimately stay empty once it exists"
        ),
    )

    gates = {
        "min_artifact_population": g1,
        "retrieval_provenance_completeness": g2,
        "independent_review_coverage": g3,
        "independent_score_coverage": g4,
        "contradiction_rate": g5,
        "unsupported_claim_rate": g6,
        "stale_input_refusal_accuracy": g7,
        "deadline_budget_adherence": g8,
        "duplicate_run_rate": g9,
        "operator_usefulness": g10,
        "rollback_test_passed": g11,
        "authority_violations": g12,
    }

    not_measured = [gid for gid, g in gates.items() if g["measured_value"] is None]
    failing = [gid for gid, g in gates.items()
               if g["measured_value"] is not None and not g["passing"]]
    passing = [gid for gid, g in gates.items() if g["passing"]]

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "agent_id": "alex",
        "measured_at": now.isoformat(),
        "root": str(root),
        "evidence_summary": {
            "actions_total": len(actions),
            "actions_real": artifact_count,
            "action_ids_resolvable": len(action_ids),
            "superseded_dedup_merges": superseded_count,
            "snapshots": len(snapshots),
            "darwin_scorecards_total": len(scorecards),
            "sentinel_reviews_total": len(sentinel_reviews),
            "reviews_naming_alex_actions": len(reviewed_ids),
            "reviews_naming_other_populations": reviews_wrong_population,
            "scores_naming_alex_actions": len(scored_ids),
            "agent_run_traces": len(run_traces),
            "handoffs_queued": len(handoffs),
            "hermes_challenges": len(challenges),
            "notifications": len(notifications),
        },
        "gates": gates,
        "summary": {
            "gates_passing": len(passing),
            "gates_total": len(gates),
            "gates_not_measured": len(not_measured),
            "gates_failing": len(failing),
            "not_measured": sorted(not_measured),
            "failing": sorted(failing),
            "promotable": len(passing) == len(gates),
            "promotion_authority": "HUMAN_ONLY",
            "automatic_promotion_permitted": False,
            "blocked_by": [
                f"{gid}: {gates[gid]['note']}" for gid in sorted(not_measured + failing)
            ],
        },
    }


_GATE_ORDER = [
    "min_artifact_population",
    "retrieval_provenance_completeness",
    "independent_review_coverage",
    "independent_score_coverage",
    "contradiction_rate",
    "unsupported_claim_rate",
    "stale_input_refusal_accuracy",
    "deadline_budget_adherence",
    "duplicate_run_rate",
    "operator_usefulness",
    "rollback_test_passed",
    "authority_violations",
]


def measurements_for_evaluate_gates(
    measurements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The mapping ``agent_runtime.agents.evaluate_gates()`` consumes.

    This is the wire that was missing: the bridge computed gate values and no
    caller could feed them to the evaluator, so the read model always used its
    ``measurements=None`` default and every gate reported NOT_YET_MEASURED for
    the wrong reason (nobody asked) rather than the right one (nothing records
    it).  A gate whose value is ``None`` here is omitted, because
    ``evaluate_gates`` treats a missing key and a ``None`` value identically and
    omitting it keeps the contract honest.
    """
    data = measurements or _measure_alex()
    out: dict[str, Any] = {}
    for gate_id, gate in (data.get("gates") or {}).items():
        value = gate.get("measured_value")
        if value is not None:
            out[gate_id] = value
    return out


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _status_label(gate: Mapping[str, Any]) -> str:
    return {
        "NOT_YET_MEASURED": "NOT MEASURED",
        "PASS": "PASS",
        "FAIL": "FAIL",
    }[gate["status"]]


def _format_report(m: dict[str, Any]) -> str:
    gates, summary, ev = m["gates"], m["summary"], m["evidence_summary"]
    lines = [
        "=== CIO 12-Gate Maturity Measurement ===",
        f"Agent:    {m['agent_id']} (Alex - Chief Investment Officer)",
        f"Measured: {m['measured_at']}",
        f"Root:     {m['root']}",
        "",
        "-- Evidence --",
        f"  Real actions:        {ev['actions_real']}  (target >= 100)",
        f"  Dedup merges:        {ev['superseded_dedup_merges']}",
        f"  Snapshots:           {ev['snapshots']}",
        f"  Darwin scorecards:   {ev['darwin_scorecards_total']} "
        f"({ev['scores_naming_alex_actions']} name an Alex action)",
        f"  Sentinel reviews:    {ev['sentinel_reviews_total']} "
        f"({ev['reviews_naming_alex_actions']} name an Alex action, "
        f"{ev['reviews_naming_other_populations']} name another population)",
        f"  Run traces:          {ev['agent_run_traces']}",
        "",
        "-- Gates --",
        f"{'GATE':<42} {'VALUE':<10} {'THRESHOLD':<10} STATUS",
        f"{'----':<42} {'-----':<10} {'---------':<10} ------",
    ]
    for gate_id in _GATE_ORDER:
        g = gates[gate_id]
        lines.append(
            f"{gate_id:<42} {_fmt(g['measured_value']):<10} "
            f"{_fmt(g['threshold']):<10} {_status_label(g)}"
        )
    lines += [
        "",
        "-- Summary --",
        f"  Passing:       {summary['gates_passing']}/{summary['gates_total']}",
        f"  Not measured:  {summary['gates_not_measured']}",
        f"  Failing:       {summary['gates_failing']}",
        f"  Promotable:    {summary['promotable']} "
        f"(authority: {summary['promotion_authority']}, "
        f"automatic: {summary['automatic_promotion_permitted']})",
        "",
        "-- Why each unmeasured gate is unmeasured --",
    ]
    for gate_id in summary["not_measured"]:
        lines.append(f"  * {gate_id}: {gates[gate_id]['note']}")
    if summary["failing"]:
        lines += ["", "-- Measured and failing --"]
        for gate_id in summary["failing"]:
            g = gates[gate_id]
            lines.append(f"  * {gate_id}: {_fmt(g['measured_value'])} "
                         f"vs {_fmt(g['threshold'])} - {g['evidence']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", default="alex", help="Agent ID to measure")
    parser.add_argument("--root", default=None,
                        help="Repo root holding data/cio (default: TRADE_AI_PROJECT_ROOT)")
    parser.add_argument("--json", action="store_true", help="JSON instead of a report")
    parser.add_argument("--write-measurements", nargs="?", const="", default=None,
                        metavar="PATH",
                        help="Write the evaluate_gates() measurements file "
                             "(default: data/cio/agent_gate_measurements.json)")
    parser.add_argument("--update-catalog", action="store_true",
                        help="Write gate measurements into config/agent_maturity_catalog.json")
    args = parser.parse_args(argv)

    if args.agent != "alex":
        print(f"Only 'alex' is supported currently (got: {args.agent})", file=sys.stderr)
        return 1

    root = Path(args.root) if args.root else PROJECT_ROOT
    measurements = _measure_alex(root)

    if args.json:
        print(json.dumps(measurements, indent=2, default=str))
    else:
        print(_format_report(measurements))

    if args.write_measurements is not None:
        path = (Path(args.write_measurements) if args.write_measurements
                else root.joinpath(*MEASUREMENTS_RELPATH))
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "measured_at": measurements["measured_at"],
            "agents": {
                "alex": {
                    "measurements": measurements_for_evaluate_gates(measurements),
                    "not_measured": measurements["summary"]["not_measured"],
                    "gates": measurements["gates"],
                }
            },
        }
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"\nWrote measurements -> {path}")

    if args.update_catalog:
        catalog_path = root / "config" / "agent_maturity_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        agent = (catalog.get("agents") or {}).get("alex")
        if agent is None:
            print("alex missing from catalog; nothing written", file=sys.stderr)
            return 1
        summary = measurements["summary"]
        # The catalog previously contained ZERO occurrences of any gate id, so
        # the board could not name what it was waiting for. Every gate is
        # written, including the unmeasured ones and why.
        agent["maturity_gates"] = {
            "schema": SCHEMA,
            "measured_at": measurements["measured_at"],
            "promotion_authority": "HUMAN_ONLY",
            "automatic_promotion_permitted": False,
            "gates": {
                gate_id: {
                    "measured_value": g["measured_value"],
                    "threshold": g["threshold"],
                    "status": g["status"],
                    "evidence": g["evidence"],
                    "note": g["note"],
                }
                for gate_id, g in measurements["gates"].items()
            },
        }
        # No gate COUNT goes into catalog prose: a committed count goes stale the
        # hour after it is written ("11/12 gates passing" survived from 08-09 to
        # 09-25 while the board said 0/12). monitoring.record_from_mapping now
        # refuses such text; the count is read at render time from the
        # measurement store by scripts/agent_runtime/gate_status.py.
        agent["current_limitations"] = [
            "Gate status is NOT stored in this catalog: read it at render time from "
            "data/cio/agent_gate_measurements.json (AgentGateMeasurement@v1)",
            *(f"{gid}: {measurements['gates'][gid]['note']}"
              for gid in summary["not_measured"]),
        ]
        catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
        print(f"\nUpdated {catalog_path} - {summary['gates_passing']}/12 passing, "
              f"{summary['gates_not_measured']} not measured")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
