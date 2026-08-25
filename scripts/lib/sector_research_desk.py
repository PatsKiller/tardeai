"""Persistent sector/industry theses, independent of ticker theses."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI
from scripts.lib.security_identity import normalize_symbol
from scripts.lib.transferson_universe import get_symbol

SCHEMA = "SectorIndustryThesis@v1"
PATH = "data/cio/office/sector_theses.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _append(root: Path, row: dict[str, Any]) -> None:
    path = root / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def build_sector_theses(
    root: Path | str,
    manifest: dict[str, Any],
    *,
    persist: bool = True,
    focus_symbol: str | None = None,
) -> dict[str, Any]:
    focus = get_symbol(manifest, focus_symbol) if focus_symbol else None
    by_sector: dict[str, list[dict[str, Any]]] = {}
    by_industry: dict[str, list[dict[str, Any]]] = {}
    for rec in manifest.get("securities") or []:
        if rec.get("sector"):
            if focus and rec.get("sector") != focus.get("sector"):
                pass
            else:
                by_sector.setdefault(str(rec["sector"]), []).append(rec)
        if rec.get("industry"):
            if focus and rec.get("industry") != focus.get("industry"):
                pass
            else:
                by_industry.setdefault(str(rec["industry"]), []).append(rec)
    if focus:
        by_sector = {k: v for k, v in by_sector.items() if k == focus.get("sector")} if focus.get("sector") else {}
        by_industry = {k: v for k, v in by_industry.items() if k == focus.get("industry")} if focus.get("industry") else {}
    rows = []
    for kind, groups in (("sector", by_sector), ("industry", by_industry)):
        for name, members in groups.items():
            held = [m["symbol"] for m in members if m.get("currently_held")]
            leadership = sorted(members, key=lambda m: str(m.get("current_research_tier") or "T3-COLD"))
            row = {
                "schema": SCHEMA,
                "sector_thesis_id": f"{kind}:{name}",
                "kind": kind,
                "name": name,
                "structure": "UNRESOLVED",
                "drivers": [],
                "cycle_position": "UNRESOLVED",
                "leading_indicators": [],
                "valuation_state": "UNRESOLVED",
                "earnings_revisions": "UNRESOLVED",
                "catalysts": sorted({g for m in members for g in (m.get("catalyst_guids") or [])})[:12],
                "risks": ["UNRESOLVED"],
                "leadership": [m["symbol"] for m in leadership if m.get("current_research_tier") in {"T0-HOLD", "T0-PROP", "T1-WATCH"}][:8],
                "laggards": [m["symbol"] for m in members if m.get("current_research_tier") == "T3-COLD"][:8],
                "historical_analogues": [],
                "unresolved_questions": [
                    f"What is the current cycle position of {name}?",
                    f"Which leading indicators matter for {name}?",
                ],
                "current_theory": None,
                "member_n": len(members),
                "held": held,
                "updated_at": _now(),
                "authority": AUTHORITY,
            }
            rows.append(row)
            if persist:
                _append(Path(root), row)
    return {
        "schema": "SectorDeskSnapshot@v1",
        "n": len(rows),
        "rows": rows,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def inherit_sector_context(manifest: dict[str, Any], symbol: str, desk: dict[str, Any]) -> dict[str, Any]:
    rec = get_symbol(manifest, symbol) or {}
    matches = [
        r for r in (desk.get("rows") or [])
        if (r.get("kind") == "sector" and r.get("name") == rec.get("sector"))
        or (r.get("kind") == "industry" and r.get("name") == rec.get("industry"))
    ]
    discover = []
    for r in matches:
        discover.extend(r.get("leadership") or [])
        discover.extend(r.get("laggards") or [])
    discover = [normalize_symbol(s) for s in discover if normalize_symbol(s) != normalize_symbol(symbol)]
    return {
        "symbol": rec.get("symbol"),
        "sector": rec.get("sector"),
        "industry": rec.get("industry"),
        "inherited": matches,
        "discovered_related_tickers": sorted(set(discover))[:20],
        "authority": AUTHORITY,
    }
