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

2026-10-08 (first N1 shadow burst, 17:15:00Z): the gateway serves from ThreadingHTTPServer and every
handler thread shares this ONE connection. Two handlers each ran ``BEGIN IMMEDIATE`` on it within 60 ms,
the second raised ``cannot start a transaction within a transaction``, that handler died and the relay
saw a dropped connection. Every method that touches the connection is ``@_locked`` (one RLock per
ledger, shared by its adapters), reads included: a single SELECT on a shared connection would otherwise
observe another thread's half-finished transaction. The lock is in-process only; cross-process safety
(executor vs. gateway on the same file) stays with sqlite's BEGIN IMMEDIATE + busy timeout.

2026-10-09 (n8n maturity B5.4, design 02 §3.3): ADDITIVE schema for registry-driven dispatch. ``runs`` gains
nullable ``slot_key, attempt, parent_run_id, class, priority, worker_id, pid, heartbeat_at, verdict`` (added by
ALTER TABLE only when missing, so an old file keeps every row); new tables ``dead_letters``, ``breakers`` and
``event_cursors``. The executor writes dead letters and breakers (it holds the verdict, see
scripts/lib/n8n_retry_policy.py ``finalize_outcome``); ``coordination/due`` only reads them;
scripts/n8n_dlq.py releases them. Breaker open iff ``opened_at`` is set and (``released_at`` is NULL or
``released_at < opened_at``).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Mapping


def _locked(fn):
    """Hold the owning ledger's RLock for the whole call. Reentrant, so a locked method may call another
    (accept -> _rate_limit -> _row). Adapters expose the ledger's lock as ``self.lock``."""

    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return fn(self, *args, **kwargs)

    return wrapper

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
#: 2026-10-09 (B5.4): additive nullable ``runs`` columns -> SQL type. Row dicts carry them under the same names.
RUN_EXT_COLUMNS: dict[str, str] = {
    "slot_key": "TEXT", "attempt": "INTEGER", "parent_run_id": "TEXT", "class": "TEXT", "priority": "INTEGER",
    "worker_id": "TEXT", "pid": "INTEGER", "heartbeat_at": "TEXT", "verdict": "TEXT",
}
RUN_VERDICTS = frozenset({"ok", "retryable", "terminal", "skipped"})
DEAD_LETTER_FIELDS = ("slot_key", "lane_id", "mode", "slot_local", "attempts", "last_run_id", "last_state",
                      "last_reason", "verdict", "dead_at", "released_at", "released_by", "release_note",
                      "class", "max_attempts", "policy")
#: Additive dead_letters columns (review of #1594): what dead_letter_rearmable needs to refuse a re-run.
DEAD_LETTER_EXT_COLUMNS: dict[str, str] = {"class": "TEXT", "max_attempts": "INTEGER", "policy": "TEXT"}
#: Classes that never retry, whatever their policy says (a retry could double-send or double-write).
SINGLE_ATTEMPT_CLASSES = frozenset({"send", "learn"})


def dead_letter_rearmable(row: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Whether a dead letter may be released and so re-armed by ``coordination/due``: (ok, why_not). Pure.

    Refused for class send/learn, for a single-attempt run (``max_attempts`` <= 1), and when either is unknown
    (NULL, e.g. a legacy row): unknown means no re-run. ``release_dead_letter(s)`` enforce it; B5.3 due must
    re-arm a released dead letter only when this returns (True, "")."""
    if not row:
        return False, "not_found"
    klass, max_attempts = row.get("class"), row.get("max_attempts")
    if klass is None or max_attempts is None:
        return False, "unknown_class_or_policy"
    if klass in SINGLE_ATTEMPT_CLASSES:
        return False, f"class_{klass}_never_retries"
    if int(max_attempts) <= 1:
        return False, "single_attempt_policy"
    return True, ""
MAX_PAYLOAD_BYTES = 65536
RATE_LIMIT = 30
RATE_WINDOW_S = 60


#: 2026-10-09 (B5.5): executor v2 claim ordering (design 02 §5). Priority 0 = incident/heartbeat/approval, 9 = backfill.
DEFAULT_RUN_PRIORITY = 5
PRIORITY_AGE_STEP_S = 300
PRIORITY_AGE_MAX = 3


def aged_priority(priority: int, requested_at: str, now: float) -> int:
    """``priority - min(floor(wait_s / 300), 3)``; an unparseable requested_at ages nothing. Pure."""
    try:
        dt = datetime.fromisoformat(str(requested_at))
        wait_s = now - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        wait_s = 0.0
    return int(priority) - min(max(int(wait_s // PRIORITY_AGE_STEP_S), 0), PRIORITY_AGE_MAX)


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
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        """``read_only=True`` (B5.4 review): open with ``mode=ro``, no WAL pragma and NO migration, so a reader
        (``n8n_dlq.py list``) never alters a production schema. The file must exist. Writes raise."""
        self.path = Path(path)
        self.read_only = read_only
        # One connection, many handler threads (see the module docstring).
        self.lock = threading.RLock()
        if read_only:
            self._conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=5,
                                         isolation_level=None, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    @_locked
    def has_table(self, name: str) -> bool:
        return self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() \
            is not None

    @_locked
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
        self._migrate_dispatch_v2()

    def _migrate_dispatch_v2(self) -> None:
        """B5.4 additive migration; idempotent (columns added only when missing, tables IF NOT EXISTS)."""
        self._add_columns("runs", RUN_EXT_COLUMNS)
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS runs_slot_key ON runs (slot_key);
            CREATE INDEX IF NOT EXISTS runs_lane_state ON runs (lane_id, state);
            CREATE TABLE IF NOT EXISTS dead_letters (
                slot_key TEXT PRIMARY KEY,
                lane_id TEXT NOT NULL,
                mode TEXT,
                slot_local TEXT,
                attempts INTEGER,
                last_run_id TEXT,
                last_state TEXT,
                last_reason TEXT,
                verdict TEXT,
                dead_at TEXT NOT NULL,
                released_at TEXT,
                released_by TEXT,
                release_note TEXT,
                class TEXT,
                max_attempts INTEGER,
                policy TEXT
            );
            CREATE INDEX IF NOT EXISTS dead_letters_lane ON dead_letters (lane_id, dead_at);
            CREATE TABLE IF NOT EXISTS breakers (
                lane_id TEXT PRIMARY KEY,
                opened_at TEXT,
                consecutive INTEGER,
                released_at TEXT,
                released_by TEXT
            );
            CREATE TABLE IF NOT EXISTS event_cursors (
                lane_id TEXT NOT NULL,
                source TEXT NOT NULL,
                cursor TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (lane_id, source)
            );
            """
        )
        self._add_columns("dead_letters", DEAD_LETTER_EXT_COLUMNS)

    def _add_columns(self, table: str, columns: Mapping[str, str]) -> None:
        """ALTER TABLE ADD COLUMN for each missing column. Two processes migrating at once (gateway + executor
        starting together) can both see a column missing; the loser's "duplicate column name" is success."""
        have = {str(r["name"]) for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, typ in columns.items():
            if col in have:
                continue
            try:
                self._conn.execute(f'ALTER TABLE {table} ADD COLUMN "{col}" {typ}')
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    @_locked
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

    @_locked
    def effect_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM effects").fetchone()["n"])

    @_locked
    def nonce_present(self, nonce: str) -> bool:
        return self._conn.execute("SELECT 1 FROM nonces WHERE nonce = ?", (nonce,)).fetchone() is not None

    @_locked
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

    @_locked
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

    @_locked
    def stored_token_material(self) -> str:
        rows = self._conn.execute("SELECT token_hash FROM reference_tokens").fetchall()
        return "\n".join(str(row["token_hash"]) for row in rows)

    @_locked
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
        self.lock = ledger.lock  # the ledger's RLock; a caller that reads then writes through this adapter holds it

    @_locked
    def get(self, nonce: str, default=None):
        row = self._l._conn.execute("SELECT exp FROM nonces WHERE nonce = ?", (nonce,)).fetchone()
        return float(row["exp"]) if row is not None else default

    @_locked
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
        self.lock = ledger.lock  # the ledger's RLock; a caller that reads then writes through this adapter holds it

    @_locked
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

    @_locked
    def get(self, key: str, default=None):
        row = self._l._conn.execute("SELECT payload_hash, receipt_json FROM receipts WHERE store_key = ?", (key,)).fetchone()
        if row is None:
            return default
        return _Slot(self, key, row["payload_hash"], json.loads(row["receipt_json"]))

    def __setitem__(self, key: str, slot: Mapping[str, Any]) -> None:
        self._write(key, slot.get("payload_hash"), slot["receipt"])

    @_locked
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
        self.lock = ledger.lock  # the ledger's RLock; a caller that reads then writes through this adapter holds it

    @_locked
    def request(self, *, run_id: str, lane_id: str, mode: str, requested_by: str | None, caller_id: str | None,
                now: float, slot_key: str | None = None, attempt: int | None = None,
                parent_run_id: str | None = None, klass: str | None = None,
                priority: int | None = None) -> tuple[dict[str, Any], bool]:
        """Insert a REQUESTED row, or return the existing row for this run_id with duplicate=True.

        The B5.4 keywords are optional and stored as given (NULL when omitted); an existing row is returned
        unchanged whatever they say (insert-or-return-existing)."""
        if not run_id or not lane_id or not mode:
            raise LedgerError("malformed_event")
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._l._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if existing is not None:
                self._l._conn.execute("ROLLBACK")
                return self._row_dict(existing), True
            self._l._conn.execute(
                "INSERT INTO runs (run_id, lane_id, mode, state, requested_by, caller_id, requested_at,"
                ' slot_key, attempt, parent_run_id, "class", priority)'
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, lane_id, mode, RUN_STATE_REQUESTED, requested_by, caller_id, _iso(now),
                 slot_key, None if attempt is None else int(attempt), parent_run_id, klass,
                 None if priority is None else int(priority)))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise
        return self.get(run_id), False

    @_locked
    def get(self, run_id: str) -> dict[str, Any] | None:
        row = self._l._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else self._row_dict(row)

    @_locked
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

    # ── B5.5: executor v2 claim / heartbeat (design 02 §5). claim_next above stays the v1 path. ──

    @_locked
    def claim_next_v2(self, *, worker_id: str, exclude_classes=(), max_priority: int | None = None, now: float,
                      default_classes: Mapping[str, str] | None = None,
                      default_priority: int = DEFAULT_RUN_PRIORITY) -> dict[str, Any] | None:
        """Best eligible REQUESTED row -> RUNNING (worker_id, heartbeat_at) in one BEGIN IMMEDIATE; None if none.

        Eligible: its lane has NO RUNNING row (at most one RUNNING row per lane), its effective class
        (``runs.class``, else ``default_classes[lane_id]``, else ``"report"``) is not in ``exclude_classes``, and
        its raw priority (``runs.priority``, else ``default_priority``) is ``<= max_priority`` when given.
        Order: aged priority ``priority - min(floor(wait_s / 300), 3)``, then requested_at, then run_id.
        The returned row carries ``effective_class`` / ``effective_priority`` (not written to the row)."""
        at = _iso(now)
        excluded = frozenset(exclude_classes or ())
        classes = default_classes or {}
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            # No row LIMIT (review #1598): a window over requested_at starved a new P0 behind >= 2000 older rows.
            # The raw-priority filter runs in SQL; the scan orders by raw priority so the best rows come first.
            sql = ('SELECT run_id, lane_id, "class", priority, requested_at FROM runs r WHERE r.state = ?'
                   " AND NOT EXISTS (SELECT 1 FROM runs r2 WHERE r2.lane_id = r.lane_id AND r2.state = ?)")
            args: list[Any] = [RUN_STATE_REQUESTED, RUN_STATE_RUNNING]
            if max_priority is not None:
                sql += " AND COALESCE(r.priority, ?) <= ?"
                args += [int(default_priority), int(max_priority)]
            sql += " ORDER BY COALESCE(r.priority, ?) ASC, requested_at ASC, run_id ASC"
            args.append(int(default_priority))
            rows = self._l._conn.execute(sql, args).fetchall()
            best: tuple | None = None
            for r in rows:
                prio = int(r["priority"]) if r["priority"] is not None else int(default_priority)
                if best is not None and prio - PRIORITY_AGE_MAX > best[0][0]:
                    break                         # raw-priority order: no later row can age past the best
                klass = r["class"] or classes.get(str(r["lane_id"])) or "report"
                if klass in excluded:
                    continue
                if max_priority is not None and prio > max_priority:
                    continue
                key = (aged_priority(prio, str(r["requested_at"]), now), str(r["requested_at"]), str(r["run_id"]))
                if best is None or key < best[0]:
                    best = (key, str(r["run_id"]), klass, prio)
            if best is None:
                self._l._conn.execute("ROLLBACK")
                return None
            self._l._conn.execute(
                "UPDATE runs SET state = ?, started_at = ?, worker_id = ?, heartbeat_at = ? WHERE run_id = ? AND state = ?",
                (RUN_STATE_RUNNING, at, worker_id, at, best[1], RUN_STATE_REQUESTED))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise
        out = self.get(best[1])
        assert out is not None
        out["effective_class"], out["effective_priority"] = best[2], best[3]
        return out

    @_locked
    def touch_heartbeat(self, run_id: str, pid: int | None, now: float) -> bool:
        """Stamp heartbeat_at (and pid when given) on a RUNNING row. False when the row is no longer RUNNING."""
        return self._write("UPDATE runs SET heartbeat_at = ?, pid = COALESCE(?, pid) WHERE run_id = ? AND state = ?",
                           (_iso(now), None if pid is None else int(pid), run_id, RUN_STATE_RUNNING)) > 0

    @_locked
    def list_running(self) -> list[dict[str, Any]]:
        """Every RUNNING row, oldest start first."""
        return [self._row_dict(r) for r in self._l._conn.execute(
            "SELECT * FROM runs WHERE state = ? ORDER BY started_at ASC, run_id ASC", (RUN_STATE_RUNNING,)).fetchall()]

    @_locked
    def list_breakers(self, *, open_only: bool = True) -> list[dict[str, Any]]:
        """Breaker rows (+ ``open``), open ones only by default."""
        out = []
        for lane in [str(r["lane_id"]) for r in self._l._conn.execute(
                "SELECT lane_id FROM breakers ORDER BY lane_id").fetchall()]:
            row = self.breaker(lane)
            if row is not None and (row["open"] or not open_only):
                out.append(row)
        return out

    @_locked
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

    @_locked
    def list(self, *, state: str | None = None, lane_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM runs WHERE 1=1", []
        if state:
            sql += " AND state = ?"; args.append(state)
        if lane_id:
            sql += " AND lane_id = ?"; args.append(lane_id)
        sql += " ORDER BY requested_at DESC, run_id DESC LIMIT ?"; args.append(int(limit))
        return [self._row_dict(r) for r in self._l._conn.execute(sql, args).fetchall()]

    # ── B5.3: read helpers for coordination/due (scripts/lib/n8n_due.py); reads only, no schema change ──

    @_locked
    def runs_by_key_range(self, lo: str, hi: str, limit: int = 1000) -> list[dict[str, Any]]:
        """Rows with lo <= run_id <= hi (the run_id PRIMARY KEY index), ascending. Server-minted slot keys sort
        chronologically within one lane+mode, so one range covers a lane's whole catch-up window."""
        rows = self._l._conn.execute("SELECT * FROM runs WHERE run_id >= ? AND run_id <= ? ORDER BY run_id LIMIT ?",
                                     (lo, hi, int(limit))).fetchall()
        return [self._row_dict(r) for r in rows]

    @_locked
    def recent_done(self, lane_id: str, *, modes: Any = ("live",), limit: int = 50) -> list[dict[str, Any]]:
        """The lane's newest RUN_DONE rows in the given modes (index runs_lane_state), newest finish first."""
        modes = [str(m) for m in modes] or ["live"]
        marks = ",".join("?" for _ in modes)
        rows = self._l._conn.execute(
            f"SELECT * FROM runs WHERE lane_id = ? AND state = 'RUN_DONE' AND mode IN ({marks})"
            " ORDER BY finished_at DESC LIMIT ?", (lane_id, *modes, int(limit))).fetchall()
        return [self._row_dict(r) for r in rows]

    # ── B5.4: verdicts, dead letters, breakers, event cursors (design 02 §3.3/§3.4) ──

    def _write(self, sql: str, args: tuple) -> int:
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self._l._conn.execute(sql, args)
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise
        return int(cur.rowcount)

    @_locked
    def set_verdict(self, run_id: str, verdict: str) -> dict[str, Any]:
        if verdict not in RUN_VERDICTS:
            raise LedgerError("bad_verdict")
        if self._write("UPDATE runs SET verdict = ? WHERE run_id = ?", (verdict, run_id)) == 0:
            raise LedgerError("unknown_event")
        out = self.get(run_id)
        assert out is not None
        return out

    @_locked
    def record_dead_letter(self, *, slot_key: str, lane_id: str, mode: str | None, slot_local: str | None,
                           attempts: int | None, last_run_id: str | None, last_state: str | None,
                           last_reason: str | None, verdict: str | None, now: float, klass: str | None = None,
                           max_attempts: int | None = None, policy: str | None = None) -> dict[str, Any]:
        """Upsert the slot's dead letter. A re-dead slot (released, re-armed, died again) clears its release.
        ``klass`` / ``max_attempts`` (effective) / ``policy`` feed ``dead_letter_rearmable``; NULL = not re-armable."""
        if not slot_key or not lane_id:
            raise LedgerError("malformed_event")
        self._write(
            "INSERT INTO dead_letters (slot_key, lane_id, mode, slot_local, attempts, last_run_id, last_state,"
            " last_reason, verdict, dead_at, released_at, released_by, release_note, class, max_attempts, policy)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)"
            " ON CONFLICT(slot_key) DO UPDATE SET lane_id=excluded.lane_id, mode=excluded.mode,"
            " slot_local=excluded.slot_local, attempts=excluded.attempts, last_run_id=excluded.last_run_id,"
            " last_state=excluded.last_state, last_reason=excluded.last_reason, verdict=excluded.verdict,"
            " dead_at=excluded.dead_at, released_at=NULL, released_by=NULL, release_note=NULL,"
            " class=excluded.class, max_attempts=excluded.max_attempts, policy=excluded.policy",
            (slot_key, lane_id, mode, slot_local, attempts, last_run_id, last_state, last_reason, verdict, _iso(now),
             klass, None if max_attempts is None else int(max_attempts), policy))
        out = self.get_dead_letter(slot_key)
        assert out is not None
        return out

    @_locked
    def get_dead_letter(self, slot_key: str) -> dict[str, Any] | None:
        row = self._l._conn.execute("SELECT * FROM dead_letters WHERE slot_key = ?", (slot_key,)).fetchone()
        return None if row is None else _dead_letter_dict(row)

    @_locked
    def list_dead_letters(self, lane_id: str | None = None, include_released: bool = False) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM dead_letters WHERE 1=1", []
        if lane_id:
            sql += " AND lane_id = ?"; args.append(lane_id)
        if not include_released:
            sql += " AND released_at IS NULL"
        sql += " ORDER BY dead_at DESC, slot_key ASC"
        return [_dead_letter_dict(r) for r in self._l._conn.execute(sql, args).fetchall()]

    @_locked
    def release_dead_letter(self, slot_key: str, by: str, note: str, now: float) -> dict[str, Any] | None:
        """Mark an UNRELEASED dead letter released. None when no such row or it is already released.
        Raises ``LedgerError("release_refused:<why>")`` when ``dead_letter_rearmable`` refuses the row."""
        cur = self.get_dead_letter(slot_key)
        if cur is None or cur["released_at"]:
            return None
        ok, why = dead_letter_rearmable(cur)
        if not ok:
            raise LedgerError(f"release_refused:{why}")
        n = self._write("UPDATE dead_letters SET released_at = ?, released_by = ?, release_note = ?"
                        " WHERE slot_key = ? AND released_at IS NULL", (_iso(now), by, note, slot_key))
        return self.get_dead_letter(slot_key) if n else None

    @_locked
    def release_dead_letters(self, slot_keys: list[str], by: str, note: str, now: float, *,
                             breaker_lane: str | None = None) -> dict[str, Any]:
        """Release several dead letters and (optionally) the lane's open breaker in ONE transaction. Every key
        must be an unreleased, re-armable dead letter or nothing is written (LedgerError release_refused /
        not_found). Returns {"released": [rows], "breaker_released": bool}."""
        for key in slot_keys:
            cur = self.get_dead_letter(key)
            if cur is None or cur["released_at"]:
                raise LedgerError(f"not_found:{key}")
            ok, why = dead_letter_rearmable(cur)
            if not ok:
                raise LedgerError(f"release_refused:{why}:{key}")
        brk = self.breaker(breaker_lane) if breaker_lane else None
        at = _iso(now)
        self._l._conn.execute("BEGIN IMMEDIATE")
        try:
            for key in slot_keys:
                self._l._conn.execute("UPDATE dead_letters SET released_at = ?, released_by = ?, release_note = ?"
                                      " WHERE slot_key = ? AND released_at IS NULL", (at, by, note, key))
            if brk and brk["open"]:
                self._l._conn.execute("UPDATE breakers SET released_at = ?, released_by = ? WHERE lane_id = ?",
                                      (at, by, breaker_lane))
            self._l._conn.execute("COMMIT")
        except Exception:
            self._l._conn.execute("ROLLBACK")
            raise
        return {"released": [self.get_dead_letter(k) for k in slot_keys], "breaker_released": bool(brk and brk["open"])}

    @_locked
    def consecutive_dead(self, lane_id: str) -> int:
        """Dead slots of the lane since the later of its last RUN_DONE and its last breaker release.

        A RUN_DONE resets the streak; so does an operator breaker release (otherwise the next dead slot
        would re-open the breaker at once)."""
        last_ok = self._l._conn.execute(
            "SELECT MAX(finished_at) AS t FROM runs WHERE lane_id = ? AND state = 'RUN_DONE'", (lane_id,)).fetchone()["t"]
        brk = self.breaker(lane_id)
        cutoff = max([t for t in (last_ok, (brk or {}).get("released_at")) if t] or [""])
        row = self._l._conn.execute("SELECT COUNT(*) AS n FROM dead_letters WHERE lane_id = ? AND dead_at > ?",
                                    (lane_id, cutoff)).fetchone()
        return int(row["n"])

    @_locked
    def breaker(self, lane_id: str) -> dict[str, Any] | None:
        """The lane's breaker row plus ``open`` (bool), or None when the lane never had one."""
        row = self._l._conn.execute("SELECT * FROM breakers WHERE lane_id = ?", (lane_id,)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in ("lane_id", "opened_at", "consecutive", "released_at", "released_by")}
        out["open"] = breaker_is_open(out)
        return out

    @_locked
    def open_breaker(self, lane_id: str, consecutive: int, now: float) -> dict[str, Any]:
        self._write(
            "INSERT INTO breakers (lane_id, opened_at, consecutive, released_at, released_by) VALUES (?, ?, ?, NULL, NULL)"
            " ON CONFLICT(lane_id) DO UPDATE SET opened_at=excluded.opened_at, consecutive=excluded.consecutive,"
            " released_at=NULL, released_by=NULL", (lane_id, _iso(now), int(consecutive)))
        out = self.breaker(lane_id)
        assert out is not None
        return out

    @_locked
    def release_breaker(self, lane_id: str, by: str, now: float) -> dict[str, Any] | None:
        """Release an OPEN breaker. None when the lane has no open breaker."""
        cur = self.breaker(lane_id)
        if cur is None or not cur["open"]:
            return None
        self._write("UPDATE breakers SET released_at = ?, released_by = ? WHERE lane_id = ?", (_iso(now), by, lane_id))
        return self.breaker(lane_id)

    @_locked
    def get_cursor(self, lane_id: str, source: str) -> str | None:
        row = self._l._conn.execute("SELECT cursor FROM event_cursors WHERE lane_id = ? AND source = ?",
                                    (lane_id, source)).fetchone()
        return None if row is None else row["cursor"]

    @_locked
    def set_cursor(self, lane_id: str, source: str, cursor: str | None, now: float) -> None:
        self._write(
            "INSERT INTO event_cursors (lane_id, source, cursor, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(lane_id, source) DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at",
            (lane_id, source, cursor, _iso(now)))

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = {k: row[k] for k in RUN_ROW_FIELDS}
        keys = row.keys()
        for col in RUN_EXT_COLUMNS:
            out[col] = row[col] if col in keys else None
        raw = row["receipt_json"]
        out["receipt"] = json.loads(raw) if raw else None
        return out


def _dead_letter_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {k: (row[k] if k in keys else None) for k in DEAD_LETTER_FIELDS}


def breaker_is_open(row: Mapping[str, Any] | None) -> bool:
    """Open iff ``opened_at`` is set and (``released_at`` is NULL or ``released_at < opened_at``). Pure."""
    if not row or not row.get("opened_at"):
        return False
    released = row.get("released_at")
    return not released or str(released) < str(row["opened_at"])
