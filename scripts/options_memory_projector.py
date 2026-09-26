#!/usr/bin/env python3
"""Project the options thesis store into the CIO's bitemporal memory (M2).

    python3 scripts/options_memory_projector.py            # dry run (default): counts + a sample
    python3 scripts/options_memory_projector.py --apply    # write (M2_DSN + authorization required)

Tails data/cio/options_theses.jsonl after a watermark (the last projected
event_hash, kept in data/cio/options_memory_projector_state.json) and writes
each mapped event through CIOEnvelopeIntegrator (source_type
``options_thesis_store``, source_id = event_hash). Idempotent twice over: the
watermark skips what was projected, and before every write the fact table is
checked for a version with that source_id. A decision that supersedes an
earlier one also gets a provenance_edge SUPERSEDES (new fact -> prior fact).

The dry run never connects to a database. ``--apply`` refuses unless M2_DSN is
set; a production DSN is refused unless TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1
(the integrator's existing guard).

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0: no position, order, quantity,
stop, limit or cash field is ever written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

NO_CONSUMER_REASON = (
    "operator/scheduled CLI; not yet on a schedule (crontab is operator-owned). "
    "The CIO options review reads what it writes via options_memory_envelope.load_prior_options_facts."
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import options_memory_projection as proj  # noqa: E402

STATE_NAME = "options_memory_projector_state.json"


def _redact_dsn(dsn: str) -> str:
    """host:port/dbname only — never echo the credential into a log."""
    return str(dsn).rsplit("@", 1)[-1] or "unknown"


def _store_path(path: Optional[str]) -> Path:
    if path:
        return Path(path)
    from scripts.lib.options_thesis import _default_path  # noqa: PLC0415

    return _default_path()


def load_events(path: Path) -> list[dict[str, Any]]:
    from scripts.lib.options_thesis import OptionsThesisStore  # noqa: PLC0415

    return OptionsThesisStore(path)._events()


def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _fact_id_for_source(conn, tenant_id: str, source_id: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT memory_version_id::text
              FROM memory_r10_m2.memory_fact_version
             WHERE tenant_id = %s AND source_type = %s AND source_id = %s
             ORDER BY version_seq DESC
             LIMIT 1
            """,
            (tenant_id, proj.SOURCE_TYPE, source_id),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _write_supersedes_edge(conn, tenant_id: str, *, from_id: str, to_id: str, trace_id: str) -> bool:
    """Insert once. m2_agent holds INSERT on provenance_edge and SELECT on all tables."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM memory_r10_m2.provenance_edge
             WHERE tenant_id = %s AND from_object_id = %s::uuid AND to_object_id = %s::uuid
               AND relation = 'SUPERSEDES'
             LIMIT 1
            """,
            (tenant_id, from_id, to_id),
        )
        if cur.fetchone():
            return False
        cur.execute(
            """
            INSERT INTO memory_r10_m2.provenance_edge
              (tenant_id, from_object_id, to_object_id, relation, source, trace_id)
            VALUES (%s, %s::uuid, %s::uuid, 'SUPERSEDES', %s, %s)
            """,
            (tenant_id, from_id, to_id, proj.PROVENANCE_SOURCE, trace_id),
        )
    return True


def apply_plan(plan: dict[str, Any], *, integrator, state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Write every planned envelope. Advances the watermark only past successes."""
    conn = integrator.connect()
    integrator._set_tenant(conn)
    tenant = integrator.tenant_id
    written = skipped = edges = edges_missing = 0
    errors: list[dict[str, Any]] = []
    for env in plan["envelopes"]:
        sid = env["source_id"]
        try:
            fact_id = _fact_id_for_source(conn, tenant, sid)
            if fact_id:
                skipped += 1
            else:
                body = {k: v for k, v in env.items() if k != "provenance"}
                receipt = integrator.integrate_envelope(body, apply=True, dry_run=False)
                fact_id = receipt.get("memory_version_id")
                written += 1
                integrator._set_tenant(conn)  # the write used a transaction-local tenant
            prov = env.get("provenance")
            if prov and fact_id:
                prior = _fact_id_for_source(conn, tenant, prov["to_source_id"]) if prov.get("to_source_id") else None
                if prior:
                    edges += int(
                        _write_supersedes_edge(
                            conn, tenant, from_id=fact_id, to_id=prior, trace_id=str(env.get("trace_id") or "")
                        )
                    )
                else:
                    edges_missing += 1  # prior decision not in memory: skip gracefully
        except Exception as exc:  # noqa: BLE001 — stop at the first failure, keep the watermark honest
            errors.append(
                {
                    "source_id": sid,
                    "predicate": env.get("predicate"),
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                }
            )
            break
        state["watermark_event_hash"] = sid
    if not errors and plan.get("new_watermark"):
        state["watermark_event_hash"] = plan["new_watermark"]
    state["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state["projected_total"] = int(state.get("projected_total") or 0) + written
    save_state(state_path, state)
    return {
        "written": written,
        "skipped_existing": skipped,
        "provenance_edges": edges,
        "provenance_prior_missing": edges_missing,
        "errors": errors,
        "watermark": state.get("watermark_event_hash"),
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Project options theses into CIO bitemporal memory (M2)")
    ap.add_argument("--apply", action="store_true", help="write to M2 (default: dry run, no connection)")
    ap.add_argument("--store", default=None, help="options_theses.jsonl path (default: the store's own)")
    ap.add_argument("--state", default=None, help="watermark state file (default: next to the store)")
    ap.add_argument("--samples", type=int, default=1, help="mapped envelopes to print in a dry run")
    a = ap.parse_args(argv)

    store = _store_path(a.store)
    state_path = Path(a.state) if a.state else store.parent / STATE_NAME
    state = load_state(state_path)
    events = load_events(store)
    plan = proj.plan(events, state.get("watermark_event_hash"))
    out: dict[str, Any] = {
        "mode": "apply" if a.apply else "dry_run",
        "store": str(store),
        "state": str(state_path),
        **{k: v for k, v in plan.items() if k != "envelopes"},
    }
    if not a.apply:
        out["sample_envelopes"] = plan["envelopes"][: max(a.samples, 0)]
        print(json.dumps(out, indent=1, default=str))
        return 0

    dsn = os.getenv("M2_DSN")
    if not dsn:
        print(json.dumps({**out, "ok": False, "error": "M2_DSN_REQUIRED: --apply needs M2_DSN"}))
        return 2
    from scripts.lib.cio_memory_integration import CIOEnvelopeIntegrator  # noqa: PLC0415

    try:
        integ = CIOEnvelopeIntegrator(dsn=dsn)  # refuses :5432 unless production memory is authorized
    except RuntimeError as exc:
        print(json.dumps({**out, "ok": False, "error": str(exc), "dsn": _redact_dsn(dsn)}))
        return 2
    try:
        res = apply_plan(plan, integrator=integ, state_path=state_path, state=state)
    finally:
        integ.close()
    print(json.dumps({**out, "ok": not res["errors"], "dsn": _redact_dsn(dsn), **res}, indent=1, default=str))
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
