"""The integrator must work as the production writer role, not as a superuser.

2026-09-24 16:00 ET: the first production cognitive-memory cycle failed soft with
``InsufficientPrivilege: permission denied for table memory_fact_version``.
CIOEnvelopeIntegrator._scan_conflicts read overlapping versions with
``SELECT … FOR UPDATE``, which needs UPDATE privilege; the production writer role
m2_agent has SELECT only on memory_fact_version by design (writes go through the
SECURITY DEFINER functions). Every earlier test ran the integrator as the shadow
superuser, so nothing caught it.

These tests create a role with EXACTLY production m2_agent's grants in the
pytest database (m2_shadow_test), SET ROLE to it after the integrator connects,
and run the belief lifecycle end to end. With the old ``FOR UPDATE`` read put
back, the same flow must fail with InsufficientPrivilege.

DB-backed; skips cleanly without psycopg2 or the container.
"""

from __future__ import annotations

import os
import uuid

import pytest

PROBE_ROLE = "m5_agent_least_privilege_probe"

# Production m2_agent grants on memory_r10_m2 as measured on 2026-09-24
# (information_schema.role_table_grants + function EXECUTE).
PROD_AGENT_GRANTS = (
    "GRANT USAGE ON SCHEMA memory_r10_m2 TO {r}",
    "GRANT SELECT ON ALL TABLES IN SCHEMA memory_r10_m2 TO {r}",
    "GRANT INSERT, UPDATE ON memory_r10_m2.memory_identity TO {r}",
    "GRANT INSERT ON memory_r10_m2.adjudication_receipt TO {r}",
    "GRANT INSERT ON memory_r10_m2.provenance_edge TO {r}",
    "GRANT INSERT ON memory_r10_m2.relationship_candidate TO {r}",
    "GRANT INSERT, UPDATE ON memory_r10_m2.predicate_temporal_policy TO {r}",
    "GRANT EXECUTE ON FUNCTION memory_r10_m2.write_fact_version(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector) TO {r}",
    "GRANT EXECUTE ON FUNCTION memory_r10_m2.save_bitemporal_fact_version(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector) TO {r}",
    "GRANT EXECUTE ON FUNCTION memory_r10_m2.supersede_single_valued_fact(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,uuid) TO {r}",
)

OLD_FOR_UPDATE_READ = """
    SELECT memory_version_id::text
      FROM memory_r10_m2.memory_fact_version
     WHERE tenant_id = %s AND identity_guid = %s::uuid AND predicate = %s
       AND upper_inf(tx_period)
     ORDER BY version_seq
     FOR UPDATE
"""


def _db():
    if os.getenv("M2_SKIP_DOCKER") == "1":
        pytest.skip("M2_SKIP_DOCKER=1")
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        pytest.skip("psycopg2 not installed (CI installs only pytest+pyyaml)")
    from scripts.lib.memory_m2_v2 import connect

    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"isolated M2 test database not available: {exc}")
    return conn


@pytest.fixture(scope="module")
def agent_role():
    from scripts.lib.cio_memory_integration import apply_bitemporal_schema_v2

    conn = _db()
    assert conn.get_dsn_parameters().get("dbname") != "m2_shadow", "never the live shadow"
    verify = apply_bitemporal_schema_v2(conn)
    assert all(verify.values()), verify
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (PROBE_ROLE,))
        if not cur.fetchone():
            cur.execute(f"CREATE ROLE {PROBE_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS")
        for g in PROD_AGENT_GRANTS:
            cur.execute(g.format(r=PROBE_ROLE))
        cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=%s", (PROBE_ROLE,))
        assert cur.fetchone() == (False, False)
        cur.execute(
            "SELECT has_table_privilege(%s, 'memory_r10_m2.memory_fact_version', 'UPDATE')",
            (PROBE_ROLE,),
        )
        assert cur.fetchone()[0] is False, "probe role must not have UPDATE on facts (like prod)"
    yield conn
    with conn.cursor() as cur:
        cur.execute(f"DROP OWNED BY {PROBE_ROLE}")
        cur.execute(f"DROP ROLE IF EXISTS {PROBE_ROLE}")
    conn.close()


def _agent_integrator(tenant: str):
    """An integrator whose session runs as the least-privilege probe role."""
    from scripts.lib.cio_memory_integration import CIOEnvelopeIntegrator

    integ = CIOEnvelopeIntegrator(tenant_id=tenant)
    base_connect = integ.connect

    def connect():
        conn = base_connect()
        with conn.cursor() as cur:
            cur.execute(f"SET ROLE {PROBE_ROLE}")
        return conn

    integ.connect = connect  # type: ignore[method-assign]
    return integ


def _env(sub: str, text: str, valid_from: str) -> dict:
    return {
        "subject_guid": sub,
        "predicate": "thesis",
        "claim": text,
        "object": {"text": text},
        "valid_from": valid_from,
        "wake_job_id": f"lp-{uuid.uuid4().hex[:6]}",
    }


def test_belief_lifecycle_runs_as_the_production_writer_role(agent_role):
    tenant = f"lp-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _agent_integrator(tenant)
    try:
        first = integ.integrate_envelope(_env(sub, "thesis one", "2026-01-01T00:00:00Z"), apply=True)
        second = integ.integrate_envelope(_env(sub, "thesis two", "2026-02-01T00:00:00Z"), apply=True)
        again = integ.integrate_envelope(_env(sub, "thesis two", "2026-02-01T00:00:00Z"), apply=True)
        with integ.connect().cursor() as cur:
            cur.execute("SELECT current_user")
            assert cur.fetchone()[0] == PROBE_ROLE
    finally:
        integ.close()

    assert first["memory_version_id"]
    assert second["reason"] == "SINGLE_VALUED_SUPERSEDED"
    assert second["superseded"] == [first["memory_version_id"]]
    assert again["reason"] == "IDENTICAL_REASSERTION_NOOP"
    assert again["memory_version_id"] == second["memory_version_id"]


def test_multi_valued_write_runs_as_the_production_writer_role(agent_role):
    tenant = f"lp-mv-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    env = _env(sub, "an observation", "2026-03-01T00:00:00Z")
    env["predicate"] = "observation"
    integ = _agent_integrator(tenant)
    try:
        out = integ.integrate_envelope(env, apply=True)
    finally:
        integ.close()
    assert out["memory_version_id"] and out["writer"] == "save_bitemporal_fact_version"


def test_old_for_update_read_is_refused_for_the_writer_role(agent_role):
    """Negative control: the exact failure production hit at 16:00 on 2026-09-24."""
    import psycopg2

    tenant = f"lp-neg-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _agent_integrator(tenant)
    original = integ._scan_conflicts

    def scan_with_old_row_lock(conn, *, identity_guid, predicate, valid_period, obj):
        with conn.cursor() as cur:
            cur.execute(OLD_FOR_UPDATE_READ, (integ.tenant_id, identity_guid, predicate))
        return original(conn, identity_guid=identity_guid, predicate=predicate, valid_period=valid_period, obj=obj)

    integ._scan_conflicts = scan_with_old_row_lock  # type: ignore[method-assign]
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            integ.integrate_envelope(_env(sub, "thesis one", "2026-01-01T00:00:00Z"), apply=True)
    finally:
        integ.close()


def test_writers_for_one_belief_are_serialized_by_an_advisory_lock(agent_role):
    """The FOR UPDATE row lock is replaced, not dropped: the overlap read happens
    while this backend holds the transaction advisory lock for the belief."""
    tenant = f"lp-lock-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _agent_integrator(tenant)
    seen: list[int] = []
    original = integ._scan_conflicts

    def scan_and_check_lock(conn, **kw):
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND granted")
            seen.append(cur.fetchone()[0])
        return original(conn, **kw)

    integ._scan_conflicts = scan_and_check_lock  # type: ignore[method-assign]
    try:
        integ.integrate_envelope(_env(sub, "thesis one", "2026-01-01T00:00:00Z"), apply=True)
        with integ.connect().cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()")
            after_commit = cur.fetchone()[0]
    finally:
        integ.close()
    assert seen and seen[0] >= 1, "overlap read must run under the advisory lock"
    assert after_commit == 0, "transaction-scoped lock must release at commit"


def test_integrator_source_has_no_row_lock_read():
    """Cheap static guard that runs in CI without a database."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "cio_memory_integration.py"
    code = src.read_text(encoding="utf-8")
    # No executable SQL line may be a bare row-lock clause (the docstring may
    # explain why it is gone).
    assert not any(line.strip() == "FOR UPDATE" for line in code.splitlines())
    assert "pg_advisory_xact_lock" in code
