"""Isolated SQLite business/idempotency journal for the Temporal runtime POC."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RuntimeStore:
    """Small WAL database with uniqueness at every external side-effect boundary."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "runtime_poc.sqlite3"
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_ref TEXT PRIMARY KEY,
                    artifact_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity_results (
                    idempotency_key TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity_attempts (
                    workflow_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    worker_build_id TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (workflow_id, stage, attempt)
                );
                CREATE TABLE IF NOT EXISTS provider_requests (
                    provider_request_id TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS accepted_evidence (
                    symbol TEXT PRIMARY KEY,
                    evidence_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    notification_identity TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fault_once (
                    workflow_id TEXT NOT NULL,
                    boundary TEXT NOT NULL,
                    PRIMARY KEY (workflow_id, boundary)
                );
                CREATE TABLE IF NOT EXISTS markers (
                    workflow_id TEXT NOT NULL,
                    boundary TEXT NOT NULL,
                    marker_json TEXT NOT NULL,
                    marked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (workflow_id, boundary)
                );
                CREATE TABLE IF NOT EXISTS counters (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                """
            )

    def put_artifact(self, artifact_ref: str, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, sort_keys=True)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO artifacts(artifact_ref, artifact_json) VALUES (?, ?)",
                (artifact_ref, encoded),
            )

    def artifact(self, artifact_ref: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT artifact_json FROM artifacts WHERE artifact_ref=?", (artifact_ref,)
            ).fetchone()
        if row is None:
            raise KeyError(artifact_ref)
        return json.loads(row[0])

    def cached_result(self, key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT result_json FROM activity_results WHERE idempotency_key=?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_result(self, key: str, result: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(result, sort_keys=True)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO activity_results(idempotency_key, result_json) VALUES (?, ?)",
                (key, encoded),
            )
            row = db.execute(
                "SELECT result_json FROM activity_results WHERE idempotency_key=?", (key,)
            ).fetchone()
        return json.loads(row[0])

    def record_attempt(self, workflow_id: str, stage: str, attempt: int, build_id: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO activity_attempts(workflow_id, stage, attempt, worker_build_id) "
                "VALUES (?, ?, ?, ?)",
                (workflow_id, stage, attempt, build_id),
            )

    def reserve_fault_once(self, workflow_id: str, boundary: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO fault_once(workflow_id, boundary) VALUES (?, ?)",
                (workflow_id, boundary),
            )
        return cursor.rowcount == 1

    def marker(self, workflow_id: str, boundary: str, value: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO markers(workflow_id, boundary, marker_json) VALUES (?, ?, ?)",
                (workflow_id, boundary, json.dumps(value, sort_keys=True)),
            )

    def has_marker(self, workflow_id: str, boundary: str) -> bool:
        with self.connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM markers WHERE workflow_id=? AND boundary=?",
                    (workflow_id, boundary),
                ).fetchone()
                is not None
            )

    def increment(self, name: str) -> int:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO counters(name, value) VALUES (?, 1) "
                "ON CONFLICT(name) DO UPDATE SET value=value+1",
                (name,),
            )
            value = int(db.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()[0])
            db.execute("COMMIT")
        return value

    def counter(self, name: str) -> int:
        with self.connect() as db:
            row = db.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
        return int(row[0]) if row else 0

    def provider_response(self, request_id: str, response: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        encoded = json.dumps(response, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT response_json FROM provider_requests WHERE provider_request_id=?", (request_id,)
            ).fetchone()
            created = existing is None
            if created:
                db.execute(
                    "INSERT INTO provider_requests(provider_request_id, response_json) VALUES (?, ?)",
                    (request_id, encoded),
                )
                db.execute(
                    "INSERT INTO counters(name, value) VALUES ('provider_calls', 1) "
                    "ON CONFLICT(name) DO UPDATE SET value=value+1"
                )
                payload = response
            else:
                payload = json.loads(existing[0])
            db.execute("COMMIT")
        return payload, created

    def accepted_evidence(self, symbol: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT evidence_hash FROM accepted_evidence WHERE symbol=?", (symbol,)
            ).fetchone()
        return str(row[0]) if row else None

    def accept_evidence(self, symbol: str, evidence_hash: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO accepted_evidence(symbol, evidence_hash) VALUES (?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET evidence_hash=excluded.evidence_hash",
                (symbol, evidence_hash),
            )

    def insert_unique(self, table: str, key_column: str, key: str, payload: dict[str, Any]) -> bool:
        if (table, key_column) not in {
            ("decisions", "decision_id"),
            ("notification_outbox", "notification_identity"),
        }:
            raise ValueError("unsupported unique table")
        payload_column = "payload_json"
        with self.connect() as db:
            cursor = db.execute(
                f"INSERT OR IGNORE INTO {table}({key_column}, {payload_column}) VALUES (?, ?)",
                (key, json.dumps(payload, sort_keys=True)),
            )
        return cursor.rowcount == 1

    def evidence(self) -> dict[str, Any]:
        with self.connect() as db:
            tables = {}
            for name in (
                "activity_attempts",
                "provider_requests",
                "decisions",
                "notification_outbox",
                "markers",
            ):
                tables[name] = [dict(row) for row in db.execute(f"SELECT * FROM {name} ORDER BY 1, 2")]
            counters = {row[0]: int(row[1]) for row in db.execute("SELECT name, value FROM counters")}
        return {"tables": tables, "counters": counters}
