#!/usr/bin/env python3
"""Industry momentum v4 launcher with shared specialized due diligence.

The established Finviz industry producer still owns fetches, benchmark alignment,
quadrant math, mapping, persistence, debounce and alerts. This additive launcher
only annotates the resulting snapshot with immutable row-level research packets.
Midday rows remain visible as research, but cannot become proposal/rotation input
until a close-confirmed packet passes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import finviz_industry_groups as base
from defense_data_quality import snapshot_hash
from research_due_diligence_adapters import industry_due_diligence

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "runtime" / "industry_momentum_latest.json"


def attach_due_diligence(snapshot_path: Path = SNAPSHOT) -> dict:
    snapshot = json.loads(snapshot_path.read_text())
    states = {"PASS": 0, "REVIEW_REQUIRED": 0, "BLOCKED": 0}
    by_industry = {}
    for row in snapshot.get("industries") or []:
        packet = industry_due_diligence(row, snapshot)
        row["due_diligence"] = packet
        state = packet.get("deterministic_state") or "BLOCKED"
        states[state] = states.get(state, 0) + 1
        by_industry[str(row.get("industry") or "")] = packet

    candidates = snapshot.get("candidates") or {}
    for lane in ("defensive_short_pool", "watch_rail"):
        enriched = []
        for item in candidates.get(lane) or []:
            packet = by_industry.get(str(item.get("industry") or "")) or {}
            enriched.append({
                **item,
                "due_diligence_state": packet.get("deterministic_state") or "BLOCKED",
                "due_diligence_hash": packet.get("packet_hash"),
                "eligible_for_proposal_or_rotation": bool(
                    (packet.get("downstream") or {}).get("proposal_or_rotation_eligible")
                ),
            })
        candidates[lane] = enriched
    snapshot["candidates"] = candidates
    snapshot["due_diligence"] = {
        "contract": "research-due-diligence-v1",
        "adapter": "specialized-research-adapters-v1",
        "domain": "industry",
        "capture_kind": snapshot.get("capture_kind"),
        "states": states,
        "proposal_or_rotation_eligible_count": sum(
            1 for packet in by_industry.values()
            if (packet.get("downstream") or {}).get("proposal_or_rotation_eligible")
        ),
        "authority": "close-confirmed deterministic research only; models cannot alter mapping or quadrant math",
    }
    snapshot.pop("snapshot_hash", None)
    snapshot["snapshot_hash"] = snapshot_hash(snapshot)
    snapshot_path.write_text(json.dumps(snapshot, default=str))
    return snapshot["due_diligence"]


def main() -> int:
    result = base.main()
    if result == 0 and "--dry-run" not in sys.argv and SNAPSHOT.exists():
        summary = attach_due_diligence()
        print(f"[industry] due diligence {summary['states']} · eligible "
              f"{summary['proposal_or_rotation_eligible_count']}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
