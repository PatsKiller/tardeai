#!/usr/bin/env python3
"""Exercise the REAL admin_write guard against an isolated cluster. TEST-ONLY.

Run as a child process whose DB_* environment points at a disposable cluster, so
``db_adapter`` binds to that cluster at import and can never reach production.
The guard is not mocked, stubbed or bypassed: ``admin_write_guard.admin_write``
runs its full ACCESS -> CONFIRM -> APPLY -> AUDIT chain, and every audit row lands
in the isolated ``admin_audit_log``.

Two families of scenario, split on purpose:

  guard      direct ``admin_write`` calls whose ``apply_fn`` writes to a temp file,
             so the APPLY and AUDIT steps are genuinely exercised with nothing
             production-owned in reach.
  route      real ``api_v2.handle()`` calls, restricted to paths that terminate
             BEFORE apply — validation errors, access denials and two-step
             previews. A route whose apply_fn edits a production config file is
             never driven to the applied state.

Usage:  python3 -m support.operator_control_probe > results.json
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# scripts/ FIRST: the production tree owns the name ``lib`` (lib.setup_run_contract
# and friends), and api_v2 imports it. tests/ is appended, never prepended, so this
# package can never shadow it.
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.append(str(ROOT / "tests"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id        BIGSERIAL PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    operator  TEXT,
    action    TEXT NOT NULL,
    target    TEXT,
    old_value JSONB,
    new_value JSONB,
    result    TEXT NOT NULL,
    detail    TEXT
);

-- Minimum surface for the topic.* operator controls. Synthetic, deterministic,
-- and containing no real account, position, order, credential or personal data.
CREATE TABLE IF NOT EXISTS topic_monitor (
    topic_id   TEXT PRIMARY KEY,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

SEED = """
INSERT INTO topic_monitor (topic_id, enabled) VALUES ('probe-topic', TRUE)
ON CONFLICT (topic_id) DO NOTHING;
"""


def _identity(db) -> dict[str, Any]:
    row = db._execute(
        "select current_database() as dbname, current_user as usr, inet_server_port() as port,"
        " coalesce(host(inet_server_addr()), 'local') as host",
        None,
        fetch="one",
    )
    dd = db._execute("select setting as data_directory from pg_settings where name='data_directory'", None, fetch="one")
    out = dict(row) if row else {}
    out["data_directory"] = dict(dd).get("data_directory") if dd else None
    return out


def _audit_rows(db) -> list[dict[str, Any]]:
    rows = db._execute(
        "select id, operator, action, target, result, detail from admin_audit_log order by id",
        None,
        fetch="all",
    )
    return [dict(r) for r in (rows or [])]


def _count(db) -> int:
    r = db._execute("select count(*) as n from admin_audit_log", None, fetch="one")
    return int(dict(r)["n"]) if r else -1


#: Distinct from any failure verdict: the cluster could not be reached at all.
EXIT_CLUSTER_UNAVAILABLE = 3


def main() -> int:
    import db_adapter as db

    out: dict[str, Any] = {"schema": "OperatorControlProbe@v1", "scenarios": [], "errors": []}

    # ── the rail runs BEFORE anything is written ────────────────────────────
    from support.isolated_pg import ClusterIdentity, assert_not_production

    ident = _identity(db)
    out["resolved_identity"] = ident

    # An identity we could not READ is a different thing from an identity that looks
    # like production, and the two must not share an exit path. Empty fields mean the
    # cluster never answered -- no server binaries, no socket, no driver -- which is a
    # statement about this host, not about the target's safety. It still never proceeds;
    # it exits distinguishably so a caller can skip rather than report a false alarm
    # about writing to production.
    if not str(ident.get("dbname") or "") or not str(ident.get("usr") or ""):
        print(
            json.dumps(
                {
                    "schema": "OperatorControlProbe@v1",
                    "cluster_unavailable": True,
                    "reason": (
                        "the isolated cluster did not report an identity; it is not reachable from "
                        "this host, so nothing was written and nothing can be concluded"
                    ),
                    "resolved_identity": ident,
                }
            ),
            flush=True,
        )
        return EXIT_CLUSTER_UNAVAILABLE

    rail = assert_not_production(
        ClusterIdentity(
            host=str(ident.get("host") or "127.0.0.1"),
            port=int(ident.get("port") or 0),
            dbname=str(ident.get("dbname") or ""),
            user=str(ident.get("usr") or ""),
            data_directory=ident.get("data_directory"),
        )
    )
    out["rail"] = rail

    db._execute(SCHEMA, None, fetch=None)
    db._execute(SEED, None, fetch=None)
    out["audit_rows_before"] = _count(db)

    import admin_write_guard as g

    tmp = Path(tempfile.mkdtemp(prefix="opctl_apply_"))
    applied_marker = tmp / "applied.txt"

    def record(name: str, expect: str, fn) -> None:
        before = _count(db)
        try:
            code, resp = fn()
            err = None
        except Exception as exc:  # noqa: BLE001
            code, resp, err = None, None, f"{type(exc).__name__}: {exc}"
        after = _count(db)
        rows = _audit_rows(db)
        out["scenarios"].append(
            {
                "scenario": name,
                "expectation": expect,
                "http": code,
                "response": resp,
                "error": err,
                "audit_rows_before": before,
                "audit_rows_after": after,
                "audit_delta": after - before,
                "last_audit_row": rows[-1] if rows else None,
            }
        )

    # ── ACCESS: the token gate, exercised in both postures ──────────────────
    os.environ["ADMIN_WRITE_TOKEN"] = "correct-horse-battery-staple"

    record(
        "denied_wrong_token",
        "403, audit row result=rejected — a refused call still writes an audit row",
        lambda: g.admin_write(
            action="probe.denied",
            target="probe:wrong-token",
            old_value={"v": 0},
            new_value={"v": 1},
            apply_fn=lambda: applied_marker.write_text("SHOULD NOT HAPPEN"),
            operator="probe",
            confirmed=True,
            token="wrong-token",
        ),
    )
    record(
        "denied_missing_token",
        "403 + audit row: a missing credential is not a valid one",
        lambda: g.admin_write(
            action="probe.denied",
            target="probe:missing-token",
            old_value=None,
            new_value=None,
            apply_fn=lambda: applied_marker.write_text("SHOULD NOT HAPPEN"),
            operator="probe",
            confirmed=True,
            token=None,
        ),
    )
    record(
        "denied_empty_token",
        "403 + audit row: an empty string is not a credential",
        lambda: g.admin_write(
            action="probe.denied",
            target="probe:empty-token",
            old_value=None,
            new_value=None,
            apply_fn=lambda: applied_marker.write_text("SHOULD NOT HAPPEN"),
            operator="probe",
            confirmed=True,
            token="",
        ),
    )
    record(
        "denied_wrong_scope_token",
        "403 + audit row: a well-formed token for another scope is still wrong",
        lambda: g.admin_write(
            action="probe.denied",
            target="probe:wrong-scope",
            old_value=None,
            new_value=None,
            apply_fn=lambda: applied_marker.write_text("SHOULD NOT HAPPEN"),
            operator="probe",
            confirmed=True,
            token="correct-horse-battery-staple-OTHER-SCOPE",
        ),
    )

    # ── CONFIRM: the two-step. A preview must never mutate or audit ─────────
    record(
        "preview_does_not_apply_or_audit",
        "200 needs_confirm, audit_delta 0, apply_fn never called",
        lambda: g.admin_write(
            action="probe.preview",
            target="probe:preview",
            old_value={"v": 0},
            new_value={"v": 1},
            apply_fn=lambda: applied_marker.write_text("SHOULD NOT HAPPEN"),
            operator="probe",
            confirmed=False,
            token="correct-horse-battery-staple",
        ),
    )

    # ── APPLY + AUDIT: the allowed path, against a temp file ────────────────
    def _apply_ok() -> None:
        applied_marker.write_text("applied")

    record(
        "allowed_applies_and_audits",
        "200 applied, audit row result=applied",
        lambda: g.admin_write(
            action="probe.allowed",
            target="probe:apply",
            old_value={"v": 0},
            new_value={"v": 1},
            apply_fn=_apply_ok,
            operator="probe",
            confirmed=True,
            token="correct-horse-battery-staple",
        ),
    )
    out["apply_marker_written"] = applied_marker.is_file() and applied_marker.read_text() == "applied"

    # ── replay: the same confirmed call twice ───────────────────────────────
    record(
        "replay_second_identical_call",
        "append-only: a replay produces a SECOND audit row; the guard has no idempotency key",
        lambda: g.admin_write(
            action="probe.allowed",
            target="probe:apply",
            old_value={"v": 1},
            new_value={"v": 1},
            apply_fn=_apply_ok,
            operator="probe",
            confirmed=True,
            token="correct-horse-battery-staple",
        ),
    )

    # ── conflict: a stale old_value is NOT detected ─────────────────────────
    # There is no optimistic-concurrency check in the guard. Two writers holding
    # different beliefs about the current value both succeed, and the audit log
    # records both as "applied". Proving the absence is the point: a surface must
    # not imply a 409 that no code path can produce.
    record(
        "conflict_stale_old_value_not_detected",
        "no 409 exists: a second writer with a stale old_value still applies",
        lambda: g.admin_write(
            action="probe.allowed",
            target="probe:apply",
            old_value={"v": 999},
            new_value={"v": 4},
            apply_fn=_apply_ok,
            operator="probe-other",
            confirmed=True,
            token="correct-horse-battery-staple",
        ),
    )

    # ── failure: apply raises. Result must be recorded, not swallowed ───────
    def _apply_boom() -> None:
        raise RuntimeError("synthetic apply failure")

    record(
        "apply_failure_is_audited",
        "500 result=failed with an audit row — a failed write is still a recorded event",
        lambda: g.admin_write(
            action="probe.failure",
            target="probe:boom",
            old_value={"v": 1},
            new_value={"v": 2},
            apply_fn=_apply_boom,
            operator="probe",
            confirmed=True,
            token="correct-horse-battery-staple",
        ),
    )

    # ── declared vs effective: the open door ────────────────────────────────
    os.environ.pop("ADMIN_WRITE_TOKEN", None)
    record(
        "open_door_when_token_unset",
        "access_ok() returns True with ADMIN_WRITE_TOKEN unset: any token applies",
        lambda: g.admin_write(
            action="probe.opendoor",
            target="probe:open",
            old_value={"v": 2},
            new_value={"v": 3},
            apply_fn=_apply_ok,
            operator="probe",
            confirmed=True,
            token="literally-anything",
        ),
    )
    out["access_ok_matrix"] = {
        "token_unset_any_token": g.access_ok("anything"),
        "token_unset_none": g.access_ok(None),
    }
    os.environ["ADMIN_WRITE_TOKEN"] = "correct-horse-battery-staple"
    out["access_ok_matrix"].update(
        {
            "token_set_correct": g.access_ok("correct-horse-battery-staple"),
            "token_set_wrong": g.access_ok("nope"),
            "token_set_none": g.access_ok(None),
            "token_set_empty": g.access_ok(""),
        }
    )

    # ── the cron allowlist: a trading job may never be retried ──────────────
    out["cron_allowlist"] = {
        "non_trading_allowed": g.cron_retry_allowed("finviz_enrichment"),
        "unknown_job_refused": g.cron_retry_allowed("totally_unknown_job"),
        "trading_job_refused": g.cron_retry_allowed("place_broker_orders"),
        "approval_job_refused": g.cron_retry_allowed("trade_approvals"),
    }

    # ── real routes, stopped before apply ───────────────────────────────────
    try:
        import api_v2

        def route(name: str, expect: str, path: str, method: str, body: dict | None) -> None:
            before = _count(db)
            returned_none = False
            try:
                result = api_v2.handle(path, method=method, body=body)
                if result is None:
                    # handle() signals "not my route" with None; portfolio_server
                    # checks `is not None` and falls through, so the transport
                    # answer is 404. Recorded as its own outcome rather than being
                    # flattened into an exception.
                    returned_none, code, resp, err = True, None, None, None
                else:
                    code, resp = result
                    err = None
            except Exception as exc:  # noqa: BLE001
                code, resp, err = None, None, f"{type(exc).__name__}: {exc}"
            after = _count(db)
            out["scenarios"].append(
                {
                    "scenario": name,
                    "expectation": expect,
                    "route": path,
                    "method": method,
                    "request_body_keys": sorted((body or {}).keys()),
                    "http": code,
                    "response": (resp if isinstance(resp, dict) else str(resp)) if resp is not None else None,
                    "error": err,
                    "handle_returned_none": returned_none,
                    # handle() returning None means "not my route"; the server
                    # falls through and the transport answer is 404 — including
                    # for a wrong METHOD, so this dispatcher never emits 405.
                    "http_effective": 404 if returned_none else code,
                    "audit_rows_before": before,
                    "audit_rows_after": after,
                    "audit_delta": after - before,
                }
            )

        route(
            "route_unknown_path_404",
            "an unrouted path is 404, not a silent 200",
            "/api/v2/admin/this-route-does-not-exist",
            "POST",
            {"confirm": False},
        )
        route(
            "route_wrong_method_get_on_post_only",
            "a GET on a POST-only admin path must not apply",
            "/api/v2/admin/risk-config",
            "GET",
            None,
        )
        route(
            "route_validation_bad_field_400",
            "an uneditable field is refused with 400 before the guard",
            "/api/v2/admin/risk-config",
            "POST",
            {"field": "not_a_real_field", "value": 1, "confirm": True, "token": "correct-horse-battery-staple"},
        )
        route(
            "route_validation_missing_id_400",
            "a missing topic_id is refused with 400 before the guard is reached",
            "/api/v2/admin/topic/toggle",
            "POST",
            {"enabled": False, "confirm": True, "token": "correct-horse-battery-staple"},
        )
        route(
            "route_unknown_target_404",
            "a well-formed request for a row that does not exist is 404, not a silent success",
            "/api/v2/admin/topic/toggle",
            "POST",
            {"topic_id": "no-such-topic", "enabled": False, "confirm": True, "token": "correct-horse-battery-staple"},
        )
        route(
            "route_denied_wrong_token_403",
            "a wrong token on a real route is 403 and still writes an audit row",
            "/api/v2/admin/topic/toggle",
            "POST",
            {"topic_id": "probe-topic", "enabled": False, "confirm": True, "token": "wrong-token"},
        )
        route(
            "route_preview_no_apply",
            "confirm=false previews the diff, applies nothing and audits nothing",
            "/api/v2/admin/topic/toggle",
            "POST",
            {"topic_id": "probe-topic", "enabled": False, "confirm": False, "token": "correct-horse-battery-staple"},
        )
        route(
            "route_applied_end_to_end",
            "a fully authorized confirmed call applies to the isolated row and audits",
            "/api/v2/admin/topic/toggle",
            "POST",
            {"topic_id": "probe-topic", "enabled": False, "confirm": True, "token": "correct-horse-battery-staple"},
        )
    except Exception:  # noqa: BLE001
        out["errors"].append("api_v2 route probe failed:\n" + traceback.format_exc()[-1200:])

    # the applied route must actually have changed the isolated row
    trow = db._execute("select topic_id, enabled from topic_monitor where topic_id='probe-topic'", None, fetch="one")
    out["topic_row_after"] = dict(trow) if trow else None

    out["audit_rows_after"] = _count(db)
    out["audit_rows"] = _audit_rows(db)
    out["final_identity"] = _identity(db)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
