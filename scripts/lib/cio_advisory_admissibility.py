"""Live advisory admissibility (C2).

`is_recommendation_admissible` / `to_block` already exist. This wires them
onto the CIO advisory path. Fail-closed when holdings are unknown.
No broker. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.position_truth import (  # type: ignore
        DISPOSAL_ACTIONS,
        Ownership,
        is_recommendation_admissible,
        ownership_from_holdings,
    )
except ImportError:  # PYTHONPATH=scripts
    from position_truth import (  # type: ignore
        DISPOSAL_ACTIONS,
        Ownership,
        is_recommendation_admissible,
        ownership_from_holdings,
    )

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

UNKNOWN_HOLDING = "unknown_holding_fail_closed"


def holdings_payload_known(holdings: Any) -> bool:
    """A missing file is unknown. An empty holdings list is known (all unheld)."""
    if not isinstance(holdings, dict) or not holdings:
        return False
    return "holdings" in holdings or "generated_at" in holdings or "as_of" in holdings


def admit_advisory(
    *,
    symbol: str,
    recommendation: str,
    holdings: dict[str, Any] | None,
    holdings_available: bool | None = None,
) -> dict[str, Any]:
    """Gate one advisory row. Disposal of an unheld/unknown name is blocked."""
    rec = str(recommendation or "").strip().upper()
    sym = str(symbol or "").strip().upper()
    known = holdings_payload_known(holdings) if holdings_available is None else bool(holdings_available)
    if not rec or not sym or sym in {"PORTFOLIO", "CASH", "MMKT"}:
        return {
            "admissible": True,
            "reason": "",
            "to_block": "",
            "blocked": False,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
        }
    if not known:
        own = Ownership(sym, held=False, source="UNKNOWN", as_of="")
        ok, why = is_recommendation_admissible(ownership=own, recommendation=rec)
        if not ok or rec in DISPOSAL_ACTIONS:
            return {
                "admissible": False,
                "reason": UNKNOWN_HOLDING,
                "to_block": own.to_block(),
                "blocked": True,
                "original_recommendation": rec,
                "authority": AUTHORITY,
                "memory_behavior_influence": MBI,
            }
        return {
            "admissible": True,
            "reason": "",
            "to_block": own.to_block(),
            "blocked": False,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
        }
    own = ownership_from_holdings(sym, holdings or {})
    ok, why = is_recommendation_admissible(ownership=own, recommendation=rec)
    if not ok:
        return {
            "admissible": False,
            "reason": why or "not_held",
            "to_block": own.to_block(),
            "blocked": True,
            "original_recommendation": rec,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
        }
    return {
        "admissible": True,
        "reason": "",
        "to_block": own.to_block(),
        "blocked": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def gate_recommendation_row(row: dict[str, Any], *, holdings: dict[str, Any] | None,
                            holdings_available: bool | None = None) -> dict[str, Any]:
    """Rewrite a blocked disposal rec to NO_ACTION. Keep the row for the operator."""
    out = dict(row or {})
    rec = out.get("recommended_action") or out.get("decision") or out.get("cio_decision") or out.get("action")
    sym = out.get("symbol") or out.get("entity")
    gate = admit_advisory(
        symbol=str(sym or ""),
        recommendation=str(rec or ""),
        holdings=holdings,
        holdings_available=holdings_available,
    )
    out["admissible"] = gate["admissible"]
    if gate["blocked"]:
        out["blocked"] = True
        out["block_reason"] = gate["reason"]
        out["to_block"] = gate["to_block"]
        out["original_recommendation"] = gate.get("original_recommendation") or rec
        out["recommended_action"] = "NO_ACTION"
        if "decision" in out or "cio_decision" in out:
            out["decision"] = "NO_ACTION"
            out["cio_decision"] = "NO_ACTION"
        blockers = list(out.get("blocking_conditions") or [])
        blockers.append(gate["reason"])
        out["blocking_conditions"] = blockers
    return out


def gate_recommendation_rows(rows: list[dict[str, Any]], *, holdings: dict[str, Any] | None,
                             holdings_available: bool | None = None) -> list[dict[str, Any]]:
    return [
        gate_recommendation_row(r, holdings=holdings, holdings_available=holdings_available)
        for r in (rows or []) if isinstance(r, dict)
    ]
