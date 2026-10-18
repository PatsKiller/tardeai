"""n8n comms-intent consumption: QUEUED intents become incident fan-in incidents (2026-10-15).

Build 1 (PR #1739) queues n8n send-intents in the coordination ledger's ``comms_intents`` table and sends nothing.
This module is the host side that turns them into incidents. The operator chose the incident fan-in route, so an
intent never becomes a message of its own:

    comms_intents (QUEUED, gateway)  ->  scripts/n8n_comms_intent_consumer.py --apply  (this module)
        -> comms_intent_incidents (one OPEN row per workflow and kind)
        -> scripts/n8n_incident_fanin.py reads the open rows (``open_incident_findings``)
        -> scripts/incident_notifier.py, the existing P2 batch (DIGEST), the only sender.

Two additive tables in the same ledger file. Neither is created by the gateway, and ``comms_intents`` keeps its
schema (only its ``state`` column moves):

``comms_intent_consumption``: one row per intent_id. state, attempts, last_error, the claim lease, and the fan-in
incident the intent became: ``incident_key`` (the notifier's day-independent identity, ``inc-`` + sha256(source|item)
[:20]), ``fanin_source`` / ``fanin_item``, and ``fanin_event_key`` (the fan-in's per-UTC-day event idempotency key on
the day the intent was consumed). ``consumed_count`` is the intent's dedupe count as last folded into the incident, so
a repeat that the gateway folds into an intent that is already DONE refreshes the incident instead of opening another.

``comms_intent_incidents``: one row per ``incident_key``. OPEN until ``open_until`` (the later of the intent's last_at
and its consumption time, plus the route table's dedupe window). Deliver-before-close (2026-10-17): past
``open_until`` a notifiable (P1/P2) row is CLOSED only when the incident notifier's own state proves it reached the
operator (``delivery_verdict``: a delivery recorded at or after this generation's ``opened_at``, an open notice the
notifier still holds for the key, or an operator ack on its last live receipt). Otherwise the row is DEFERRED, not
closed: the fan-in keeps presenting it, so a P2 the notifier CAPPED (daily cap) or held (quiet hours, batch window,
source budget) leaves in the next allowed batch (07:00 ET / the cap's day reset), once (the notifier's per-key dedupe),
and the row closes on the first consumer run after that delivery. ``close_reason`` records why a row closed;
``deferred_since`` when it was first held. A P3 (DASHBOARD) row never sends, so it closes at the window as before.
A CLOSED row re-opens with ``generation`` + 1; a DEFERRED row that gets a new intent stays the same generation. A ``(fabric, workflow_error)`` intent uses the fan-in's own workflow-error identity
(``n8n_workflow_error`` / ``wferr:<workflow_id>``), so it merges into the incident the relay's workflow-error events
already open for that workflow (``scripts/n8n_incident_fanin.py`` ``_workflow_error_findings``).

State machine (``comms_intents.state``): QUEUED -> CLAIMED -> DONE | FAILED. The claim is a compare-and-set inside
``BEGIN IMMEDIATE`` (``WHERE state = 'QUEUED'``), so two consumers can never both own one intent. A transient failure
is FAILED with ``last_error`` and is claimed again on the next run until ``MAX_ATTEMPTS``; a refusal (no route, a
PAGE tier, which n8n may never reach, §24.1) is FAILED and ``terminal``, never retried and never sent. A CLAIMED row
whose lease expired (the consumer died between the two transactions) is claimed again.

Tier -> fan-in severity (ALERT_TAXONOMY.md §2): DIGEST -> P2 (the notifier's batched P2 path, quiet-held overnight),
DASHBOARD -> P3 (never sent). LOG -> no incident (DONE, recorded only). PAGE -> refused (FAILED, terminal).

Dead-letter rule (``dead_letter_findings``, read by the fan-in): any intent FAILED ``MAX_ATTEMPTS`` times or refused
as terminal is one aggregated P2 ``n8n_comms_intent_dlq`` / ``dead_letter`` finding; any intent QUEUED (or with an
expired claim) for more than ``QUEUED_STALE_S`` is one aggregated P2 ``queued_stale`` finding. Aggregated on purpose:
WS1-09 found the channel already saturated, so a backlog is one line, not one line per intent.

AUTHORITY: READ_ONLY_ADVISORY for the operator surface. Writes only the two tables above and ``comms_intents.state``.
No send, no network, no subprocess, no Telegram import (tests/test_n8n_comms_intent_consumer_20261015.py ratchet).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from scripts.lib.n8n_fabric_store import (
    FabricStoreError,
    load_host_intent_routes,
    load_intent_routes,
    merged_intent_routes,
)

LANE_ID = "n8n-comms-intent-consumer"
SCHEMA = "N8nCommsIntentConsumption@v1"
MAX_ATTEMPTS = 3
QUEUED_STALE_S = 2 * 3600
CLAIM_LEASE_S = 600
INTENT_IDS_KEPT = 20  # per incident row; the count keeps the total
CLAIMABLE_SCAN = 5000  # rows read to count the deferred backlog; the gateway admits at most max_per_hour (30) an hour
#: ALERT_TAXONOMY.md §2. PAGE is absent on purpose: the P1 path never depends on n8n (§24.1).
TIER_SEVERITY = {"DIGEST": "P2", "DASHBOARD": "P3"}
LOG_TIER = "LOG"
REFUSED_TIERS = frozenset({"PAGE"})

# The fan-in identities this module writes. Kept as literals so the fan-in (which imports this module) is not imported
# back; tests/test_n8n_comms_intent_consumer_20261015.py asserts they equal scripts/n8n_incident_fanin.py WFERR_SOURCE,
# idem_key and scripts/incident_notifier.py incident_key.
WFERR_SOURCE = "n8n_workflow_error"
INTENT_SOURCE = "n8n_comms_intent"
DLQ_SOURCE = "n8n_comms_intent_dlq"
LEDGER_REL = "data/governance/n8n_coordination_ledger.sqlite"

STATE_QUEUED, STATE_CLAIMED, STATE_DONE, STATE_FAILED = "QUEUED", "CLAIMED", "DONE", "FAILED"
#: comms_intent_incidents.state. DEFERRED = past its window but not yet delivered: still open to the fan-in, never
#: terminal. Only CLOSED is terminal, and only after delivery evidence (``delivery_verdict``).
INC_OPEN, INC_DEFERRED, INC_CLOSED = "OPEN", "DEFERRED", "CLOSED"
LIVE_INCIDENT_STATES = (INC_OPEN, INC_DEFERRED)
#: Severities scripts/incident_notifier.py sends (it pages a P0 as P1); anything else is never delivered by design.
NOTIFIABLE_SEVERITIES = frozenset({"P0", "P1", "P2"})
# The notifier's own files (scripts/incident_notifier.py STATE_REL / RECEIPT_REL / STATE_SCHEMA), literals so this
# module never imports the sender; tests/test_comms_intent_deliver_before_close_20261017.py pins them equal.
NOTIFIER_STATE_REL = "data/runtime/incident_notifier_state.json"
NOTIFIER_RECEIPT_REL = "data/runtime/incident_notifier_last.json"
NOTIFIER_STATE_SCHEMA = "IncidentNotifierState@v1"

DDL = """
CREATE TABLE IF NOT EXISTS comms_intent_consumption (
    intent_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    terminal INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    claim_token TEXT,
    claimed_at TEXT,
    done_at TEXT,
    outcome TEXT,
    incident_key TEXT,
    fanin_source TEXT,
    fanin_item TEXT,
    fanin_event_key TEXT,
    severity TEXT,
    consumed_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comms_intent_consumption_state ON comms_intent_consumption (state, attempts);
CREATE TABLE IF NOT EXISTS comms_intent_incidents (
    incident_key TEXT PRIMARY KEY,
    fanin_source TEXT NOT NULL,
    fanin_item TEXT NOT NULL,
    domain TEXT NOT NULL,
    kind TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    severity TEXT NOT NULL,
    runbook_id TEXT,
    state TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL,
    last_at TEXT NOT NULL,
    open_until TEXT NOT NULL,
    closed_at TEXT,
    count INTEGER NOT NULL DEFAULT 0,
    intent_ids TEXT NOT NULL,
    last_execution_id TEXT,
    last_node TEXT,
    last_summary TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comms_intent_incidents_open ON comms_intent_incidents (state, open_until);
"""
#: Additive columns (2026-10-17 deliver-before-close), added to an existing ledger by ``connect_rw``.
INCIDENT_COLUMNS_ADDED = (("close_reason", "TEXT"), ("deferred_since", "TEXT"))


# ── identities ─────────────────────────────────────────────────────────────────────────────────────────────────────


def notifier_incident_key(source: str, item: str) -> str:
    """scripts/incident_notifier.py incident_key: the incident's day-independent identity."""
    return "inc-" + hashlib.sha256(f"{source}|{item}".encode("utf-8")).hexdigest()[:20]


def fanin_event_key(source: str, item: str, day: str) -> str:
    """scripts/n8n_incident_fanin.py idem_key: the fan-in's coordination event key for one UTC day."""
    return "inc-" + hashlib.sha256(f"{source}|{item}|{day}".encode("utf-8")).hexdigest()[:24]


def fanin_identity(domain: str, kind: str, workflow_id: str) -> tuple[str, str]:
    """(fan-in source, item): deduped per workflow and kind. A workflow error joins the relay's per-workflow one."""
    if (domain, kind) == ("fabric", "workflow_error"):
        return WFERR_SOURCE, f"wferr:{workflow_id}"
    return INTENT_SOURCE, f"{domain}.{kind}:{workflow_id}"


# ── time helpers ───────────────────────────────────────────────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── mapping (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────


def map_intent(intent: Mapping[str, Any], routes: Mapping[str, Any]) -> dict[str, Any]:
    """What one intent becomes, from the route table as it reads now. Pure.

    Returns {action: incident | log | refuse, ...}. ``refuse`` carries ``reason`` and is terminal."""
    domain, kind = str(intent.get("domain") or ""), str(intent.get("kind") or "")
    route = (routes.get("routes") or {}).get((domain, kind))
    if route is None:
        return {"action": "refuse", "reason": "intent_unrouted"}
    tier = str(route.get("tier") or "")
    if tier in REFUSED_TIERS:
        return {"action": "refuse", "reason": "page_tier_never_from_n8n", "tier": tier}
    if tier == LOG_TIER:
        return {"action": "log", "tier": tier, "runbook_id": route.get("runbook_id")}
    severity = TIER_SEVERITY.get(tier)
    if severity is None:
        return {"action": "refuse", "reason": "tier_unmapped", "tier": tier}
    workflow_id = str(intent.get("workflow_id") or "")
    if not workflow_id:
        return {"action": "refuse", "reason": "workflow_id_missing"}
    source, item = fanin_identity(domain, kind, workflow_id)
    return {
        "action": "incident",
        "tier": tier,
        "severity": severity,
        "runbook_id": route.get("runbook_id"),
        "fanin_source": source,
        "fanin_item": item,
        "incident_key": notifier_incident_key(source, item),
    }


# ── connections ────────────────────────────────────────────────────────────────────────────────────────────────────


def connect_ro(path: Path) -> Optional[sqlite3.Connection]:
    """mode=ro, no WAL pragma, no migration. None when the file is absent."""
    if not Path(path).exists():
        return None
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def connect_rw(path: Path) -> sqlite3.Connection:
    """The ledger file the gateway writes (WAL); additive DDL only. Raises FileNotFoundError when absent: the consumer
    never creates a ledger, the gateway does."""
    if not Path(path).exists():
        raise FileNotFoundError(str(path))
    conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(DDL)
    have = {r[1] for r in conn.execute("PRAGMA table_info(comms_intent_incidents)")}
    for name, typ in INCIDENT_COLUMNS_ADDED:
        if name not in have:
            conn.execute(f"ALTER TABLE comms_intent_incidents ADD COLUMN {name} {typ}")
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _row(r: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return None if r is None else {k: r[k] for k in r.keys()}


# ── selection ──────────────────────────────────────────────────────────────────────────────────────────────────────


def claimable(conn: sqlite3.Connection, now: datetime, limit: int) -> list[dict[str, Any]]:
    """Intents this run may claim, oldest first: QUEUED; FAILED and retryable; CLAIMED with an expired lease."""
    tables = _tables(conn)
    if "comms_intents" not in tables:
        return []
    if "comms_intent_consumption" not in tables:
        rows = conn.execute(
            "SELECT i.*, NULL AS c_state, 0 AS attempts, 0 AS terminal, NULL AS claimed_at, 0 AS consumed_count"
            " FROM comms_intents i WHERE i.state = ? ORDER BY i.first_at ASC LIMIT ?",
            (STATE_QUEUED, int(limit)),
        ).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]
    lease_cut = _iso(now - timedelta(seconds=CLAIM_LEASE_S))
    rows = conn.execute(
        "SELECT i.*, c.state AS c_state, COALESCE(c.attempts, 0) AS attempts, COALESCE(c.terminal, 0) AS terminal,"
        " c.claimed_at AS claimed_at, COALESCE(c.consumed_count, 0) AS consumed_count"
        " FROM comms_intents i LEFT JOIN comms_intent_consumption c ON c.intent_id = i.intent_id"
        " WHERE i.state = ?"
        "    OR (i.state = ? AND COALESCE(c.terminal, 0) = 0 AND COALESCE(c.attempts, 0) < ?)"
        "    OR (i.state = ? AND (c.claimed_at IS NULL OR c.claimed_at < ?))"
        " ORDER BY i.first_at ASC LIMIT ?",
        (STATE_QUEUED, STATE_FAILED, MAX_ATTEMPTS, STATE_CLAIMED, lease_cut, int(limit)),
    ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def refreshable(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """DONE intents the gateway folded more repeats into since they were consumed (count > consumed_count)."""
    if not {"comms_intents", "comms_intent_consumption"} <= _tables(conn):
        return []
    rows = conn.execute(
        "SELECT i.*, c.incident_key AS incident_key, c.consumed_count AS consumed_count, c.outcome AS outcome"
        " FROM comms_intents i JOIN comms_intent_consumption c ON c.intent_id = i.intent_id"
        " WHERE i.state = ? AND c.outcome = 'incident' AND i.count > c.consumed_count ORDER BY i.first_at ASC",
        (STATE_DONE,),
    ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def backlog(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    """Counts by state; how many more QUEUED intents wait beyond this run."""
    if "comms_intents" not in _tables(conn):
        return {"table": "absent"}
    by_state = {r[0]: r[1] for r in conn.execute("SELECT state, COUNT(*) FROM comms_intents GROUP BY state")}
    return {"table": "present", "by_state": by_state}


# ── one intent ─────────────────────────────────────────────────────────────────────────────────────────────────────


def claim(conn: sqlite3.Connection, intent: Mapping[str, Any], *, token: str, now: datetime) -> bool:
    """Atomic compare-and-set: the intent moves to CLAIMED only from the state it was selected in."""
    iid, prior = intent["intent_id"], intent["state"]
    lease_cut = _iso(now - timedelta(seconds=CLAIM_LEASE_S))
    conn.execute("BEGIN IMMEDIATE")
    try:
        if prior == STATE_CLAIMED:
            cur = conn.execute(
                "UPDATE comms_intents SET state = ? WHERE intent_id = ? AND state = ? AND NOT EXISTS ("
                " SELECT 1 FROM comms_intent_consumption c WHERE c.intent_id = ? AND c.claimed_at >= ?)",
                (STATE_CLAIMED, iid, STATE_CLAIMED, iid, lease_cut),
            )
        else:
            cur = conn.execute(
                "UPDATE comms_intents SET state = ? WHERE intent_id = ? AND state = ?", (STATE_CLAIMED, iid, prior)
            )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return False
        conn.execute(
            "INSERT INTO comms_intent_consumption (intent_id, state, attempts, claim_token, claimed_at, updated_at)"
            " VALUES (?, ?, 1, ?, ?, ?)"
            " ON CONFLICT(intent_id) DO UPDATE SET state = excluded.state, attempts = attempts + 1,"
            " claim_token = excluded.claim_token, claimed_at = excluded.claimed_at, updated_at = excluded.updated_at",
            (iid, STATE_CLAIMED, token, _iso(now), _iso(now)),
        )
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _upsert_incident(
    conn: sqlite3.Connection,
    intent: Mapping[str, Any],
    m: Mapping[str, Any],
    *,
    now: datetime,
    window_s: int,
    count: int,
) -> str:
    """Create, update or re-open the incident row. Returns created | updated | reopened. Caller holds the txn."""
    last_at = _parse(intent.get("last_at")) or now
    open_until = _iso(max(last_at, now) + timedelta(seconds=window_s))
    key = m["incident_key"]
    prev = _row(conn.execute("SELECT * FROM comms_intent_incidents WHERE incident_key = ?", (key,)).fetchone())
    detail = (str(intent.get("execution_id") or ""), str(intent.get("node") or ""), str(intent.get("summary") or ""))
    if prev is None:
        conn.execute(
            "INSERT INTO comms_intent_incidents (incident_key, fanin_source, fanin_item, domain, kind, workflow_id,"
            " tier, severity, runbook_id, state, generation, opened_at, last_at, open_until, count, intent_ids,"
            " last_execution_id, last_node, last_summary, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                m["fanin_source"],
                m["fanin_item"],
                intent["domain"],
                intent["kind"],
                intent["workflow_id"],
                m["tier"],
                m["severity"],
                m.get("runbook_id"),
                _iso(now),
                _iso(last_at),
                open_until,
                count,
                json.dumps([intent["intent_id"]]),
                *detail,
                _iso(now),
            ),
        )
        return "created"
    ids = [i for i in json.loads(prev.get("intent_ids") or "[]") if i != intent["intent_id"]] + [intent["intent_id"]]
    if prev["state"] in LIVE_INCIDENT_STATES:  # a DEFERRED row is still undelivered: same generation, OPEN again
        conn.execute(
            "UPDATE comms_intent_incidents SET state = 'OPEN', last_at = MAX(last_at, ?),"
            " open_until = MAX(open_until, ?),"
            " count = count + ?, intent_ids = ?, last_execution_id = ?, last_node = ?, last_summary = ?,"
            " severity = ?, tier = ?, updated_at = ? WHERE incident_key = ?",
            (
                _iso(last_at),
                open_until,
                count,
                json.dumps(ids[-INTENT_IDS_KEPT:]),
                *detail,
                m["severity"],
                m["tier"],
                _iso(now),
                key,
            ),
        )
        return "updated"
    conn.execute(
        "UPDATE comms_intent_incidents SET state = 'OPEN', generation = generation + 1, opened_at = ?, last_at = ?,"
        " open_until = ?, closed_at = NULL, close_reason = NULL, deferred_since = NULL, count = ?, intent_ids = ?,"
        " last_execution_id = ?, last_node = ?,"
        " last_summary = ?, severity = ?, tier = ?, updated_at = ? WHERE incident_key = ?",
        (
            _iso(now),
            _iso(last_at),
            open_until,
            count,
            json.dumps([intent["intent_id"]]),
            *detail,
            m["severity"],
            m["tier"],
            _iso(now),
            key,
        ),
    )
    return "reopened"


def complete(
    conn: sqlite3.Connection,
    intent: Mapping[str, Any],
    m: Mapping[str, Any],
    *,
    token: str,
    now: datetime,
    window_s: int,
) -> dict[str, Any]:
    """One transaction: the incident row, the consumption row and comms_intents.state (DONE or FAILED terminal)."""
    iid = intent["intent_id"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        held = conn.execute(
            "SELECT 1 FROM comms_intents i JOIN comms_intent_consumption c ON c.intent_id = i.intent_id"
            " WHERE i.intent_id = ? AND i.state = ? AND c.claim_token = ?",
            (iid, STATE_CLAIMED, token),
        ).fetchone()
        if held is None:
            conn.execute("ROLLBACK")
            return {"intent_id": iid, "state": "LOST_CLAIM"}
        count = int(intent.get("count") or 1)
        out: dict[str, Any] = {"intent_id": iid, "action": m["action"]}
        if m["action"] == "refuse":
            conn.execute("UPDATE comms_intents SET state = ? WHERE intent_id = ?", (STATE_FAILED, iid))
            conn.execute(
                "UPDATE comms_intent_consumption SET state = ?, terminal = 1, last_error = ?, outcome = 'refused',"
                " updated_at = ? WHERE intent_id = ?",
                (STATE_FAILED, m["reason"], _iso(now), iid),
            )
            out.update(state=STATE_FAILED, reason=m["reason"])
        elif m["action"] == "log":
            conn.execute("UPDATE comms_intents SET state = ? WHERE intent_id = ?", (STATE_DONE, iid))
            conn.execute(
                "UPDATE comms_intent_consumption SET state = ?, last_error = NULL, outcome = 'log', done_at = ?,"
                " consumed_count = ?, updated_at = ? WHERE intent_id = ?",
                (STATE_DONE, _iso(now), count, _iso(now), iid),
            )
            out.update(state=STATE_DONE)
        else:
            change = _upsert_incident(conn, intent, m, now=now, window_s=window_s, count=count)
            ev_key = fanin_event_key(
                m["fanin_source"], m["fanin_item"], now.astimezone(timezone.utc).strftime("%Y-%m-%d")
            )
            conn.execute("UPDATE comms_intents SET state = ? WHERE intent_id = ?", (STATE_DONE, iid))
            conn.execute(
                "UPDATE comms_intent_consumption SET state = ?, last_error = NULL, outcome = 'incident', done_at = ?,"
                " incident_key = ?, fanin_source = ?, fanin_item = ?, fanin_event_key = ?, severity = ?,"
                " consumed_count = ?, updated_at = ? WHERE intent_id = ?",
                (
                    STATE_DONE,
                    _iso(now),
                    m["incident_key"],
                    m["fanin_source"],
                    m["fanin_item"],
                    ev_key,
                    m["severity"],
                    count,
                    _iso(now),
                    iid,
                ),
            )
            out.update(
                state=STATE_DONE,
                incident=change,
                incident_key=m["incident_key"],
                fanin_item=m["fanin_item"],
                fanin_event_key=ev_key,
                severity=m["severity"],
            )
        conn.execute("COMMIT")
        return out
    except Exception:
        conn.execute("ROLLBACK")
        raise


def fail(conn: sqlite3.Connection, intent_id: str, *, token: str, error: str, now: datetime) -> None:
    """A transient failure: FAILED with last_error; retried until MAX_ATTEMPTS."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE comms_intents SET state = ? WHERE intent_id = ? AND state = ?",
            (STATE_FAILED, intent_id, STATE_CLAIMED),
        )
        conn.execute(
            "UPDATE comms_intent_consumption SET state = ?, last_error = ?, updated_at = ? WHERE intent_id = ?"
            " AND claim_token = ?",
            (STATE_FAILED, error[:300], _iso(now), intent_id, token),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def refresh(conn: sqlite3.Connection, intent: Mapping[str, Any], *, now: datetime, window_s: int) -> dict[str, Any]:
    """Fold repeats the gateway counted on a DONE intent into its incident (re-opening it if it closed)."""
    iid, delta = intent["intent_id"], int(intent["count"]) - int(intent["consumed_count"])
    conn.execute("BEGIN IMMEDIATE")
    try:
        inc = _row(
            conn.execute(
                "SELECT * FROM comms_intent_incidents WHERE incident_key = ?", (intent["incident_key"],)
            ).fetchone()
        )
        if inc is None or delta <= 0:
            conn.execute("ROLLBACK")
            return {"intent_id": iid, "refreshed": False}
        m = {k: inc[k] for k in ("fanin_source", "fanin_item", "tier", "severity", "runbook_id")}
        m["incident_key"] = intent["incident_key"]
        change = _upsert_incident(conn, intent, m, now=now, window_s=window_s, count=delta)
        conn.execute(
            "UPDATE comms_intent_consumption SET consumed_count = ?, updated_at = ? WHERE intent_id = ?",
            (int(intent["count"]), _iso(now), iid),
        )
        conn.execute("COMMIT")
        return {"intent_id": iid, "refreshed": True, "incident": change, "added": delta}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def load_delivery_evidence(state_root: Optional[Path]) -> dict[str, Any]:
    """What scripts/incident_notifier.py recorded as delivered, read-only from its own files under ``state_root``.

    {"status", "notified": {incident_key: record}, "acked_keys": set, "receipt_status"}. The notifier writes a record
    only for a message that was actually delivered (SENT, or ALREADY_DELIVERED with the prior message_id): a CAPPED,
    quiet-held, HELD, FAILED or DEDUPED_UNCONFIRMED message leaves no record (incident_notifier.apply_result). An
    absent or unreadable state file is no evidence, so every notifiable row is held: never guessed delivered."""
    out: dict[str, Any] = {"status": "absent", "notified": {}, "acked_keys": set(), "receipt_status": "absent"}
    if state_root is None:
        out["status"] = out["receipt_status"] = "no_state_root"
        return out
    root = Path(state_root)
    try:
        doc = json.loads((root / NOTIFIER_STATE_REL).read_text(encoding="utf-8"))
    except FileNotFoundError:
        doc = None
    except (OSError, ValueError):
        doc, out["status"] = None, "unreadable"
    if isinstance(doc, dict):
        if doc.get("schema") == NOTIFIER_STATE_SCHEMA and isinstance(doc.get("notified"), dict):
            out["status"] = "ok"
            out["notified"] = {str(k): v for k, v in doc["notified"].items() if isinstance(v, dict)}
        else:
            out["status"] = "unrecognized"
    try:
        rec = json.loads((root / NOTIFIER_RECEIPT_REL).read_text(encoding="utf-8"))
    except FileNotFoundError:
        rec = None
    except (OSError, ValueError):
        rec, out["receipt_status"] = None, "unreadable"
    if isinstance(rec, dict):
        if rec.get("mode") == "live":  # a dry run's acks are a preview, never a decision
            out["receipt_status"] = "ok"
            out["acked_keys"] = {str(k) for k in rec.get("acked_keys") or []}
        else:
            out["receipt_status"] = "not_live"
    return out


def delivery_verdict(row: Mapping[str, Any], evidence: Optional[Mapping[str, Any]]) -> tuple[bool, str]:
    """(closable, reason) for one expired incident row. Pure.

    closable reasons: ``not_notifiable`` (P3: the notifier never sends it), ``delivered`` (a delivery at or after this
    generation's opened_at), ``covered_by_open_notice`` (the notifier holds an open, un-recovered notice for this key:
    the operator's last word on it is "open", and the notifier's dedupe is its explicit decision not to repeat it),
    ``operator_ack`` (acked on the notifier's last live receipt). Anything else is ``undelivered`` -> DEFERRED."""
    if str(row.get("severity") or "") not in NOTIFIABLE_SEVERITIES:
        return True, "not_notifiable"
    ev = evidence or {}
    key = str(row.get("incident_key") or "")
    if key in (ev.get("acked_keys") or set()):
        return True, "operator_ack"
    rec = (ev.get("notified") or {}).get(key)
    if not isinstance(rec, dict):
        return False, "undelivered"
    last = _parse(rec.get("last_notified_at"))
    if last is None:
        return False, "undelivered"
    opened = _parse(row.get("opened_at"))
    if opened is not None and last >= opened:
        return True, "delivered"
    recovered = _parse(rec.get("recovered_at"))
    if rec.get("open", True) is True and (recovered is None or recovered < last):
        return True, "covered_by_open_notice"
    return False, "undelivered"


def close_expired(
    conn: sqlite3.Connection, now: datetime, evidence: Optional[Mapping[str, Any]] = None
) -> dict[str, list[str]]:
    """Expired OPEN/DEFERRED incidents: CLOSED when ``delivery_verdict`` proves the operator was told (the fan-in then
    closes its incident: recovery), else DEFERRED (still presented; re-checked every run). {"closed", "deferred"}.

    Deliver-before-close (2026-10-17): before this, every expired row closed here whether or not the notifier had
    delivered it, so a P2 consumed during quiet hours or after the daily cap was spent closed unsent and vanished."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = [
            _row(r) or {}
            for r in conn.execute(
                "SELECT incident_key, severity, opened_at, state FROM comms_intent_incidents"
                " WHERE state IN (?, ?) AND open_until < ?",
                (*LIVE_INCIDENT_STATES, _iso(now)),
            )
        ]
        closed: list[str] = []
        deferred: list[str] = []
        for r in rows:
            ok, reason = delivery_verdict(r, evidence)
            if ok:
                conn.execute(
                    "UPDATE comms_intent_incidents SET state = 'CLOSED', closed_at = ?, close_reason = ?,"
                    " updated_at = ? WHERE incident_key = ?",
                    (_iso(now), reason, _iso(now), r["incident_key"]),
                )
                closed.append(r["incident_key"])
            else:
                if r.get("state") != INC_DEFERRED:
                    conn.execute(
                        "UPDATE comms_intent_incidents SET state = 'DEFERRED',"
                        " deferred_since = COALESCE(deferred_since, ?), updated_at = ? WHERE incident_key = ?",
                        (_iso(now), _iso(now), r["incident_key"]),
                    )
                deferred.append(r["incident_key"])
        conn.execute("COMMIT")
        return {"closed": closed, "deferred": deferred}
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ── the run ────────────────────────────────────────────────────────────────────────────────────────────────────────


def load_routes(path: Optional[Path] = None, host_path: Optional[Path] = None) -> dict[str, Any]:
    """The n8n route table plus (2026-10-15) the host-lane table config/host_comms_intent_routes.json, so an intent a
    HOST lane queued (scripts/lib/host_comms_intents.py) maps to its tier here. The n8n gateway never reads the host
    table. An unreadable host table leaves the n8n table alone (``host_routes: unreadable``): a host intent is then
    refused as unrouted (terminal -> the dead-letter finding), never guessed."""
    routes = load_intent_routes(path)
    try:
        merged = merged_intent_routes(routes, load_host_intent_routes(host_path))
    except FabricStoreError:
        return {**routes, "host_routes": "unreadable"}
    merged["host_routes"] = "ok"
    return merged


def plan(
    conn: Optional[sqlite3.Connection],
    routes: Mapping[str, Any],
    now: datetime,
    max_intents: int,
    evidence: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """What an apply run would do, from a read-only connection. Pure apart from SELECTs."""
    if conn is None:
        return {
            "ledger": "absent",
            "would": [],
            "would_refresh": [],
            "would_close": [],
            "would_hold_undelivered": [],
            "deferred": 0,
        }
    picks = claimable(conn, now, CLAIMABLE_SCAN)
    deferred = max(0, len(picks) - max_intents)
    would = []
    open_keys: dict[str, str] = {}
    if "comms_intent_incidents" in _tables(conn):
        open_keys = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT incident_key, state FROM comms_intent_incidents WHERE state IN (?, ?)", LIVE_INCIDENT_STATES
            )
        }
    for it in picks[:max_intents]:
        m = map_intent(it, routes)
        row = {
            "intent_id": it["intent_id"],
            "domain": it["domain"],
            "kind": it["kind"],
            "workflow_id": it["workflow_id"],
            "execution_id": it["execution_id"],
            "from_state": it["state"],
            "attempt": int(it.get("attempts") or 0) + 1,
            **m,
        }
        if m["action"] == "incident":
            row["incident"] = (
                "update_open" if open_keys.get(m["incident_key"]) in LIVE_INCIDENT_STATES else "create_or_reopen"
            )
            row["fanin_event_key"] = fanin_event_key(m["fanin_source"], m["fanin_item"], now.strftime("%Y-%m-%d"))
            open_keys[m["incident_key"]] = "OPEN"
        would.append(row)
    would_close: list[str] = []
    would_hold: list[str] = []
    if "comms_intent_incidents" in _tables(conn):
        for r in conn.execute(
            "SELECT incident_key, severity, opened_at, state FROM comms_intent_incidents"
            " WHERE state IN (?, ?) AND open_until < ?",
            (*LIVE_INCIDENT_STATES, _iso(now)),
        ):
            (would_close if delivery_verdict(_row(r) or {}, evidence)[0] else would_hold).append(r["incident_key"])
    return {
        "ledger": "present",
        "would": would,
        "would_refresh": [
            {"intent_id": r["intent_id"], "add": int(r["count"]) - int(r["consumed_count"])} for r in refreshable(conn)
        ],
        "would_close": would_close,
        "would_hold_undelivered": would_hold,
        "deferred": deferred,
        "backlog": backlog(conn, now),
    }


def apply(
    conn: sqlite3.Connection,
    routes: Mapping[str, Any],
    now: datetime,
    max_intents: int,
    token: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Close delivered expired incidents (hold the undelivered ones DEFERRED), claim and complete up to
    ``max_intents`` intents, fold repeats. Idempotent. ``evidence``: ``load_delivery_evidence``; None = no evidence,
    so every notifiable expired row is held."""
    window_s = int(routes.get("dedupe_window_s") or 3600)
    settled = close_expired(conn, now, evidence)
    closed = settled["closed"]
    picks = claimable(conn, now, CLAIMABLE_SCAN)
    deferred = max(0, len(picks) - max_intents)
    results: list[dict[str, Any]] = []
    for it in picks[:max_intents]:
        if not claim(conn, it, token=token, now=now):
            results.append({"intent_id": it["intent_id"], "state": "CLAIM_LOST"})
            continue
        try:
            m = map_intent(it, routes)
            results.append(complete(conn, it, m, token=token, now=now, window_s=window_s))
        except Exception as exc:  # noqa: BLE001 — one bad intent is FAILED with its error; the run goes on
            err = f"{type(exc).__name__}: {str(exc)[:200]}"
            fail(conn, it["intent_id"], token=token, error=err, now=now)
            results.append({"intent_id": it["intent_id"], "state": STATE_FAILED, "error": err, "transient": True})
    refreshed = [refresh(conn, r, now=now, window_s=window_s) for r in refreshable(conn)]
    return {
        "closed": closed,
        "held_undelivered": settled["deferred"],
        "results": results,
        "refreshed": [r for r in refreshed if r.get("refreshed")],
        "deferred": deferred,
        "backlog": backlog(conn, now),
    }


# ── fan-in readers (read-only) ─────────────────────────────────────────────────────────────────────────────────────


def open_incident_findings(ledger: Path, now: datetime) -> tuple[list[dict[str, Any]], str]:
    """Fan-in findings for every OPEN or DEFERRED (expired, undelivered) comms-intent incident. (findings, note).
    Never writes."""
    conn = connect_ro(ledger)
    if conn is None:
        return [], "ledger:absent"
    try:
        if "comms_intent_incidents" not in _tables(conn):
            return [], "incidents_table:absent"
        # Every row not CLOSED, past its window or not: closing is the consumer's decision, taken only after delivery
        # (``close_expired``). The old ``open_until >= now`` filter hid an expired, undelivered row from the notifier.
        rows = conn.execute(
            "SELECT * FROM comms_intent_incidents WHERE state IN (?, ?) ORDER BY incident_key", LIVE_INCIDENT_STATES
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = _row(r) or {}
        where = f"{d.get('last_node') or '-'}: {d.get('last_summary') or ''}".strip()
        out.append(
            {
                "source": d["fanin_source"],
                "item": d["fanin_item"],
                "severity": d["severity"],
                "detail": (
                    f"{d['count']} n8n intent(s) {d['domain']}/{d['kind']} tier {d['tier']} "
                    f"exec {d.get('last_execution_id')} · {where} [route:{d['tier']}]"
                )[:160],
                "artifact_rel": LEDGER_REL,
                "store": "persistent-state",
                "detected_at": d["opened_at"],
                "workflow_id": d["workflow_id"],
                "count": int(d["count"]),
                "event_keys": json.loads(d.get("intent_ids") or "[]"),
                "comms_intent_incident_key": d["incident_key"],
                "comms_intent_incident_state": d["state"],
            }
        )
    return out, f"ok:open={len(out)}"


def dead_letter_findings(ledger: Path, now: datetime) -> tuple[list[dict[str, Any]], str]:
    """The dead-letter rule: FAILED MAX_ATTEMPTS times (or refused) -> dead_letter; QUEUED > QUEUED_STALE_S ->
    queued_stale. One aggregated P2 each. (findings, note). Never writes."""
    conn = connect_ro(ledger)
    if conn is None:
        return [], "ledger:absent"
    try:
        tables = _tables(conn)
        if "comms_intents" not in tables:
            return [], "intents_table:absent"
        stale_cut = _iso(now - timedelta(seconds=QUEUED_STALE_S))
        lease_cut = _iso(now - timedelta(seconds=CLAIM_LEASE_S))
        if "comms_intent_consumption" in tables:
            stale = conn.execute(
                "SELECT i.intent_id, i.first_at FROM comms_intents i LEFT JOIN comms_intent_consumption c"
                " ON c.intent_id = i.intent_id WHERE i.first_at < ? AND (i.state = ?"
                " OR (i.state = ? AND (c.claimed_at IS NULL OR c.claimed_at < ?))) ORDER BY i.first_at",
                (stale_cut, STATE_QUEUED, STATE_CLAIMED, lease_cut),
            ).fetchall()
            dead = conn.execute(
                "SELECT i.intent_id, c.attempts, c.terminal, c.last_error, c.updated_at FROM comms_intents i"
                " JOIN comms_intent_consumption c ON c.intent_id = i.intent_id"
                " WHERE i.state = ? AND (c.terminal = 1 OR c.attempts >= ?) ORDER BY c.updated_at",
                (STATE_FAILED, MAX_ATTEMPTS),
            ).fetchall()
        else:
            stale = conn.execute(
                "SELECT intent_id, first_at FROM comms_intents WHERE state = ? AND first_at < ? ORDER BY first_at",
                (STATE_QUEUED, stale_cut),
            ).fetchall()
            dead = []
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if dead:
        reasons: dict[str, int] = {}
        for r in dead:
            k = str(r["last_error"] or "unknown").split(":", 1)[0]
            reasons[k] = reasons.get(k, 0) + 1
        out.append(
            {
                "source": DLQ_SOURCE,
                "item": "dead_letter",
                "severity": "P2",
                "detail": (
                    f"{len(dead)} comms intent(s) FAILED (>= {MAX_ATTEMPTS} attempts or refused): "
                    + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
                )[:160],
                "artifact_rel": LEDGER_REL,
                "store": "persistent-state",
                "detected_at": day0,
                "count": len(dead),
                "event_keys": [r["intent_id"] for r in dead][:INTENT_IDS_KEPT],
            }
        )
    if stale:
        oldest = _parse(stale[0]["first_at"])
        age_h = None if oldest is None else round((now - oldest).total_seconds() / 3600, 1)
        out.append(
            {
                "source": DLQ_SOURCE,
                "item": "queued_stale",
                "severity": "P2",
                "detail": (
                    f"{len(stale)} comms intent(s) QUEUED > {QUEUED_STALE_S // 3600} h, oldest {age_h} h: "
                    f"is {LANE_ID} running?"
                )[:160],
                "artifact_rel": LEDGER_REL,
                "store": "persistent-state",
                "detected_at": day0,
                "count": len(stale),
                "event_keys": [r["intent_id"] for r in stale][:INTENT_IDS_KEPT],
            }
        )
    return out, f"ok:dead_letter={len(dead)}:queued_stale={len(stale)}"


__all__ = [
    "FabricStoreError",
    "LANE_ID",
    "MAX_ATTEMPTS",
    "QUEUED_STALE_S",
    "apply",
    "close_expired",
    "dead_letter_findings",
    "delivery_verdict",
    "load_delivery_evidence",
    "map_intent",
    "open_incident_findings",
    "plan",
]
