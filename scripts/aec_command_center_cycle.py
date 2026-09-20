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


def _prior_commitment_from_bus(recent: list) -> dict | None:
    """Last non-suppressed advisor commitment on the bus (for OUTCOME re-eval)."""
    for ev in reversed(list(recent or [])):
        try:
            agent = getattr(ev, "agent_id", None) or (
                ev.get("agent_id") if isinstance(ev, dict) else None
            )
            if agent != "advisor_agent":
                continue
            payload = getattr(ev, "payload", None) or (
                ev.get("payload") if isinstance(ev, dict) else None
            ) or {}
            if payload.get("suppressed"):
                continue
            cmt = payload.get("commitment")
            if isinstance(cmt, dict) and cmt.get("commitment_id"):
                return cmt
        except Exception:  # noqa: BLE001 — bus shape may vary; fail soft
            continue
    return None


def _learning_has_terminal_outcome(snap, commitment_id: str) -> bool:
    """True when learning spine already recorded a terminal OUTCOME for this id."""
    cid = str(commitment_id or "")
    if not cid:
        return False
    spines = getattr(snap, "spines", None) or {}
    for fact in spines.get("learning") or []:
        if not isinstance(fact, dict):
            continue
        if str(fact.get("commitment_id") or "") != cid:
            continue
        if fact.get("kind") == "commitment_outcome" and fact.get("outcome") in {
            "CONFIRMED",
            "REFUTED",
            "EXPIRED",
        }:
            return True
    return False


def run_cycle(
    *,
    subject_key: str | None,
    apply: bool,
    observe: dict | None = None,
    now: datetime | None = None,
) -> dict:
    when = now or datetime.now(timezone.utc)
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
    # Operational spine — infrastructure / automation posture (internal AEC
    # facts only; never invents relationship-domain sources).
    if apply:
        mem.append_fact(
            "operational",
            {
                "kind": "cio_cycle_status",
                "subject_key": subject_key,
                "bus_seen": len(bus.topics_for("cio_agent", recent)),
                "memory_counts": {k: len(v) for k, v in relevant.items()},
                "summary": cio_summary[:240],
            },
        )

    # Settle any open prior advisor commitment before minting (hourly EXPIRED /
    # observe path). Not gated on claim fingerprint — a new hour/day claim must
    # still close yesterday's open OUTCOME edge.
    prior_open = _prior_commitment_from_bus(recent)
    settled_prior_outcome: dict | None = None
    if prior_open is not None and not _learning_has_terminal_outcome(
        snap, str(prior_open.get("commitment_id") or "")
    ):
        settled_prior_outcome = evaluate_commitment(
            prior_open, observation=observe, now=when
        )
        if apply and settled_prior_outcome.get("outcome") in {
            "CONFIRMED",
            "REFUTED",
            "EXPIRED",
        }:
            mem.append_fact(
                "learning",
                {
                    "kind": "commitment_outcome",
                    "subject_key": subject_key,
                    "outcome": settled_prior_outcome.get("outcome"),
                    "commitment_id": settled_prior_outcome.get("commitment_id"),
                    "via": "prior_open_settle",
                },
            )
            # Refresh snap so same-cycle suppress path sees the terminal row.
            snap = mem.load()

    # Advisor — AgentView@v1 (existing producer) + optional commitment.
    # Hour-bucket the claim so each timer fire can mint a fresh 1h commitment
    # while prior_open_settle closes the previous hour's OUTCOME (EXPIRED /
    # observe). Day-only bucketing left OUTCOME stuck on INSUFFICIENT until the
    # next calendar day — and then never re-evaluated the prior commitment.
    hour_utc = when.strftime("%Y-%m-%dT%H")
    advisor_claim = (
        f"Advisor reviewed subject={subject} against strategic spine [{hour_utc}]"
    )
    fp = mem.claim_fingerprint(advisor_claim)
    repeated = mem.seen_claim(snap, fp)
    view_payload: dict = {}
    commitment_payload: dict | None = None
    outcome_payload: dict | None = None
    if repeated:
        advisor_summary = f"SUPPRESSED_REPEAT fp={fp}"
        # Same-day suppress still re-evaluates the open commitment so OUTCOME
        # can move to CONFIRMED/REFUTED/EXPIRED without minting a new view.
        prior = _prior_commitment_from_bus(recent)
        if prior is not None and not _learning_has_terminal_outcome(
            snap, str(prior.get("commitment_id") or "")
        ):
            commitment_payload = prior
            outcome_payload = evaluate_commitment(
                prior, observation=observe, now=when
            )
            if apply and outcome_payload.get("outcome") in {
                "CONFIRMED",
                "REFUTED",
                "EXPIRED",
            }:
                mem.append_fact(
                    "learning",
                    {
                        "kind": "commitment_outcome",
                        "subject_key": subject_key,
                        "outcome": outcome_payload.get("outcome"),
                        "commitment_id": outcome_payload.get("commitment_id"),
                        "claim_fp": fp,
                        "via": "suppressed_repeat_reeval",
                    },
                )
        elif prior is not None:
            commitment_payload = prior
            if outcome_payload is None:
                outcome_payload = evaluate_commitment(
                    prior, observation=observe, now=when
                )
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
            # AEC cycle commitments are short-horizon settlement probes for the
            # OUTCOME edge on the hourly timer (1h). The falsifier text still
            # names the 7d strategic-spine contradiction window; due_at is the
            # schedule-settlement clock so EXPIRED can land unattended.
            due = when + timedelta(hours=1)
            commitment = mint_commitment_from_view(
                view.to_dict(),
                due_at=due.isoformat().replace("+00:00", "Z"),
                horizon="1h",
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
                now=when,
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
                        "via": "fresh_mint",
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
            # Prior hour's settle (EXPIRED/CONFIRMED/REFUTED) when this fire
            # mints a fresh 1h claim — kept separate so mint INSUFFICIENT does
            # not erase the OUTCOME edge that just closed.
            "prior_outcome": settled_prior_outcome,
        },
        dry_run=not apply,
    )

    # Narrator — executive briefing text (not sent here; publish to bus only)
    # Cognitive memory on isolated :55432 only (prod :5432 refused in integrator).
    # Fail-soft: a bitemporal schema/function miss must not abort the cycle after
    # AgentView/commitment/OUTCOME already landed (2026-09-20T05:00Z exit 1 left
    # narrator unrun while hour-bucket mint had succeeded).
    try:
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
            apply=apply,
        )
    except Exception as exc:  # noqa: BLE001 — isolated memory must not kill AEC
        bitemporal_receipt = {
            "schema": "CIOEnvelopeIntegration@v1",
            "dry_run": not apply,
            "error": f"{type(exc).__name__}: {exc}"[:400],
            "authority": "READ_ONLY_ADVISORY",
            "mbi_behavior": 0,
            "via": "aec_bitemporal_fail_soft",
        }
    narr_summary = (
        f"Narrator brief: cio={cio_ev.summary[:80]}; advisor={adv_ev.summary[:80]}; "
        f"learning_rows={len(relevant.get('learning') or [])}; "
        f"bitemporal_dry_run={bitemporal_receipt.get('dry_run')}"
    )
    brief = render_executive_brief(subject_key=subject_key)
    # Live Telegram only when AEC_NARRATOR_NOTIFY=1 and --apply. Default dry-run.
    import os as _os

    _narr_notify = str(_os.environ.get("AEC_NARRATOR_NOTIFY", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    notify_receipt = notify_executive_brief(brief, apply=bool(apply and _narr_notify))
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
            "reason": (
                "cycle_narrator_notify"
                if (apply and _narr_notify)
                else "cycle_renders_brief_notify_requires_AEC_NARRATOR_NOTIFY"
            ),
            "aec_narrator_notify": bool(_narr_notify),
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
        "prior_outcome": settled_prior_outcome,
        "bitemporal": bitemporal_receipt,
        "narrator_brief": brief,
        "narrator_notify": notify_receipt,
        "authority": "READ_ONLY_ADVISORY",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    # Mutually exclusive: --dry-run was previously declared but never read, so
    # `--dry-run --apply` silently applied. argparse now rejects that pairing
    # instead of letting the more dangerous flag win by accident.
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default; no durable write")
    mode.add_argument("--apply", action="store_true", help="append bus + memory (still advisory)")
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
