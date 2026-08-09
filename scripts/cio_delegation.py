#!/usr/bin/env python3
"""cio_delegation.py — Autonomous specialist delegation + Hermes challenge engine.

Runs as part of the CIO heartbeat cycle. When material changes are detected:
  1. Enqueues specialist handoffs (Maria, Steph, Guardian, Ledger) for relevant domains
  2. Enqueues Hermes challenge requests for material/contradictory findings
  3. Tracks handoff lifecycle (PENDING → CLAIMED → COMPLETED)

Shadow-only: no Telegram, no broker actions, no model calls in the delegation layer.
The specialists and Hermes use their own governed model routing (DeepSeek-first).

Usage:
  python3 scripts/cio_delegation.py --once [--max-handoffs 3] [--max-challenges 2]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_hash(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()[:12]


# ── Domain → specialist mapping ───────────────────────────────────────────────

DOMAIN_SPECIALIST: dict[str, list[str]] = {
    "portfolio": ["steph"],
    "risk": ["guardian"],
    "watch": ["maria", "guardian"],
    "rotation": ["steph", "maria"],
    "income": ["steph", "ledger"],
    "reconciliation": ["ledger"],
    "hermes_research": [],  # Hermes challenges itself — no specialist needed
}

# ── What Hermes should challenge ──────────────────────────────────────────────

HERMES_CHALLENGE_DOMAINS = {
    "risk": "research_gap",
    "rotation": "freshness_decay",
    "watch": "research_gap",
    "portfolio": "contradiction",
}


def enqueue_specialist_handoffs(
    domain: str,
    change: dict[str, Any],
    snapshot: dict[str, Any],
    max_handoffs: int = 3,
) -> list[dict[str, Any]]:
    """Enqueue handoffs to specialists for a changed domain. Returns list of handoff results."""
    from lib.cio_agent_handoff_queue import enqueue_handoff

    specialists = DOMAIN_SPECIALIST.get(domain, [])
    results: list[dict[str, Any]] = []

    for specialist_id in specialists[:max_handoffs]:
        handoff_id = f"hb-{_short_hash(f'{domain}:{specialist_id}:{_now_iso()}')}"
        snapshot_hash = snapshot.get("content_hash", "unknown") if snapshot else "unknown"

        handoff = {
            "handoff_id": handoff_id,
            "from_agent": "alex",
            "to_agent": specialist_id,
            "task_type": _domain_to_task_type(domain),
            "task_summary": (
                f"[{change.get('change_type', 'MATERIAL_CHANGE')}] {domain}: "
                f"{change.get('description', 'Material change detected')}"
            ),
            "input_snapshot_id": snapshot.get("snapshot_id", "unknown"),
            "input_hash": snapshot_hash,
            "max_budget_usd": 0.02,  # Shadow budget — specialist review only
            "priority": change.get("priority", "normal"),
            "idempotency_key": f"{domain}:{specialist_id}:{snapshot_hash[:8]}",
            "parent_run_id": None,
            "deadline_seconds": 3600,  # 1 hour
            "evidence_refs": change.get("evidence_refs", []),
        }

        try:
            result = enqueue_handoff(handoff, actor_id="alex")
            actual_status = result.get("event_type", "UNKNOWN")
            is_blocked = "BLOCKED" in actual_status
            status = "BLOCKED" if is_blocked else "ENQUEUED"
            results.append({"handoff_id": handoff_id, "status": status, "to": specialist_id})
            print(f"  [delegation] {domain} → {specialist_id}: {status} ({handoff_id})")
        except ValueError as e:
            # NOT_READY agents will BLOCK the handoff — that's correct behavior
            results.append({"handoff_id": handoff_id, "status": "BLOCKED", "to": specialist_id, "reason": str(e)})
            print(f"  [delegation] {domain} → {specialist_id}: BLOCKED ({e})")
        except Exception as e:
            results.append({"handoff_id": handoff_id, "status": "FAILED", "to": specialist_id, "reason": str(e)[:120]})
            print(f"  [delegation] {domain} → {specialist_id}: FAILED ({e})")

    return results


def enqueue_hermes_challenges(
    domain: str,
    change: dict[str, Any],
    max_challenges: int = 2,
) -> list[dict[str, Any]]:
    """Enqueue Hermes challenges for domains that warrant independent review."""
    from lib.cio_hermes_challenge_queue import HermesChallengeQueue

    challenge_type = HERMES_CHALLENGE_DOMAINS.get(domain)
    if not challenge_type:
        return []

    queue = HermesChallengeQueue()
    results: list[dict[str, Any]] = []

    descriptions = {
        "risk": f"Risk domain changed: {change.get('change_type')}. Verify concentration and stop coverage independently.",
        "rotation": f"Rotation domain changed: {change.get('change_type')}. Challenge the prevailing sector thesis.",
        "watch": f"Watch domain changed: {change.get('change_type')}. Find counter-evidence for the current watch thesis.",
        "portfolio": f"Portfolio domain changed: {change.get('change_type')}. Independently verify allocation drift vs IPS.",
    }

    description = descriptions.get(domain, f"CIO detected material change in {domain}. Independent challenge requested.")
    priority = "high" if change.get("change_type") in ("DOMAIN_WENT_STALE", "DATA_CHANGED") else "normal"

    try:
        result = queue.enqueue(
            challenge_type=challenge_type,
            description=description,
            source=f"cio_heartbeat:{domain}",
            priority=priority,
            evidence_refs=change.get("evidence_refs", []),
            actor_id="alex",
        )
        challenge_id = result.get("stream_id", "unknown")
        results.append({"challenge_id": challenge_id, "status": "ENQUEUED", "type": challenge_type})
        print(f"  [hermes] {domain}: CHALLENGE ENQUEUED ({challenge_id}, type={challenge_type})")
    except Exception as e:
        results.append({"status": "FAILED", "reason": str(e)[:120]})
        print(f"  [hermes] {domain}: FAILED ({e})")

    return results


def _domain_to_task_type(domain: str) -> str:
    mapping = {
        "portfolio": "allocation_review",
        "risk": "risk_review",
        "watch": "fundamental_research",
        "rotation": "allocation_review",
        "income": "retirement_review",
        "reconciliation": "evidence_review",
        "hermes_research": "evidence_review",
    }
    return mapping.get(domain, "cio_question")


def run_delegation_cycle(
    domain: str | None = None,
    change: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    max_handoffs: int = 3,
    max_challenges: int = 2,
) -> dict[str, Any]:
    """Run one delegation cycle. Returns summary dict."""
    t0 = time.time()
    handoff_results: list[dict[str, Any]] = []
    challenge_results: list[dict[str, Any]] = []

    if domain and change:
        handoff_results = enqueue_specialist_handoffs(domain, change, snapshot or {}, max_handoffs)
        challenge_results = enqueue_hermes_challenges(domain, change, max_challenges)

    elapsed = time.time() - t0
    return {
        "handoffs_enqueued": sum(1 for r in handoff_results if r.get("status") == "ENQUEUED"),
        "handoffs_blocked": sum(1 for r in handoff_results if r.get("status") == "BLOCKED"),
        "challenges_enqueued": sum(1 for r in challenge_results if r.get("status") == "ENQUEUED"),
        "elapsed_ms": int(elapsed * 1000),
        "mode": "shadow",
        "model_calls": 0,
        "cost_usd": 0.0,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CIO Delegation Engine — specialist handoffs + Hermes challenges (shadow-only)"
    )
    parser.add_argument("--once", action="store_true", default=True, help="Run once and exit")
    parser.add_argument("--domain", type=str, help="Specific domain to delegate for (omit for all)")
    parser.add_argument("--max-handoffs", type=int, default=3, help="Max specialist handoffs per cycle")
    parser.add_argument("--max-challenges", type=int, default=2, help="Max Hermes challenges per cycle")
    args = parser.parse_args()

    print(f"CIO Delegation Engine — {_now_iso()[:19]}")
    print(f"  mode=shadow  max_handoffs={args.max_handoffs}  max_challenges={args.max_challenges}")

    # Run a test delegation for the portfolio domain (demonstrates the wiring)
    summary = run_delegation_cycle(
        domain=args.domain or "portfolio",
        change={
            "change_type": "MATERIAL_CHANGE",
            "description": "Portfolio composition changed — CIO heartbeat detected drift",
            "priority": "normal",
            "evidence_refs": ["cio_heartbeat:portfolio"],
        },
        max_handoffs=args.max_handoffs,
        max_challenges=args.max_challenges,
    )

    print(f"  summary: {json.dumps(summary, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
