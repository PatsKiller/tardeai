#!/usr/bin/env python3
"""Defense recommendation v11 launcher with shared due-diligence gating.

The v10 launcher still owns account-specific exposure, sizing and stock-quality
math and delegates mature protection/trim/hedge paths to the established engine.
This additive v11 postprocessor:

- binds every rotate-in card to the upstream sector research packet and withholds
  non-passing cards from ``groups.get_into``;
- attaches the shared evidence-maturity contract to every other recommendation
  group, pair and stance without changing its mechanics;
- retains every non-passing object for audit;
- defers free critics until deterministic attachment is complete, then sends
  only PASS or REVIEW_REQUIRED cards through the strict v2 oversight contract.

No recommendation is activated, no proposal state is changed and no
broker/order/approval/2FA path exists here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import defense_recommendations_v10 as v10
from defense_data_quality import snapshot_hash
from defense_research_due_diligence import defense_card_due_diligence
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
    return next(
        (row for row in rows
         if str(row.get("sector") or "").upper() in title),
        None,
    )


def _record_state(states: dict, by_group: dict, group: str, packet: dict) -> str:
    state = packet.get("deterministic_state") or "BLOCKED"
    states[state] = states.get(state, 0) + 1
    group_counts = by_group.setdefault(
        group, {"PASS": 0, "REVIEW_REQUIRED": 0, "BLOCKED": 0}
    )
    group_counts[state] = group_counts.get(state, 0) + 1
    return state


def _annotate_non_rotate_groups(recommendations: dict, states: dict,
                                by_group: dict) -> None:
    groups = recommendations.setdefault("groups", {})
    for group, cards in list(groups.items()):
        if group == "get_into" or not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            card.setdefault("group", group)
            packet = defense_card_due_diligence(card, recommendations)
            card["due_diligence"] = packet
            _record_state(states, by_group, group, packet)

    for pair in recommendations.get("pairs") or []:
        if not isinstance(pair, dict):
            continue
        pair.setdefault("group", "pair")
        packet = defense_card_due_diligence(pair, recommendations)
        pair["due_diligence"] = packet
        _record_state(states, by_group, "pair", packet)

    snapshot_mode = recommendations.get("mode")
    for stance in recommendations.get("stances") or []:
        if not isinstance(stance, dict):
            continue
        view = {
            **stance,
            "id": stance.get("id") or (
                f"stance-{stance.get('symbol')}-{stance.get('account')}"
            ),
            "group": "stance",
            "title": stance.get("title") or (
                f"{stance.get('symbol')} {stance.get('stance')}"
            ),
            "mode": stance.get("mode") or snapshot_mode,
            "accounts": [stance.get("account")] if stance.get("account") else [],
            "instruments": [{"symbol": stance.get("symbol")}]
            if stance.get("symbol") else [],
            "rationale": stance.get("reason"),
            "on_trigger": stance.get("on_trigger"),
        }
        packet = defense_card_due_diligence(view, recommendations)
        stance["due_diligence"] = packet
        _record_state(states, by_group, "stance", packet)


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
    by_group: dict[str, dict] = {}

    for card in rotate_in:
        sector_row = _sector_for_card(card, sector_snapshot)
        sector_packet = (sector_row or {}).get("due_diligence") or (
            sector_due_diligence(
                sector_row or {},
                sector_snapshot,
                benchmark="SPY",
            ) if sector_row else {}
        )
        packet = defense_due_diligence(
            card,
            sector_snapshot,
            sector_packet=sector_packet,
            oversight=None,
        )
        card["due_diligence"] = packet
        state = _record_state(states, by_group, "get_into", packet)
        if (packet.get("downstream") or {}).get("recommendation_card_eligible"):
            eligible.append(card)
        else:
            withheld.append({
                "card": card,
                "withheld_reason": (
                    packet.get("hard_failures")
                    or packet.get("warnings")
                    or ["due diligence did not pass"]
                ),
                "due_diligence_state": state,
                "due_diligence_hash": packet.get("packet_hash"),
            })

    groups["get_into"] = eligible
    _annotate_non_rotate_groups(recommendations, states, by_group)
    recommendations["due_diligence_withheld"] = withheld
    recommendations["due_diligence"] = {
        "contract": "research-due-diligence-v1",
        "policy": "research-due-diligence-policy-v1",
        "adapters": [
            "specialized-research-adapters-v1",
            "defense-all-groups-due-diligence-v1",
        ],
        "domain": "defense",
        "states": states,
        "states_by_group": by_group,
        "eligible_get_into": len(eligible),
        "withheld_get_into": len(withheld),
        "all_recommendation_groups_assessed": True,
        "authority": (
            "deterministic research gate only; free/OAuth/paid oversight is "
            "critique-only and cannot restore a withheld card or activate advice"
        ),
    }
    recommendations.pop("snapshot_hash", None)
    recommendations["snapshot_hash"] = snapshot_hash(recommendations)
    recommendations_path.write_text(json.dumps(recommendations, default=str))
    return recommendations["due_diligence"]


def _run_post_attachment_oversight() -> dict:
    import defense_oversight_v2 as oversight
    from db_adapter import _get_conn

    oversight.activate_free()
    conn = _get_conn()
    cur = conn.cursor()
    try:
        result = oversight.run_free_critiques(cur)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def main() -> int:
    import defense_oversight_v2 as oversight

    # The inherited v10 producer normally calls critics before returning. Defer
    # that exact call so the shared deterministic packet exists first.
    oversight.install(defer_free=True)
    result = v10.main()
    if (
        result == 0
        and "--dry-run" not in sys.argv
        and RECOMMENDATIONS.exists()
        and SECTORS.exists()
    ):
        summary = attach_due_diligence()
        print(
            f"[defense] due diligence {summary['states']} · eligible "
            f"{summary['eligible_get_into']} · withheld "
            f"{summary['withheld_get_into']}"
        )
        try:
            review = _run_post_attachment_oversight()
            print(
                f"[defense] oversight after diligence: {review.get('seats', {})} · "
                f"provider calls {review.get('provider_calls', 0)}"
            )
        except Exception as exc:
            print(
                "[defense] oversight after diligence skipped: "
                + str(exc).splitlines()[0][:120]
            )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
