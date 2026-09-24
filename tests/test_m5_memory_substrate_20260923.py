"""M5 Module 2 — memory substrate: supersession, atomic receipts, token budget, views.

The M5 audit (2026-09-23) found, on the isolated shadow:
  * frozen beliefs — a SINGLE_VALUED thesis could never change, because CURRENT
    versions carry open-ended valid periods, every later assertion overlapped,
    and integrate_envelope suppressed it ("first thesis wins forever");
  * the adjudication receipt and the fact were written in separate autocommit
    statements, with rejected_fact_ids=[] although "pending_new" was rejected;
  * token_estimate was computed but never enforced on a context envelope;
  * the @v views had no security_invoker, and row_kind was not exposed at all.

DB-backed tests run against the pytest-routed m2_shadow_test database (see
tests/conftest.py) and skip cleanly without psycopg2 or the container.
"""
from __future__ import annotations

import os
import uuid

import pytest

from scripts.lib import memory_retrieval_unit as mru

# ---------------------------------------------------------------------------
# Token budget (no database)
# ---------------------------------------------------------------------------


def _unit(i: int, tokens: int) -> dict:
    return {"memory_version_id": f"m{i}", "token_estimate": tokens}


def test_budget_keeps_priority_prefix_and_names_dropped():
    out = mru.enforce_token_budget([_unit(1, 50), _unit(2, 40), _unit(3, 30), _unit(4, 5)], budget=100)
    assert [u["memory_version_id"] for u in out["units"]] == ["m1", "m2"]
    # Strict prefix: the small low-priority unit m4 is dropped too, never
    # promoted past the higher-priority m3 it would have displaced.
    assert out["dropped_for_budget"] == ["m3", "m4"]
    assert out["token_estimate"] == 90
    assert out["token_budget"] == 100


def test_budget_default_is_12000_and_env_configurable(monkeypatch):
    monkeypatch.delenv(mru.TOKEN_BUDGET_ENV, raising=False)
    assert mru.token_budget() == 12000
    monkeypatch.setenv(mru.TOKEN_BUDGET_ENV, "250")
    assert mru.token_budget() == 250
    monkeypatch.setenv(mru.TOKEN_BUDGET_ENV, "not-a-number")
    assert mru.token_budget() == 12000


def test_budget_estimates_units_without_token_estimate():
    unit = {"receipt_id": "r1", "payload": "x" * 400}
    assert mru.unit_token_estimate(unit) >= 100
    out = mru.enforce_token_budget([unit], budget=10)
    assert out["units"] == [] and out["dropped_for_budget"] == ["r1"]


def test_from_fact_units_carry_token_estimate_the_budget_uses():
    u = mru.from_fact({"memory_version_id": "v1", "object": "y" * 800}, mode="CURRENT", why_selected="t")
    assert u["token_estimate"] == 125  # content_summary capped at 500 chars / 4
    assert mru.unit_token_estimate(u) == 125


def test_cio_context_v2_memory_units_are_bounded(monkeypatch):
    from scripts.lib.cio_persistent_cognition import build_cio_context_v2

    monkeypatch.setenv(mru.TOKEN_BUDGET_ENV, "60")
    receipts = [{"receipt_id": f"r{i}", "why": "x" * 120} for i in range(5)]
    env = build_cio_context_v2({"items": [], "receipts": receipts, "as_of": "2026-09-23T00:00:00Z"})
    sec = env["sections"]["MEMORY_RETRIEVAL_UNITS"]
    assert sec["token_budget"] == 60
    assert sec["token_estimate"] <= 60
    kept = [r["receipt_id"] for r in sec["payload"]]
    assert kept == ["r0"]
    assert sec["dropped_for_budget"] == ["r1", "r2", "r3", "r4"]


def test_agent_envelope_episodic_records_are_bounded(monkeypatch):
    from scripts.lib.agent_context_envelope import build_context_envelope

    monkeypatch.setenv(mru.TOKEN_BUDGET_ENV, "30")
    records = [{"memory_id": f"e{i}", "content": "z" * 80} for i in range(3)]
    env = build_context_envelope(agent="alex", role="cio", episodic_memory={"records": records})
    epi = env["episodic_memory"]
    assert [r["memory_id"] for r in epi["records"]] == ["e0"]
    assert epi["dropped_for_budget"] == ["e1", "e2"]
    assert epi["token_budget"] == 30


def test_agent_envelope_without_records_keeps_empty_drop_list():
    from scripts.lib.agent_context_envelope import build_context_envelope

    env = build_context_envelope(agent="alex", role="cio")
    assert env["episodic_memory"]["dropped_for_budget"] == []
    assert env["episodic_memory"]["records"] == []


# ---------------------------------------------------------------------------
# SQL text (no database) — prod-cutover blockers the delta must not carry
# ---------------------------------------------------------------------------


def test_sql_grants_to_role_m2_are_conditional():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("sql/trade-ai-bitemporal-schema-v2.sql", "sql/r10_m2_isolated_benchmark.sql"):
        text = (root / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or stripped.startswith("||") or stripped.startswith("EXECUTE"):
                continue
            assert not stripped.endswith("TO m2;"), f"{rel}: unconditional GRANT to role m2: {stripped}"


def test_views_are_security_invoker_and_row_kind_is_computed():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "sql/trade-ai-bitemporal-schema-v2.sql").read_text(encoding="utf-8")
    assert text.count("WITH (security_invoker = true)") == 4
    assert "CASE WHEN upper_inf(f.tx_period) THEN 'current' ELSE 'audit' END AS row_kind" in text
    # Never a stored column: the architect reconciliation stands.
    assert "ADD COLUMN row_kind" not in text


# ---------------------------------------------------------------------------
# Database-backed (m2_shadow_test)
# ---------------------------------------------------------------------------


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
def m2_db():
    from scripts.lib.cio_memory_integration import apply_bitemporal_schema_v2

    conn = _db()
    name = conn.get_dsn_parameters().get("dbname")
    assert name != "m2_shadow", "tests must never run against the live shadow"
    verify = apply_bitemporal_schema_v2(conn)
    assert all(verify.values()), verify
    yield conn
    conn.close()


def _integrator(tenant: str):
    from scripts.lib.cio_memory_integration import CIOEnvelopeIntegrator

    return CIOEnvelopeIntegrator(tenant_id=tenant)


def _env(sub: str, text: str, valid_from: str) -> dict:
    return {
        "subject_guid": sub,
        "predicate": "thesis",
        "claim": text,
        "object": {"text": text},
        "valid_from": valid_from,
        "wake_job_id": f"m5-{uuid.uuid4().hex[:6]}",
    }


def _rows(conn, tenant: str, sub: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute(
            """
            SELECT object_value->>'text', lower(valid_period), upper(valid_period),
                   upper_inf(tx_period), row_kind, memory_version_id::text, supersedes_id::text
              FROM memory_r10_m2."MemoryFactVersion@v2"
             WHERE tenant_id=%s AND subject_guid=%s
             ORDER BY version_seq
            """,
            (tenant, sub),
        )
        return cur.fetchall()


def test_packaging_health_includes_supersede_writer_and_row_kind(m2_db):
    from scripts.lib.bitemporal_schema_heal import check_bitemporal_packaging_health

    h = check_bitemporal_packaging_health(m2_db)
    assert h["supersede_fn_ok"] is True
    assert h["view_row_kind_ok"] is True
    assert h["healthy"] is True


def test_frozen_belief_is_superseded_not_suppressed(m2_db):
    """Before: the second thesis was suppressed and the first stayed current forever.
    After: the second supersedes the overlap; the first keeps [t1, t2) as current."""
    tenant = f"m5-sup-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _integrator(tenant)
    try:
        first = integ.integrate_envelope(_env(sub, "thesis one", "2026-01-01T00:00:00Z"), apply=True)
        second = integ.integrate_envelope(_env(sub, "thesis two", "2026-02-01T00:00:00Z"), apply=True)
    finally:
        integ.close()

    assert first["memory_version_id"] and not first.get("suppressed")
    assert second.get("suppressed") is False
    assert second["reason"] == "SINGLE_VALUED_SUPERSEDED"
    assert second["superseded"] == [first["memory_version_id"]]

    rows = _rows(m2_db, tenant, sub)
    current = [r for r in rows if r[3]]
    audit = [r for r in rows if not r[3]]
    assert {r[4] for r in current} == {"current"} and {r[4] for r in audit} == {"audit"}
    # The original open-ended version is closed in tx time, kept for audit.
    assert [(r[0], r[5]) for r in audit] == [("thesis one", first["memory_version_id"])]
    by_text = {r[0]: r for r in current}
    assert set(by_text) == {"thesis one", "thesis two"}
    # Old belief remains current for [2026-01-01, 2026-02-01) ...
    assert by_text["thesis one"][1].isoformat().startswith("2026-01-01")
    assert by_text["thesis one"][2].isoformat().startswith("2026-02-01")
    assert by_text["thesis one"][6] == first["memory_version_id"]
    # ... and the new belief is current from 2026-02-01 onward.
    assert by_text["thesis two"][1].isoformat().startswith("2026-02-01")
    assert by_text["thesis two"][2] is None
    assert by_text["thesis two"][5] == second["memory_version_id"]


def test_adjudication_receipt_names_selected_and_rejected(m2_db):
    tenant = f"m5-adj-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _integrator(tenant)
    try:
        first = integ.integrate_envelope(_env(sub, "a", "2026-01-01T00:00:00Z"), apply=True)
        second = integ.integrate_envelope(_env(sub, "b", "2026-03-01T00:00:00Z"), apply=True)
    finally:
        integ.close()
    with m2_db.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute(
            """
            SELECT selected_fact_id::text, rejected_fact_ids::text[], candidate_fact_ids::text[],
                   deterministic_policy, provider, model, prompt_version, chain_of_thought
              FROM memory_r10_m2."AdjudicationReceipt@v1" WHERE tenant_id=%s
            """,
            (tenant,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    sel, rej, cand, policy, provider, model, prompt, cot = rows[0]
    assert sel == second["memory_version_id"]
    assert rej == [first["memory_version_id"]]
    assert set(cand) == {first["memory_version_id"], second["memory_version_id"]}
    assert policy == "latest_assertion_supersedes_overlap"
    # No LLM judged this; the LLM fields stay null rather than invented.
    assert (provider, model, prompt) == (None, None, None)
    assert cot is False


def test_identical_reassertion_writes_nothing(m2_db):
    tenant = f"m5-same-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _integrator(tenant)
    try:
        first = integ.integrate_envelope(_env(sub, "same", "2026-01-01T00:00:00Z"), apply=True)
        again = integ.integrate_envelope(_env(sub, "same", "2026-01-05T00:00:00Z"), apply=True)
    finally:
        integ.close()
    assert again["reason"] == "IDENTICAL_REASSERTION_NOOP"
    assert again["memory_version_id"] == first["memory_version_id"]
    assert len(_rows(m2_db, tenant, sub)) == 1


def test_bounded_assertion_inside_open_belief_splits_it(m2_db):
    """A bounded new belief [t2, t3) inside an open one leaves [t1, t2) and [t3, …) current."""
    tenant = f"m5-split-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _integrator(tenant)
    try:
        integ.integrate_envelope(_env(sub, "base", "2026-01-01T00:00:00Z"), apply=True)
        env = _env(sub, "interlude", "2026-02-01T00:00:00Z")
        env["valid_to"] = "2026-03-01T00:00:00Z"
        integ.integrate_envelope(env, apply=True)
    finally:
        integ.close()
    current = sorted((r for r in _rows(m2_db, tenant, sub) if r[3]), key=lambda r: r[1])
    assert [r[0] for r in current] == ["base", "interlude", "base"]
    assert current[0][2].isoformat().startswith("2026-02-01")
    assert current[2][1].isoformat().startswith("2026-03-01") and current[2][2] is None


def test_receipt_and_fact_are_atomic(m2_db, monkeypatch):
    """A failure after the receipt insert leaves neither receipt nor fact behind."""
    from scripts.lib import cio_memory_integration as cmi

    tenant = f"m5-atom-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _integrator(tenant)
    try:
        integ.integrate_envelope(_env(sub, "one", "2026-01-01T00:00:00Z"), apply=True)
        real_insert = cmi.CIOEnvelopeIntegrator._insert_adjudication

        def insert_then_fail(self, conn, adj):
            real_insert(self, conn, adj)
            raise RuntimeError("injected failure after receipt")

        monkeypatch.setattr(cmi.CIOEnvelopeIntegrator, "_insert_adjudication", insert_then_fail)
        with pytest.raises(RuntimeError, match="injected failure"):
            integ.integrate_envelope(_env(sub, "two", "2026-02-01T00:00:00Z"), apply=True)
        assert integ.connect().autocommit is True
    finally:
        integ.close()
    with m2_db.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute("SELECT count(*) FROM memory_r10_m2.adjudication_receipt WHERE tenant_id=%s", (tenant,))
        assert cur.fetchone()[0] == 0
    rows = _rows(m2_db, tenant, sub)
    assert [(r[0], r[3]) for r in rows] == [("one", True)]


def test_multi_valued_predicates_keep_the_existing_writer(m2_db):
    tenant = f"m5-multi-{uuid.uuid4().hex[:6]}"
    sub = f"cog-{uuid.uuid4().hex[:8]}"
    integ = _integrator(tenant)
    try:
        env = _env(sub, "note", "2026-01-01T00:00:00Z")
        env["predicate"] = "research_candidate"
        out = integ.integrate_envelope(env, apply=True)
    finally:
        integ.close()
    assert out["writer"] == "save_bitemporal_fact_version"
    assert out["adjudication"] is None
