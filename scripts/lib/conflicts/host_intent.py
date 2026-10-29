"""Queue a host comms intent without importing scripts/lib/host_comms_intents.py.

Same rows, dedupe, hourly cap and refusal reasons as host_comms_intents.queue_intent. That module imports the
coordination gateway, whose closure reaches broker modules, and an n8n-allowlisted lane must not
(tests/test_lane_transitive_capabilities_20261015.py). Mirrors scripts/disk_usage_monitor.queue_host_intent and
scripts/check_registry_runtime_truth.py. Never a send: the host comms-intent consumer and incident notifier deliver.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional


class HostIntentError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def default_ledger_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Same resolution as scripts/n8n_coordination_gateway.default_ledger_path (not imported: see queue_host_intent)."""
    source = environ if environ is not None else os.environ
    explicit = source.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    root = source.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


class _LedgerConn:
    """The two attributes CommsIntentStore uses (``_conn``, ``lock``) on a plain sqlite connection to an EXISTING
    ledger. Same rows, dedupe and cap as scripts/lib/host_comms_intents.queue_intent, whose import closure (via
    scripts/n8n_coordination_gateway.py) reaches broker modules — an n8n-allowlisted lane must not
    (tests/test_lane_transitive_capabilities_20261015.py), so this lane talks to the store directly. Mirrors
    scripts/check_registry_runtime_truth.py."""

    read_only = False

    def __init__(self, path: Path) -> None:
        import sqlite3
        import threading

        self.lock = threading.RLock()  # CommsIntentStore re-enters it (accept -> _receipt -> get)
        self._conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()


def queue_host_intent(
    *,
    producer: str,
    domain: str,
    kind: str,
    subject: str,
    summary: str,
    execution_id: str,
    node: str,
    ledger_path: Optional[Path],
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Queue one host comms intent (never a send). Raises HostIntentError(<reason>) with host_comms_intents' reasons:
    producer_refused, intent_unrouted, intent_rate_limited, intent_routes_unreadable, malformed_event, ledger_absent
    (the consumer and gateway create the ledger; a lane never does), intent_store_unavailable."""
    import sqlite3
    import time

    from scripts.lib.n8n_fabric_store import (
        PRODUCER_RE,
        SUBJECT_MAX,
        SUMMARY_MAX,
        CommsIntentStore,
        FabricStoreError,
        load_host_intent_routes,
        load_intent_routes,
        merged_intent_routes,
    )

    if not PRODUCER_RE.fullmatch(producer):
        raise HostIntentError("producer_refused")
    try:
        hosts = load_host_intent_routes()
        routes = merged_intent_routes(load_intent_routes(), hosts)
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

    def clean(text: Any, limit: int) -> str:
        flat = " ".join("".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(text or "")).split())
        return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"

    request = {
        "domain": domain,
        "kind": kind,
        "subject": clean(subject, SUBJECT_MAX),
        "summary": clean(summary, SUMMARY_MAX),
        "workflow_id": f"host.{producer}",
        "execution_id": str(execution_id)[:40],
        "node": clean(node, 64),
    }
    try:
        ledger = _LedgerConn(path)
    except (sqlite3.Error, OSError) as exc:
        raise HostIntentError("intent_store_unavailable") from exc
    try:
        store = CommsIntentStore(ledger, routes=routes)
        return dict(store.accept(request, caller_id=f"host:{producer}", now=time.time() if now is None else now))
    except FabricStoreError as exc:
        raise HostIntentError(getattr(exc, "reason", "intent_store_unavailable")) from exc
    except sqlite3.Error as exc:
        raise HostIntentError("intent_store_unavailable") from exc
    finally:
        ledger.close()
