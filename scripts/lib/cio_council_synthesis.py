"""CIOCouncilSynthesis@v1 — deterministic join. The council does not think.

Wave 3B. Joins VALID `SpecialistArtifact` rows with CASE_SUMMARY, the desk pin
and thesis fields into a synthesis block the operator product can already
render.

Two rules make this a join rather than a council:

  1. **No model is called.** A test asserts the module contains no provider
     client and no `build_product`-style model hop.
  2. **Disagreement is labelled, not resolved.** If two VALID artifacts take
     opposite positions the block is `DISPUTED` and both are shown. Picking a
     winner is exactly the judgement that would require a model, and a
     deterministic tie-break would be a fake one — an alphabetically-first
     provider is not more correct.

It also mints nothing: no plan is created or attached here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

COUNCIL_SCHEMA = "CIOCouncilSynthesis@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

AGREED = "AGREED"
DISPUTED = "DISPUTED"
SINGLE = "SINGLE_SOURCE"
NO_INPUT = "NO_VALID_ARTIFACTS"

# T/D/A labels the operator product already renders.
LABELS = ("THESIS", "DIVERGENCE", "ACTIONABILITY")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _position(artifact: dict[str, Any]) -> Optional[str]:
    """A coarse stance, read only from explicit fields.

    Never inferred from prose: parsing a sentence for a stance is the kind of
    silent judgement this module exists to avoid.
    """
    for key in ("position", "stance", "verdict"):
        v = artifact.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
    return None


def synthesize(*, artifacts: Optional[list[dict[str, Any]]] = None,
               case_summary: Optional[dict[str, Any]] = None,
               desk_pin: Optional[dict[str, Any]] = None,
               thesis_fields: Optional[dict[str, Any]] = None,
               workflow_id: str | None = None,
               plan_id: str | None = None,
               symbol: str | None = None) -> dict[str, Any]:
    """Join the inputs. Deterministic, offline, mints nothing."""
    rows = [a for a in (artifacts or [])
            if isinstance(a, dict) and a.get("outcome") == "VALID"]
    considered = list(artifacts or [])

    positions = {}
    for a in rows:
        p = _position(a)
        if p:
            positions.setdefault(p, []).append(a.get("artifact_id"))

    if not rows:
        state = NO_INPUT
    elif len(positions) > 1:
        state = DISPUTED
    elif len(rows) == 1:
        state = SINGLE
    else:
        state = AGREED

    block = {
        "schema": COUNCIL_SCHEMA,
        "as_of": _utc(),
        "authority": AUTHORITY,
        "workflow_id": workflow_id,
        "financial_action": False,
        "plan_id": plan_id,
        "symbol": symbol,
        "state": state,
        "positions": positions,
        "artifact_ids": [a.get("artifact_id") for a in rows],
        "artifacts_considered": len(considered),
        "artifacts_valid": len(rows),
        "excluded_non_valid": [
            {"artifact_id": a.get("artifact_id"), "outcome": a.get("outcome")}
            for a in considered if a.get("outcome") != "VALID"
        ],
        "case_summary_present": bool(case_summary),
        "desk_pin": (desk_pin or {}).get("pin") if isinstance(desk_pin, dict) else None,
        "thesis_fields": dict(thesis_fields or {}),
        "source_refs": [r for a in rows for r in (a.get("source_refs") or [])],
        "total_cost_usd": round(
            sum(float(a.get("cost_usd") or 0) for a in considered), 6),
        "model_called": False,
        "mints_plan": False,
        "attaches_plan": False,
        "labels": list(LABELS),
    }
    if state == DISPUTED:
        block["disputed_note"] = (
            "Two or more VALID artifacts take different positions. Both are "
            "shown. No winner is selected: choosing one would require the "
            "judgement this join deliberately does not make.")
    return block


def render_lines(block: dict[str, Any]) -> list[str]:
    """T/D/A lines for the operator product. Descriptive, never imperative."""
    state = block.get("state")
    out = [f"THESIS: {block.get('symbol') or 'book'} — council {state.lower()}"
           if state else "THESIS: council unavailable"]
    if state == DISPUTED:
        pos = ", ".join(sorted(block.get("positions") or {}))
        out.append(f"DIVERGENCE: specialists disagree ({pos}); no winner selected")
    elif state == NO_INPUT:
        out.append("DIVERGENCE: no VALID artifact to synthesise")
    else:
        out.append(f"DIVERGENCE: none recorded across "
                   f"{block.get('artifacts_valid', 0)} valid artifact(s)")
    out.append(f"ACTIONABILITY: advisory context only "
               f"(cost ${block.get('total_cost_usd', 0):.2f}, no plan minted)")
    return out
