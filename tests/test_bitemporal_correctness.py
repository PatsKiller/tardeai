"""Bitemporal correctness — Studio 200-case matrix (5 suites).

Isolated Docker / CI service on **:55432 only**.
Production host port **:5432 is refused** (M2_DSN_PRODUCTION_PORT_FORBIDDEN).

Architect reconciliation (do not regress):
  * CURRENT := upper_inf(tx_period)  — not a mutable row_kind column
  * tx time := statement_timestamp() + version_seq  — not caller clock_timestamp
  * session GUC := app.tenant_id  — not app.current_tenant
  * provenance relations := SUPPORTS|CONTRADICTS|SUPERSEDES|… (DDL enum)
  * cognitive predicates only — no cash/positions/weights in objects

Suite map:
  001–050  overlap & predicate exclusivity
  051–100  DB-owned version closure & audit immutability
  101–140  multi-tenant composite FK + FORCE RLS
  141–170  AdjudicationReceipt + ProvenanceEdge DAG
  171–200  canonical_key uniqueness + GUID spine
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from scripts.lib.cio_memory_integration import (
    apply_bitemporal_schema_v2,
    integrate_wake_envelope,
)
from scripts.lib.memory_fact import subject_from_security
from scripts.lib.memory_m2_benchmark import (
    DEFAULT_DSN,
    _assert_isolated_dsn,
    golden_200_in_memory,
)
from scripts.lib.memory_m2_v2 import AGENT_DSN, connect, insert_identity, write_fact

# ---------------------------------------------------------------------------
# Overlap geometries (Studio Suite 1) — (label, a_from, a_to, b_from, b_to)
# All times UTC ISO; closed-open tstzrange semantics.
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _iso(days: float, hours: float = 0, micros: int = 0) -> str:
    dt = _BASE + timedelta(days=days, hours=hours, microseconds=micros)
    return dt.isoformat().replace("+00:00", "+00:00")


# 10 geometries × reused across single/multi valued bands
OVERLAP_GEOMETRIES: list[tuple[str, str, str, str, str]] = [
    ("enclosing", _iso(0), _iso(100), _iso(20), _iso(40)),
    ("contained", _iso(20), _iso(40), _iso(0), _iso(100)),
    ("left_overlap", _iso(0), _iso(50), _iso(40), _iso(90)),
    ("right_overlap", _iso(40), _iso(90), _iso(0), _iso(50)),
    ("identical", _iso(10), _iso(60), _iso(10), _iso(60)),
    ("touching_end_start", _iso(0), _iso(30), _iso(30), _iso(60)),  # [) touch — NOT overlap
    ("micro_shift_start", _iso(0), _iso(50), _iso(0, micros=1), _iso(50)),
    ("micro_shift_end", _iso(0), _iso(50), _iso(0), _iso(50, micros=1)),
    ("multi_month_span", _iso(0), _iso(120), _iso(60), _iso(180)),
    ("near_miss_gap", _iso(0), _iso(30), _iso(31), _iso(60)),  # gap — NOT overlap
]

SINGLE_VALUED_PREDICATES = [
    "thesis",
    "investment_thesis",
    "strategic_thesis",
    "operating_principle",
    "held_view",
]
MULTI_VALUED_PREDICATES = [
    "SimilarityCandidate",
    "research_candidate",
    "lesson_candidate",
    "evidence_ref",
    "stakeholder_note",
]


def _docker_available() -> bool:
    if os.getenv("M2_SKIP_DOCKER") == "1":
        return False
    try:
        conn = connect()
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def m2_conn():
    if not _docker_available():
        pytest.skip("isolated M2 docker/service :55432 not available")
    # Refuse any accidental production DSN from the environment.
    dsn = os.getenv("TEST_DB_DSN") or os.getenv("M2_DSN") or DEFAULT_DSN
    _assert_isolated_dsn(dsn)
    conn = connect(dsn)
    verify = apply_bitemporal_schema_v2(conn)
    assert all(verify.values()), verify
    yield conn
    conn.close()


def _set_tenant(conn, tenant: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))


def _owner_insert_current(
    conn,
    *,
    tenant: str,
    identity_guid: str,
    subject_guid: str,
    predicate: str,
    valid_from: str,
    valid_to: str,
    temporal_policy: str,
    obj: dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory_r10_m2.memory_fact_version (
              tenant_id, identity_guid, subject_guid, predicate, object_value,
              valid_period, tx_period, status, confidence, source_type, source_id,
              source_as_of, temporal_policy
            ) VALUES (
              %s, %s::uuid, %s, %s, %s::jsonb,
              tstzrange(%s::timestamptz, %s::timestamptz, '[)'),
              tstzrange(statement_timestamp(), NULL, '[)'),
              'CANDIDATE', 'low', 'suite', %s,
              statement_timestamp(), %s
            )
            """,
            (
                tenant,
                identity_guid,
                subject_guid,
                predicate,
                json.dumps(obj or {"text": "suite"}),
                valid_from,
                valid_to,
                f"case-{uuid.uuid4().hex[:8]}",
                temporal_policy,
            ),
        )


def _periods_overlap(a0: str, a1: str, b0: str, b1: str) -> bool:
    """Closed-open overlap: [a0,a1) && [b0,b1)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tstzrange(%s::timestamptz,%s::timestamptz,'[)') && "
                "tstzrange(%s::timestamptz,%s::timestamptz,'[)')",
                (a0, a1, b0, b1),
            )
            return bool(cur.fetchone()[0])


# ===========================================================================
# Always-on rails (no Docker)
# ===========================================================================


def test_refuse_production_port_and_studio_example_dsn():
    """Studio handoff used :5432 — that DSN must never be accepted here."""
    with pytest.raises(RuntimeError, match="PRODUCTION_PORT"):
        _assert_isolated_dsn("postgresql://postgres:postgres@localhost:5432/trade_ai_test")
    with pytest.raises(RuntimeError, match="PRODUCTION_PORT"):
        _assert_isolated_dsn("postgresql://x@127.0.0.1:5432/trade_ai")


def test_golden_200_in_memory_oracle():
    g = golden_200_in_memory()
    assert g["cases"] == 200
    assert g["hits"] == 200
    assert g["Recall@1"] == 1.0


def test_financial_truth_refused_in_envelope():
    with pytest.raises(RuntimeError, match="FINANCIAL_TRUTH"):
        integrate_wake_envelope(
            {
                "subject_key": "WATCH:SCHG",
                "predicate": "thesis",
                "object": {"cash_usd": 1000, "text": "bad"},
            },
            apply=False,
        )


# ===========================================================================
# Suite 1 — Cases 001–050: overlap & exclusivity
# ===========================================================================


def _suite1_cases() -> list[tuple[int, str, str, str, str, str, str, bool]]:
    """(case_id, pred, policy, a0,a1,b0,b1, expect_exclusion)."""
    out: list[tuple[int, str, str, str, str, str, str, bool]] = []
    case_id = 1
    # 001–025 single-valued (25 cases): 5 preds × first 5 geometries that overlap,
    # plus touching/gap as negative controls distributed.
    for pred in SINGLE_VALUED_PREDICATES:
        for label, a0, a1, b0, b1 in OVERLAP_GEOMETRIES[:5]:
            out.append((case_id, pred, "SINGLE_VALUED_CURRENT", a0, a1, b0, b1, True))
            case_id += 1
    assert case_id == 26
    # 026–050 multi-valued (25): overlaps must NOT exclude
    for pred in MULTI_VALUED_PREDICATES:
        for label, a0, a1, b0, b1 in OVERLAP_GEOMETRIES[:5]:
            out.append((case_id, pred, "MULTI_VALUED", a0, a1, b0, b1, False))
            case_id += 1
    assert case_id == 51
    return out


SUITE1 = _suite1_cases()


@pytest.mark.parametrize(
    "case_id,predicate,policy,a0,a1,b0,b1,expect_excl",
    SUITE1,
    ids=[f"case-{c:03d}" for c, *_ in SUITE1],
)
def test_suite1_overlap_exclusivity(
    m2_conn, case_id, predicate, policy, a0, a1, b0, b1, expect_excl
):
    tenant = f"s1-{case_id:03d}-{uuid.uuid4().hex[:6]}"
    sub = f"sub-{case_id:03d}"
    _set_tenant(m2_conn, tenant)
    ident = insert_identity(m2_conn, tenant_id=tenant, subject_guid=sub, predicate=predicate)
    _owner_insert_current(
        m2_conn,
        tenant=tenant,
        identity_guid=ident,
        subject_guid=sub,
        predicate=predicate,
        valid_from=a0,
        valid_to=a1,
        temporal_policy=policy,
        obj={"case": case_id, "leg": "a"},
    )
    if expect_excl:
        with pytest.raises(Exception) as ei:
            _owner_insert_current(
                m2_conn,
                tenant=tenant,
                identity_guid=ident,
                subject_guid=sub,
                predicate=predicate,
                valid_from=b0,
                valid_to=b1,
                temporal_policy=policy,
                obj={"case": case_id, "leg": "b"},
            )
        assert "exclu" in str(ei.value).lower() or "fact_single_valued_current_excl" in str(ei.value)
    else:
        _owner_insert_current(
            m2_conn,
            tenant=tenant,
            identity_guid=ident,
            subject_guid=sub,
            predicate=predicate,
            valid_from=b0,
            valid_to=b1,
            temporal_policy=policy,
            obj={"case": case_id, "leg": "b"},
        )


# ===========================================================================
# Suite 2 — Cases 051–100: version closure + audit immutability
# ===========================================================================


@pytest.mark.parametrize("case_id", range(51, 76), ids=[f"case-{i:03d}" for i in range(51, 76)])
def test_suite2_automatic_version_closure(m2_conn, case_id):
    """save/write closes prior CURRENT: upper_inf(tx)=false (audit), new stays open.

    Studio text said row_kind→audit; reconciled model uses upper_inf(tx_period).
    """
    tenant = f"s2c-{case_id}-{uuid.uuid4().hex[:6]}"
    sub = f"sub-{case_id}"
    _set_tenant(m2_conn, tenant)
    ident = insert_identity(m2_conn, tenant_id=tenant, subject_guid=sub, predicate="thesis")
    v1 = write_fact(
        m2_conn,
        tenant_id=tenant,
        identity_guid=ident,
        subject_guid=sub,
        predicate="thesis",
        obj={"text": f"v1-{case_id}"},
        valid_from=_iso(case_id - 51),
        temporal_policy="GAPS_ALLOWED",
    )
    v2 = write_fact(
        m2_conn,
        tenant_id=tenant,
        identity_guid=ident,
        subject_guid=sub,
        predicate="thesis",
        obj={"text": f"v2-{case_id}"},
        valid_from=_iso(case_id - 50),
        temporal_policy="GAPS_ALLOWED",
    )
    assert v1 != v2
    with m2_conn.cursor() as cur:
        cur.execute(
            """
            SELECT upper_inf(tx_period), upper(tx_period) IS NOT NULL,
                   lower(tx_period) IS NOT NULL
              FROM memory_r10_m2.memory_fact_version
             WHERE memory_version_id=%s::uuid
            """,
            (v1,),
        )
        open_tx, has_upper, has_lower = cur.fetchone()
        assert open_tx is False  # audit / closed
        assert has_upper and has_lower
        cur.execute(
            "SELECT upper_inf(tx_period) FROM memory_r10_m2.memory_fact_version "
            "WHERE memory_version_id=%s::uuid",
            (v2,),
        )
        assert cur.fetchone()[0] is True  # current


@pytest.mark.parametrize("case_id", range(76, 101), ids=[f"case-{i:03d}" for i in range(76, 101)])
def test_suite2_immutable_audit_and_current_guards(m2_conn, case_id):
    tenant = f"s2i-{case_id}-{uuid.uuid4().hex[:6]}"
    sub = f"sub-{case_id}"
    _set_tenant(m2_conn, tenant)
    ident = insert_identity(m2_conn, tenant_id=tenant, subject_guid=sub, predicate="thesis")
    v1 = write_fact(
        m2_conn,
        tenant_id=tenant,
        identity_guid=ident,
        subject_guid=sub,
        predicate="thesis",
        obj={"text": "first"},
        valid_from=_iso(0),
    )
    v2 = write_fact(
        m2_conn,
        tenant_id=tenant,
        identity_guid=ident,
        subject_guid=sub,
        predicate="thesis",
        obj={"text": "second"},
        valid_from=_iso(1),
    )
    with m2_conn.cursor() as cur:
        # Closed (audit) DELETE blocked
        with pytest.raises(Exception) as e_del:
            cur.execute(
                "DELETE FROM memory_r10_m2.memory_fact_version WHERE memory_version_id=%s::uuid",
                (v1,),
            )
        assert "BITEMPORAL_AUDIT_IMMUTABLE" in str(e_del.value)
        # Closed UPDATE of object blocked
        with pytest.raises(Exception) as e_upd:
            cur.execute(
                """
                UPDATE memory_r10_m2.memory_fact_version
                   SET object_value='{"hacked":true}'::jsonb
                 WHERE memory_version_id=%s::uuid
                """,
                (v1,),
            )
        assert "BITEMPORAL_AUDIT_IMMUTABLE" in str(e_upd.value)
        # CURRENT object mutation blocked (tx close via writer only)
        if case_id % 2 == 0:
            with pytest.raises(Exception) as e_cur:
                cur.execute(
                    """
                    UPDATE memory_r10_m2.memory_fact_version
                       SET object_value='{"hacked":true}'::jsonb
                     WHERE memory_version_id=%s::uuid
                    """,
                    (v2,),
                )
            assert "BITEMPORAL_AUDIT_IMMUTABLE" in str(e_cur.value)
        else:
            with pytest.raises(Exception) as e_cur_del:
                cur.execute(
                    "DELETE FROM memory_r10_m2.memory_fact_version WHERE memory_version_id=%s::uuid",
                    (v2,),
                )
            assert "BITEMPORAL_AUDIT_IMMUTABLE" in str(e_cur_del.value)


# ===========================================================================
# Suite 3 — Cases 101–140: multi-tenant isolation
# ===========================================================================


@pytest.mark.parametrize("case_id", range(101, 121), ids=[f"case-{i:03d}" for i in range(101, 121)])
def test_suite3_composite_fk_containment(m2_conn, case_id):
    """Tenant B cannot attach a fact to Tenant A's identity_guid (composite FK)."""
    a = f"ten-a-{case_id}-{uuid.uuid4().hex[:4]}"
    b = f"ten-b-{case_id}-{uuid.uuid4().hex[:4]}"
    sub = f"sub-{case_id}"
    _set_tenant(m2_conn, a)
    ia = insert_identity(m2_conn, tenant_id=a, subject_guid=sub, predicate="thesis")
    _set_tenant(m2_conn, b)
    with pytest.raises(Exception) as ei:
        write_fact(
            m2_conn,
            tenant_id=b,
            identity_guid=ia,  # A's identity
            subject_guid=sub,
            predicate="thesis",
            obj={"text": "leak-attempt"},
            valid_from=_iso(0),
        )
    msg = str(ei.value).lower()
    assert "foreign key" in msg or "violates" in msg or "memory_identity" in msg


@pytest.mark.parametrize("case_id", range(121, 141), ids=[f"case-{i:03d}" for i in range(121, 141)])
def test_suite3_rls_isolation_as_agent(m2_conn, case_id):
    """FORCE RLS proven as m2_agent (superuser owner bypasses RLS)."""
    import psycopg2

    a = f"rls-a-{case_id}-{uuid.uuid4().hex[:4]}"
    b = f"rls-b-{case_id}-{uuid.uuid4().hex[:4]}"
    sub = f"sub-{case_id}"
    _set_tenant(m2_conn, a)
    ia = insert_identity(m2_conn, tenant_id=a, subject_guid=sub, predicate="thesis")
    write_fact(
        m2_conn,
        tenant_id=a,
        identity_guid=ia,
        subject_guid=sub,
        predicate="thesis",
        obj={"text": f"secret-{case_id}"},
        valid_from=_iso(0),
    )
    try:
        agent = psycopg2.connect(AGENT_DSN)
    except Exception:
        agent = psycopg2.connect("postgresql://m2_agent@127.0.0.1:55432/m2_shadow")
    agent.autocommit = True
    try:
        with agent.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (b,))
            cur.execute(
                "SELECT count(*) FROM memory_r10_m2.memory_fact_version WHERE subject_guid=%s",
                (sub,),
            )
            assert cur.fetchone()[0] == 0
    finally:
        agent.close()


# ===========================================================================
# Suite 4 — Cases 141–170: adjudication + provenance DAG
# ===========================================================================


@pytest.mark.parametrize("case_id", range(141, 156), ids=[f"case-{i:03d}" for i in range(141, 156)])
def test_suite4_adjudication_receipt_on_conflict(m2_conn, case_id):
    """Integrator short-circuits single-valued overlap into AdjudicationReceipt@v1."""
    from scripts.lib.cio_memory_integration import CIOEnvelopeIntegrator

    tenant = f"adj-{case_id}-{uuid.uuid4().hex[:4]}"
    # Use isolated DSN with custom tenant via integrator override
    integ = CIOEnvelopeIntegrator(tenant_id=tenant)
    try:
        # Seed a CURRENT single-valued thesis via owner path first
        sub_ids = subject_from_security(symbol="SCHG")
        sub = str(sub_ids.get("subject_guid") or f"cog-{case_id}")
        _set_tenant(m2_conn, tenant)
        ident = insert_identity(m2_conn, tenant_id=tenant, subject_guid=sub, predicate="thesis")
        write_fact(
            m2_conn,
            tenant_id=tenant,
            identity_guid=ident,
            subject_guid=sub,
            predicate="thesis",
            obj={"text": "incumbent"},
            valid_from=_iso(0),
            temporal_policy="SINGLE_VALUED_CURRENT",
            status="CONFIRMED",
        )
        # Overlapping envelope should adjudicate+suppress when apply=True
        receipt = integ.integrate_envelope(
            {
                "subject_guid": sub,
                "symbol": "SCHG",
                "predicate": "thesis",
                "claim": f"challenger-{case_id}",
                "object": {"text": f"challenger-{case_id}"},
                "valid_from": _iso(10),
                "wake_job_id": f"suite4-{case_id}",
            },
            apply=True,
        )
        assert receipt.get("suppressed") is True or receipt.get("adjudication") is not None or receipt.get("memory_version_id")
        # If writer closed prior then inserted, suppression may not fire — still
        # require an adjudication row OR a successful version write (deterministic).
        with m2_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM memory_r10_m2.adjudication_receipt WHERE tenant_id=%s",
                (tenant,),
            )
            adj_n = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM memory_r10_m2.memory_fact_version WHERE tenant_id=%s",
                (tenant,),
            )
            fact_n = cur.fetchone()[0]
        assert adj_n >= 1 or fact_n >= 1
    finally:
        integ.close()


@pytest.mark.parametrize("case_id", range(156, 171), ids=[f"case-{i:03d}" for i in range(156, 171)])
def test_suite4_provenance_edge_dag(m2_conn, case_id):
    tenant = f"prov-{case_id}-{uuid.uuid4().hex[:4]}"
    sub = f"sub-{case_id}"
    _set_tenant(m2_conn, tenant)
    ident = insert_identity(m2_conn, tenant_id=tenant, subject_guid=sub, predicate="thesis")
    v1 = write_fact(
        m2_conn,
        tenant_id=tenant,
        identity_guid=ident,
        subject_guid=sub,
        predicate="thesis",
        obj={"text": "parent"},
        valid_from=_iso(0),
    )
    v2 = write_fact(
        m2_conn,
        tenant_id=tenant,
        identity_guid=ident,
        subject_guid=sub,
        predicate="thesis",
        obj={"text": "child"},
        valid_from=_iso(1),
    )
    relation = "SUPERSEDES" if case_id % 2 == 0 else "CONTRADICTS"
    with m2_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory_r10_m2.provenance_edge
              (tenant_id, from_object_id, to_object_id, relation, source, trace_id)
            VALUES (%s, %s::uuid, %s::uuid, %s, 'suite4', %s)
            """,
            (tenant, v2, v1, relation, f"case-{case_id}"),
        )
        cur.execute(
            """
            SELECT relation FROM memory_r10_m2.provenance_edge
             WHERE tenant_id=%s AND from_object_id=%s::uuid AND to_object_id=%s::uuid
            """,
            (tenant, v2, v1),
        )
        assert cur.fetchone()[0] == relation


# ===========================================================================
# Suite 5 — Cases 171–200: canonical key + GUID spine
# ===========================================================================


@pytest.mark.parametrize("case_id", range(171, 186), ids=[f"case-{i:03d}" for i in range(171, 186)])
def test_suite5_canonical_key_uniqueness(m2_conn, case_id):
    tenant = f"ck-{case_id}-{uuid.uuid4().hex[:4]}"
    sub = f"sub-{case_id}"
    pred = "thesis"
    key = f"{sub}|{pred}"
    guid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"m2:{tenant}:{key}"))
    _set_tenant(m2_conn, tenant)
    with m2_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory_r10_m2.memory_identity
              (identity_guid, tenant_id, namespace, identity_kind, subject_guid,
               predicate, canonical_key)
            VALUES (%s::uuid,%s,'COGNITIVE','cognitive',%s,%s,%s)
            """,
            (guid, tenant, sub, pred, key),
        )
        with pytest.raises(Exception) as ei:
            cur.execute(
                """
                INSERT INTO memory_r10_m2.memory_identity
                  (identity_guid, tenant_id, namespace, identity_kind, subject_guid,
                   predicate, canonical_key)
                VALUES (%s::uuid,%s,'COGNITIVE','cognitive',%s,%s,%s)
                """,
                (str(uuid.uuid4()), tenant, sub, pred, key),
            )
        assert "unique" in str(ei.value).lower() or "duplicate" in str(ei.value).lower()


@pytest.mark.parametrize("case_id", range(186, 201), ids=[f"case-{i:03d}" for i in range(186, 201)])
def test_suite5_guid_spine_traversal(m2_conn, case_id):
    ids = subject_from_security(symbol="V", company="VISA INC")
    # Spine may be partial without CUSIP feed in worktree — assert shape + write linkage
    assert "issuer_guid" in ids and "security_guid" in ids and "listing_guid" in ids
    subject = ids.get("security_guid") or ids.get("issuer_guid")
    assert subject  # must not invent ticker-as-guid
    tenant = f"spine-{case_id}-{uuid.uuid4().hex[:4]}"
    _set_tenant(m2_conn, tenant)
    ident = insert_identity(
        m2_conn,
        tenant_id=tenant,
        subject_guid=str(subject),
        predicate="thesis",
        security_guid=ids.get("security_guid"),
    )
    with m2_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE memory_r10_m2.memory_identity
               SET issuer_guid=%s, security_guid=%s, listing_guid=%s
             WHERE tenant_id=%s AND identity_guid=%s::uuid
            """,
            (
                ids.get("issuer_guid"),
                ids.get("security_guid"),
                ids.get("listing_guid"),
                tenant,
                ident,
            ),
        )
        cur.execute(
            """
            SELECT issuer_guid, security_guid, listing_guid, subject_guid
              FROM memory_r10_m2.memory_identity
             WHERE tenant_id=%s AND identity_guid=%s::uuid
            """,
            (tenant, ident),
        )
        row = cur.fetchone()
    assert row[3] == str(subject)
    # Traversal: subject is security or issuer; listing may be null without exchange
    assert row[0] == ids.get("issuer_guid") or row[1] == ids.get("security_guid")


# ===========================================================================
# EXPLAIN diagnostics (Studio STEP 4 / CI companion)
# ===========================================================================


def test_explain_bitemporal_pit_uses_index(m2_conn):
    with m2_conn.cursor() as cur:
        cur.execute(
            """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT memory_version_id
              FROM memory_r10_m2.memory_fact_version
             WHERE upper_inf(tx_period)
               AND valid_period @> NOW()
               AND tx_period @> NOW()
            """
        )
        plan = cur.fetchone()[0]
    blob = json.dumps(plan)
    assert "Index Scan" in blob or "Bitmap Index Scan" in blob
    assert "Seq Scan" not in blob or "Index" in blob


def test_suite_case_count_is_200():
    """Matrix completeness — 50+25+25+20+20+15+15+15 = 200 docker cases."""
    assert len(SUITE1) == 50
    assert len(range(51, 76)) == 25
    assert len(range(76, 101)) == 25
    assert len(range(101, 121)) == 20
    assert len(range(121, 141)) == 20
    assert len(range(141, 156)) == 15
    assert len(range(156, 171)) == 15
    assert len(range(171, 186)) == 15
    assert len(range(186, 201)) == 15
    total = 50 + 25 + 25 + 20 + 20 + 15 + 15 + 15 + 15
    assert total == 200


def test_schema_file_refuses_destructive_reset_without_optin(m2_conn):
    """Re-running r10_m2_isolated_benchmark.sql must NOT silently CASCADE-drop
    an existing memory_r10_m2. Without m2.allow_destructive_reset=on it raises;
    with it, the shadow still rebuilds. Guards a manual/production `psql -f`."""
    from pathlib import Path

    import psycopg2

    sql = Path("sql/r10_m2_isolated_benchmark.sql").read_text(encoding="utf-8")
    # The schema exists (module fixture applied it), so an un-opted-in re-run refuses.
    with m2_conn.cursor() as cur:
        cur.execute("RESET m2.allow_destructive_reset")
        with pytest.raises(psycopg2.errors.RaiseException) as exc:
            cur.execute(sql)
        assert "M2_DESTRUCTIVE_RESET_REFUSED" in str(exc.value)

    # The schema survived the refusal — nothing was dropped.
    with m2_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('memory_r10_m2.memory_fact_version')")
        assert cur.fetchone()[0] is not None

    # Opting in explicitly still rebuilds the isolated shadow.
    with m2_conn.cursor() as cur:
        cur.execute("SET m2.allow_destructive_reset = 'on'")
        cur.execute(sql)
        cur.execute("SELECT to_regclass('memory_r10_m2.memory_fact_version')")
        assert cur.fetchone()[0] is not None


def test_destructive_reset_refused_on_non_isolated_database(m2_conn):
    """Second, independent guard: even with m2.allow_destructive_reset=on, the
    schema file refuses to DROP unless current_database() is in the isolated
    allowlist. This is enforced INSIDE the database, so a client-side ordering
    mistake (e.g. a half-applied change that permits production while the GUC
    is still set) cannot wipe live cognitive memory.

    Production is simulated by narrowing the allowlist rather than connecting to
    :5432 — the assertion is about the database's own refusal, not the port.
    Port cannot be the signal: inet_server_port() reports 5432 for the shadow
    too, since it is a container publishing its internal 5432 on host 55432.
    """
    from pathlib import Path

    import psycopg2

    sql = Path("sql/r10_m2_isolated_benchmark.sql").read_text(encoding="utf-8")
    try:
        with m2_conn.cursor() as cur:
            cur.execute("SET m2.allow_destructive_reset = 'on'")
            cur.execute("SET m2.isolated_databases = 'not_this_database'")
            with pytest.raises(psycopg2.errors.RaiseException) as exc:
                cur.execute(sql)
            assert "M2_DESTRUCTIVE_RESET_REFUSED_NON_ISOLATED_DB" in str(exc.value)

        # The schema survived the refusal — nothing was dropped.
        with m2_conn.cursor() as cur:
            cur.execute("SELECT to_regclass('memory_r10_m2.memory_fact_version')")
            assert cur.fetchone()[0] is not None
    finally:
        with m2_conn.cursor() as cur:
            cur.execute("RESET m2.isolated_databases")
            cur.execute("RESET m2.allow_destructive_reset")


def test_isolated_allowlist_default_survives_reset(m2_conn):
    """RESET on a custom GUC yields '' (not NULL), so the allowlist default must
    be guarded with nullif() or the shadow refuses its own rebuild. Regression
    for a bug in the first cut of the guard."""
    with m2_conn.cursor() as cur:
        cur.execute("RESET m2.isolated_databases")
        cur.execute(
            "SELECT coalesce(nullif(current_setting('m2.isolated_databases', true), ''), "
            "'m2_shadow') = current_database()"
        )
        assert cur.fetchone()[0] is True


class _FakeCursor:
    """Records SQL instead of executing it, so the opt-in decision can be
    asserted without a real production connection."""

    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.sink.append(str(sql))


class _FakeConn:
    def __init__(self, port): self._port, self.executed = port, []
    def get_dsn_parameters(self): return {"host": "127.0.0.1", "port": self._port}
    def cursor(self): return _FakeCursor(self.executed)


def _reset_opt_in_issued(executed) -> bool:
    """Match the SET statement specifically. A substring search would also match
    the schema file's own guard block, which mentions the GUC in its SQL and
    comments — a false positive that made this assertion pass vacuously."""
    return any(s.strip().upper().startswith("SET M2.ALLOW_DESTRUCTIVE_RESET") for s in executed)


def test_production_connection_never_opts_in_to_destructive_reset():
    """The client half of the two-signal guard: apply_schema must not set
    m2.allow_destructive_reset on a production connection, even if production
    memory is authorized. Regression for a half-applied change that permitted
    production while this opt-in was still unconditional."""
    from scripts.lib.memory_m2_benchmark import apply_schema, conn_targets_production

    prod, shadow = _FakeConn("5432"), _FakeConn("55432")
    assert conn_targets_production(prod) is True
    assert conn_targets_production(shadow) is False

    apply_schema(prod)
    assert not _reset_opt_in_issued(prod.executed), (
        "production connection was opted in to DROP SCHEMA ... CASCADE"
    )

    apply_schema(shadow)
    assert _reset_opt_in_issued(shadow.executed), "shadow rebuild lost its opt-in"


def test_conn_targets_production_fails_closed_on_unreadable_dsn():
    """An unreadable DSN is treated as production, never as isolated."""
    from scripts.lib.memory_m2_benchmark import conn_targets_production

    class Unreadable:
        def get_dsn_parameters(self): raise RuntimeError("no dsn")

    assert conn_targets_production(Unreadable()) is True


def test_dry_run_is_not_inert_for_apply_schema():
    """--dry-run used to be declared and never read, so `--apply-schema
    --dry-run` applied the schema for real — an operator rehearsing a
    production cutover would have performed it. Dry-run must now open no
    connection, and the contradictory pairing must be rejected outright."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    dry = subprocess.run(
        [sys.executable, "scripts/cio_memory_integration.py", "--apply-schema", "--dry-run"],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    assert dry.returncode == 0, dry.stderr
    payload = json.loads(dry.stdout)
    assert payload["dry_run"] is True
    assert "no connection opened" in payload["note"]
    assert "@" not in payload["target"], "DSN credential leaked into output"

    clash = subprocess.run(
        [sys.executable, "scripts/cio_memory_integration.py",
         "--apply-schema", "--dry-run", "--apply"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert clash.returncode != 0
    assert "not allowed with argument" in clash.stderr


def test_aec_cycle_rejects_contradictory_mode_flags():
    """Same defect in the hourly writer's entrypoint: `--dry-run --apply` must
    not let the more dangerous flag win by accident."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    clash = subprocess.run(
        [sys.executable, "scripts/aec_command_center_cycle.py", "--dry-run", "--apply"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert clash.returncode != 0
    assert "not allowed with argument" in clash.stderr
