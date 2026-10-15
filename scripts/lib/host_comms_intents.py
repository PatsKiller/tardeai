"""Host-lane notification intents: queue, never send (2026-10-15; AGENTS.md §23.23, §24.1, §9.1).

A host lane fired by the n8n fabric may not call a sender (``config/n8n_run_allowlist.json`` never-list), and n8n
holds no messaging credential. The operator still has to hear about what the lane found. This module is that route:
the lane QUEUES its notification as a comms intent in the coordination ledger's ``comms_intents`` table — the same
table, dedupe and hourly cap the gateway's ``comms/intent`` operation uses (scripts/lib/n8n_fabric_store.py
CommsIntentStore) — and the host comms-intent consumer (scripts/n8n_comms_intent_consumer.py) turns it into an
incident that the incident notifier sends (DIGEST -> P2, quiet-held). Nothing here sends, spawns or opens a socket.

Routes are the closed table ``config/host_comms_intent_routes.json``: each (domain, kind) names the ONE producer that
may queue it, so a lane cannot borrow another lane's route, and n8n (whose gateway reads only
config/n8n_comms_intent_routes.json) cannot queue a host-lane intent at all. The row's ``workflow_id`` is
``host.<producer>`` and its ``caller_id`` ``host:<producer>``: a host intent never passes as an n8n one.

First producer: scripts/hermes_outcome_feedback_agent.py ``--notify queue`` (lib/hermes_outcome_bus/
alert_notifications.py), the live argv of fabric step outcome_feedback_agent at cutover.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_fabric_store import (  # noqa: E402
    PRODUCER_RE,
    SUBJECT_MAX,
    SUMMARY_MAX,
    CommsIntentStore,
    FabricStoreError,
    load_host_intent_routes,
    load_intent_routes,
    merged_intent_routes,
)

CONTROL_CHARS = {chr(c) for c in range(32)} | {chr(127)}


class HostIntentError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def clean_text(text: Any, limit: int) -> str:
    """One line, no control characters, at most ``limit`` characters (the store refuses anything else)."""
    flat = "".join(" " if ch in CONTROL_CHARS else ch for ch in str(text or ""))
    flat = " ".join(flat.split())
    return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"


def default_ledger_path() -> Path:
    from scripts.n8n_coordination_gateway import default_ledger_path as gw_default

    return gw_default()


def queue_intent(
    *,
    producer: str,
    domain: str,
    kind: str,
    subject: str,
    summary: str,
    execution_id: str,
    node: str = "",
    ledger_path: Optional[Path] = None,
    now: Optional[float] = None,
    n8n_routes: Optional[Mapping[str, Any]] = None,
    host_routes: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Queue one intent; return the CommsIntentReceipt@v1 (``duplicate: true`` when folded into a recent identical
    one). Raises HostIntentError(<reason>): ``producer_refused`` (bad name or not this route's producer),
    ``intent_unrouted``, ``intent_rate_limited``, ``intent_routes_unreadable``, ``malformed_event``,
    ``ledger_absent`` (the consumer and gateway create the ledger; a lane never does) or ``intent_store_unavailable``."""
    if not isinstance(producer, str) or not PRODUCER_RE.fullmatch(producer):
        raise HostIntentError("producer_refused")
    try:
        hosts = host_routes if host_routes is not None else load_host_intent_routes()
        n8n = n8n_routes if n8n_routes is not None else load_intent_routes()
        routes = merged_intent_routes(n8n, hosts)
    except FabricStoreError as exc:
        raise HostIntentError(getattr(exc, "reason", "intent_routes_unreadable")) from exc
    route = hosts["routes"].get((domain, kind))
    if route is None:
        raise HostIntentError("intent_unrouted")
    if route.get("producer") != producer:
        raise HostIntentError("producer_refused")
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    if not path.exists():
        raise HostIntentError("ledger_absent")
    request = {
        "domain": domain,
        "kind": kind,
        "subject": clean_text(subject, SUBJECT_MAX),
        "summary": clean_text(summary, SUMMARY_MAX),
        "workflow_id": f"host.{producer}",
        "execution_id": str(execution_id)[:40],
        "node": clean_text(node, 64),
    }
    import sqlite3

    from scripts.lib.n8n_coordination_ledger import CoordinationLedger

    try:
        ledger = CoordinationLedger(path)
    except (sqlite3.Error, OSError) as exc:
        raise HostIntentError("intent_store_unavailable") from exc
    try:
        store = CommsIntentStore(ledger, routes=routes)
        receipt = store.accept(request, caller_id=f"host:{producer}", now=time.time() if now is None else now)
    except FabricStoreError as exc:
        raise HostIntentError(getattr(exc, "reason", "intent_store_unavailable")) from exc
    except sqlite3.Error as exc:
        raise HostIntentError("intent_store_unavailable") from exc
    finally:
        close = getattr(ledger, "close", None)
        if callable(close):
            close()
    return dict(receipt)
