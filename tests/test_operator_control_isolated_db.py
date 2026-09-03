#!/usr/bin/env python3
"""Operator controls, proven against a disposable PostgreSQL cluster.

The previous tranche reported this as a non-bypassable blocker: every guarded
operator write goes through ``admin_write_guard.admin_write()``, whose AUDIT step
appends to the append-only ``admin_audit_log`` on EVERY outcome including a
rejection — so observing authorization, validation, conflict or replay behaviour
appeared to require a production write.

It did not. It required a database that is not production. This suite stands one
up per run: its own ``initdb`` data directory in a temp path, loopback-only on a
dynamically allocated port, test-only role and database, destroyed afterwards.
The guard is exercised for real — not mocked, not stubbed, not bypassed.

Nothing here touches the production cluster. The hard rail in
``tests/lib/isolated_pg.assert_not_production`` runs inside the probe process
before a single row is written, and it is itself covered by positive and negative
controls below.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Appended, not prepended: tests/conftest.py puts scripts/ on sys.path so the suite
# can import the production ``lib`` package, and prepending tests/ would shadow it.
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from support.isolated_pg import (  # noqa: E402
    ClusterIdentity,
    IsolatedPostgres,
    ProductionIdentityError,
    assert_not_production,
)

try:
    from support.isolated_pg import pg_bin_dir

    pg_bin_dir()
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False

needs_pg = pytest.mark.skipif(not HAVE_PG, reason="no PostgreSQL server binaries on this host")


# ── the rail, with controls in both directions ───────────────────────────────
# A guard that cannot fail proves nothing, so the production shapes are asserted
# to raise and the isolated shape is asserted to pass.


def _isolated_identity(**over) -> ClusterIdentity:
    base = dict(
        host="127.0.0.1",
        port=45999,
        dbname="tradeai_test_abc123",
        user="tradeai_test_def456",
        data_directory="/tmp/tradeai_testpg_xyz/data",
    )
    base.update(over)
    return ClusterIdentity(**base)


def test_rail_positive_control_accepts_an_isolated_target():
    verdict = assert_not_production(_isolated_identity())
    assert verdict["verdict"] == "ISOLATED"
    assert all(verdict["checks"].values())


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("port", 5432, "the production port"),
        ("dbname", "trade_ai", "the production database name"),
        ("user", "trade_ai", "the production role"),
        ("host", "10.0.0.5", "a non-loopback host"),
        ("data_directory", "/var/lib/postgresql/17/main", "the production data directory"),
        ("dbname", "scratch", "a database that does not announce itself as test-only"),
        ("user", "scratch_user", "a role that does not announce itself as test-only"),
    ],
)
def test_rail_negative_controls_reject_production_shapes(field, value, reason):
    with pytest.raises(ProductionIdentityError) as exc:
        assert_not_production(_isolated_identity(**{field: value}))
    assert "refusing to write" in str(exc.value), reason


def test_rail_rejects_the_real_production_dsn():
    """The exact target this campaign must never write to."""
    with pytest.raises(ProductionIdentityError):
        assert_not_production(ClusterIdentity(host="127.0.0.1", port=5432, dbname="trade_ai", user="trade_ai"))


# ── the isolated cluster itself ──────────────────────────────────────────────


@needs_pg
def test_cluster_is_isolated_and_destroys_itself():
    pg = IsolatedPostgres()
    data_dir = None
    try:
        pg.start()
        data_dir = Path(str(pg.data_dir))
        assert pg.verify_isolated()["verdict"] == "ISOLATED"
        assert pg.port != 5432
        assert pg.host == "127.0.0.1"
        assert pg.dbname.startswith("tradeai_test_")
        assert pg.user.startswith("tradeai_test_")
        assert data_dir.exists()
        r = pg.psql("select 1 as ok;")
        assert r.returncode == 0, r.stderr
    finally:
        proof = pg.stop()
    assert proof["data_directory_removed"] is True
    assert proof["base_directory_removed"] is True
    assert proof["port_released"] is True
    assert data_dir is not None and not data_dir.exists()


# ── the operator-control matrix ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def probe() -> dict:
    """One cluster, one probe run, shared by every assertion below."""
    if not HAVE_PG:
        pytest.skip("no PostgreSQL server binaries on this host")
    pg = IsolatedPostgres()
    try:
        pg.start()
        pg.verify_isolated()
        env = {**os.environ, **pg.env(), "TRADE_AI_CI": "1"}
        env.pop("ADMIN_WRITE_TOKEN", None)
        r = subprocess.run(
            [sys.executable, "-m", "support.operator_control_probe"],
            cwd=str(ROOT / "tests"),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            pytest.fail(f"probe exited {r.returncode}\n{r.stderr[-2000:]}")
        data = json.loads(r.stdout)
        data["_cluster_env"] = pg.env()
        return data
    finally:
        pg.stop()


def _s(probe: dict, name: str) -> dict:
    for row in probe["scenarios"]:
        if row["scenario"] == name:
            return row
    raise AssertionError(f"scenario {name!r} not in probe output")


@needs_pg
def test_probe_ran_against_the_isolated_cluster_only(probe):
    ident = probe["resolved_identity"]
    assert ident["port"] != 5432
    assert ident["dbname"].startswith("tradeai_test_")
    assert ident["usr"].startswith("tradeai_test_")
    assert ident["host"] == "127.0.0.1"
    assert str(ident["data_directory"]).startswith("/tmp/tradeai_testpg_")
    assert probe["rail"]["verdict"] == "ISOLATED"
    assert probe["audit_rows_before"] == 0, "the isolated audit log must start empty"


@needs_pg
@pytest.mark.parametrize(
    "scenario",
    ["denied_wrong_token", "denied_missing_token", "denied_empty_token", "denied_wrong_scope_token"],
)
def test_every_denial_is_403_and_still_audited(probe, scenario):
    """The premise of the old blocker, now measured instead of asserted."""
    row = _s(probe, scenario)
    assert row["http"] == 403
    assert row["response"]["ok"] is False
    assert row["audit_delta"] == 1, "a refused write must still leave an audit record"
    assert row["last_audit_row"]["result"] == "rejected"


@needs_pg
def test_preview_neither_applies_nor_audits(probe):
    row = _s(probe, "preview_does_not_apply_or_audit")
    assert row["http"] == 200
    assert row["response"]["needs_confirm"] is True
    assert row["audit_delta"] == 0, "a two-step preview is not an event"
    assert "old_value" in row["response"]["preview"]
    assert "new_value" in row["response"]["preview"]


@needs_pg
def test_authorized_call_applies_and_audits(probe):
    row = _s(probe, "allowed_applies_and_audits")
    assert row["http"] == 200
    assert row["response"]["result"] == "applied"
    assert row["audit_delta"] == 1
    assert row["last_audit_row"]["result"] == "applied"
    assert probe["apply_marker_written"] is True, "apply_fn must actually have run"


@needs_pg
def test_apply_failure_is_recorded_not_swallowed(probe):
    row = _s(probe, "apply_failure_is_audited")
    assert row["http"] == 500
    assert row["response"]["result"] == "failed"
    assert row["audit_delta"] == 1
    assert "synthetic apply failure" in (row["last_audit_row"]["detail"] or "")


@needs_pg
def test_replay_is_not_idempotent_and_says_so(probe):
    """Truthful negative result: the guard has no idempotency key."""
    row = _s(probe, "replay_second_identical_call")
    assert row["http"] == 200
    assert row["audit_delta"] == 1, "a replay appends a second row rather than being absorbed"


@needs_pg
def test_no_conflict_detection_exists(probe):
    """A stale old_value still applies — so no surface may imply a 409."""
    row = _s(probe, "conflict_stale_old_value_not_detected")
    assert row["http"] == 200
    assert row["response"]["result"] == "applied"


@needs_pg
def test_declared_versus_effective_gate(probe):
    """access_ok() opens the door when ADMIN_WRITE_TOKEN is unset."""
    m = probe["access_ok_matrix"]
    assert m["token_unset_any_token"] is True
    assert m["token_unset_none"] is True
    assert m["token_set_correct"] is True
    assert m["token_set_wrong"] is False
    assert m["token_set_none"] is False
    assert m["token_set_empty"] is False
    assert _s(probe, "open_door_when_token_unset")["response"]["result"] == "applied"


@needs_pg
def test_trading_jobs_can_never_be_retried_from_the_admin_surface(probe):
    a = probe["cron_allowlist"]
    assert a["non_trading_allowed"] is True
    assert a["unknown_job_refused"] is False
    assert a["trading_job_refused"] is False
    assert a["approval_job_refused"] is False


# ── real routes ──────────────────────────────────────────────────────────────


@needs_pg
def test_unknown_route_is_404_and_writes_nothing(probe):
    row = _s(probe, "route_unknown_path_404")
    assert row["http_effective"] == 404
    assert row["audit_delta"] == 0


@needs_pg
def test_wrong_method_never_applies_but_cannot_produce_405(probe):
    """Recorded as it is: handle() returns None for a wrong method, and the
    server's fall-through turns that into 404. No code path emits 405."""
    row = _s(probe, "route_wrong_method_get_on_post_only")
    assert row["handle_returned_none"] is True
    assert row["http_effective"] == 404
    assert row["audit_delta"] == 0


@needs_pg
@pytest.mark.parametrize(
    "scenario,expected",
    [("route_validation_bad_field_400", 400), ("route_validation_missing_id_400", 400)],
)
def test_validation_errors_stop_before_the_guard(probe, scenario, expected):
    row = _s(probe, scenario)
    assert row["http"] == expected
    assert row["response"]["ok"] is False
    assert row["audit_delta"] == 0, "a request rejected by validation is not an audited attempt"


@needs_pg
def test_unknown_target_is_404(probe):
    row = _s(probe, "route_unknown_target_404")
    assert row["http"] == 404
    assert row["audit_delta"] == 0


@needs_pg
def test_route_denial_is_403_and_audited(probe):
    row = _s(probe, "route_denied_wrong_token_403")
    assert row["http"] == 403
    assert row["audit_delta"] == 1


@needs_pg
def test_route_preview_then_apply_end_to_end(probe):
    preview = _s(probe, "route_preview_no_apply")
    assert preview["http"] == 200 and preview["response"]["needs_confirm"] is True
    assert preview["audit_delta"] == 0

    applied = _s(probe, "route_applied_end_to_end")
    assert applied["http"] == 200
    assert applied["response"]["result"] == "applied"
    assert applied["audit_delta"] == 1
    assert probe["topic_row_after"] == {"topic_id": "probe-topic", "enabled": False}, (
        "the confirmed call must have changed the isolated row"
    )


@needs_pg
def test_all_audit_rows_landed_in_the_isolated_cluster(probe):
    assert probe["audit_rows_after"] == len(probe["audit_rows"])
    assert probe["audit_rows_after"] >= 10
    assert probe["final_identity"]["dbname"].startswith("tradeai_test_")
    assert probe["final_identity"]["port"] != 5432
    results = {r["result"] for r in probe["audit_rows"]}
    assert {"applied", "rejected", "failed"} <= results, (
        "the isolated log must contain every outcome class the guard can produce"
    )


@needs_pg
def test_no_broker_order_or_financial_path_was_exercised(probe):
    """Nothing in the probe may touch the broker execution subsystem."""
    blob = json.dumps(probe, default=str).lower()
    for banned in ("place_order", "submit_order", "broker-orders/approve", "/atm/", "promote-from-paper"):
        assert banned not in blob, f"probe touched {banned}"
    for row in probe["audit_rows"]:
        assert row["action"].startswith(("probe.", "topic.")), row["action"]
