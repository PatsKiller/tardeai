"""DEFER end-to-end: due → reopen same lineage → revalidate → publish if material.

The systemd unit must call this module, not ``print(len(due_defers()))``.

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
from scripts.lib.cio_symbol_research import retrieve_symbol_research
from scripts.lib.cio_telegram_transport import cio_delivery_mode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = PROJECT_ROOT / "data" / "audit" / "cio_defer_revisit_last.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_row(plan: dict[str, Any], decision_id: str, symbol: str) -> Optional[dict[str, Any]]:
    for row in plan.get("position_decisions") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("decision_id") or "") == str(decision_id):
            return row
        if symbol and str(row.get("symbol") or "").upper() == symbol.upper():
            return row
    return None


def decisions_from_due(due: list[dict[str, Any]], *, plan: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Build reopened decisions (does not publish). Used by the material scanner."""
    plan = plan or {}
    out: list[dict[str, Any]] = []
    for lin in due:
        row = _plan_row(plan, str(lin.get("decision_id") or ""), str(lin.get("symbol") or ""))
        base = dict(row or {})
        reopened = reopen_deferred(lin, decision=base)
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
        row = _plan_row(plan, did, sym) if plan.get("ok") is not False else None
        reopened = reopen_deferred(lin, decision=dict(row or {}))
        research = retrieve_symbol_research(sym, decision=reopened)
        mat = is_material_event(kind="decision", decision=reopened)
        item: dict[str, Any] = {
            "decision_id": did,
            "lineage_id": lin.get("lineage_id"),
            "reopened": True,
            "material": bool(mat.get("material")),
            "material_reason": mat.get("reason"),
            "research_audit": (research.get("decision_use_audit") or {}),
            "published": False,
        }
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
        "note": "due defer → reopen same decision_id → revalidate current plan/research → publish only if material",
    }
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    receipt["receipt_path"] = str(RECEIPT_PATH)
    return receipt
