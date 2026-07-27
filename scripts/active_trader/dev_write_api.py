"""Active Trader Stage 7 — isolated dev/test write plane.

Namespace `/api/v3/active-trader/dev`. Separate app factory from the Stage 4 read API.
Loopback only, DEFAULT DISABLED, SHADOW/SIMULATION only, trade_ai_test only, test
identity only, strict route allowlist, optimistic versioning, audit journal. No broker
call, no real 2FA, no production mount. It writes session drafts / feature-flag rows /
audit journal events to the lab DB via a WRITE lab identity (fixture-loader identity),
distinct from the read API's read-only identity.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from active_trader.migrate import _resolve_dsn, MigrationError
from active_trader.contracts import ContractViolation, Environment, FlagMode
from active_trader.session_builder import (
    SessionDraftV2, AccountSelection, AccountRole, validate_feature_change,
)

DEV_PREFIX = "/api/v3/active-trader/dev"
ALLOWED_ENVS = ("SHADOW", "SIMULATION")


class DevApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class DevWriteApp:
    """Factory-built dev write plane. LIVE is unrepresentable."""

    def __init__(self, dsn: str, environment: str = "SHADOW", identities=("dev-operator",)):
        if environment not in ALLOWED_ENVS:
            raise DevApiError(403, "ENV_FORBIDDEN", "dev write plane is SHADOW/SIMULATION only")
        if not dsn:
            raise MigrationError("dev write plane requires an explicit lab DSN (no fallback)")
        self.env = environment
        self.identities = set(identities)
        self._dsn = _resolve_dsn(dsn)
        if "trade_ai_test" not in self._dsn:
            raise MigrationError("dev write plane accepts only trade_ai_test")

    def _conn(self):
        import psycopg2
        c = psycopg2.connect(self._dsn)
        c.autocommit = False
        return c

    def _audit(self, cur, action, reason, identity, ref):
        cur.execute(
            """INSERT INTO active_trader_journal_events
                   (environment, event_type, symbol, payload, occurred_at)
               VALUES (%s,%s,NULL,%s, now())""",
            (self.env, f"dev_write:{action}",
             json.dumps({"reason": reason, "by": identity, "ref": str(ref)})))

    def request(self, method, path, body: Optional[dict] = None, headers: Optional[dict] = None):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        rid = str(uuid.uuid4())
        try:
            if not path.startswith(DEV_PREFIX):
                raise DevApiError(404, "NOT_FOUND", "unknown route")
            identity = headers.get("x-at-test-identity", "")
            if identity not in self.identities:
                raise DevApiError(401, "UNAUTHENTICATED", "test identity required (factory-injected)")
            sub = path[len(DEV_PREFIX):].strip("/")
            reason = (body or {}).get("audit_reason")
            if method.upper() in ("POST", "PUT", "PATCH") and not reason:
                raise DevApiError(400, "AUDIT_REQUIRED", "mutating dev requests need an audit_reason")
            data = self._dispatch(method.upper(), sub, body or {}, identity)
            return 200, {"x-request-id": rid}, {"api_version": "v3", "service": "active-trader-dev-write",
                                                 "environment": self.env, "request_id": rid, "data": data}
        except (DevApiError, ContractViolation, MigrationError) as e:
            status = getattr(e, "status", 422)
            code = getattr(e, "code", "CONTRACT")
            return status, {"x-request-id": rid}, {"api_version": "v3",
                "service": "active-trader-dev-write", "request_id": rid,
                "error": {"code": code, "message": str(e)}}
        except Exception:
            return 500, {"x-request-id": rid}, {"api_version": "v3", "request_id": rid,
                "error": {"code": "INTERNAL", "message": "internal error"}}

    def _dispatch(self, method, sub, body, identity):
        parts = sub.split("/") if sub else []
        route = parts[0] if parts else ""
        if route == "session" and method == "POST" and parts[1:] == ["draft"]:
            return self._save_draft(body, identity)
        if route == "session" and method == "GET" and len(parts) == 2:
            return self._load_draft(parts[1])
        if route == "session" and method == "POST" and parts[1:2] == ["clone"]:
            return self._clone_draft(body, identity)
        if route == "features" and method == "POST":
            return self._set_feature(body, identity)
        raise DevApiError(404, "NOT_FOUND", "unknown dev route")

    def _draft_from_body(self, b, identity: str) -> SessionDraftV2:
        accs = [AccountSelection(**a) if isinstance(a, dict) else a for a in b.get("account_roles", [])]
        return SessionDraftV2(
            draft_id=b["draft_id"], draft_version=b.get("draft_version", 1),
            environment=Environment.parse(b.get("environment", self.env)),
            session_name=b.get("session_name", ""), start=b.get("start", ""),
            end=b.get("end", ""), entry_cutoff=b.get("entry_cutoff", ""),
            symbol_policy=b.get("symbol_policy", {}), account_roles=accs,
            quantity_policy=b.get("quantity_policy", {}),
            gross_notional_cap=b.get("gross_notional_cap", 0),
            per_symbol_caps=b.get("per_symbol_caps", {}), per_account_caps=b.get("per_account_caps", {}),
            risk_cap=b.get("risk_cap", 0), trade_count_cap=b.get("trade_count_cap", 0),
            daily_loss_cap=b.get("daily_loss_cap", 0), fallback_policy=b.get("fallback_policy", {}),
            quick_add_config=b.get("quick_add_config", {}), runner_policy=b.get("runner_policy", {}),
            feature_policy_versions=b.get("feature_policy_versions", {}),
            created_by=identity, notes=b.get("notes", ""))

    def _save_draft(self, body, identity):
        draft = self._draft_from_body(body, identity)
        expected = body.get("expected_prev_version")
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT max(draft_version) FROM active_trader_session_drafts
                           WHERE draft_id = %s""", (draft.draft_id,))
            cur_max = cur.fetchone()[0]
            if cur_max is not None and expected is not None and expected != cur_max:
                raise DevApiError(409, "OPTIMISTIC_CONFLICT",
                                  f"expected prev version {expected}, current {cur_max}")
            version = (cur_max or 0) + 1
            # The Stage 1 draft_hash column is globally UNIQUE, so store a per-version
            # ROW address (draft_id|version|authority_hash); the canonical AUTHORITY hash
            # (draft.hash) is returned for later authorization binding.
            import hashlib as _hl
            row_hash = _hl.sha256(f"{draft.draft_id}|{version}|{draft.hash}".encode()).hexdigest()
            cur.execute(
                """INSERT INTO active_trader_session_drafts
                       (draft_id, draft_version, environment, session_name, broker_set,
                        account_policy, symbol_policy, risk_limits, time_bounds, runner_policy,
                        feature_policy_versions, draft_hash, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (draft.draft_id, version, draft.environment.value, draft.session_name,
                 json.dumps(sorted({a.broker if isinstance(a, AccountSelection) else a["broker"]
                                    for a in draft.account_roles})),
                 json.dumps(body.get("account_roles", [])), json.dumps(draft.symbol_policy),
                 json.dumps({"gross_notional_cap": draft.gross_notional_cap,
                             "risk_cap": draft.risk_cap, "daily_loss_cap": draft.daily_loss_cap,
                             "trade_count_cap": draft.trade_count_cap}),
                 json.dumps({"start": draft.start, "end": draft.end, "entry_cutoff": draft.entry_cutoff}),
                 json.dumps(draft.runner_policy), json.dumps(draft.feature_policy_versions),
                 row_hash, identity))
            self._audit(cur, "save_draft", body.get("audit_reason"), identity, draft.draft_id)
            conn.commit()
            return {"draft_id": draft.draft_id, "draft_version": version, "authority_hash": draft.hash, "row_hash": row_hash}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _load_draft(self, draft_id):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT draft_id, draft_version, environment, session_name, draft_hash
                           FROM active_trader_session_drafts WHERE draft_id = %s
                           ORDER BY draft_version DESC""", (draft_id,))
            rows = cur.fetchall()
            if not rows:
                raise DevApiError(404, "NOT_FOUND", "no such draft")
            return {"draft_id": draft_id, "versions": [
                {"draft_version": r[1], "environment": r[2], "session_name": r[3],
                 "draft_hash": r[4], "immutable": True} for r in rows]}
        finally:
            conn.close()

    def _clone_draft(self, body, identity):
        src = self._load_draft(body["draft_id"])
        new_id = body.get("new_draft_id") or f"clone-{uuid.uuid4().hex[:8]}"
        return {"cloned_from": body["draft_id"], "new_draft_id": new_id,
                "source_versions": len(src["versions"]),
                "note": "clone starts at version 1; call session/draft to persist"}

    def _set_feature(self, body, identity):
        flag = body["flag_name"]
        mode = FlagMode(body["mode"])
        validate_feature_change(flag, mode)      # rejects LIVE_CANARY etc.
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT coalesce(max(version),0) FROM active_trader_feature_flags
                           WHERE flag_name=%s AND scope_key=%s""",
                        (flag, body.get("scope_key", "test")))
            version = cur.fetchone()[0] + 1
            cur.execute(
                """INSERT INTO active_trader_feature_flags
                       (flag_name, scope_key, version, mode, reason, changed_by)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (flag, body.get("scope_key", "test"), version, mode.value,
                 body.get("audit_reason"), identity))
            self._audit(cur, "set_feature", body.get("audit_reason"), identity, f"{flag}:{mode.value}")
            conn.commit()
            return {"flag_name": flag, "scope_key": body.get("scope_key", "test"),
                    "version": version, "mode": mode.value, "authorizes_trading": False}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def main(argv=None) -> int:
    import argparse, os, sys
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    if os.environ.get("ACTIVE_TRADER_DEV_WRITE_ENABLED", "").lower() != "true":
        print("dev write plane disabled (set ACTIVE_TRADER_DEV_WRITE_ENABLED=true) — exiting")
        return 0
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("ERROR: non-loopback refused", file=sys.stderr); return 2
    print("dev write plane is app-factory + test-harness only in Stage 7 (no standalone listener)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
