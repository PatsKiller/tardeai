"""CIO reconciliation domain producer — honest internal consistency.

READ_ONLY_ADVISORY. Writes data/reconciliation/state/latest.json from existing
holdings / plans / actions / research queue. Never fabricates broker fills.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"


def _cio() -> Path:
    env = os.environ.get("TRADEAI_CIO_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "cio"


def _holdings_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "portfolios" / "state" / "holdings.json"


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def build() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    holdings = {}
    hp = _holdings_path()
    if hp.is_file():
        try:
            holdings = json.loads(hp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            holdings = {}
    h_as_of = holdings.get("as_of") or holdings.get("generated_at")
    h_dt = _parse(h_as_of)
    holdings_age_h = ((now - h_dt).total_seconds() / 3600.0) if h_dt else None
    holdings_state = "CURRENT" if holdings_age_h is not None and holdings_age_h < 24 else (
        "STALE" if holdings_age_h is not None else "UNAVAILABLE"
    )

    plans_n = draft_n = proposed_n = 0
    try:
        from lib.cio_plans import CIOPlanStore
        store = CIOPlanStore()
        plans = store.list_plans(limit=200) if hasattr(store, "list_plans") else []
        if isinstance(plans, dict):
            plans = plans.get("plans") or []
        plans_n = len(plans)
        for p in plans:
            st = str(p.get("status") or "").lower()
            if st == "draft":
                draft_n += 1
            elif st in {"proposed", "active"}:
                proposed_n += 1
    except Exception:
        pass

    actions_open = 0
    diagnostics = 0
    ledger = _cio() / "cio_action_ledger.jsonl"
    if ledger.is_file():
        folded: dict[str, dict] = {}
        for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            pl = ev.get("payload") if isinstance(ev.get("payload"), dict) else ev
            aid = str(pl.get("action_id") or ev.get("action_id") or "")
            if not aid:
                continue
            folded.setdefault(aid, {}).update(pl)
        for a in folded.values():
            if str(a.get("status") or "").upper() in {"OPEN", "ACKNOWLEDGED"}:
                actions_open += 1
                pri = str(a.get("priority") or a.get("severity") or "").upper()
                src = str(a.get("source") or a.get("actor") or "").lower()
                if "backfill" in src or pri == "LOW" or "system" in src:
                    diagnostics += 1

    pending = 0
    try:
        from lib.hermes_queue_health import build as qh
        pending = int(qh().get("pending") or 0)
    except Exception:
        pass

    inconsistencies = []
    if holdings_state != "CURRENT":
        inconsistencies.append({
            "code": "HOLDINGS_SOURCE_STALE",
            "detail": f"holdings as_of={h_as_of} age_h={holdings_age_h}",
        })
    if draft_n and draft_n >= max(4, int(0.6 * max(plans_n, 1))):
        inconsistencies.append({
            "code": "PLAN_DRAFT_BACKLOG",
            "detail": f"draft={draft_n} of {plans_n}",
        })
    if diagnostics:
        inconsistencies.append({
            "code": "DIAGNOSTIC_ACTIONS_OPEN",
            "detail": f"diagnostics={diagnostics} of open={actions_open}",
        })
    if pending:
        inconsistencies.append({
            "code": "RESEARCH_PENDING",
            "detail": f"pending_challenges={pending}",
        })

    rec = {
        "schema": "CIOReconciliation@v1",
        "reconciled_at": now.isoformat(),
        "authority": AUTHORITY,
        "financial_action": False,
        "holdings_source_as_of": h_as_of,
        "holdings_source_freshness": holdings_state,
        "holdings_source_age_hours": round(holdings_age_h, 2) if holdings_age_h is not None else None,
        "plans_total": plans_n,
        "plans_draft": draft_n,
        "plans_proposed": proposed_n,
        "actions_open": actions_open,
        "actions_diagnostic": diagnostics,
        "actions_operator": max(0, actions_open - diagnostics),
        "research_pending": pending,
        "inconsistencies": inconsistencies,
        "ok": len(inconsistencies) == 0,
        "quality_state": "AVAILABLE",
    }
    return rec


def persist(rec: dict[str, Any] | None = None) -> dict[str, Any]:
    rec = rec or build()
    dests = [
        Path(__file__).resolve().parents[2] / "data" / "reconciliation" / "state" / "latest.json",
        _cio() / "reconciliation_latest.json",
        Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/reconciliation/state/latest.json"),
    ]
    payload = json.dumps(rec, indent=2, sort_keys=True) + "\n"
    written = []
    for dest in dests:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + f".tmp.{os.getpid()}")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, dest)
            written.append(str(dest))
        except Exception:
            continue
    rec["path"] = written[0] if written else ""
    rec["written"] = written
    return rec
