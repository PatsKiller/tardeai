"""Ops -> Controls stores: Postgres (production) and an in-memory twin (tests), one interface.

Tables: migrations/2026_10_22_ops_controls.sql (NOT applied until the operator runs it). Until then
:meth:`PgStore.tables_status` answers NOT_MIGRATED and every mutating route refuses.

Rules both implementations keep (tests run the same suite against each):
  * ops_audit and operator_settings_history are append-only; ops_audit rows are hash-chained (prev_hash, row_hash).
  * request status moves only by compare-and-set (:meth:`transition`), so two writers cannot both win.
  * a WebAuthn challenge is single use and expires; a TOTP time step is accepted once (strictly increasing).
  * nothing is ever deleted: passkeys are revoked, settings are unset (active = false), requests are terminal.
AUTHORITY: OPERATOR_ONLY (written by the CC Ops handler and the host applier only).
"""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

TABLES = ("operator_settings", "operator_settings_history", "ops_audit", "ops_applier_requests",
          "ops_webauthn_challenges", "webauthn_credentials", "totp_recovery")

REQUEST_COLUMNS = ("request_id", "idempotency_key", "kind", "direction", "executor", "params", "phrase", "preview",
                   "expected_state_digest", "actor", "status", "status_at", "created_at", "stepup_token_hash",
                   "stepup_expires_at", "stepup_factor", "stepup_credential_id", "stepup_used_at", "approved_at",
                   "approval_sig", "applied_at", "result", "undo_of", "undone_by")
JSON_REQUEST_COLUMNS = ("params", "preview", "result")


class StoreError(Exception):
    def __init__(self, code: str, detail: str = "", status: int = 409) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def audit_hash(prev_hash: Optional[str], row: dict) -> str:
    body = {k: row.get(k) for k in ("at", "actor", "action", "kind", "request_id", "outcome", "detail")}
    return hashlib.sha256(((prev_hash or "") + _canon(body)).encode("utf-8")).hexdigest()


def verify_audit_chain(rows: Iterable[dict]) -> bool:
    prev = None
    for r in sorted(rows, key=lambda r: r["seq"]):
        if r.get("prev_hash") != prev or audit_hash(prev, r) != r.get("row_hash"):
            return False
        prev = r["row_hash"]
    return True


# ── in-memory twin ──────────────────────────────────────────────────────────────────────────────────────────────────


class MemoryStore:
    """Same behaviour as PgStore, in memory. Test double; never used by a served process."""

    def __init__(self, *, migrated: bool = True, clock: Callable[[], datetime] = _now) -> None:
        self.migrated = migrated
        self.clock = clock
        self._lock = threading.RLock()
        self.requests: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.settings: dict[str, dict] = {}
        self.history: list[dict] = []
        self.challenges: dict[str, dict] = {}
        self.credentials: dict[str, dict] = {}
        self.totp: list[dict] = []

    def tables_status(self) -> dict:
        if not self.migrated:
            return {"state": "NOT_MIGRATED", "missing_tables": list(TABLES), "reason": "migration not applied"}
        return {"state": "OK", "missing_tables": [], "reason": None}

    # requests
    def create_request(self, row: dict) -> tuple[dict, bool]:
        with self._lock:
            for r in self.requests.values():
                if r["idempotency_key"] == row["idempotency_key"]:
                    return copy.deepcopy(r), False
            full = {c: None for c in REQUEST_COLUMNS}
            full.update(copy.deepcopy(row))
            full.setdefault("created_at", self.clock())
            full["created_at"] = full["created_at"] or self.clock()
            full["status_at"] = full.get("status_at") or self.clock()
            self.requests[row["request_id"]] = full
            return copy.deepcopy(full), True

    def get_request(self, request_id: str) -> Optional[dict]:
        with self._lock:
            r = self.requests.get(request_id)
            return copy.deepcopy(r) if r else None

    def list_requests(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = sorted(self.requests.values(), key=lambda r: r["created_at"], reverse=True)[:limit]
            return copy.deepcopy(rows)

    def list_approved(self, executor: str = "applier", limit: int = 10) -> list[dict]:
        with self._lock:
            rows = [r for r in self.requests.values() if r["status"] == "APPROVED" and r["executor"] == executor]
            return copy.deepcopy(sorted(rows, key=lambda r: r["approved_at"] or r["created_at"])[:limit])

    def transition(self, request_id: str, from_statuses: Iterable[str], to_status: str, **fields: Any) -> Optional[dict]:
        with self._lock:
            r = self.requests.get(request_id)
            if not r or r["status"] not in set(from_statuses):
                return None
            r.update(copy.deepcopy(fields))
            r["status"] = to_status
            r["status_at"] = self.clock()
            return copy.deepcopy(r)

    def set_fields(self, request_id: str, **fields: Any) -> None:
        with self._lock:
            if request_id in self.requests:
                self.requests[request_id].update(copy.deepcopy(fields))

    # audit (append-only)
    def append_audit(self, *, actor: str, action: str, kind: Optional[str], request_id: Optional[str], outcome: str,
                     detail: Optional[dict] = None) -> int:
        with self._lock:
            prev = self.audit[-1]["row_hash"] if self.audit else None
            row = {"seq": len(self.audit) + 1, "at": self.clock().isoformat(), "actor": actor, "action": action,
                   "kind": kind, "request_id": request_id, "outcome": outcome, "detail": dict(detail or {}),
                   "prev_hash": prev}
            row["row_hash"] = audit_hash(prev, row)
            self.audit.append(row)
            return row["seq"]

    def list_audit(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return copy.deepcopy(list(reversed(self.audit))[:limit])

    def audit_update(self, seq: int, **fields: Any) -> None:
        raise StoreError("APPEND_ONLY", "ops_audit refuses UPDATE", 403)

    def audit_delete(self, seq: int) -> None:
        raise StoreError("APPEND_ONLY", "ops_audit refuses DELETE", 403)

    # settings
    def setting_get(self, key: str) -> Optional[dict]:
        with self._lock:
            r = self.settings.get(key)
            return copy.deepcopy(r) if r else None

    def settings_all(self) -> dict[str, dict]:
        with self._lock:
            return copy.deepcopy(self.settings)

    def settings_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return copy.deepcopy(list(reversed(self.history))[:limit])

    def setting_apply(self, key: str, value: Any, active: bool, *, actor: str, request_id: str,
                      expect: dict) -> dict:
        with self._lock:
            cur = self.settings.get(key)
            cur_active = bool(cur and cur["active"])
            cur_val = cur["value"] if cur_active else None
            if cur_active != bool(expect.get("active")) or cur_val != expect.get("value"):
                raise StoreError("STATE_CHANGED", f"{key} changed since the preview", 409)
            h = {"seq": len(self.history) + 1, "key": key, "op": "set" if active else "unset",
                 "old_value": cur["value"] if cur else None, "old_active": cur["active"] if cur else None,
                 "new_value": value if active else (cur["value"] if cur else None), "new_active": active,
                 "actor": actor, "request_id": request_id, "at": self.clock().isoformat()}
            self.history.append(h)
            self.settings[key] = {"key": key, "value": h["new_value"], "active": active,
                                  "updated_at": self.clock().isoformat(), "updated_by": actor, "request_id": request_id}
            return copy.deepcopy(h)

    # challenges
    def challenge_put(self, *, request_id: str, purpose: str, challenge: str, expires_at: datetime) -> str:
        with self._lock:
            cid = "ch_" + secrets.token_hex(8)
            self.challenges[cid] = {"challenge_id": cid, "request_id": request_id, "purpose": purpose,
                                    "challenge": challenge, "created_at": self.clock(), "expires_at": expires_at,
                                    "used_at": None}
            return cid

    def challenge_take(self, *, request_id: str, purpose: str, challenge: str) -> dict:
        """Consume the challenge the client echoes back. Single use; bound to (request, purpose); must be unexpired."""
        with self._lock:
            hits = [c for c in self.challenges.values() if c["request_id"] == request_id and c["purpose"] == purpose
                    and c["challenge"] == challenge]
            if not hits:
                raise StoreError("CHALLENGE_UNKNOWN", "no challenge issued for this request", 403)
            c = hits[0]
            if c["used_at"] is not None:
                raise StoreError("CHALLENGE_REPLAYED", "challenge already used", 403)
            if c["expires_at"] <= self.clock():
                raise StoreError("CHALLENGE_EXPIRED", "challenge expired", 403)
            c["used_at"] = self.clock()
            return copy.deepcopy(c)

    # credentials
    def credentials_list(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(sorted(self.credentials.values(), key=lambda c: str(c["created_at"])))

    def credential_get(self, credential_id: str) -> Optional[dict]:
        with self._lock:
            c = self.credentials.get(credential_id)
            return copy.deepcopy(c) if c else None

    def credential_add(self, row: dict) -> None:
        with self._lock:
            if row["credential_id"] in self.credentials:
                raise StoreError("CREDENTIAL_EXISTS", "passkey already registered", 409)
            full = {"sign_count": 0, "transports": [], "aaguid": None, "last_used_at": None, "revoked_at": None,
                    "revoked_by": None, "revoke_request_id": None, "created_at": self.clock().isoformat()}
            full.update(copy.deepcopy(row))
            self.credentials[row["credential_id"]] = full

    def credential_touch(self, credential_id: str, *, old_count: int, new_count: int) -> bool:
        with self._lock:
            c = self.credentials.get(credential_id)
            if not c or c["revoked_at"] or c["sign_count"] != old_count:
                return False
            c["sign_count"] = new_count
            c["last_used_at"] = self.clock().isoformat()
            return True

    def credential_revoke(self, credential_id: str, *, actor: str, request_id: str) -> bool:
        with self._lock:
            c = self.credentials.get(credential_id)
            if not c or c["revoked_at"]:
                return False
            c.update(revoked_at=self.clock().isoformat(), revoked_by=actor, revoke_request_id=request_id)
            return True

    # totp
    def totp_get(self) -> Optional[dict]:
        with self._lock:
            act = [t for t in self.totp if not t["revoked_at"]]
            return copy.deepcopy(act[-1]) if act else None

    def totp_enroll(self, *, label: str, fingerprint: str, actor: str) -> dict:
        with self._lock:
            for t in self.totp:
                if not t["revoked_at"]:
                    t["revoked_at"] = self.clock().isoformat()
            row = {"id": len(self.totp) + 1, "label": label, "secret_fingerprint": fingerprint,
                   "enrolled_at": self.clock().isoformat(), "enrolled_by": actor, "last_used_step": None,
                   "last_used_at": None, "revoked_at": None}
            self.totp.append(row)
            return copy.deepcopy(row)

    def totp_mark_step(self, totp_id: int, step: int) -> bool:
        with self._lock:
            for t in self.totp:
                if t["id"] == totp_id and not t["revoked_at"]:
                    if t["last_used_step"] is not None and step <= t["last_used_step"]:
                        return False
                    t["last_used_step"] = step
                    t["last_used_at"] = self.clock().isoformat()
                    return True
            return False


# ── Postgres ────────────────────────────────────────────────────────────────────────────────────────────────────────


class PgStore:
    """psycopg2 implementation. ``connect`` returns a connection; ``owned`` closes it after each call (the applier),
    otherwise the shared thread connection of the Command Center (db_adapter.ensure_conn) is reused and committed."""

    def __init__(self, connect: Callable[[], Any], *, owned: bool = False) -> None:
        self._connect = connect
        self._owned = owned

    def _tx(self, fn: Callable[[Any], Any]) -> Any:
        import psycopg2.extras

        conn = self._connect()
        if conn is None:
            raise StoreError("STORE_UNAVAILABLE", "no database connection", 503)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                out = fn(cur)
            conn.commit()
            return out
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            if self._owned:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    @staticmethod
    def _j(v: Any) -> Any:
        from psycopg2.extras import Json

        return Json(v, dumps=lambda o: json.dumps(o, default=str))

    def tables_status(self) -> dict:
        try:
            def q(cur):
                cur.execute("SELECT t, to_regclass('public.' || t) IS NOT NULL AS present FROM unnest(%s::text[]) t",
                            (list(TABLES),))
                return [r["t"] for r in cur.fetchall() if not r["present"]]
            missing = self._tx(q)
        except Exception as exc:  # noqa: BLE001 — unreadable is UNAVAILABLE, never OK
            return {"state": "UNAVAILABLE", "missing_tables": [], "reason": type(exc).__name__}
        if missing:
            return {"state": "NOT_MIGRATED", "missing_tables": missing, "reason": "migration not applied"}
        return {"state": "OK", "missing_tables": [], "reason": None}

    # requests
    def create_request(self, row: dict) -> tuple[dict, bool]:
        cols = [c for c in REQUEST_COLUMNS if c in row and row[c] is not None]

        def q(cur):
            vals = [self._j(row[c]) if c in JSON_REQUEST_COLUMNS else row[c] for c in cols]
            cur.execute(f"INSERT INTO ops_applier_requests ({', '.join(cols)}) VALUES "
                        f"({', '.join(['%s'] * len(cols))}) ON CONFLICT (idempotency_key) DO NOTHING RETURNING *", vals)
            r = cur.fetchone()
            if r:
                return dict(r), True
            cur.execute("SELECT * FROM ops_applier_requests WHERE idempotency_key = %s", (row["idempotency_key"],))
            return dict(cur.fetchone()), False
        return self._tx(q)

    def get_request(self, request_id: str) -> Optional[dict]:
        def q(cur):
            cur.execute("SELECT * FROM ops_applier_requests WHERE request_id = %s", (request_id,))
            r = cur.fetchone()
            return dict(r) if r else None
        return self._tx(q)

    def list_requests(self, limit: int = 20) -> list[dict]:
        def q(cur):
            cur.execute("SELECT * FROM ops_applier_requests ORDER BY created_at DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]
        return self._tx(q)

    def list_approved(self, executor: str = "applier", limit: int = 10) -> list[dict]:
        def q(cur):
            cur.execute("SELECT * FROM ops_applier_requests WHERE status = 'APPROVED' AND executor = %s "
                        "ORDER BY approved_at NULLS LAST, created_at LIMIT %s", (executor, limit))
            return [dict(r) for r in cur.fetchall()]
        return self._tx(q)

    def transition(self, request_id: str, from_statuses: Iterable[str], to_status: str, **fields: Any) -> Optional[dict]:
        sets = ["status = %s", "status_at = now()"]
        vals: list[Any] = [to_status]
        for k, v in fields.items():
            if k not in REQUEST_COLUMNS or k in ("request_id", "status", "status_at"):
                raise StoreError("FIELD_INVALID", k, 500)
            sets.append(f"{k} = %s")
            vals.append(self._j(v) if k in JSON_REQUEST_COLUMNS else v)

        def q(cur):
            cur.execute(f"UPDATE ops_applier_requests SET {', '.join(sets)} WHERE request_id = %s AND status = ANY(%s) "
                        "RETURNING *", vals + [request_id, list(from_statuses)])
            r = cur.fetchone()
            return dict(r) if r else None
        return self._tx(q)

    def set_fields(self, request_id: str, **fields: Any) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            if k not in ("undone_by",):
                raise StoreError("FIELD_INVALID", k, 500)
            sets.append(f"{k} = %s")
            vals.append(v)

        def q(cur):
            cur.execute(f"UPDATE ops_applier_requests SET {', '.join(sets)} WHERE request_id = %s", vals + [request_id])
        self._tx(q)

    # audit
    def append_audit(self, *, actor: str, action: str, kind: Optional[str], request_id: Optional[str], outcome: str,
                     detail: Optional[dict] = None) -> int:
        def q(cur):
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('ops_audit'))")
            cur.execute("SELECT row_hash FROM ops_audit ORDER BY seq DESC LIMIT 1")
            r = cur.fetchone()
            prev = r["row_hash"] if r else None
            cur.execute("SELECT now() AS at")
            at = cur.fetchone()["at"].isoformat()
            row = {"at": at, "actor": actor, "action": action, "kind": kind, "request_id": request_id,
                   "outcome": outcome, "detail": dict(detail or {})}
            h = audit_hash(prev, row)
            cur.execute("INSERT INTO ops_audit (at, actor, action, kind, request_id, outcome, detail, prev_hash, "
                        "row_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING seq",
                        (at, actor, action, kind, request_id, outcome, self._j(row["detail"]), prev, h))
            return cur.fetchone()["seq"]
        return self._tx(q)

    def list_audit(self, limit: int = 100) -> list[dict]:
        def q(cur):
            cur.execute("SELECT * FROM ops_audit ORDER BY seq DESC LIMIT %s", (limit,))
            out = []
            for r in cur.fetchall():
                d = dict(r)
                d["at"] = d["at"].isoformat() if hasattr(d["at"], "isoformat") else d["at"]
                out.append(d)
            return out
        return self._tx(q)

    def audit_update(self, seq: int, **fields: Any) -> None:
        def q(cur):
            cur.execute("UPDATE ops_audit SET outcome = %s WHERE seq = %s", (fields.get("outcome", "x"), seq))
        self._tx(q)

    def audit_delete(self, seq: int) -> None:
        def q(cur):
            cur.execute("DELETE FROM ops_audit WHERE seq = %s", (seq,))
        self._tx(q)

    # settings
    def setting_get(self, key: str) -> Optional[dict]:
        def q(cur):
            cur.execute("SELECT * FROM operator_settings WHERE key = %s", (key,))
            r = cur.fetchone()
            return dict(r) if r else None
        return self._tx(q)

    def settings_all(self) -> dict[str, dict]:
        def q(cur):
            cur.execute("SELECT * FROM operator_settings")
            return {r["key"]: dict(r) for r in cur.fetchall()}
        return self._tx(q)

    def settings_history(self, limit: int = 50) -> list[dict]:
        def q(cur):
            cur.execute("SELECT * FROM operator_settings_history ORDER BY seq DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]
        return self._tx(q)

    def setting_apply(self, key: str, value: Any, active: bool, *, actor: str, request_id: str, expect: dict) -> dict:
        def q(cur):
            cur.execute("SELECT * FROM operator_settings WHERE key = %s FOR UPDATE", (key,))
            cur_row = cur.fetchone()
            cur_active = bool(cur_row and cur_row["active"])
            cur_val = cur_row["value"] if cur_active else None
            if cur_active != bool(expect.get("active")) or cur_val != expect.get("value"):
                raise StoreError("STATE_CHANGED", f"{key} changed since the preview", 409)
            new_value = value if active else (cur_row["value"] if cur_row else None)
            cur.execute("INSERT INTO operator_settings_history (key, op, old_value, old_active, new_value, new_active, "
                        "actor, request_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                        (key, "set" if active else "unset", self._j(cur_row["value"]) if cur_row else None,
                         cur_row["active"] if cur_row else None, self._j(new_value), active, actor, request_id))
            h = dict(cur.fetchone())
            cur.execute("INSERT INTO operator_settings (key, value, active, updated_at, updated_by, request_id) "
                        "VALUES (%s, %s, %s, now(), %s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                        "active = EXCLUDED.active, updated_at = now(), updated_by = EXCLUDED.updated_by, "
                        "request_id = EXCLUDED.request_id", (key, self._j(new_value), active, actor, request_id))
            return h
        return self._tx(q)

    # challenges
    def challenge_put(self, *, request_id: str, purpose: str, challenge: str, expires_at: datetime) -> str:
        cid = "ch_" + secrets.token_hex(8)

        def q(cur):
            cur.execute("INSERT INTO ops_webauthn_challenges (challenge_id, request_id, purpose, challenge, expires_at) "
                        "VALUES (%s, %s, %s, %s, %s)", (cid, request_id, purpose, challenge, expires_at))
        self._tx(q)
        return cid

    def challenge_take(self, *, request_id: str, purpose: str, challenge: str) -> dict:
        def q(cur):
            cur.execute("SELECT *, expires_at <= now() AS expired FROM ops_webauthn_challenges WHERE request_id = %s "
                        "AND purpose = %s AND challenge = %s FOR UPDATE", (request_id, purpose, challenge))
            r = cur.fetchone()
            if not r:
                raise StoreError("CHALLENGE_UNKNOWN", "no challenge issued for this request", 403)
            if r["used_at"] is not None:
                raise StoreError("CHALLENGE_REPLAYED", "challenge already used", 403)
            if r["expired"]:
                raise StoreError("CHALLENGE_EXPIRED", "challenge expired", 403)
            cur.execute("UPDATE ops_webauthn_challenges SET used_at = now() WHERE challenge_id = %s",
                        (r["challenge_id"],))
            return dict(r)
        return self._tx(q)

    # credentials
    def credentials_list(self) -> list[dict]:
        def q(cur):
            cur.execute("SELECT * FROM webauthn_credentials ORDER BY created_at")
            return [dict(r) for r in cur.fetchall()]
        return self._tx(q)

    def credential_get(self, credential_id: str) -> Optional[dict]:
        def q(cur):
            cur.execute("SELECT * FROM webauthn_credentials WHERE credential_id = %s", (credential_id,))
            r = cur.fetchone()
            return dict(r) if r else None
        return self._tx(q)

    def credential_add(self, row: dict) -> None:
        def q(cur):
            cur.execute("INSERT INTO webauthn_credentials (credential_id, name, public_key, sign_count, transports, "
                        "aaguid, user_handle, created_by, created_request_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
                        "%s) ON CONFLICT (credential_id) DO NOTHING RETURNING credential_id",
                        (row["credential_id"], row["name"], row["public_key"], row.get("sign_count", 0),
                         self._j(row.get("transports") or []), row.get("aaguid"), row["user_handle"],
                         row["created_by"], row["created_request_id"]))
            if not cur.fetchone():
                raise StoreError("CREDENTIAL_EXISTS", "passkey already registered", 409)
        self._tx(q)

    def credential_touch(self, credential_id: str, *, old_count: int, new_count: int) -> bool:
        def q(cur):
            cur.execute("UPDATE webauthn_credentials SET sign_count = %s, last_used_at = now() WHERE credential_id = %s "
                        "AND revoked_at IS NULL AND sign_count = %s RETURNING credential_id",
                        (new_count, credential_id, old_count))
            return cur.fetchone() is not None
        return self._tx(q)

    def credential_revoke(self, credential_id: str, *, actor: str, request_id: str) -> bool:
        def q(cur):
            cur.execute("UPDATE webauthn_credentials SET revoked_at = now(), revoked_by = %s, revoke_request_id = %s "
                        "WHERE credential_id = %s AND revoked_at IS NULL RETURNING credential_id",
                        (actor, request_id, credential_id))
            return cur.fetchone() is not None
        return self._tx(q)

    # totp
    def totp_get(self) -> Optional[dict]:
        def q(cur):
            cur.execute("SELECT * FROM totp_recovery WHERE revoked_at IS NULL ORDER BY id DESC LIMIT 1")
            r = cur.fetchone()
            return dict(r) if r else None
        return self._tx(q)

    def totp_enroll(self, *, label: str, fingerprint: str, actor: str) -> dict:
        def q(cur):
            cur.execute("UPDATE totp_recovery SET revoked_at = now() WHERE revoked_at IS NULL")
            cur.execute("INSERT INTO totp_recovery (label, secret_fingerprint, enrolled_by) VALUES (%s, %s, %s) "
                        "RETURNING *", (label, fingerprint, actor))
            return dict(cur.fetchone())
        return self._tx(q)

    def totp_mark_step(self, totp_id: int, step: int) -> bool:
        def q(cur):
            cur.execute("UPDATE totp_recovery SET last_used_step = %s, last_used_at = now() WHERE id = %s AND "
                        "revoked_at IS NULL AND (last_used_step IS NULL OR last_used_step < %s) RETURNING id",
                        (step, totp_id, step))
            return cur.fetchone() is not None
        return self._tx(q)
