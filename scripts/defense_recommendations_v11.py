#!/usr/bin/env python3
"""Defense recommendation v11 launcher with shared due-diligence gating.

The v10 launcher still owns account-specific exposure, sizing and stock-quality
math and delegates mature protection/trim/hedge paths to the established engine.
This additive v11 postprocessor binds every rotate-in card to the upstream sector
research packet and withholds non-passing cards from ``groups.get_into``.

Withheld cards remain in the snapshot for audit. No recommendation is activated,
no proposal state is changed and no broker/order/approval/2FA path exists here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import defense_recommendations_v10 as v10
from defense_data_quality import snapshot_hash
from research_due_diligence_adapters import defense_due_diligence, sector_due_diligence

ROOT = Path(__file__).resolve().parent.parent
RECOMMENDATIONS = ROOT / "data" / "runtime" / "defense_recommendations_latest.json"
SECTORS = ROOT / "data" / "runtime" / "sector_momentum_latest.json"


def _sector_for_card(card: dict, sector_snapshot: dict) -> dict | None:
    rows = sector_snapshot.get("rows") or []
    symbols = {
        str(item.get("symbol") or "").upper()
        for item in card.get("instruments") or []
        if isinstance(item, dict)
    }
    by_etf = {str(row.get("etf") or "").upper(): row for row in rows}
    for symbol in symbols:
        if symbol in by_etf:
            return by_etf[symbol]
    title = str(card.get("title") or "").upper()
    return next((row for row in rows if str(row.get("sector") or "").upper() in title), None)


def attach_due_diligence(
    recommendations_path: Path = RECOMMENDATIONS,
    sectors_path: Path = SECTORS,
) -> dict:
    recommendations = json.loads(recommendations_path.read_text())
    sector_snapshot = json.loads(sectors_path.read_text())
    groups = recommendations.setdefault("groups", {})
    rotate_in = list(groups.get("get_into") or [])
    eligible = []
    withheld = []
    states = {"PASS": 0, "REVIEW_REQUIRED": 0, "BLOCKED": 0}

    for card in rotate_in:
        sector_row = _sector_for_card(card, sector_snapshot)
        sector_packet = (sector_row or {}).get("due_diligence") or (
            sector_due_diligence(
                sector_row or {},
                sector_snapshot,
                benchmark=((sector_snapshot.get("evidence") or {}).get("benchmark") or "SPY"),
            ) if sector_row else {}
        )
        packet = defense_due_diligence(
            card,
            sector_snapshot,
            sector_packet=sector_packet,
            oversight=None,
        )
        card["due_diligence"] = packet
        state = packet.get("deterministic_state") or "BLOCKED"
        states[state] = states.get(state, 0) + 1
        if (packet.get("downstream") or {}).get("recommendation_card_eligible"):
            eligible.append(card)
        else:
            withheld.append({
                "card": card,
                "withheld_reason": (packet.get("hard_failures")
                                    or packet.get("warnings")
                                    or ["due diligence did not pass"]),
                "due_diligence_state": state,
                "due_diligence_hash": packet.get("packet_hash"),
            })

    groups["get_into"] = eligible
    recommendations["due_diligence_withheld"] = withheld
    recommendations["due_diligence"] = {
        "contract": "research-due-diligence-v1",
        "adapter": "specialized-research-adapters-v1",
        "domain": "defense",
        "states": states,
        "eligible_get_into": len(eligible),
        "withheld_get_into": len(withheld),
        "authority": (
            "deterministic research gate only; free/OAuth/paid oversight is critique-only "
            "and cannot restore a withheld card"
        ),
    }
    recommendations.pop("snapshot_hash", None)
    recommendations["snapshot_hash"] = snapshot_hash(recommendations)
    recommendations_path.write_text(json.dumps(recommendations, default=str))
    return recommendations["due_diligence"]


def main() -> int:
    result = v10.main()
    if result == 0 and "--dry-run" not in sys.argv and RECOMMENDATIONS.exists() and SECTORS.exists():
        summary = attach_due_diligence()
        print(f"[defense] due diligence {summary['states']} · eligible "
              f"{summary['eligible_get_into']} · withheld {summary['withheld_get_into']}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
