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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import aec_agent_bus as bus  # noqa: E402
from lib import aec_memory_spines as mem  # noqa: E402


def run_cycle(*, subject_key: str | None, apply: bool) -> dict:
    snap = mem.load()
    relevant = mem.retrieve_relevant(snap, subject_key=subject_key)
    recent = bus.read_recent(limit=20)

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
        payload={"memory_counts": {k: len(v) for k, v in relevant.items()}},
        dry_run=not apply,
    )

    # Advisor — thesis / opportunity (cognition only)
    advisor_claim = f"Advisor reviewed subject={subject_key or 'PORTFOLIO'} against strategic spine"
    fp = mem.claim_fingerprint(advisor_claim)
    repeated = mem.seen_claim(snap, fp)
    if repeated:
        advisor_summary = f"SUPPRESSED_REPEAT fp={fp}"
    else:
        advisor_summary = advisor_claim
        if apply:
            mem.append_fact(
                "learning",
                {"kind": "recommendation", "claim_fp": fp, "text": advisor_claim, "subject_key": subject_key},
            )
            mem.append_fact(
                "strategic",
                {"kind": "thesis_touch", "subject_key": subject_key, "note": "cycle touch"},
            )
    adv_ev = bus.publish(
        agent_id="advisor_agent",
        topic="cycle.advisor.thesis",
        summary=advisor_summary,
        subject_key=subject_key,
        payload={"claim_fp": fp, "suppressed": repeated},
        dry_run=not apply,
    )

    # Narrator — executive briefing text (not sent here; publish to bus only)
    narr_summary = (
        f"Narrator brief: cio={cio_ev.summary[:80]}; advisor={adv_ev.summary[:80]}; "
        f"learning_rows={len(relevant.get('learning') or [])}"
    )
    narr_ev = bus.publish(
        agent_id="narrator_agent",
        topic="cycle.narrator.brief",
        summary=narr_summary,
        subject_key=subject_key,
        payload={"would_telegram": False, "reason": "cycle_bus_only_until_narrator_transport_wired"},
        dry_run=not apply,
    )

    return {
        "schema": "AecCommandCenterCycle@v1",
        "apply": apply,
        "subject_key": subject_key,
        "memory_relevant": {k: len(v) for k, v in relevant.items()},
        "events": [json.loads(cio_ev.to_json()), json.loads(adv_ev.to_json()), json.loads(narr_ev.to_json())],
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
