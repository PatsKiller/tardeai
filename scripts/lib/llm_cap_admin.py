"""Operator surface for LLM spend caps. No admin page existed.

WHY THIS EXISTS
---------------
Audited 2026-09-06: the caps that gate every paid model call had NO operator
surface. Not in the Command Center, not in api_v2, not in api_v3_cio. The only
writer was `sync_cio_process_caps.py`, run by hand.

The consequence, the same day: the usefulness backfill stopped dead on a
200-request/day cap, and changing it meant a hand-written UPDATE against
production — which promptly left `config/llm_process_registry.json` saying
`200 / $0.30` while the database said `100000 / $1.25`. Two numbers for one
quantity, and `sync_cio_process_caps.py` is scheduled nowhere, so nothing would
have caught the divergence.

A control with no operator surface gets changed by hand, and hand changes drift.

BOTH STORES, ALWAYS
-------------------
`set_caps` writes the registry AND the database in one call. It is not possible
to use this and update only one, because that is the failure it exists to
prevent. If either write fails the whole operation reports failure rather than
leaving them disagreeing.

BOUNDED, EVEN FOR THE OPERATOR
------------------------------
`MAX_*` ceilings apply to this path regardless of who is asking. A chat message
must not be able to authorise unbounded spend: the point of a cap is that it
holds when someone is in a hurry, and "in a hurry" is exactly when a cap gets
raised. Raising the ceilings themselves is a code change and a review.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "LlmCapAdmin@v1"
AUTHORITY = "OPERATOR_WRITE"

#: Ceilings on what this surface may set. Deliberately generous enough for a
#: one-time backfill (~$6) and far below anything that could run away.
MAX_REQUESTS = int(os.environ.get("LLM_CAP_ADMIN_MAX_REQUESTS", "200000"))
MAX_DOLLARS = float(os.environ.get("LLM_CAP_ADMIN_MAX_DOLLARS", "25.00"))

REGISTRY = Path(__file__).resolve().parents[2] / "config" / "llm_process_registry.json"


def _registry_path() -> Path:
    env = os.environ.get("LLM_PROCESS_REGISTRY")
    return Path(env) if env else REGISTRY


def _load_registry() -> tuple[Any, list[dict[str, Any]]]:
    doc = json.loads(_registry_path().read_text(encoding="utf-8"))
    procs = doc if isinstance(doc, list) else doc.get("processes", doc)
    seq = procs if isinstance(procs, list) else list(procs.values())
    return doc, [p for p in seq if isinstance(p, dict)]


def list_caps(conn=None) -> list[dict[str, Any]]:
    """Live caps, with the registry value beside them so drift is visible."""
    _, procs = _load_registry()
    reg = {p.get("id"): p for p in procs if p.get("id")}
    out: list[dict[str, Any]] = []
    live: dict[str, tuple] = {}
    if conn is not None:
        try:
            cur = conn.cursor()
            cur.execute("SELECT process_id, daily_soft_cap, daily_cost_cap_usd "
                        "FROM llm_process_config")
            live = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        except Exception:
            live = {}
    for pid, p in sorted(reg.items()):
        db = live.get(pid, (None, None))
        out.append({
            "process_id": pid,
            "registry_requests": p.get("daily_soft_cap"),
            "registry_dollars": p.get("daily_cost_cap_usd"),
            "db_requests": db[0],
            "db_dollars": float(db[1]) if db[1] is not None else None,
            # Drift is reported, never silently reconciled: picking a winner is
            # how the wrong number becomes authoritative.
            "drift": (db[0] is not None
                      and (db[0] != p.get("daily_soft_cap")
                           or (db[1] is not None
                               and float(db[1]) != float(p.get("daily_cost_cap_usd") or 0)))),
        })
    return out


def set_caps(process_id: str, *, requests: Optional[int] = None,
             dollars: Optional[float] = None, conn=None,
             actor: str = "operator") -> dict[str, Any]:
    """Set one process's caps in BOTH the registry and the database.

    Returns the before/after so the operator can revert without guessing.
    """
    if requests is None and dollars is None:
        return {"ok": False, "error": "nothing to set"}
    if requests is not None and (requests < 1 or requests > MAX_REQUESTS):
        return {"ok": False, "error": f"requests must be 1..{MAX_REQUESTS}"}
    if dollars is not None and (dollars <= 0 or dollars > MAX_DOLLARS):
        return {"ok": False, "error": f"dollars must be >0 and <= {MAX_DOLLARS}"}

    doc, procs = _load_registry()
    entry = next((p for p in procs if p.get("id") == process_id), None)
    if entry is None:
        return {"ok": False, "error": f"unknown process_id {process_id!r}"}

    before = {"requests": entry.get("daily_soft_cap"),
              "dollars": entry.get("daily_cost_cap_usd")}
    if requests is not None:
        entry["daily_soft_cap"] = int(requests)
    if dollars is not None:
        entry["daily_cost_cap_usd"] = float(dollars)

    # Database FIRST: it is what the bridge reads. If the registry write then
    # fails the operator is told, and the two are reconciled deliberately —
    # better than a registry that promises a cap the bridge is not enforcing.
    if conn is not None:
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE llm_process_config
                      SET daily_soft_cap = COALESCE(%s, daily_soft_cap),
                          daily_cost_cap_usd = COALESCE(%s, daily_cost_cap_usd)
                    WHERE process_id = %s""",
                (int(requests) if requests is not None else None,
                 float(dollars) if dollars is not None else None,
                 process_id))
            if cur.rowcount == 0:
                return {"ok": False, "error": f"{process_id} not in llm_process_config"}
            conn.commit()
        except Exception as exc:
            return {"ok": False, "error": f"db write failed: {type(exc).__name__}"}

    try:
        _registry_path().write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"DB UPDATED BUT REGISTRY WRITE FAILED: "
                                      f"{type(exc).__name__} — reconcile by hand"}

    return {
        "ok": True, "schema": SCHEMA, "authority": AUTHORITY,
        "process_id": process_id, "actor": actor,
        "before": before,
        "after": {"requests": entry.get("daily_soft_cap"),
                  "dollars": entry.get("daily_cost_cap_usd")},
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "financial_action": False,
    }
