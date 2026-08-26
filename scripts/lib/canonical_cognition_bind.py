"""Bind sector / industry / catalyst events into CIOOperatorProduct sections.

Uses existing producers (sector_momentum_latest, industry_momentum_latest,
catalyst files). Does not create a parallel model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

MATERIALITY = (
    "INFORMATIONAL",
    "CONTEXT_CHANGE",
    "MATERIAL_TO_PORTFOLIO",
    "MATERIAL_TO_WATCH",
    "THESIS_RELEVANT",
)
ACTIONABLE = frozenset({
    "CONTEXT_CHANGE", "MATERIAL_TO_PORTFOLIO", "MATERIAL_TO_WATCH", "THESIS_RELEVANT",
})
NO_EVENTS = "NO_RELEVANT_CURRENT_EVENTS"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def classify_sector_row(row: dict[str, Any], *, transition: dict[str, Any] | None = None) -> str:
    pct = float(row.get("book_pct") or 0)
    if transition and pct >= 3:
        return "MATERIAL_TO_PORTFOLIO"
    if transition and pct < 3:
        return "CONTEXT_CHANGE" if pct > 0 else "INFORMATIONAL"
    if pct >= 10:
        return "MATERIAL_TO_PORTFOLIO"
    if pct >= 3:
        return "CONTEXT_CHANGE"
    return "INFORMATIONAL"


def classify_industry_row(row: dict[str, Any]) -> str:
    held = list(row.get("held") or [])
    watched = list(row.get("watched") or [])
    if held and str(row.get("state") or "") in {"LEADING", "IMPROVING", "WEAKENING"}:
        return "MATERIAL_TO_PORTFOLIO"
    if watched:
        return "MATERIAL_TO_WATCH"
    return "INFORMATIONAL"


def sector_delta_to_product(
    event: dict[str, Any],
    *,
    holdings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sector = event.get("sector") or event.get("industry")
    frm = event.get("from") or event.get("from_state")
    to = event.get("to") or event.get("to_state") or event.get("state")
    contrib = event.get("book_contributors") or event.get("held") or []
    names = []
    for c in contrib[:6]:
        if isinstance(c, dict):
            names.append(str(c.get("fund") or c.get("symbol") or ""))
        else:
            names.append(str(c))
    names = [n for n in names if n]
    pct = event.get("book_pct")
    if pct is None:
        pct = event.get("exposure_pct") or 0
    materiality = event.get("materiality") or classify_sector_row(
        {"book_pct": pct},
        transition={"from": frm, "to": to} if frm and to and frm != to else None,
    )
    prose = (
        f"{sector} {('moved ' + str(frm) + '→' + str(to)) if frm and to and frm != to else 'is ' + str(to or event.get('state'))}. "
        f"You have {pct}% exposure ({', '.join(names) if names else 'no tagged names'}). "
        "No portfolio change recommended unless the CIO decision list says otherwise."
    )
    return {
        "schema": "SectorResearchDelta@v1",
        "sector": sector,
        "industry": event.get("industry"),
        "from_state": frm,
        "to_state": to,
        "state": event.get("state") or to,
        "exposure_pct": pct,
        "affected_holdings": names,
        "materiality": materiality,
        "cio_implication": "NO_ACTION unless a named decision says otherwise",
        "operator_action": "NO_ACTION",
        "cio_decision": "NO_ACTION",
        "prose": prose,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def catalyst_to_product(event: dict[str, Any]) -> dict[str, Any]:
    entity = event.get("entity") or event.get("symbol")
    return {
        "schema": "CatalystBinding@v1",
        "catalyst": event.get("catalyst") or event.get("title") or event.get("type") or event.get("catalyst_type"),
        "entity": entity,
        "when": event.get("when") or event.get("date") or event.get("as_of"),
        "materiality": event.get("materiality") or "THESIS_RELEVANT",
        "why_relevant": event.get("why_relevant") or event.get("headline") or event.get("rationale") or "",
        "affected_holdings": list(event.get("held") or ([entity] if entity else [])),
        "affected_watch": list(event.get("watched") or []),
        "research_state": event.get("research_state") or "UNSCHEDULED",
        "next_review": event.get("next_review") or event.get("when"),
        "traceable_to_entity": bool(entity),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def bind_market_context(*, root: Path | str) -> dict[str, Any]:
    base = Path(root)
    sector_doc = _load_json(base / "data/runtime/sector_momentum_latest.json")
    industry_doc = _load_json(base / "data/runtime/industry_momentum_latest.json")
    transitions = {str(t.get("sector")): t for t in (sector_doc.get("transitions_today") or []) if isinstance(t, dict)}

    sectors = []
    for row in sector_doc.get("rows") or []:
        if not isinstance(row, dict):
            continue
        t = transitions.get(str(row.get("sector")))
        event = {**row, "from": (t or {}).get("from"), "to": (t or {}).get("to") or row.get("state")}
        bound = sector_delta_to_product(event)
        if bound.get("materiality") in ACTIONABLE:
            sectors.append(bound)

    industries = []
    for row in industry_doc.get("industries") or []:
        if not isinstance(row, dict):
            continue
        mat = classify_industry_row(row)
        if mat not in ACTIONABLE:
            continue
        held = list(row.get("held") or [])
        industries.append({
            "industry": row.get("industry"),
            "sector": row.get("sector"),
            "state": row.get("state"),
            "held": held,
            "watched": list(row.get("watched") or [])[:6],
            "rel1w": row.get("rel1w"),
            "materiality": mat,
            "prose": (
                f"{row.get('industry')} is {row.get('state')} (rel1w {row.get('rel1w')}). "
                f"Held: {', '.join(held) if held else 'none'}."
            ),
            "operator_action": "NO_ACTION",
            "authority": AUTHORITY,
            "financial_action": False,
        })

    catalysts = _collect_catalysts(base, held_symbols=_held_from_sector(sector_doc))
    return {
        "sector": sectors,
        "industry": industries[:12],
        "catalysts": catalysts,
        "sector_reason": None if sectors else NO_EVENTS,
        "industry_reason": None if industries else NO_EVENTS,
        "catalysts_reason": None if catalysts else NO_EVENTS,
        "binding": "sector_momentum_latest + industry_momentum_latest + catalyst files",
        "authority": AUTHORITY,
        "financial_action": False,
    }


def _held_from_sector(doc: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in doc.get("rows") or []:
        for c in row.get("book_contributors") or []:
            if isinstance(c, dict) and c.get("fund"):
                out.add(str(c["fund"]).upper())
    return out


def _collect_catalysts(root: Path, *, held_symbols: set[str]) -> list[dict[str, Any]]:
    cat_dir = root / "data/hermes/momentum_catalysts"
    rows: list[dict[str, Any]] = []
    if cat_dir.is_dir():
        files = sorted(cat_dir.glob("*_catalysts.jsonl"))[-5:]
        for p in files:
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    sym = str(obj.get("symbol") or obj.get("ticker") or "").upper()
                    if held_symbols and sym and sym not in held_symbols:
                        continue
                    if not sym and not obj.get("headline"):
                        continue
                    rows.append(catalyst_to_product({**obj, "symbol": sym or obj.get("entity")}))
            except OSError:
                continue
    # Cap operator-facing list.
    return rows[:12]
