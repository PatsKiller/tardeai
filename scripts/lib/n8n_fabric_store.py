"""n8n fabric Phase 1 host stores: terminal run outcomes and comms send-intents.

2026-10-14 (AGENTS.md §23.23, 10.0.0 PROPOSED; REFACTOR_PLAN B4/B6; TARGET_ARCHITECTURE §7). Two additive tables
in the coordination ledger file, on the ledger's own connection and RLock (scripts/lib/n8n_coordination_ledger.py):

``run_outcomes`` — written by scripts/n8n_run_executor.py when a run reaches a terminal state, read by the gateway's
read-only ``coordination/run_outcome`` operation. One row per run_id: status (success / failed / refused_policy /
skipped_lock), exit code, receipt path, duration, effect key. A refusal is a STATUS here, never an error: the Run
Lane sub-workflow branches on it (§23.23 governance (5)). When the executor has not written a row (it is older than
this module, or its write failed) the view falls back to the ``runs`` row itself (``source: runs_row``); a run that
is still REQUESTED or RUNNING is ``pending``.

``comms_intents`` — written by the gateway's ``comms/intent`` operation. n8n asks the host to notify; it holds no
bot token. The host dedupes on (domain, kind, subject) inside a window, applies an hourly cap, and routes by a
closed (domain, kind) -> tier table (config/n8n_comms_intent_routes.json, after ALERT_TAXONOMY.md §2-§3). An intent
is QUEUED for the host comms gateway; nothing in this module or the gateway sends (§24.1: the comms gateway is the
only sender). An intent whose (domain, kind) has no row is refused (``intent_unrouted``): an n8n caller cannot
invent a route, and nothing from n8n becomes a P1 by default (§24.1: the P1 path does not depend on n8n).

AUTHORITY: READ_ONLY_ADVISORY. No send, no spawn, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]

OUTCOME_SCHEMA = "RunOutcome@v1"
INTENT_RECEIPT_SCHEMA = "CommsIntentReceipt@v1"
INTENT_ROUTES_SCHEMA = "N8nCommsIntentRoutes@v1"
INTENT_ROUTES_REL = Path("config") / "n8n_comms_intent_routes.json"

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_REFUSED = "refused_policy"
STATUS_SKIPPED = "skipped_lock"
STATUS_PENDING = "pending"
STATUS_UNKNOWN = "unknown"
TERMINAL_STATUSES = (STATUS_SUCCESS, STATUS_FAILED, STATUS_REFUSED, STATUS_SKIPPED)
#: Ledger run state -> outcome status. RUN_TIMEOUT is a failure (the executor deadline or the reaper's
#: executor_lost); whether it may be retried is the Run Lane's retry budget plus the effect key's UNKNOWN hold.
STATE_TO_STATUS = {
    "RUN_DONE": STATUS_SUCCESS,
    "RUN_FAILED": STATUS_FAILED,
    "RUN_TIMEOUT": STATUS_FAILED,
    "RUN_REFUSED": STATUS_REFUSED,
    "RUN_SKIPPED_LOCK": STATUS_SKIPPED,
}
PENDING_STATES = frozenset({"REQUESTED", "RUNNING"})
TIERS = ("PAGE", "DIGEST", "DASHBOARD", "LOG")
#: ALERT_TAXONOMY.md §3 domains. Closed.
DOMAINS = frozenset(
    {
        "broker",
        "stops",
        "positions",
        "market_data",
        "alert_plane",
        "fabric",
        "host",
        "data",
        "research",
        "agents",
        "security",
    }
)
KIND_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
INTENT_STATE_QUEUED = "QUEUED"
SUBJECT_MAX = 120
SUMMARY_MAX = 300
NODE_MAX = 64
WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
EXECUTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
INTENT_FIELDS = frozenset({"domain", "kind", "subject", "summary", "workflow_id", "execution_id", "node"})


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _ts(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def status_for_state(state: str | None) -> str:
    if state in STATE_TO_STATUS:
        return STATE_TO_STATUS[str(state)]
    if state in PENDING_STATES:
        return STATUS_PENDING
    return STATUS_UNKNOWN


class FabricStoreError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── run outcomes ───────────────────────────────────────────────────────────────────────────────────────────────


class RunOutcomeStore:
    """``run_outcomes`` on a CoordinationLedger. The executor records; the gateway reads (``view``)."""

    def __init__(self, ledger: Any) -> None:
        self._l = ledger
        self.lock = ledger.lock
        if not getattr(ledger, "read_only", False):
            with self.lock:
                self._l._conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS run_outcomes (
                        run_id TEXT PRIMARY KEY,
                        lane_id TEXT NOT NULL,
                        mode TEXT,
                        status TEXT NOT NULL,
                        run_state TEXT NOT NULL,
                        exit_code INTEGER,
                        receipt_path TEXT,
                        duration_s REAL,
                        effect_key TEXT,
                        reason TEXT,
                        attempt INTEGER,
                        finished_at TEXT,
                        recorded_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS run_outcomes_lane ON run_outcomes (lane_id, recorded_at);
                    """
                )

    def record(self, receipt: Mapping[str, Any], *, receipt_path: str | None, now: float) -> dict[str, Any]:
        """Upsert the terminal outcome of one run from its RunReceipt (v1 or v2). Idempotent per run_id: a second
        record (a pending completion that lands twice) replaces the row with the same values."""
        run_id = str(receipt.get("run_id") or "")
        state = str(receipt.get("state") or "")
        if not run_id or state not in STATE_TO_STATUS:
            raise FabricStoreError("outcome_not_terminal")
        effect = receipt.get("effect")
        effect_key = effect.get("key") if isinstance(effect, Mapping) else None
        exit_code = receipt.get("exit_code")
        duration = receipt.get("duration_s")
        attempt = receipt.get("attempt")
        row = (
            run_id,
            str(receipt.get("lane_id") or ""),
            receipt.get("mode"),
            STATE_TO_STATUS[state],
            state,
            int(exit_code) if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
            receipt_path,
            float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
            effect_key if isinstance(effect_key, str) else None,
            (str(receipt.get("reason"))[:200] if receipt.get("reason") is not None else None),
            int(attempt) if isinstance(attempt, int) and not isinstance(attempt, bool) else None,
            receipt.get("finished_at"),
            _iso(now),
        )
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO run_outcomes (run_id, lane_id, mode, status, run_state, exit_code, receipt_path,"
                    " duration_s, effect_key, reason, attempt, finished_at, recorded_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(run_id) DO UPDATE SET lane_id=excluded.lane_id, mode=excluded.mode,"
                    " status=excluded.status, run_state=excluded.run_state, exit_code=excluded.exit_code,"
                    " receipt_path=excluded.receipt_path, duration_s=excluded.duration_s,"
                    " effect_key=excluded.effect_key, reason=excluded.reason, attempt=excluded.attempt,"
                    " finished_at=excluded.finished_at, recorded_at=excluded.recorded_at",
                    row,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        out = self.get(run_id)
        assert out is not None
        return out

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._l._conn.execute("SELECT * FROM run_outcomes WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else {k: row[k] for k in row.keys()}

    def view(self, run_id: str, run_store: Any = None) -> dict[str, Any]:
        """RunOutcome@v1 for ``run_id``: the executor's row, else the ledger ``runs`` row, else unknown."""
        out: dict[str, Any] = {
            "schema": OUTCOME_SCHEMA,
            "state": "OK",
            "run_id": run_id,
            "lane_id": None,
            "mode": None,
            "status": STATUS_UNKNOWN,
            "terminal": False,
            "run_state": None,
            "exit_code": None,
            "receipt_path": None,
            "duration_s": None,
            "effect_key": None,
            "reason": None,
            "attempt": None,
            "finished_at": None,
            "source": "none",
        }
        row = self.get(run_id)
        if row is not None:
            for k in (
                "lane_id",
                "mode",
                "status",
                "run_state",
                "exit_code",
                "receipt_path",
                "duration_s",
                "effect_key",
                "reason",
                "attempt",
                "finished_at",
            ):
                out[k] = row[k]
            out["terminal"] = out["status"] in TERMINAL_STATUSES
            out["source"] = "outcome"
            run = run_store.get(run_id) if run_store is not None else None
            if run is not None:
                _attach_identity(out, run)
            return out
        run = run_store.get(run_id) if run_store is not None else None
        if run is None:
            return out
        _attach_identity(out, run)
        receipt = run.get("receipt") if isinstance(run.get("receipt"), Mapping) else {}
        state = run.get("state")
        out.update(
            {
                "lane_id": run.get("lane_id"),
                "mode": receipt.get("mode") or run.get("mode"),
                "status": status_for_state(state),
                "run_state": state,
                "exit_code": run.get("exit_code"),
                "duration_s": run.get("duration_s"),
                "reason": receipt.get("reason"),
                "attempt": run.get("attempt"),
                "finished_at": run.get("finished_at"),
                "source": "runs_row",
            }
        )
        effect = receipt.get("effect")
        if isinstance(effect, Mapping) and isinstance(effect.get("key"), str):
            out["effect_key"] = effect["key"]
        out["terminal"] = out["status"] in TERMINAL_STATUSES
        return out


def _attach_identity(out: dict[str, Any], run: Mapping[str, Any]) -> None:
    """2026-10-15 (audit DD03/DD04, additive): the run's immutable request identity, so a caller can verify the outcome
    is the one it asked for, and the typed retry decision (owner, retryable, next_attempt_at, attempts_remaining,
    terminal_reason, dlq_ref) the executor recorded on the receipt."""
    out["identity"] = {
        "run_id": run.get("run_id"),
        "lane_id": run.get("lane_id"),
        "requested_mode": run.get("mode"),
        "requested_by": run.get("requested_by"),
        "caller_id": run.get("caller_id"),
        "slot_key": run.get("slot_key"),
        "attempt": run.get("attempt"),
    }
    receipt = run.get("receipt") if isinstance(run.get("receipt"), Mapping) else {}
    retry = receipt.get("retry")
    out["retry"] = dict(retry) if isinstance(retry, Mapping) else None


# ── comms intents ──────────────────────────────────────────────────────────────────────────────────────────────


def load_intent_routes(path: Path | None = None) -> dict[str, Any]:
    """The closed (domain, kind) -> tier table. Raises FabricStoreError("intent_routes_unreadable")."""
    p = path or (ROOT / INTENT_ROUTES_REL)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FabricStoreError("intent_routes_unreadable") from exc
    if not isinstance(doc, dict) or doc.get("schema") != INTENT_ROUTES_SCHEMA:
        raise FabricStoreError("intent_routes_unreadable")
    window, cap, rows = doc.get("dedupe_window_s"), doc.get("max_per_hour"), doc.get("routes")
    if not (isinstance(window, int) and 60 <= window <= 86400 and isinstance(cap, int) and 1 <= cap <= 1000):
        raise FabricStoreError("intent_routes_unreadable")
    if not isinstance(rows, list):
        raise FabricStoreError("intent_routes_unreadable")
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            raise FabricStoreError("intent_routes_unreadable")
        domain, kind, tier = r.get("domain"), r.get("kind"), r.get("tier")
        if domain not in DOMAINS or not isinstance(kind, str) or not KIND_RE.fullmatch(kind) or tier not in TIERS:
            raise FabricStoreError("intent_routes_unreadable")
        if (domain, kind) in routes:
            raise FabricStoreError("intent_routes_unreadable")
        routes[(domain, kind)] = {"tier": tier, "runbook_id": r.get("runbook_id")}
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"dedupe_window_s": window, "max_per_hour": cap, "routes": routes, "sha256": hashlib.sha256(raw).hexdigest()}


HOST_INTENT_ROUTES_SCHEMA = "HostCommsIntentRoutes@v1"
HOST_INTENT_ROUTES_REL = Path("config") / "host_comms_intent_routes.json"
PRODUCER_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def load_host_intent_routes(path: Path | None = None) -> dict[str, Any]:
    """(2026-10-15) The closed (domain, kind) -> {tier, runbook_id, producer} table for HOST-lane intents
    (config/host_comms_intent_routes.json; scripts/lib/host_comms_intents.py). Never read by the gateway's n8n
    ``comms/intent`` operation. Raises FabricStoreError("intent_routes_unreadable"); a pair that is also an n8n route
    is refused (one owner per route)."""
    p = path or (ROOT / HOST_INTENT_ROUTES_REL)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FabricStoreError("intent_routes_unreadable") from exc
    if not isinstance(doc, dict) or doc.get("schema") != HOST_INTENT_ROUTES_SCHEMA or not isinstance(doc.get("routes"), list):
        raise FabricStoreError("intent_routes_unreadable")
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    for r in doc["routes"]:
        if not isinstance(r, dict):
            raise FabricStoreError("intent_routes_unreadable")
        domain, kind, tier, producer = r.get("domain"), r.get("kind"), r.get("tier"), r.get("producer")
        if domain not in DOMAINS or not isinstance(kind, str) or not KIND_RE.fullmatch(kind) or tier not in TIERS:
            raise FabricStoreError("intent_routes_unreadable")
        if tier == "PAGE" or not isinstance(producer, str) or not PRODUCER_RE.fullmatch(producer):
            raise FabricStoreError("intent_routes_unreadable")
        if (domain, kind) in routes:
            raise FabricStoreError("intent_routes_unreadable")
        routes[(domain, kind)] = {"tier": tier, "runbook_id": r.get("runbook_id"), "producer": producer}
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"routes": routes, "sha256": hashlib.sha256(raw).hexdigest()}


def merged_intent_routes(n8n_routes: Mapping[str, Any], host_routes: Mapping[str, Any]) -> dict[str, Any]:
    """The n8n table plus the host table, for the HOST side only (host_comms_intents queueing and the comms-intent
    consumer's tier mapping). Window and cap stay the n8n table's; a pair in both tables is refused."""
    both = set(n8n_routes["routes"]) & set(host_routes["routes"])
    if both:
        raise FabricStoreError("intent_routes_unreadable")
    routes = dict(n8n_routes["routes"])
    routes.update(host_routes["routes"])
    sha = hashlib.sha256(f"{n8n_routes.get('sha256')}|{host_routes.get('sha256')}".encode("utf-8")).hexdigest()
    return {
        "dedupe_window_s": n8n_routes["dedupe_window_s"],
        "max_per_hour": n8n_routes["max_per_hour"],
        "routes": routes,
        "sha256": sha,
    }


def validate_intent(request: Mapping[str, Any]) -> dict[str, str]:
    """The seven intent fields, exact and bounded, or FabricStoreError(<reason>)."""
    body = {k: request.get(k) for k in INTENT_FIELDS}
    if not all(isinstance(v, str) for v in body.values()):
        raise FabricStoreError("malformed_event")
    if body["domain"] not in DOMAINS or not KIND_RE.fullmatch(body["kind"]):
        raise FabricStoreError("intent_unrouted")
    if not WORKFLOW_ID_RE.fullmatch(body["workflow_id"]) or not EXECUTION_ID_RE.fullmatch(body["execution_id"]):
        raise FabricStoreError("malformed_event")
    for name, limit in (("subject", SUBJECT_MAX), ("summary", SUMMARY_MAX), ("node", NODE_MAX)):
        if len(body[name]) > limit or CONTROL_RE.search(body[name]):
            raise FabricStoreError("malformed_event")
    if not body["subject"].strip():
        raise FabricStoreError("malformed_event")
    return body  # type: ignore[return-value]


def dedupe_key(domain: str, kind: str, subject: str) -> str:
    """Host-minted, never free-form: sha256 over (domain, kind, normalised subject)."""
    norm = " ".join(subject.lower().split())
    return "cd-" + hashlib.sha256(f"{domain}|{kind}|{norm}".encode("utf-8")).hexdigest()[:32]


class CommsIntentStore:
    """``comms_intents`` on a CoordinationLedger. ``accept`` dedupes, caps, routes and queues; it never sends."""

    def __init__(self, ledger: Any, routes: Mapping[str, Any] | None = None, routes_path: Path | None = None) -> None:
        self._l = ledger
        self.lock = ledger.lock
        self._routes = routes
        self._routes_path = routes_path
        if not getattr(ledger, "read_only", False):
            with self.lock:
                self._l._conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS comms_intents (
                        intent_id TEXT PRIMARY KEY,
                        dedupe_key TEXT NOT NULL,
                        domain TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        tier TEXT NOT NULL,
                        runbook_id TEXT,
                        subject TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        workflow_id TEXT NOT NULL,
                        execution_id TEXT NOT NULL,
                        node TEXT,
                        caller_id TEXT,
                        state TEXT NOT NULL,
                        count INTEGER NOT NULL DEFAULT 1,
                        first_at TEXT NOT NULL,
                        last_at TEXT NOT NULL,
                        routes_sha256 TEXT
                    );
                    CREATE INDEX IF NOT EXISTS comms_intents_dedupe ON comms_intents (dedupe_key, first_at);
                    CREATE INDEX IF NOT EXISTS comms_intents_first ON comms_intents (first_at);
                    """
                )

    def routes(self) -> Mapping[str, Any]:
        """Re-read per call unless fixed by the constructor, so a reviewed route change applies without restart."""
        return self._routes if self._routes is not None else load_intent_routes(self._routes_path)

    def accept(self, request: Mapping[str, Any], *, caller_id: str | None, now: float) -> dict[str, Any]:
        body = validate_intent(request)
        routes = self.routes()
        route = routes["routes"].get((body["domain"], body["kind"]))
        if route is None:
            raise FabricStoreError("intent_unrouted")
        dkey = dedupe_key(body["domain"], body["kind"], body["subject"])
        window = int(routes["dedupe_window_s"])
        since_window, since_hour = _iso(now - window), _iso(now - 3600)
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                prior = conn.execute(
                    "SELECT * FROM comms_intents WHERE dedupe_key = ? AND first_at >= ? ORDER BY first_at DESC LIMIT 1",
                    (dkey, since_window),
                ).fetchone()
                if prior is not None:
                    conn.execute(
                        "UPDATE comms_intents SET count = count + 1, last_at = ? WHERE intent_id = ?",
                        (_iso(now), prior["intent_id"]),
                    )
                    conn.execute("COMMIT")
                    return self._receipt(prior["intent_id"], duplicate=True)
                accepted = conn.execute(
                    "SELECT COUNT(*) AS n FROM comms_intents WHERE first_at >= ?", (since_hour,)
                ).fetchone()["n"]
                if int(accepted) >= int(routes["max_per_hour"]):
                    conn.execute("ROLLBACK")
                    raise FabricStoreError("intent_rate_limited")
                intent_id = "ci-" + hashlib.sha256(f"{dkey}|{_iso(now)}".encode("utf-8")).hexdigest()[:24]
                conn.execute(
                    "INSERT INTO comms_intents (intent_id, dedupe_key, domain, kind, tier, runbook_id, subject,"
                    " summary, workflow_id, execution_id, node, caller_id, state, count, first_at, last_at,"
                    " routes_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (
                        intent_id,
                        dkey,
                        body["domain"],
                        body["kind"],
                        route["tier"],
                        route.get("runbook_id"),
                        body["subject"],
                        body["summary"],
                        body["workflow_id"],
                        body["execution_id"],
                        body["node"],
                        caller_id,
                        INTENT_STATE_QUEUED,
                        _iso(now),
                        _iso(now),
                        routes.get("sha256"),
                    ),
                )
                conn.execute("COMMIT")
            except FabricStoreError:
                raise
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self._receipt(intent_id, duplicate=False)

    def get(self, intent_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._l._conn.execute("SELECT * FROM comms_intents WHERE intent_id = ?", (intent_id,)).fetchone()
        return None if row is None else {k: row[k] for k in row.keys()}

    def list_queued(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._l._conn.execute(
                "SELECT * FROM comms_intents WHERE state = ? ORDER BY first_at ASC LIMIT ?",
                (INTENT_STATE_QUEUED, int(limit)),
            ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def _receipt(self, intent_id: str, *, duplicate: bool) -> dict[str, Any]:
        row = self.get(intent_id) or {}
        return {
            "schema": INTENT_RECEIPT_SCHEMA,
            "state": "ACCEPTED",
            "intent_id": intent_id,
            "dedupe_key": row.get("dedupe_key"),
            "tier": row.get("tier"),
            "count": row.get("count"),
            "duplicate": duplicate,
            "delivery": "queued_for_host_comms_gateway",
            "outbound": "blocked",
            "durable": True,
        }
