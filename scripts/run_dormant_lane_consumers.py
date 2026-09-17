#!/usr/bin/env python3
"""P10 — give the built-but-unwired lanes a production caller.

The recurring defect in this repository is building a correct thing and never
wiring the caller. Each artifact passes its own tests, so nothing reports a
problem, and the module sits dark for months. `check_dark_contracts.py` catches
the *schema* version of this; it explicitly does not catch the transitive form
("a module whose only consumer is itself dark"), and that is where these lanes
were hiding.

This script is the caller. It reaches each dormant symbol from ONE production
entrypoint so the code is no longer dark, and it does so **advisory-only**:

    CriticPanel / reconcile_critics   tier-0 deterministic reconciliation, no
                                      provider configured, $0, never voted
    sentinel.inspect_ticket           deterministic kernel over a real ticket
    MvlRuntime.resume                 reachable; only acts with --resume-run-id
    close_goal                        proposes closures; only acts with --apply
    commitment_outcome_sweep          invoked through its own entrypoint module
    hermes_challenge_queue.resolve    reachable; only acts with --apply
    research_contradiction            the reader 31,762 candidates never had
    data_gap_registry                 already live (cron + api_v2 + health_agent)
    evidence_refresh_job              already live (free-first circulation timer)
    run_tiered_validation_gate        the P6 sibling that was never armed; tier 0,
                                      no provider, $0 (added 2026-09-17)

Two of the ten turn out to be ALREADY WIRED. They are reported as such rather
than wired twice -- a second caller for a live lane is not progress, and
claiming credit for wiring something that already ran would be exactly the kind
of unverified assertion this programme exists to remove.

**Nothing here is scheduled.** Installing a cron or systemd entry is
operator-only (AGENTS.md §17). Nothing here writes unless `--apply` is passed,
and `--apply` is refused for the two lanes whose write would adjudicate between
two candidate truths.

    python3 scripts/run_dormant_lane_consumers.py --json
    python3 scripts/run_dormant_lane_consumers.py --lane contradictions

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. FINANCIAL_ACTION = False.
Exit codes: 0 report produced · 1 a lane raised · 2 cannot run.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEMA = "DormantLaneConsumerReport@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
FINANCIAL_ACTION = False

SCHEDULED_ENTRYPOINT = (
    "INSTALLED, active — crontab `50 * * * *`, hourly at :50, from the rebuild "
    "tree with /run/user/$UID/tradeai/env loaded. Armed 2026-09-16 under operator "
    "APPROVE (full package, dormant-lane wire). Lane: dormant-lane-consumers."
)

# Lanes whose write adjudicates between two candidate truths. --apply is refused
# for these on purpose: AGENTS.md §17, escalate-never-resolve.
ESCALATE_NEVER_RESOLVE = frozenset({"contradictions"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ok(lane: str, wired: str, **detail: Any) -> dict[str, Any]:
    return {"lane": lane, "ok": True, "wired": wired, "authority": AUTHORITY, **detail}


# ── lane: CriticPanel / reconcile_critics ────────────────────────────────

def lane_critics(_: argparse.Namespace) -> dict[str, Any]:
    """Tier-0 deterministic reconciliation. No provider, no cost, no vote.

    `CriticPanel.review` short-circuits to BLOCK_DETERMINISTIC *before any
    critic call* when the deterministic report refuses release, so the free path
    is exercised without configuring a provider. `reconcile_critics` is then
    called directly with zero lanes, which is the PROVIDER_FAILURE branch --
    the honest state for "no reflective lane completed", and the branch a
    production caller hits first.
    """
    from scripts.agent_runtime.critics import CriticLane, CriticPanel, reconcile_critics
    from scripts.agent_runtime.sentinel import inspect_ticket

    ticket = {
        "symbol": "PROBE",
        "state": "REVIEW",
        "validation_hash": "0" * 64,
        "input_hash": "0" * 64,
    }
    deterministic = inspect_ticket(ticket, {"state": "PASS"}, now=_now())

    panel = CriticPanel(
        lanes=[CriticLane(lane_id="tier0", provider_family="deterministic",
                          model="none", max_cost_usd=0.0, enabled=False)],
        providers={},
    )
    reconciliation = panel.review(ticket, deterministic)
    direct = reconcile_critics((), deterministic)

    return _ok(
        "critics",
        "scripts.agent_runtime.critics.CriticPanel.review + reconcile_critics",
        deterministic_verdict=deterministic.verdict,
        deterministic_release_allowed=deterministic.release_allowed,
        deterministic_finding_codes=[f.code for f in deterministic.findings],
        panel_state=reconciliation.state,
        direct_state=direct.state,
        operator_action=direct.operator_action,
        cost_usd=0.0,
        provider_calls=0,
        note=("tier-0 only: no provider is configured, so no reflective lane "
              "can be called and no cost can be incurred. BLOCK_DETERMINISTIC "
              "is the short-circuit taken BEFORE any critic call; the finding "
              "codes say why the kernel refused release"),
    )


# ── lane: sentinel.inspect_ticket ────────────────────────────────────────

def lane_sentinel(_: argparse.Namespace) -> dict[str, Any]:
    """The deterministic kernel, over a ticket that should BLOCK and one that should not."""
    from scripts.agent_runtime.sentinel import inspect_ticket

    clean = inspect_ticket(
        {"symbol": "PROBE", "state": "REVIEW",
         "validation_hash": "0" * 64, "input_hash": "0" * 64},
        {"state": "PASS"}, now=_now(),
    )
    # A ticket with no identity and no validation binding must be refused. A
    # kernel that passes this is not inspecting anything.
    broken = inspect_ticket({}, {"state": "FAIL", "hard_failures": ["probe"]}, now=_now())

    return _ok(
        "sentinel",
        "scripts.agent_runtime.sentinel.inspect_ticket",
        clean_verdict=clean.verdict,
        clean_release_allowed=clean.release_allowed,
        refused_verdict=broken.verdict,
        refused_release_allowed=broken.release_allowed,
        refused_finding_codes=[f.code for f in broken.findings],
        negative_control_held=(not broken.release_allowed),
        note=("negative_control_held False would mean the kernel released a "
              "ticket with no identity and a failed validation"),
    )


# ── lane: MvlRuntime.resume ──────────────────────────────────────────────

def lane_mvl_resume(args: argparse.Namespace) -> dict[str, Any]:
    """Make `MvlRuntime.resume` reachable; act only on an explicit run id.

    `resume` is a state-machine transition, so this lane reports reachability by
    default and transitions only when the operator names a run. Resuming an
    arbitrary run because a report was requested would be a side effect nobody
    asked for.
    """
    from scripts.agent_runtime.runtime import MvlRuntime

    resume_fn: Callable[..., Any] = MvlRuntime.resume
    detail: dict[str, Any] = {
        "callable": f"{MvlRuntime.__module__}.MvlRuntime.resume",
        "signature": "resume(self, run_id: str) -> Mapping[str, Any]",
        "reachable": callable(resume_fn),
        "resumed": None,
        "note": ("reachable, not invoked. Pass --resume-run-id to transition a "
                 "run; CANCELLED and FAILED runs are refused by the runtime"),
    }
    if getattr(args, "resume_run_id", None):
        detail["note"] = "resume requires an operator-constructed runtime; not built here"
        detail["refused"] = (
            "MvlRuntime requires an AgentDefinition, journal, retrieval and model "
            "provider. This advisory entrypoint does not construct a live runtime, "
            "because doing so would need a model provider and therefore a budget."
        )
    return _ok("mvl_resume", "scripts.agent_runtime.runtime.MvlRuntime.resume", **detail)


# ── lane: close_goal ─────────────────────────────────────────────────────

def lane_close_goal(args: argparse.Namespace) -> dict[str, Any]:
    """Propose goal closures. `close_goal` has never had a production caller.

    Measured: the goal store is constructed in six live modules and nothing
    closes a goal, so GOAL_STATUS_CHANGED has never been appended. This lane
    names which open goals are closable and, with --apply, closes them with an
    explicit reason. It never invents a reason: a goal with no evidence of
    completion is reported, not closed.
    """
    from scripts.lib.cio_goals import CIOGoalStore

    root = Path(args.root) if args.root else REPO
    store = CIOGoalStore(
        event_path=root / "data" / "cio" / "cio_goals.jsonl",
        projection_path=root / "data" / "cio" / "cio_goals_projection.json",
        cursor_path=root / "data" / "cio" / "cio_goal_event_cursors.json",
    )
    open_goals = store.list_open_goals(limit=200)

    proposals: list[dict[str, Any]] = []
    for goal in open_goals:
        # Only a goal whose own record says it is finished is proposed. This is
        # deliberately narrow: closing a goal because it looks stale is how a
        # goal loop learns to declare success by timeout.
        done = goal.get("completed_ts") or goal.get("achieved_ts")
        evidence = goal.get("evidence") or goal.get("evidence_refs") or []
        if not done:
            continue
        proposals.append({
            "goal_id": goal.get("goal_id"),
            "title": goal.get("title"),
            "owner_agent": goal.get("owner_agent"),
            "proposed_status": "achieved",
            "evidence_refs": list(evidence),
            "has_evidence": bool(evidence),
        })

    closed: list[str] = []
    if args.apply:
        for proposal in proposals:
            if not proposal["has_evidence"]:
                continue        # never close a goal that cannot say why
            store.close_goal(
                proposal["goal_id"],
                status="achieved",
                reason="closed by run_dormant_lane_consumers --apply with recorded evidence",
                actor_id="cio_dormant_lane_consumer",
            )
            closed.append(proposal["goal_id"])

    return _ok(
        "close_goal",
        "scripts.lib.cio_goals.CIOGoalStore.close_goal",
        open_goals=len(open_goals),
        closable_proposals=len(proposals),
        proposals_without_evidence=sum(1 for p in proposals if not p["has_evidence"]),
        closed=closed,
        applied=bool(args.apply),
        sample=proposals[:10],
        note=("a goal is proposed only when its own record carries a completion "
              "timestamp; --apply additionally requires recorded evidence"),
    )


# ── lane: commitment_outcome_sweep ───────────────────────────────────────

def lane_commitments(args: argparse.Namespace) -> dict[str, Any]:
    """Invoke the sweep through its own entrypoint module.

    The entrypoint exists and is scheduled nowhere, so `sweep_due_commitments`
    has never run unattended. Calling its `main()` here rather than
    re-implementing the argument handling keeps one code path.
    """
    import io
    import contextlib
    from scripts import sweep_commitment_outcomes as entry

    argv = ["--json"]
    if getattr(args, "state_root", None):
        argv += ["--state-root", args.state_root]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = entry.main(argv)
    raw = buffer.getvalue().strip()
    try:
        report = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        report = {"unparsed_stdout": raw[:2000]}

    return _ok(
        "commitments",
        "scripts.sweep_commitment_outcomes.main -> commitment_outcome_sweep.sweep_due_commitments",
        exit_code=rc,
        store_present=(rc != 2),
        report=report,
        note=("exit 2 means NO_COMMITMENT_STORE -- an absent store, which is "
              "not the same as nothing being due"),
    )


# ── lane: hermes_challenge_queue.resolve ─────────────────────────────────

def lane_challenges(args: argparse.Namespace) -> dict[str, Any]:
    """Report resolvable challenges. `resolve` has never had a production caller.

    Measured: challenges are enqueued by four live modules and resolved by none,
    so the queue accumulates ENQUEUED rows with no terminal. `resolve` requires
    status IN_PROGRESS and a non-empty artifact, so this lane reports what is
    actually resolvable rather than claiming the whole backlog is.
    """
    from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue

    root = Path(args.root) if args.root else REPO
    queue = HermesChallengeQueue(
        event_store_path=root / "data" / "cio" / "hermes_challenge_queue.jsonl"
    )
    by_status: dict[str, int] = {}
    for status in ("PENDING", "IN_PROGRESS", "RESOLVED", "FAILED",
                   "EXPIRED", "CANCELLED", "RELEASED"):
        by_status[status] = len(queue.list_challenges(status=status, limit=10_000))

    in_progress = queue.list_challenges(status="IN_PROGRESS", limit=50)
    resolvable = [
        {"challenge_id": c.get("challenge_id"),
         "challenge_type": c.get("challenge_type"),
         "has_artifact": bool((c.get("payload") or {}).get("artifact"))}
        for c in in_progress
    ]

    resolved: list[str] = []
    if args.apply:
        for row in resolvable:
            artifact = None
            for c in in_progress:
                if c.get("challenge_id") == row["challenge_id"]:
                    artifact = (c.get("payload") or {}).get("artifact")
            if not artifact:
                continue        # resolve() refuses an empty artifact, correctly
            queue.resolve(
                row["challenge_id"], artifact,
                resolution_note="resolved by run_dormant_lane_consumers --apply",
                actor_id="cio_dormant_lane_consumer",
            )
            resolved.append(row["challenge_id"])

    return _ok(
        "challenges",
        "scripts.lib.cio_hermes_challenge_queue.HermesChallengeQueue.resolve",
        by_status=by_status,
        in_progress=len(in_progress),
        resolvable_with_artifact=sum(1 for r in resolvable if r["has_artifact"]),
        resolved=resolved,
        applied=bool(args.apply),
        sample=resolvable[:10],
        note=("only IN_PROGRESS challenges carrying an artifact are resolvable; "
              "a PENDING backlog is not resolvable without being claimed first"),
    )


# ── lane: research_contradiction ─────────────────────────────────────────

def lane_contradictions(args: argparse.Namespace) -> dict[str, Any]:
    """The reader the candidate store never had. Escalates; never resolves."""
    from scripts.lib import research_contradiction_consumer as consumer

    root = Path(args.root) if args.root else REPO
    candidates = consumer.load_candidates(root=root)
    report = consumer.digest(candidates, now=_now())

    return _ok(
        "contradictions",
        "scripts.lib.research_contradiction_consumer.digest",
        candidates_read=report["candidates_read"],
        subjects_in_conflict=report["subjects_in_conflict"],
        top_subjects=report["top_subjects"][:10],
        applied=False,
        apply_refused=("--apply is refused for this lane: resolving a "
                       "contradiction picks one of two candidate truths "
                       "(AGENTS.md §17, escalate-never-resolve)"),
        note=report["note"],
    )


# ── lane: run_tiered_validation_gate ─────────────────────────────────────

def lane_tiered_validation(_: argparse.Namespace) -> dict[str, Any]:
    """`run_tiered_validation_gate.run_once` — the P6 sibling that never got armed.

    Four entrypoints shipped in the 2026-09-16 tranche. Three were installed on the host
    that day -- `:35` cio_gate_measurement_bridge, `:40` run_goal_pilot_material_change,
    `:50` this runner -- and the fourth was not. Measured 2026-09-17 it had zero callers
    in scripts/, zero references in tests/, zero crontab lines and no lane registry row.

    It was not lying about that. It declared `SCHEDULED_ENTRYPOINT = "PROPOSAL ONLY --
    not installed"`, which is true, and which is also why nothing reported it:
    `check_dark_contracts.py` skips any module holding that constant whatever it says, so
    the module with no caller at all passed the gate written to catch modules with no
    caller. The constant is gone; this function is the caller.

    It cannot spend, for two independent structural reasons:

      1. `providers=None` -- a lane with no provider is *preserved as a failed lane*, never
         silently substituted, which is the property `CriticPanel` exists to guarantee. No
         provider means nothing reaches the network;
      2. the fixture ticket carries no identity, so tier 0 refuses release and `validate()`
         returns BLOCK_DETERMINISTIC **before the panel is constructed**. That short-circuit
         exists precisely so that a deterministic refusal cannot cost anything.

    `TRADEAI_TIER2_PAID_JUDGE` is read by `TierPolicy.from_env()` and is set in the host
    environment. It changes nothing here: tier 2 is unreachable from a tier-0 block, and
    `run_once` injects no paid judge, so even an enabled flag could only ever reach
    DENIED_NO_PAID_JUDGE_CONFIGURED. The check below is the belt to that pair of braces --
    a lane that reports a cent fails loudly rather than billing quietly.
    """
    from scripts import run_tiered_validation_gate as gate

    ticket, validation = gate.self_check_ticket()
    payload = gate.run_once(ticket, validation, providers=None, sequence_number=1)
    result = payload["result"]

    # Fail closed. `run()` turns this into ok:False and a non-zero exit for the whole
    # report, which is the correct loudness for "the free tier billed us".
    if result["cost_usd"] != 0.0 or result["paid_calls"] != 0:
        raise AssertionError(
            f"tiered_validation reported {result['cost_usd']} USD across "
            f"{result['paid_calls']} paid call(s); this lane is free by construction"
        )

    return _ok(
        "tiered_validation",
        "scripts.run_tiered_validation_gate.run_once -> scripts.lib.tiered_validation.validate",
        gate_schema=payload["schema"],
        state=result["state"],
        tier_reached=result["tier_reached"],
        deterministic_verdict=result["deterministic_verdict"],
        release_allowed=result["release_allowed"],
        tier2_state=result["tier2_state"],
        critic_calls=result["critic_calls"],
        paid_calls=result["paid_calls"],
        cost_usd=result["cost_usd"],
        provider_calls=0,
        note=("tier 0 only: the fixture ticket has no identity, so the kernel refuses "
              "release and validate() returns before any critic is constructed. "
              "tier2_state NOT_REACHED_TIER0_BLOCK is the evidence that the operator's "
              "paid-judge flag was never consulted"),
    )


# ── lanes that are ALREADY WIRED ─────────────────────────────────────────

def lane_data_gap_registry(_: argparse.Namespace) -> dict[str, Any]:
    """Already live. Reported, not re-wired."""
    from scripts.lib.writers import data_gap_registry_writer as writer

    return _ok(
        "data_gap_registry",
        "ALREADY_WIRED",
        table=getattr(writer, "TABLE", "data_gap_registry"),
        live_readers=[
            "scripts/api_v2.py (gap summary + stats surfaces)",
            "scripts/health_agent.py (open-gap alarm)",
            "scripts/data_gap_resolver.py (hourly cron + pre-overnight + weekly audit)",
        ],
        note=("already has live readers and an installed schedule; a second "
              "caller here would be duplication, not wiring"),
    )


def lane_evidence_refresh(_: argparse.Namespace) -> dict[str, Any]:
    """Already live via the free-first circulation timer. Reported, not re-wired."""
    from scripts.lib import evidence_refresh_job as job

    return _ok(
        "evidence_refresh_job",
        "ALREADY_WIRED",
        schema=getattr(job, "SCHEMA", None),
        live_chain=("scripts/lib/free_first_circulation.py -> scripts/free_first_refresh.py "
                    "-> tradeai-free-first-circulation.timer (hourly)"),
        paid_forbidden=True,
        note=("consumed by free_first_circulation and cio_residual_web; the "
              "timer is already installed, so this lane is not dormant"),
    )


LANES: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
    "critics": lane_critics,
    "sentinel": lane_sentinel,
    "mvl_resume": lane_mvl_resume,
    "close_goal": lane_close_goal,
    "commitments": lane_commitments,
    "challenges": lane_challenges,
    "contradictions": lane_contradictions,
    "tiered_validation": lane_tiered_validation,
    "data_gap_registry": lane_data_gap_registry,
    "evidence_refresh_job": lane_evidence_refresh,
}


def run(args: argparse.Namespace) -> dict[str, Any]:
    selected = [args.lane] if args.lane else list(LANES)
    results: list[dict[str, Any]] = []
    for name in selected:
        fn = LANES.get(name)
        if fn is None:
            results.append({"lane": name, "ok": False, "error": "unknown lane"})
            continue
        if args.apply and name in ESCALATE_NEVER_RESOLVE:
            # Refused loudly rather than silently ignored: a flag that appears
            # to be honoured and is not is worse than one that is refused.
            results.append({
                "lane": name, "ok": True, "applied": False,
                "apply_refused": "escalate-never-resolve lane (AGENTS.md §17)",
            })
            continue
        try:
            results.append(fn(args))
        except Exception as exc:                                 # noqa: BLE001
            results.append({
                "lane": name, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=4),
            })
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "as_of": _now().isoformat(),
        "applied": bool(args.apply),
        "lanes_run": len(results),
        "lanes_ok": sum(1 for r in results if r.get("ok")),
        "lanes_failed": [r["lane"] for r in results if not r.get("ok")],
        "already_wired": [r["lane"] for r in results if r.get("wired") == "ALREADY_WIRED"],
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lane", choices=sorted(LANES), default=None,
                    help="run one lane (default: all)")
    ap.add_argument("--root", default=None, help="repo root holding data/cio")
    ap.add_argument("--state-root", default=None,
                    help="persistent-wake state root for the commitment sweep")
    ap.add_argument("--resume-run-id", default=None,
                    help="run id for the MvlRuntime.resume lane")
    ap.add_argument("--apply", action="store_true",
                    help="perform the writes the lanes propose (refused for "
                         "escalate-never-resolve lanes)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    report = run(args)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"DormantLaneConsumerReport  as_of={report['as_of']}  "
              f"applied={report['applied']}")
        for result in report["results"]:
            mark = "ok " if result.get("ok") else "ERR"
            wired = result.get("wired", "")
            tag = " [already wired]" if wired == "ALREADY_WIRED" else ""
            print(f"  [{mark}] {result['lane']}{tag}")
            if not result.get("ok"):
                print(f"        {result.get('error')}")
            elif result.get("note"):
                print(f"        {result['note']}")
        print(f"\n  lanes ok: {report['lanes_ok']}/{report['lanes_run']}  "
              f"already wired: {len(report['already_wired'])}")
        if report["lanes_failed"]:
            print(f"  FAILED: {report['lanes_failed']}")

    return 1 if report["lanes_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
