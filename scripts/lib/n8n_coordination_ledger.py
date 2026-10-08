"""Source-side nonce and idempotency ledger for the n8n coordination lab.

This is not the CIO action ledger, the CIO notification outbox, or
communication_deliveries. Those stores record operator notifications or CIO
actions, including telegram channels. Putting a coordination nonce in them
would couple a lab claim to a live send path.

2026-10-07 (plan tranche B): the gateway process opens this file by default
(`--ledger`), through the dict-like adapters below, so nonces, receipts and
artifact references survive a restart. ``durable`` on a row means the SQLite
COMMIT returned; it still does not prove delivery to n8n or to an operator.

No HMAC seed is stored. A reference token is returned once and only its hash
is kept.

2026-10-08 (n8n scheduler-of-record, tranche N1): the ``runs`` table. The gateway
``run`` operation inserts a REQUESTED row; scripts/n8n_run_executor.py claims the
oldest REQUESTED row (RUNNING) in one transaction and finishes it with a
RunReceipt@v1. The gateway never spawns; the executor never authenticates.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

NO_CONSUMER_REASON = (
    "Source-side coordination ledger. Opened by scripts/n8n_coordination_gateway.py (--ledger) and read by the "
    "Command Center projection (scripts/lib/n8n_coordination_projection.py); neither is a scheduled lane yet."
)

LEDGER_SCHEMA = "N8nCoordinationLedgerRow@v1"
REFERENCE_SCOPE = "coordination_read"
RUN_STATE_REQUESTED = "REQUESTED"
RUN_STATE_RUNNING = "RUNNING"
RUN_FINISHED_STATES = frozenset({"RUN_DONE", "RUN_FAILED", "RUN_TIMEOUT", "RUN_SKIPPED_LOCK", "RUN_REFUSED"})
RUN_STATES = frozenset({RUN_STATE_REQUESTED, RUN_STATE_RUNNING}) | RUN_FINISHED_STATES
RUN_ROW_FIELDS = ("run_id", "lane_id", "mode", "state", "requested_by", "caller_id", "requested_at", "started_at",
                  "finished_at", "exit_code", "duration_s")
MAX_PAYLOAD_BYTES = 65536
RATE_LIMIT = 30
RATE_WINDOW_S = 60


class LedgerError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _load_edges() -> dict[str, set[str]]:
    try:
        from scripts.lib.n8n_coordination_gateway import EDGES  # type: ignore
    except ImportError:
        from n8n_coordination_gateway import EDGES  # type: ignore
    return EDGES


_EDGES = _load_edges()


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
            CREATE TABLE IF NOT EXISTS receipts (
                store_key TEXT PRIMARY KEY,
                payload_hash TEXT,
                receipt_json TEXT NOT NULL,
                project TEXT,
                lane_id TEXT,
                state TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifact_refs (
                store_key TEXT NOT NULL,
                store TEXT NOT NULL,
                ref TEXT NOT NULL,
                sha256 TEXT,
                as_of TEXT,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reference_tokens (
                token_hash TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                project TEXT NOT NULL,
                lane_id TEXT NOT NULL,
                exp REAL NOT NULL,
                scope TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                lane_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                state TEXT NOT NULL,
                requested_by TEXT,
                caller_id TEXT,
                requested_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                exit_code INTEGER,
                duration_s REAL,
                receipt_json TEXT
            );
            CREATE INDEX IF NOT EXISTS runs_state_requested_at ON runs (state, requested_at);
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
            # 2026-10-07: the gateway's transition table applies here too; before this any terminal
            # state could follow any other (CONSUMED straight from ACCEPTED, FAILED after CONSUMED).
            if state not in _EDGES.get(str(current["state"]), set()):
                raise LedgerError(f"illegal_transition:{current['state']}->{state}")
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
        body["durable"] = True          # the COMMIT returned; see module docstring for what that does not prove
        body["durable_scope"] = "sqlite_commit_returned"
        body["exactly_once_scope"] = "source_side_file_only"
        body["external_delivery"] = "NOT_CLAIMED"
        return body


def payload_too_large(event: Mapping[str, Any]) -> bool:
    import json

    return len(json.dumps(event).encode("utf-8")) > MAX_PAYLOAD_BYTES


# ── dict-like adapters so the gateway library (which only knows dict stores) persists here ──


class LedgerNonceStore:
    """nonce -> exp, backed by the nonces table. Expired rows are pruned lazily."""

    durable = True

    def __init__(self, ledger: CoordinationLedger) -> None:
        self._l = ledger

    def get(self, nonce: str, default=None):
        row = self._l._conn.execute("SELECT exp FROM nonces WHERE nonce = ?", (nonce,)).fetchone()
        return float(row["exp"]) if row is not None else default

    def __setitem__(self, nonce: str, exp: float) -> None:
        now = datetime.now(timezone.utc).timestamp()
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            self._l._conn.execute("DELETE FROM nonces WHERE exp < ?", (now - 3600,))
            self._l._conn.execute("INSERT OR REPLACE INTO nonces (nonce, exp, consumed_at) VALUES (?, ?, ?)",
                                  (nonce, float(exp), _iso(now)))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise

    def __contains__(self, nonce: str) -> bool:
        return self.get(nonce) is not None


class _Slot(dict):
    """{payload_hash, receipt}: assigning `receipt` writes through to the receipts table."""

    def __init__(self, store: "LedgerReceiptStore", key: str, payload_hash: str | None, receipt: dict) -> None:
        super().__init__(payload_hash=payload_hash, receipt=receipt)
        self._store, self._key = store, key

    def __setitem__(self, name: str, value) -> None:
        super().__setitem__(name, value)
        if name == "receipt":
            self._store._write(self._key, self.get("payload_hash"), value)


class LedgerReceiptStore:
    """``project:idempotency_key`` -> slot, backed by the receipts table. Durable: a slot is readable
    only after its INSERT committed, so a restart replays what was accepted, nothing more."""

    durable = True

    def __init__(self, ledger: CoordinationLedger) -> None:
        self._l = ledger

    def _write(self, key: str, payload_hash: str | None, receipt: Mapping[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            self._l._conn.execute(
                "INSERT OR REPLACE INTO receipts (store_key, payload_hash, receipt_json, project, lane_id, state, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, payload_hash, json.dumps(dict(receipt), sort_keys=True, default=str),
                 receipt.get("source_project"), receipt.get("lane_id"), receipt.get("state"), now.isoformat()))
            ref = receipt.get("artifact_ref")
            if isinstance(ref, Mapping) and receipt.get("state") == "ARTIFACT_WRITTEN":
                self._l._conn.execute(
                    "INSERT INTO artifact_refs (store_key, store, ref, sha256, as_of, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (key, str(ref.get("store")), str(ref.get("ref")), ref.get("sha256"), ref.get("as_of"), now.isoformat()))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise

    def get(self, key: str, default=None):
        row = self._l._conn.execute("SELECT payload_hash, receipt_json FROM receipts WHERE store_key = ?", (key,)).fetchone()
        if row is None:
            return default
        return _Slot(self, key, row["payload_hash"], json.loads(row["receipt_json"]))

    def __setitem__(self, key: str, slot: Mapping[str, Any]) -> None:
        self._write(key, slot.get("payload_hash"), slot["receipt"])

    def iter_receipts(self, *, project: str | None = None, lane_id: str | None = None, state: str | None = None,
                      since: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT receipt_json FROM receipts WHERE 1=1", []
        if project:
            sql += " AND project = ?"; args.append(project)
        if lane_id:
            sql += " AND lane_id = ?"; args.append(lane_id)
        if state:
            sql += " AND state = ?"; args.append(state)
        if since:
            sql += " AND updated_at >= ?"; args.append(since)
        sql += " ORDER BY updated_at DESC LIMIT ?"; args.append(int(limit))
        return [json.loads(r["receipt_json"]) for r in self._l._conn.execute(sql, args).fetchall()]


class LedgerRunStore:
    """``runs`` table adapter. ``request`` is what the gateway's run operation calls; ``claim_next`` and
    ``finish`` belong to the executor. Every write is one BEGIN IMMEDIATE ... COMMIT, so two executors
    polling the same file cannot both claim a row, and a gateway restart replays what was requested."""

    durable = True

    def __init__(self, ledger: CoordinationLedger) -> None:
        self._l = ledger

    def request(self, *, run_id: str, lane_id: str, mode: str, requested_by: str | None, caller_id: str | None,
                now: float) -> tuple[dict[str, Any], bool]:
        """Insert a REQUESTED row, or return the existing row for this run_id with duplicate=True."""
        if not run_id or not lane_id or not mode:
            raise LedgerError("malformed_event")
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._l._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if existing is not None:
                self._l._conn.execute("ROLLBACK")
                return self._row_dict(existing), True
            self._l._conn.execute(
                "INSERT INTO runs (run_id, lane_id, mode, state, requested_by, caller_id, requested_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, lane_id, mode, RUN_STATE_REQUESTED, requested_by, caller_id, _iso(now)))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise
        return self.get(run_id), False

    def get(self, run_id: str) -> dict[str, Any] | None:
        row = self._l._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else self._row_dict(row)

    def claim_next(self, *, now: float | None = None) -> dict[str, Any] | None:
        """Oldest REQUESTED row -> RUNNING in one transaction; None when the queue is empty."""
        at = _iso(now if now is not None else datetime.now(timezone.utc).timestamp())
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._l._conn.execute(
                "SELECT run_id FROM runs WHERE state = ? ORDER BY requested_at ASC, run_id ASC LIMIT 1",
                (RUN_STATE_REQUESTED,)).fetchone()
            if row is None:
                self._l._conn.execute("ROLLBACK")
                return None
            self._l._conn.execute("UPDATE runs SET state = ?, started_at = ? WHERE run_id = ? AND state = ?",
                                  (RUN_STATE_RUNNING, at, row["run_id"], RUN_STATE_REQUESTED))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise
        return self.get(str(row["run_id"]))

    def finish(self, run_id: str, *, state: str, receipt: Mapping[str, Any], now: float | None = None) -> dict[str, Any]:
        """RUNNING -> one of RUN_FINISHED_STATES with the RunReceipt@v1 stored on the row."""
        if state not in RUN_FINISHED_STATES:
            raise LedgerError("illegal_transition")
        at = _iso(now if now is not None else datetime.now(timezone.utc).timestamp())
        exit_code = receipt.get("exit_code")
        duration = receipt.get("duration_s")
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            current = self._l._conn.execute("SELECT state FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if current is None:
                raise LedgerError("unknown_event")
            if current["state"] != RUN_STATE_RUNNING:
                raise LedgerError(f"illegal_transition:{current['state']}->{state}")
            self._l._conn.execute(
                "UPDATE runs SET state = ?, finished_at = ?, exit_code = ?, duration_s = ?, receipt_json = ? WHERE run_id = ?",
                (state, receipt.get("finished_at") or at,
                 int(exit_code) if isinstance(exit_code, int) else None,
                 float(duration) if isinstance(duration, (int, float)) else None,
                 json.dumps(dict(receipt), sort_keys=True, default=str), run_id))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise
        out = self.get(run_id)
        assert out is not None
        return out

    def list(self, *, state: str | None = None, lane_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM runs WHERE 1=1", []
        if state:
            sql += " AND state = ?"; args.append(state)
        if lane_id:
            sql += " AND lane_id = ?"; args.append(lane_id)
        sql += " ORDER BY requested_at DESC, run_id DESC LIMIT ?"; args.append(int(limit))
        return [self._row_dict(r) for r in self._l._conn.execute(sql, args).fetchall()]

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = {k: row[k] for k in RUN_ROW_FIELDS}
        raw = row["receipt_json"]
        out["receipt"] = json.loads(raw) if raw else None
        return out
