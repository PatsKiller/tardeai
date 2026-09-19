#!/usr/bin/env python3
"""aec_command_center_cycle.py — one Autonomous Executive Command Center cycle.

Production consumer for aec_agent_bus + aec_memory_spines (wiring guard).

Default is --dry-run: prints what each agent would publish after retrieve-memory.
Live append requires --apply (still advisory-only; never broker).

Usage:
  python3 scripts/aec_command_center_cycle.py --dry-run
  python3 scripts/aec_command_center_cycle.py --apply --subject-key WATCH:SCHG
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

NO_CONSUMER_REASON = (
    "AEC Command Center cycle entrypoint; stdout receipt is the consumer until "
    "a scheduled Narrator/wake imports it (operator license 2026-09-19)"
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import aec_agent_bus as bus  # noqa: E402
from lib import aec_memory_spines as mem  # noqa: E402
from lib.agent_view_v1 import persist_allowed, produce_agent_view_v1  # noqa: E402
from lib.agent_commitment_v1 import evaluate_commitment, mint_commitment_from_view  # noqa: E402
from lib.cio_disposition_identity import (  # noqa: E402
    applicable_dispositions,
    canonical_key,
    parse_key,
)
from lib.cio_memory_integration import integrate_wake_envelope  # noqa: E402
from lib.aec_narrator import render_executive_brief, notify_executive_brief  # noqa: E402


def run_cycle(*, subject_key: str | None, apply: bool, observe: dict | None = None) -> dict:
    snap = mem.load()
    relevant = mem.retrieve_relevant(snap, subject_key=subject_key)
    recent = bus.read_recent(limit=20)
    subject = subject_key or "PORTFOLIO"

    # CIO — infrastructure / automation posture (placeholder from memory only)
    cio_summary = (
        f"CIO cycle: operational facts={len(relevant.get('operational') or [])}; "
        f"bus_seen={len(bus.topics_for('cio_agent', recent))}"
    )
    cio_ev = bus.publish(
        agent_id="cio_agent",
        topic="cycle.cio.status",
        summary=cio_summary,
        subject_key=subject_key,
        payload={
            "memory_counts": {k: len(v) for k, v in relevant.items()},
            # Gate-B identity resolver consumer: alias → canonical on bus.
            "mentioned_agents": ["risk_agent", "tax_agent", "guardian", "ledger"],
        },
        dry_run=not apply,
    )

    # Advisor — AgentView@v1 (existing producer) + optional commitment
    advisor_claim = f"Advisor reviewed subject={subject} against strategic spine"
    fp = mem.claim_fingerprint(advisor_claim)
    repeated = mem.seen_claim(snap, fp)
    view_payload: dict = {}
    commitment_payload: dict | None = None
    outcome_payload: dict | None = None
    if repeated:
        advisor_summary = f"SUPPRESSED_REPEAT fp={fp}"
    else:
        view = produce_agent_view_v1(
            subject=subject,
            summary=advisor_claim,
            citations=["aec_memory:strategic", "aec_agent_bus:recent"],
            confidence=0.62,
            source_sha="aec_cycle",
            falsifier="strategic spine gains a contradicting fact within 7d",
            provenance_class="T",
        )
        view_payload = view.to_dict()
        advisor_summary = f"{view.stance}: {advisor_claim}"
        if persist_allowed(view):
            # due_at must be after mint time or evaluate_commitment returns EXPIRED
            # immediately (horizon "7d" is the falsifier window, not produced_at).
            due = datetime.now(timezone.utc) + timedelta(days=7)
            commitment = mint_commitment_from_view(
                view.to_dict(),
                due_at=due.isoformat().replace("+00:00", "Z"),
                horizon="7d",
                falsifier=view.falsifier,
            )
            commitment_payload = commitment.to_dict()
            # Immutable disposition identity (was KNOWN_DARK): commitment_id is
            # the decision_id; legacy position: keys never auto-apply.
            decision_id = str(commitment_payload.get("commitment_id") or "")
            decision_key = canonical_key(decision_id=decision_id)
            commitment_payload["decision_key"] = decision_key
            commitment_payload["decision_key_parsed"] = parse_key(decision_key)
            prior_disp = applicable_dispositions({}, decision_id=decision_id)
            commitment_payload["prior_disposition"] = prior_disp
            # OUTCOME edge: evaluate when observation supplied; else honest
            # INSUFFICIENT_EVIDENCE. Never broker/policy.
            outcome_payload = evaluate_commitment(
                commitment_payload,
                observation=observe,
            )
        if apply:
            mem.append_fact(
                "learning",
                {
                    "kind": "agent_view",
                    "claim_fp": fp,
                    "text": advisor_claim,
                    "subject_key": subject_key,
                    "view_id": view.view_id,
                    "stance": view.stance,
                },
            )
            if commitment_payload:
                mem.append_fact(
                    "learning",
                    {
                        "kind": "commitment",
                        "subject_key": subject_key,
                        "commitment_id": commitment_payload.get("commitment_id"),
                        "claim_fp": fp,
                    },
                )
            if outcome_payload:
                mem.append_fact(
                    "learning",
                    {
                        "kind": "commitment_outcome",
                        "subject_key": subject_key,
                        "outcome": outcome_payload.get("outcome"),
                        "commitment_id": outcome_payload.get("commitment_id"),
                        "claim_fp": fp,
                    },
                )
            mem.append_fact(
                "strategic",
                {"kind": "thesis_touch", "subject_key": subject_key, "note": "cycle touch", "view_id": view.view_id},
            )
    adv_ev = bus.publish(
        agent_id="advisor_agent",
        topic="cycle.advisor.thesis",
        summary=advisor_summary,
        subject_key=subject_key,
        payload={
            "claim_fp": fp,
            "suppressed": repeated,
            "agent_view": view_payload or None,
            "commitment": commitment_payload,
            "outcome": outcome_payload,
        },
        dry_run=not apply,
    )

    # Narrator — executive briefing text (not sent here; publish to bus only)
    # Cognitive memory dry-run (isolated substrate; never financial truth).
    bitemporal_receipt = integrate_wake_envelope(
        {
            "subject_key": subject,
            "predicate": "thesis",
            "claim": advisor_summary[:240],
            "object": {
                "text": advisor_summary[:240],
                "kind": "cognitive_hypothesis",
                "cycle": True,
            },
            "wake_job_id": f"aec-cycle-{subject}",
        },
        apply=False,
    )
    narr_summary = (
        f"Narrator brief: cio={cio_ev.summary[:80]}; advisor={adv_ev.summary[:80]}; "
        f"learning_rows={len(relevant.get('learning') or [])}; "
        f"bitemporal_dry_run={bitemporal_receipt.get('dry_run')}"
    )
    brief = render_executive_brief(subject_key=subject_key)
    notify_receipt = notify_executive_brief(brief, apply=False)  # never auto-Telegram from cycle
    narr_ev = bus.publish(
        agent_id="narrator_agent",
        topic="cycle.narrator.brief",
        summary=narr_summary if not brief.get("suppressed_repeat") else f"SUPPRESSED_REPEAT {brief.get('claim_fp')}",
        subject_key=subject_key,
        payload={
            "would_telegram": bool(notify_receipt.get("would_telegram")),
            "telegram": notify_receipt.get("telegram"),
            "claim_fp": brief.get("claim_fp"),
            "brief_schema": brief.get("schema"),
            "reason": "cycle_renders_brief_notify_requires_explicit_flag",
        },
        dry_run=not apply,
    )

    return {
        "schema": "AecCommandCenterCycle@v1",
        "apply": apply,
        "subject_key": subject_key,
        "memory_relevant": {k: len(v) for k, v in relevant.items()},
        "events": [json.loads(cio_ev.to_json()), json.loads(adv_ev.to_json()), json.loads(narr_ev.to_json())],
        "agent_view": view_payload or None,
        "commitment": commitment_payload,
        "outcome": outcome_payload,
        "bitemporal": bitemporal_receipt,
        "narrator_brief": brief,
        "narrator_notify": notify_receipt,
        "authority": "READ_ONLY_ADVISORY",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true", help="append bus + memory (still advisory)")
    ap.add_argument("--subject-key", default=None)
    args = ap.parse_args()
    apply = bool(args.apply)
    out = run_cycle(subject_key=args.subject_key, apply=apply)
    print(json.dumps(out, indent=2))
    if not apply:
        print("DRY_RUN no durable write", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
