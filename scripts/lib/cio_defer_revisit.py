"""DEFER end-to-end: due → eligibility → exact parent → revalidate → publish.

A due defer is a workflow event. It is not an investment thesis.

Live publication requires:
  production advisory eligibility
  exact parent decision/product lineage
  current capital-plan / research context
  materiality (after provenance)

A raw lineage is never published as CIO NOW.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_alex_telegram import (
    due_defers,
    is_material_event,
    reopen_deferred,
)
from scripts.lib.cio_material_publisher import publish_material_decision
from scripts.lib.cio_office_state import AUTHORITY, fetch_capital_plan
from scripts.lib.cio_production_eligibility import (
    attach_capital_truth,
    cio_state_root,
    classify_advisory_record,
    eligibility_verdict,
    guard_test_cio_write,
    is_forbidden_from_production,
    is_production_advisory_eligible,
    quarantine_record,
)
from scripts.lib.cio_symbol_research import retrieve_symbol_research
from scripts.lib.cio_telegram_transport import cio_delivery_mode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = PROJECT_ROOT / "data" / "audit" / "cio_defer_revisit_last.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _receipt_path() -> Path:
    return guard_test_cio_write(cio_state_root() / "data" / "audit" / "cio_defer_revisit_last.json")


def _append_lineage(row: dict[str, Any]) -> None:
    from scripts.lib.cio_alex_telegram import _defer_path
    path = _defer_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def plan_row_lookup(
    plan: dict[str, Any],
    decision_id: str,
    symbol: str,
    *,
    allow_symbol_fallback: bool = False,
) -> tuple[Optional[dict[str, Any]], str]:
    """Exact decision_id for live publication. Symbol-only is diagnostic only."""
    symbol_hit: Optional[dict[str, Any]] = None
    for row in plan.get("position_decisions") or []:
        if not isinstance(row, dict):
            continue
        if decision_id and str(row.get("decision_id") or "") == str(decision_id):
            return row, "exact_decision_id"
        if symbol and str(row.get("symbol") or "").upper() == symbol.upper() and symbol_hit is None:
            symbol_hit = row
    if allow_symbol_fallback and symbol_hit is not None:
        return symbol_hit, "symbol_only_diagnostic"
    if symbol_hit is not None:
        return None, "symbol_only_refused_for_live"
    return None, "missing"


def _plan_row(plan: dict[str, Any], decision_id: str, symbol: str) -> Optional[dict[str, Any]]:
    """Backward-compatible diagnostic helper (symbol fallback allowed)."""
    row, _how = plan_row_lookup(plan, decision_id, symbol, allow_symbol_fallback=True)
    return row


def decisions_from_due(due: list[dict[str, Any]], *, plan: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Build reopened decisions that are safe to inspect. Does not publish."""
    plan = plan or {}
    out: list[dict[str, Any]] = []
    for lin in due:
        if is_forbidden_from_production(lin):
            continue
        row, how = plan_row_lookup(
            plan, str(lin.get("decision_id") or ""), str(lin.get("symbol") or ""),
            allow_symbol_fallback=False,
        )
        if row is None:
            continue
        reopened = reopen_deferred(lin, decision=dict(row))
        reopened["parent_lookup"] = how
        out.append(reopened)
    return out


def process_due_defers(*, dry_run: bool = True, now: Optional[datetime] = None) -> dict[str, Any]:
    mode = cio_delivery_mode()
    if not dry_run and mode != "CIO_ONLY_LIVE":
        dry_run = True
    due = due_defers(now=now)
    plan = fetch_capital_plan()
    processed: list[dict[str, Any]] = []
    for lin in due:
        did = str(lin.get("decision_id") or "")
        sym = str(lin.get("symbol") or "")
        elig = eligibility_verdict(lin, purpose="production_publication")
        item: dict[str, Any] = {
            "decision_id": did,
            "lineage_id": lin.get("lineage_id"),
            "reopened": False,
            "published": False,
            "eligibility": elig,
            "classification": elig.get("classification"),
        }

        if is_forbidden_from_production(lin) or not is_production_advisory_eligible(
            lin, purpose="production_publication"
        ):
            classified = classify_advisory_record(lin)
            if classified["classification"] in {"SYNTHETIC_E2E", "SYNTHETIC_TEST", "SHADOW"}:
                _append_lineage(quarantine_record(
                    lin,
                    classification=classified["classification"],
                    reason="r610_non_prod_defer_excluded_from_current",
                ))
                item["status"] = "quarantined"
            item["reason"] = "not_production_advisory_eligible"
            processed.append(item)
            continue

        row, how = plan_row_lookup(
            plan if plan.get("ok") is not False else {},
            did, sym, allow_symbol_fallback=False,
        )
        item["parent_lookup"] = how
        if row is None:
            _append_lineage({
                **lin,
                "status": "revalidation_required",
                "classification": "ORPHANED_DEFER",
                "classification_reason": how,
                "revalidation_at": _now(),
            })
            item["status"] = "REVALIDATION_REQUIRED"
            item["reason"] = "exact_parent_unavailable"
            processed.append(item)
            continue

        current = attach_capital_truth(dict(row), plan if plan.get("ok") is not False else None)
        reopened = reopen_deferred(lin, decision=current)
        reopened["parent_lookup"] = how
        item["reopened"] = True
        if is_forbidden_from_production(reopened) or not is_production_advisory_eligible(
            reopened, purpose="production_publication"
        ):
            item["reason"] = "reopened_not_production_eligible"
            processed.append(item)
            continue

        research = retrieve_symbol_research(sym, decision=reopened)
        mat = is_material_event(kind="decision", decision=reopened)
        item["material"] = bool(mat.get("material"))
        item["material_reason"] = mat.get("reason")
        item["research_audit"] = (research.get("decision_use_audit") or {})
        if mat.get("material"):
            pub = publish_material_decision(
                reopened,
                capital_plan=plan if plan.get("ok") is not False else None,
                dry_run=dry_run,
                event_type="DEFER_REOPEN",
            )
            item["published"] = bool(pub.get("published"))
            item["case_id"] = pub.get("case_id")
            item["delivery"] = {
                "delivered": (pub.get("delivery") or {}).get("delivered"),
                "reason": (pub.get("delivery") or {}).get("reason"),
                "dry_run": pub.get("dry_run"),
            }
        else:
            item["reason"] = "reopened_not_material_no_publish"
        processed.append(item)

    receipt = {
        "ok": True,
        "dry_run": dry_run,
        "delivery_mode": mode,
        "authority": AUTHORITY,
        "at": _now(),
        "due": len(due),
        "processed": processed,
        "note": (
            "due defer → production eligibility → exact parent → current truth "
            "→ revalidate → publish only if material. Raw lineage is not a thesis."
        ),
    }
    path = _receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    receipt["receipt_path"] = str(path)
    return receipt
