#!/usr/bin/env python3
"""n8n_comms_intent_consumer.py — QUEUED n8n comms intents become incident fan-in incidents.

The host side of the gateway's ``comms/intent`` operation (PR #1739). n8n asks; the host decides (AGENTS.md §23.23)
and the host comms gateway is the only sender (§24.1). The operator chose the incident fan-in route: an intent never
becomes a message of its own. Each QUEUED intent is claimed (QUEUED -> CLAIMED -> DONE | FAILED), mapped through the
closed route table (config/n8n_comms_intent_routes.json) to a fan-in incident at the route's tier (DIGEST -> P2), and
folded into the OPEN incident for the same workflow and kind when one exists. scripts/n8n_incident_fanin.py reads the
open incidents; scripts/incident_notifier.py's P2 batch carries them to the operator. Mechanics and the dead-letter
rule: scripts/lib/n8n_comms_intent_consumption.py.

    python3 scripts/n8n_comms_intent_consumer.py              # --dry-run (default): mode=ro, writes nothing
    python3 scripts/n8n_comms_intent_consumer.py --apply

Paths: the ledger is --ledger, else TRADEAI_N8N_COORDINATION_LEDGER, else
<state root>/data/governance/n8n_coordination_ledger.sqlite; the state root is --state-root, else TRADEAI_STATE_ROOT,
else ~/trade-ai-releases/persistent-state. An apply run writes LaneRunReceipt@v1
<state root>/data/runtime/n8n-comms-intent-consumer_last.json (ok_at only on success); a dry run prints
``DRY-RUN {...}`` and writes no file, no table and no receipt.

Exit: 0 = the run completed (a refused intent is a finding, not a failed run); 1 = the ledger or the route table could
not be read, or a write failed, or an intent failed transiently; 2 = usage.

Output verdict (2026-10-17, lane live on the n8n fabric at */5; config/n8n_health_contracts.json expected_output,
allowlist ``output_receipt: v2``): every apply run's receipt carries the LaneRunReceipt@v2 output fields (``output=``
spelling, so ``_last.json`` stays v1 for v1 readers and the executor gets the immutable per-attempt v2 copy).
produced = intents this run moved to DONE + DONE intents whose incident it refreshed; attempted = produced + refused
+ claim-lost + transient. An empty queue is ``empty_reason: no_new_input``; a run whose only claims were refused
(dead-lettered by the fan-in as one P2) is ``nothing_due`` (nothing was due for an incident); an unreadable ledger or route table is the fatal
skip ``dependency_unavailable``. See :func:`lane_output`.

MBI_BEHAVIOR = 0. No send, no network, no subprocess, no Telegram import. Authority: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_comms_intent_consumption as C  # noqa: E402
from scripts.lib.n8n_fabric_store import FabricStoreError  # noqa: E402

LANE_ID = C.LANE_ID
SCRIPT = "scripts/n8n_comms_intent_consumer.py"
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"


def resolve_paths(ledger: Optional[str], state_root: Optional[str]) -> tuple[Path, Path]:
    sr = Path(state_root) if state_root else Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    if ledger:
        return Path(ledger), sr
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    return (Path(explicit) if explicit else sr / C.LEDGER_REL), sr


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return datetime.now(timezone.utc)
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def run(
    *,
    ledger: Path,
    state_root: Path,
    apply: bool,
    max_intents: int,
    now: datetime,
    routes_path: Optional[Path] = None,
    receipt: Optional[Path] = None,
) -> int:
    from scripts.lib import lane_last_receipt as R

    receipt = receipt or R.receipt_path(LANE_ID, state_root)
    summary: dict[str, Any] = {"schema": C.SCHEMA, "ledger": str(ledger), "max_intents": max_intents}
    try:
        routes = C.load_routes(routes_path)
        summary["routes_sha256"] = routes.get("sha256")
    except FabricStoreError as exc:
        summary["error"] = exc.reason
        return _finish(R, apply, receipt, ok=False, summary=summary, now=now)
    if not apply:
        conn = C.connect_ro(ledger)
        try:
            summary.update(C.plan(conn, routes, now, max_intents))
        finally:
            if conn is not None:
                conn.close()
        would = (
            [str(receipt)] if summary.get("would") or summary.get("would_close") or summary.get("would_refresh") else []
        )
        return _finish(R, False, receipt, ok=True, summary=summary, now=now, would=would)
    token = f"{LANE_ID}:{now.strftime('%Y%m%dT%H%M%SZ')}:{uuid.uuid4().hex[:8]}"
    try:
        conn = C.connect_rw(ledger)
    except (FileNotFoundError, OSError, Exception) as exc:  # noqa: BLE001 — the receipt names the cause
        summary["error"] = f"{type(exc).__name__}: ledger"
        return _finish(R, True, receipt, ok=False, summary=summary, now=now)
    try:
        res = C.apply(conn, routes, now, max_intents, token)
    except Exception as exc:  # noqa: BLE001
        summary["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return _finish(R, True, receipt, ok=False, summary=summary, now=now)
    finally:
        conn.close()
    results = res["results"]
    summary.update(
        claim_token=token,
        done=sum(1 for r in results if r.get("state") == C.STATE_DONE),
        refused=sum(1 for r in results if r.get("state") == C.STATE_FAILED and not r.get("transient")),
        failed_transient=sum(1 for r in results if r.get("transient")),
        claim_lost=sum(1 for r in results if r.get("state") in ("CLAIM_LOST", "LOST_CLAIM")),
        incidents_created=sum(1 for r in results if r.get("incident") in ("created", "reopened")),
        incidents_updated=sum(1 for r in results if r.get("incident") == "updated"),
        refreshed=len(res["refreshed"]),
        closed=len(res["closed"]),
        deferred=res["deferred"],
        results=results,
        backlog=res["backlog"],
    )
    ok = summary["failed_transient"] == 0
    return _finish(R, True, receipt, ok=ok, summary=summary, now=now, output=lane_output(summary))


#: Empty reasons the health contract allows (config/n8n_health_contracts.json expected_output.empty_allowed_reasons).
EMPTY_NO_INPUT = "no_new_input"
EMPTY_ALL_REFUSED = "nothing_due"  # closed enum (check_n8n_workflow_framework EMPTY_ALLOWED_REASONS)
#: The fatal skip: the ledger or the route table could not be read or written (expected_output.fatal_skip_reasons).
SKIP_DEPENDENCY = "dependency_unavailable"


def lane_output(summary: dict[str, Any]) -> dict[str, Any]:
    """LaneRunReceipt@v2 output fields for one apply run (unit: comms intents consumed into incidents).

    produced = intents moved to DONE (incident or log outcome) + DONE intents whose incident was refreshed with
    repeats; attempted = produced + refused + claim-lost + transient. An error before any claim (no ledger, routes
    unreadable, write failed) is the fatal skip ``dependency_unavailable``. Pure."""
    if summary.get("error"):
        return {"produced_count": 0, "attempted_count": 0, "skipped_reasons": {SKIP_DEPENDENCY: 1}, "empty_reason": None}
    done, refreshed = int(summary.get("done") or 0), int(summary.get("refreshed") or 0)
    refused, lost = int(summary.get("refused") or 0), int(summary.get("claim_lost") or 0)
    transient = int(summary.get("failed_transient") or 0)
    skipped = {
        k: v
        for k, v in (("intent_refused", refused), ("claim_lost", lost), ("intent_failed_transient", transient))
        if v
    }
    produced = done + refreshed
    attempted = produced + refused + lost + transient
    empty = None
    if produced == 0:
        if attempted == 0:
            empty = EMPTY_NO_INPUT
        elif refused and not transient and not lost:
            empty = EMPTY_ALL_REFUSED
    return {"produced_count": produced, "attempted_count": attempted, "skipped_reasons": skipped, "empty_reason": empty}


def _finish(
    R: Any,
    apply: bool,
    receipt: Path,
    *,
    ok: bool,
    summary: dict[str, Any],
    now: datetime,
    would: Optional[list[str]] = None,
    output: Optional[dict[str, Any]] = None,
) -> int:
    if not apply:
        R.dry_run_report(LANE_ID, summary, would_write=would or [], receipt=receipt)
        return 0 if ok else 1
    output = output if output is not None else lane_output(summary)
    written = R.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        started_at=now,
        script=SCRIPT,
        summary=summary,
        error=summary.get("error"),
        path=receipt,
        output=output,
    )
    print(
        json.dumps(
            {
                "mode": "apply",
                "ok": ok,
                "receipt": str(written) if written else None,
                "produced_count": output["produced_count"],
                "empty_reason": output["empty_reason"],
                **{
                    k: summary.get(k)
                    for k in (
                        "done",
                        "refused",
                        "failed_transient",
                        "incidents_created",
                        "incidents_updated",
                        "refreshed",
                        "closed",
                        "deferred",
                        "error",
                    )
                },
            },
            default=str,
        )
    )
    if written is None:
        return 1
    return 0 if ok else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: read-only plan, writes nothing")
    g.add_argument("--apply", action="store_true", help="claim, map and record; writes the ledger tables + receipt")
    ap.add_argument("--ledger", help="coordination ledger (default: TRADEAI_N8N_COORDINATION_LEDGER, else state root)")
    ap.add_argument("--state-root", help="persistent-state root (default: TRADEAI_STATE_ROOT)")
    ap.add_argument(
        "--max-intents", type=int, default=None, help="per-run claim cap (default: the route table's max_per_hour)"
    )
    ap.add_argument("--routes", help=argparse.SUPPRESS)  # tests: a fixture route table
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: pin the clock (ISO 8601, aware)
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    now = _parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    ledger, state_root = resolve_paths(a.ledger, a.state_root)
    routes_path = Path(a.routes) if a.routes else None
    max_intents = a.max_intents
    if max_intents is None:
        try:
            max_intents = int(C.load_routes(routes_path)["max_per_hour"])
        except FabricStoreError:
            max_intents = 30
    if max_intents < 1:
        print("--max-intents must be >= 1", file=sys.stderr)
        return 2
    return run(
        ledger=ledger,
        state_root=state_root,
        apply=bool(a.apply),
        max_intents=max_intents,
        now=now,
        routes_path=routes_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
