"""Source-side nonce and idempotency ledger for the n8n coordination lab.

This is not the CIO action ledger, the CIO notification outbox, or
communication_deliveries. Those stores record operator notifications or CIO
actions, including telegram channels. Putting a coordination nonce in them
would couple a lab claim to a live send path.

The default gateway process does not open this file. durable=false stays on
the gateway receipt until a served process passes a restart and a consumer
test. A row here can prove exactly-once acceptance inside this file. It does
not prove exactly-once delivery to n8n or to an operator.

No HMAC seed is stored. A reference token is returned once and only its hash
is kept.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

NO_CONSUMER_REASON = (
    "Source-side lab ledger for blocked n8n pilots. No production job imports it. "
    "Tests are not a consumer. durable stays false until a served path passes a restart and a consumer test."
)

LEDGER_SCHEMA = "N8nCoordinationLedgerRow@v1"
REFERENCE_SCOPE = "coordination_read"
MAX_PAYLOAD_BYTES = 65536
RATE_LIMIT = 30
RATE_WINDOW_S = 60


class LedgerError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CoordinationLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nonces (
                nonce TEXT PRIMARY KEY,
                exp REAL NOT NULL,
                consumed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                idempotency_key TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                source_sha TEXT,
                served_sha TEXT,
                workflow_version TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                expiry REAL,
                terminal_result TEXT,
                refusal_reason TEXT,
                dead_letter INTEGER NOT NULL DEFAULT 0,
                consumer TEXT,
                consumer_receipt_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS effects (
                idempotency_key TEXT PRIMARY KEY,
                effect TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accept_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caller_id TEXT NOT NULL,
                at_unix REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reference_tokens (
                token_hash TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                project TEXT NOT NULL,
                lane_id TEXT NOT NULL,
                exp REAL NOT NULL,
                scope TEXT NOT NULL
            );
            """
        )

    def accept(
        self,
        *,
        nonce: str,
        nonce_exp: float,
        idempotency_key: str,
        payload_hash: str,
        now: float,
        source_sha: str,
        served_sha: str | None,
        caller_id: str,
        workflow_version: str | None = None,
        payload_bytes: int = 0,
        crash_before_commit: bool = False,
    ) -> dict[str, Any]:
        if payload_bytes > MAX_PAYLOAD_BYTES:
            raise LedgerError("payload_too_large")
        if not nonce or len(nonce) < 8 or not idempotency_key:
            raise LedgerError("malformed_event")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._rate_limit(caller_id, now)
            prior_nonce = self._conn.execute("SELECT exp FROM nonces WHERE nonce = ?", (nonce,)).fetchone()
            if prior_nonce is not None and float(prior_nonce["exp"]) >= now:
                raise LedgerError("replayed_nonce")
            existing = self._conn.execute(
                "SELECT payload_hash, state FROM events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise LedgerError("idempotency_conflict")
                self._conn.execute("ROLLBACK")
                return self._row(idempotency_key, duplicate=True)
            self._conn.execute(
                "INSERT INTO nonces (nonce, exp, consumed_at) VALUES (?, ?, ?)",
                (nonce, nonce_exp, _iso(now)),
            )
            self._conn.execute(
                """
                INSERT INTO events (
                    idempotency_key, payload_hash, state, source_sha, served_sha,
                    workflow_version, attempts, expiry, created_at, updated_at
                ) VALUES (?, ?, 'ACCEPTED', ?, ?, ?, 0, ?, ?, ?)
                """,
                (idempotency_key, payload_hash, source_sha, served_sha, workflow_version, nonce_exp, _iso(now), _iso(now)),
            )
            self._conn.execute(
                "INSERT INTO effects (idempotency_key, effect) VALUES (?, 'source_accept')",
                (idempotency_key,),
            )
            self._conn.execute(
                "INSERT INTO accept_log (caller_id, at_unix) VALUES (?, ?)",
                (caller_id, now),
            )
            if crash_before_commit:
                raise RuntimeError("crash_before_commit")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        row = self._row(idempotency_key, duplicate=False)
        row["external_delivery"] = "NOT_CLAIMED"
        return row

    def effect_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM effects").fetchone()["n"])

    def nonce_present(self, nonce: str) -> bool:
        return self._conn.execute("SELECT 1 FROM nonces WHERE nonce = ?", (nonce,)).fetchone() is not None

    def issue_reference(
        self,
        *,
        idempotency_key: str,
        project: str,
        lane_id: str,
        exp: float,
    ) -> str:
        """Return a one-time reference. The raw token is not stored."""
        token = secrets.token_urlsafe(32)
        digest = _token_hash(token)
        self._conn.execute(
            """
            INSERT INTO reference_tokens (token_hash, idempotency_key, project, lane_id, exp, scope)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (digest, idempotency_key, project, lane_id, exp, REFERENCE_SCOPE),
        )
        return token

    def redeem_reference(
        self,
        token: str,
        *,
        idempotency_key: str,
        project: str,
        lane_id: str,
        now: float,
    ) -> dict[str, Any]:
        digest = _token_hash(token)
        row = self._conn.execute(
            "SELECT * FROM reference_tokens WHERE token_hash = ?",
            (digest,),
        ).fetchone()
        if row is None:
            raise LedgerError("unknown_reference")
        if float(row["exp"]) < now:
            raise LedgerError("reference_expired")
        if row["scope"] != REFERENCE_SCOPE:
            raise LedgerError("bad_scope")
        if row["project"] != project or row["lane_id"] != lane_id or row["idempotency_key"] != idempotency_key:
            raise LedgerError("reference_bound")
        return {
            "scope": REFERENCE_SCOPE,
            "project": project,
            "lane_id": lane_id,
            "idempotency_key": idempotency_key,
            "hmac_key_returned": False,
            "can_mint_claim": False,
        }

    def stored_token_material(self) -> str:
        rows = self._conn.execute("SELECT token_hash FROM reference_tokens").fetchall()
        return "\n".join(str(row["token_hash"]) for row in rows)

    def mark_terminal(
        self,
        idempotency_key: str,
        *,
        state: str,
        now: float,
        reason: str | None = None,
        consumer: str | None = None,
        consumer_receipt_id: str | None = None,
        dead_letter: bool = False,
    ) -> dict[str, Any]:
        allowed = {"CLAIMED", "STARTED", "ARTIFACT_WRITTEN", "CONSUMED", "REFUSED", "FAILED", "DEAD_LETTER"}
        if state not in allowed:
            raise LedgerError("illegal_transition")
        if state == "CONSUMED" and (not consumer or not consumer_receipt_id):
            raise LedgerError("no_consumer_receipt")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            current = self._conn.execute(
                "SELECT state, attempts FROM events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if current is None:
                raise LedgerError("unknown_event")
            self._conn.execute(
                """
                UPDATE events
                   SET state = ?, attempts = ?, updated_at = ?, refusal_reason = ?,
                       consumer = ?, consumer_receipt_id = ?, dead_letter = ?,
                       terminal_result = ?
                 WHERE idempotency_key = ?
                """,
                (
                    state,
                    int(current["attempts"]) + 1,
                    _iso(now),
                    reason,
                    consumer,
                    consumer_receipt_id,
                    1 if dead_letter or state == "DEAD_LETTER" else 0,
                    state if state in {"CONSUMED", "REFUSED", "FAILED", "DEAD_LETTER"} else None,
                    idempotency_key,
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self._row(idempotency_key, duplicate=False)

    def _rate_limit(self, caller_id: str, now: float) -> None:
        cutoff = now - RATE_WINDOW_S
        count = self._conn.execute(
            "SELECT COUNT(*) AS n FROM accept_log WHERE caller_id = ? AND at_unix >= ?",
            (caller_id, cutoff),
        ).fetchone()["n"]
        if int(count) >= RATE_LIMIT:
            raise LedgerError("rate_limited")

    def _row(self, idempotency_key: str, *, duplicate: bool) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM events WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if row is None:
            raise LedgerError("unknown_event")
        body = {key: row[key] for key in row.keys()}
        body["schema"] = LEDGER_SCHEMA
        body["duplicate"] = duplicate
        body["persistence"] = "sqlite_file"
        body["durable"] = False
        body["exactly_once_scope"] = "source_side_file_only"
        body["external_delivery"] = "NOT_CLAIMED"
        return body


def payload_too_large(event: Mapping[str, Any]) -> bool:
    import json

    return len(json.dumps(event).encode("utf-8")) > MAX_PAYLOAD_BYTES
