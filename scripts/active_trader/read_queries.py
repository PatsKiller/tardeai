"""Active Trader Stage 4 — transport-independent read/query layer.

Parameterized SQL only; strict sort/filter allowlists; cursor pagination with
deterministic ordering; bounded page size; lab-DSN guard (production refused);
typed row mapping with source/freshness projection. No write statement exists
in this module, and the runtime identity (trade_ai_lab_ro) refuses writes at
the session level (default_transaction_read_only=on, statement_timeout=5s).
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from active_trader.migrate import _resolve_dsn, MigrationError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_DATE_RANGE_DAYS = 92

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class QueryError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def normalize_symbol(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not s or len(s) > 10 or any(ord(c) < 32 or c in "/\\%" for c in raw or ""):
        raise QueryError(400, "INVALID_SYMBOL", "symbol failed conservative validation")
    if not SYMBOL_RE.match(s):
        raise QueryError(400, "INVALID_SYMBOL", "unsupported symbol format")
    return s


def parse_limit(raw: Optional[str]) -> int:
    if raw is None:
        return DEFAULT_LIMIT
    try:
        n = int(raw)
    except ValueError:
        raise QueryError(422, "INVALID_LIMIT", "limit must be an integer")
    if n < 1 or n > MAX_LIMIT:
        raise QueryError(422, "INVALID_LIMIT", f"limit must be 1..{MAX_LIMIT}")
    return n


def parse_cursor(raw: Optional[str]) -> int:
    if not raw:
        return 0
    try:
        text = base64.urlsafe_b64decode(raw.encode()).decode()
        if not text.startswith("o:"):
            raise ValueError
        n = int(text[2:])
        if n < 0:
            raise ValueError
        return n
    except Exception:
        raise QueryError(422, "INVALID_CURSOR", "cursor is not a valid opaque token")


def make_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def parse_date(raw: Optional[str], name: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise QueryError(422, "INVALID_DATE", f"{name} is not ISO-8601")


def check_range(frm: Optional[datetime], to: Optional[datetime]):
    if frm and to:
        if to < frm:
            raise QueryError(422, "INVALID_DATE", "to precedes from")
        if (to - frm).days > MAX_DATE_RANGE_DAYS:
            raise QueryError(422, "EXCESSIVE_RANGE", f"date range exceeds {MAX_DATE_RANGE_DAYS} days")


def mask_row_id(v: Any) -> str:
    s = str(v or "")
    return f"***{s[-4:]}" if len(s) > 4 and any(c.isdigit() for c in s) else (s or "***")


class ReadStore:
    """Guarded lab-only read store. One psycopg2 connection, read-only role."""

    def __init__(self, dsn: str):
        if not dsn:
            raise MigrationError("read store requires an explicit DSN (no env fallback)")
        checked = _resolve_dsn(dsn)
        if "trade_ai_test" not in checked:
            raise MigrationError("read store accepts only the trade_ai_test lab database")
        import psycopg2
        self._conn = psycopg2.connect(checked)
        self._conn.autocommit = True   # read-only role enforces no writes

    def close(self):
        self._conn.close()

    def _rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    # ---- health/version -------------------------------------------------
    def health(self) -> dict:
        (db, usr, ro) = self._rows(
            "SELECT current_database(), current_user, current_setting('default_transaction_read_only')")[0]
        mig = self._rows("SELECT max(version) FROM active_trader_schema_migrations")[0][0]
        return {"database": db, "db_identity": usr, "read_only_session": ro == "on",
                "schema_migration_version": mig, "production_access": "DISABLED"}

    def migration_versions(self) -> list[int]:
        return [r[0] for r in self._rows(
            "SELECT version FROM active_trader_schema_migrations ORDER BY version")]

    # ---- session --------------------------------------------------------
    def session(self) -> Optional[dict]:
        rows = self._rows(
            """SELECT a.session_authorization_id, a.environment, a.status, a.draft_version,
                      left(a.authorization_hash, 12), a.session_start, a.session_entry_cutoff,
                      a.session_expiry, d.session_name, d.risk_limits, d.time_bounds,
                      d.feature_policy_versions
               FROM active_trader_session_authorizations a
               JOIN active_trader_session_drafts d
                 ON d.draft_id = a.draft_id AND d.draft_version = a.draft_version
               ORDER BY a.created_at DESC LIMIT 1""")
        if not rows:
            return None
        r = rows[0]
        accounts = [f"{b}/{l}" for b, l in self._rows(
            """SELECT broker, account_label FROM active_trader_session_accounts
               WHERE session_authorization_id = %s AND role <> 'DISABLED'
               ORDER BY broker, account_label""", (r[0],))]
        return {"session_authorization_id": r[0], "environment": r[1], "session_state": r[2],
                "draft_version": r[3], "authorization_short_hash": r[4],
                "session_start": r[5], "entry_cutoff": r[6], "expiry": r[7],
                "session_name": r[8], "risk_limits": r[9], "time_bounds": r[10],
                "feature_policy_versions": r[11], "selected_accounts": accounts,
                "authorization_state": r[2]}

    # ---- capabilities ---------------------------------------------------
    CAP_FILTERS = {"broker": "broker", "account": "account_label",
                   "capability": "capability", "state": "state"}

    def capabilities(self, filters: dict, limit: int, offset: int, now: datetime) -> list[dict]:
        where, params = [], []
        for k, col in self.CAP_FILTERS.items():
            if filters.get(k):
                where.append(f"{col} = %s")
                params.append(filters[k])
        sql = ("SELECT broker, account_label, environment, capability, state, source, "
               "verified_at, expires_at, adapter_version, evidence_ref, notes "
               "FROM broker_account_capabilities "
               + ("WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY broker, account_label, capability LIMIT %s OFFSET %s")
        params += [limit + 1, offset]
        out = []
        for r in self._rows(sql, tuple(params)):
            state = r[4]
            expired = r[7] is not None and now >= r[7]
            out.append({"broker": r[0], "account_label": r[1], "masked_account_id": "***",
                        "environment": r[2], "capability": r[3],
                        "recorded_state": state,
                        "effective_state": "UNKNOWN" if (expired and state == "SUPPORTED") else state,
                        "expired": expired, "source": r[5],
                        "verified_at": r[6], "expires_at": r[7],
                        "adapter_version": r[8], "evidence_ref": r[9], "notes": r[10]})
        return out

    # ---- rejections -----------------------------------------------------
    REJ_FILTERS = {"broker": "broker", "account": "account_label", "symbol": "symbol",
                   "normalized_code": "normalized_code"}

    def rejections(self, filters: dict, frm, to, limit: int, offset: int) -> list[dict]:
        where, params = [], []
        for k, col in self.REJ_FILTERS.items():
            if filters.get(k):
                where.append(f"{col} = %s")
                params.append(filters[k])
        for k in ("requires_operator", "requires_broker_call"):
            if filters.get(k) in ("true", "false"):
                where.append(f"{k} = %s")
                params.append(filters[k] == "true")
        if frm:
            where.append("first_seen_at >= %s"); params.append(frm)
        if to:
            where.append("first_seen_at <= %s"); params.append(to)
        sql = ("SELECT rejection_event_id, environment, broker, account_label, symbol, "
               "raw_status, raw_code, raw_message, normalized_code, retryable, "
               "requires_operator, requires_broker_call, affected_capability, occurrence_count, "
               "first_seen_at, last_seen_at, classifier_version, matched_rule_id, confidence, "
               "notification_state, fallback_state FROM broker_rejection_events "
               + ("WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY first_seen_at DESC, rejection_event_id LIMIT %s OFFSET %s")
        params += [limit + 1, offset]
        cols = ("rejection_event_id environment broker account_label symbol raw_status raw_code "
                "raw_message_redacted normalized_code retryable requires_operator "
                "requires_broker_call affected_capability occurrence_count first_seen_at "
                "last_seen_at classifier_version matched_rule_id confidence "
                "notification_state fallback_state").split()
        return [dict(zip(cols, r)) for r in self._rows(sql, tuple(params))]

    # ---- notifications --------------------------------------------------
    def notifications(self, filters: dict, frm, to, limit: int, offset: int) -> list[dict]:
        where, params = [], []
        if filters.get("status"):
            where.append("status = %s"); params.append(filters["status"])
        if filters.get("severity"):
            where.append("severity = %s"); params.append(filters["severity"])
        if frm:
            where.append("created_at >= %s"); params.append(frm)
        if to:
            where.append("created_at <= %s"); params.append(to)
        sql = ("SELECT notification_event_id, environment, severity, category, title, body, "
               "requires_operator_action, channels, dedupe_key, status, created_at, "
               "acknowledged_at, expires_at FROM active_trader_notification_events "
               + ("WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY created_at DESC, notification_event_id LIMIT %s OFFSET %s")
        params += [limit + 1, offset]
        cols = ("notification_event_id environment severity category title body "
                "requires_operator_action channels dedupe_key status created_at "
                "acknowledged_at expires_at").split()
        return [dict(zip(cols, r)) for r in self._rows(sql, tuple(params))]

    # ---- orders / positions / journal ----------------------------------
    def orders(self, filters: dict, limit: int, offset: int) -> list[dict]:
        where, params = ["environment <> 'LIVE'"], []
        for k, col in (("account", "account_label"), ("broker", "broker"),
                       ("symbol", "symbol"), ("state", "status"), ("environment", "environment")):
            if filters.get(k):
                where.append(f"{col} = %s"); params.append(filters[k])
        sql = ("SELECT order_intent_id, environment, broker, account_label, symbol, side, "
               "quantity, order_type, limit_price, stop_price, time_in_force, trading_session, "
               "status, created_at FROM active_trader_order_intents WHERE "
               + " AND ".join(where) + " ORDER BY created_at DESC, order_intent_id LIMIT %s OFFSET %s")
        params += [limit + 1, offset]
        cols = ("order_intent_id environment broker account_label symbol side quantity "
                "order_type limit_price stop_price time_in_force trading_session status "
                "created_at").split()
        return [dict(zip(cols, r)) | {"masked_account_id": "***"} for r in self._rows(sql, tuple(params))]

    def positions(self, limit: int, offset: int) -> list[dict]:
        sql = ("SELECT position_state_id, environment, broker, account_label, symbol, state, "
               "quantity, avg_entry, protection_state, resilience_score, resistance_score, "
               "as_of FROM active_trader_position_states WHERE environment <> 'LIVE' "
               "ORDER BY as_of DESC, position_state_id LIMIT %s OFFSET %s")
        cols = ("position_state_id environment broker account_label symbol state shares "
                "average_entry protection_state res rrs as_of").split()
        return [dict(zip(cols, r)) | {"masked_account_id": "***"} for r in
                self._rows(sql, (limit + 1, offset))]

    def journal(self, filters: dict, frm, to, limit: int, offset: int) -> list[dict]:
        where, params = [], []
        for k, col in (("session", "session_authorization_id"), ("symbol", "symbol"),
                       ("event_type", "event_type")):
            if filters.get(k):
                where.append(f"{col} = %s"); params.append(filters[k])
        if frm:
            where.append("occurred_at >= %s"); params.append(frm)
        if to:
            where.append("occurred_at <= %s"); params.append(to)
        sql = ("SELECT journal_event_id, environment, event_type, session_authorization_id, "
               "order_intent_id, symbol, feature_snapshot_ref, replay_segment_ref, "
               "policy_version, occurred_at FROM active_trader_journal_events "
               + ("WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY occurred_at DESC, journal_event_id LIMIT %s OFFSET %s")
        params += [limit + 1, offset]
        cols = ("journal_event_id environment event_type session_authorization_id "
                "order_intent_id symbol feature_snapshot_ref replay_segment_ref "
                "policy_version occurred_at").split()
        return [dict(zip(cols, r)) for r in self._rows(sql, tuple(params))]

    # ---- features / parity ----------------------------------------------
    def feature_rows(self) -> list[dict]:
        sql = ("SELECT DISTINCT ON (flag_name, scope_key) flag_name, scope_key, version, mode, "
               "expires_at, reason, changed_by FROM active_trader_feature_flags "
               "ORDER BY flag_name, scope_key, version DESC")
        cols = "flag_name scope_key version mode expires_at reason changed_by".split()
        return [dict(zip(cols, r)) for r in self._rows(sql)]

    def parity_checks(self, limit: int) -> list[dict]:
        sql = ("SELECT parity_check_id, check_kind, matched, detail, checked_at "
               "FROM active_trader_parity_checks ORDER BY checked_at DESC LIMIT %s")
        cols = "parity_check_id check_kind matched detail checked_at".split()
        return [dict(zip(cols, r)) for r in self._rows(sql, (limit,))]


# -------------------------------------------------------------- snapshots

def load_snapshot(path: Path, now: datetime, max_fresh_hours: int = 48) -> tuple[dict, dict]:
    """Load the Stage 2 discovery snapshot (committed evidence). Returns (data, source_meta)."""
    if not path.exists():
        return {}, {"source_name": str(path.name), "source_type": "SNAPSHOT",
                    "observed_at": None, "expires_at": None,
                    "freshness_state": "UNAVAILABLE", "evidence_ref": None}
    data = json.loads(path.read_text())
    observed = data.get("generated_at")
    fresh = "FRESH"
    try:
        ts = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        age = now - ts
        fresh = "FRESH" if age < timedelta(hours=max_fresh_hours) else (
            "AGING" if age < timedelta(hours=max_fresh_hours * 4) else "STALE")
    except Exception:
        fresh = "UNVERIFIED"
    return data, {"source_name": path.name, "source_type": "SNAPSHOT", "observed_at": observed,
                  "expires_at": None, "freshness_state": fresh,
                  "evidence_ref": data.get("source_sha")}
