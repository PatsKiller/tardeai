#!/usr/bin/env python3
"""Pure composition pipeline for specialized research and proposals.

No database, network, provider or filesystem writes. Producers call these
functions before persistence or proposal handoff.
"""
from __future__ import annotations

from specialized_research_due_diligence import (
    defense_packet,
    industry_packet,
    proposal_packet,
    sector_packet,
)


def enrich_sector_rows(rows: list[dict]) -> list[dict]:
    enriched = []
    for original in rows or []:
        row = dict(original)
        row["due_diligence"] = sector_packet(row)
        row["proposal_research_eligible"] = row["due_diligence"]["release_allowed"]
        enriched.append(row)
    return enriched


def enrich_industry_snapshot(snapshot: dict) -> dict:
    result = dict(snapshot or {})
    industries = []
    for original in result.get("industries") or []:
        row = dict(original)
        row["due_diligence"] = industry_packet(row, result)
        row["proposal_research_eligible"] = row["due_diligence"]["release_allowed"]
        industries.append(row)
    result["industries"] = industries
    by_name = {row.get("industry"): row for row in industries}

    candidates = dict(result.get("candidates") or {})
    for lane in ("defensive_short_pool", "watch_rail"):
        normalized = []
        for candidate in candidates.get(lane) or []:
            item = dict(candidate)
            research = by_name.get(item.get("industry"), {}).get("due_diligence")
            item["due_diligence"] = research
            item["proposal_research_eligible"] = bool(
                research and research.get("release_allowed")
            )
            normalized.append(item)
        candidates[lane] = normalized
    result["candidates"] = candidates
    result["due_diligence_contract"] = "research-due-diligence-v1"
    return result


def enrich_defense_cards(
    cards: list[dict],
    sector_rows: list[dict],
    industry_snapshot: dict,
) -> list[dict]:
    sector_by_name = {row.get("sector"): row for row in (sector_rows or [])}
    industry_by_name = {
        row.get("industry"): row for row in (industry_snapshot or {}).get("industries") or []
    }
    output = []
    for original in cards or []:
        card = dict(original)
        title = str(card.get("title") or "")
        sector = next(
            (row for name, row in sector_by_name.items() if name and name in title),
            {},
        )
        dependencies = []
        for instrument in card.get("instruments") or []:
            industry = instrument.get("industry") or (instrument.get("quality") or {}).get("industry")
            packet = (industry_by_name.get(industry) or {}).get("due_diligence")
            if packet:
                dependencies.append(packet)
        card["due_diligence"] = defense_packet(card, sector, dependencies)
        card["proposal_research_eligible"] = card["due_diligence"]["release_allowed"]
        output.append(card)
    return output


def build_proposal_research(subject: str, *packets: dict) -> dict:
    return proposal_packet(subject, [packet for packet in packets if packet])
