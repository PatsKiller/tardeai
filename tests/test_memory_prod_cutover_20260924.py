"""M2 bitemporal production cutover (M5, 2026-09-24).

Production :5432 holds the base memory_r10_m2 tables but never received the v2
packaging, and every isolated apply path refuses production by design. The
cutover (scripts/lib/memory_prod_cutover.py) turns the REVIEWED SQL files into a
RUN/SKIP plan against the live catalog and applies it in one transaction with
post-checks and a rolled-back smoke run.

Pure tests need no database (CI has only pytest+pyyaml). Database tests run on
m2_shadow_test, rebuilt to production's "base only" shape, and never touch the
live m2_shadow or production.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import memory_prod_cutover as mc  # noqa: E402

BASE_TEXT = mc.BASE_SQL.read_text(encoding="utf-8")
V2_TEXT = mc.V2_SQL.read_text(encoding="utf-8")

# The catalog production showed on 2026-09-24 (read-only snapshot): base
# objects present, v2 packaging absent, m2_agent provisioned, no role m2.
PROD_LIKE_STATE = {
    "schema_exists": True,
    "extensions": ["btree_gist", "pgcrypto", "plpgsql", "vector"],
    "tables": list(mc.MEMORY_TABLES),
    "views": [],
    "indexes": [
        "fact_current_idx",
        "fact_subject_pred_btree",
        "fact_valid_gist",
        "fact_tx_gist",
        "fact_id_pred_valid_gist",
        "fact_valid_spgist",
        "provenance_from_idx",
        "provenance_to_idx",
    ],
    "constraints": ["fact_single_valued_current_excl"],
    "triggers": ["trg_no_agent_direct_insert"],
    "policies": [
        "memory_identity.tenant_iso_identity",
        "memory_fact_version.tenant_iso_fact",
        "adjudication_receipt.tenant_iso_adj",
        "provenance_edge.tenant_iso_prov",
        "relationship_candidate.tenant_iso_rel",
        "predicate_temporal_policy.tenant_iso_pred",
    ],
    "rls_enabled": list(mc.MEMORY_TABLES),
    "rls_forced": list(mc.MEMORY_TABLES),
    "functions": ["forbid_client_tx_authoring", "write_fact_version"],
    "agent_role": {"exists": True, "safe": True, "can_login": True},
    "role_m2_exists": False,
    "db_create_privilege": True,
    "row_counts": {t: 0 for t in mc.MEMORY_TABLES},
}


# ---------------------------------------------------------------------------
# Pure (no database)
# ---------------------------------------------------------------------------


def test_split_keeps_dollar_bodies_with_digit_tags_whole():
    # $ensure_m2_agent$ / $grant_m2_write$ carry digits; a tag regex without
    # digits split their bodies on inner semicolons (caught by the dry run).
    sql = "DO $grant_m2_write$ BEGIN PERFORM 1; PERFORM 'a;b'; END $grant_m2_write$;\nSELECT 'it''s; fine';"
    parts = mc.split_sql(sql)
    assert len(parts) == 2
    assert parts[0].endswith("$grant_m2_write$")
    assert parts[1] == "SELECT 'it''s; fine'"


def test_every_reviewed_statement_is_classified():
    for text in (BASE_TEXT, V2_TEXT):
        for stmt in mc.split_sql(text):
            assert mc.classify(stmt)["kind"] != "unclassified", stmt[:120]


def test_prod_like_plan_has_no_refusals_and_no_destructive_step():
    plan = mc.build_plan(PROD_LIKE_STATE)
    assert plan.refusals == []
    kinds_run = {s.kind for s in plan.run_steps}
    assert {"do_destructive_reset", "do_role", "drop_trigger", "table"}.isdisjoint(kinds_run)
    for s in plan.run_steps:
        assert not mc._FORBIDDEN_HEAD.match(s.sql), s.sql[:80]
    # The v2 trigger is created (missing); the base insert trigger is kept.
    trig = {s.name: s.action for s in plan.steps if s.kind == "trigger"}
    assert trig == {"trg_no_agent_direct_insert": "SKIP", "trg_block_fact_manipulation": "RUN"}
    # The "do not apply to production" comment is replaced, not re-applied.
    comment = [s for s in plan.steps if s.kind == "schema_comment"]
    assert len(comment) == 1 and "do not apply to production" not in comment[0].sql.lower()


def test_plan_refuses_without_the_operator_provisioned_role():
    state = {**PROD_LIKE_STATE, "agent_role": {"exists": False, "safe": False, "can_login": False}}
    assert any("M2_AGENT_ROLE_MISSING" in r for r in mc.build_plan(state).refusals)


def test_plan_refuses_when_vector_needs_a_superuser():
    state = {**PROD_LIKE_STATE, "extensions": ["btree_gist", "pgcrypto", "plpgsql"]}
    assert any("EXTENSION_NEEDS_SUPERUSER: vector" in r for r in mc.build_plan(state).refusals)


@pytest.mark.parametrize(
    "smuggled",
    [
        "DROP TABLE memory_r10_m2.memory_identity;",
        "TRUNCATE memory_r10_m2.memory_fact_version;",
        "ALTER TABLE memory_r10_m2.memory_identity DROP COLUMN issuer_guid;",
        "ALTER ROLE m2_agent PASSWORD 'x';",
        "SELECT 1;",
    ],
)
def test_anything_unreviewed_refuses_the_whole_plan(smuggled):
    plan = mc.build_plan(PROD_LIKE_STATE, base_sql=BASE_TEXT, v2_sql=V2_TEXT + "\n" + smuggled)
    assert plan.refusals, smuggled
    assert all(not mc._FORBIDDEN_HEAD.match(s.sql) for s in plan.run_steps)


def test_no_credential_in_committed_sql():
    for path in (ROOT / "sql").glob("*.sql"):
        text = path.read_text(encoding="utf-8")
        assert "m2agent" not in text, path.name
    assert "PASSWORD '" not in BASE_TEXT
    # The role is only ever created on an isolated database, from the GUC.
    assert "M2_AGENT_ROLE_MISSING" in BASE_TEXT and "m2.agent_password" in BASE_TEXT


def test_isolated_password_never_reaches_a_production_session():
    from scripts.lib.m2_live_shadow_guard import set_isolated_agent_password

    class Cur:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))

    prod, iso = Cur(), Cur()
    assert set_isolated_agent_password(prod, is_production=True) is False and prod.calls == []
    assert set_isolated_agent_password(iso, is_production=False) is True
    assert iso.calls and "m2.agent_password" in iso.calls[0][0]


def test_receipts_are_pytest_safe(monkeypatch):
    monkeypatch.delenv(mc.RECEIPTS_ENV, raising=False)
    assert mc.receipts_path() is None


# ---------------------------------------------------------------------------
# Database-backed (m2_shadow_test, rebuilt to production's base-only shape)
# ---------------------------------------------------------------------------


def _connect():
    if os.getenv("M2_SKIP_DOCKER") == "1":
        pytest.skip("M2_SKIP_DOCKER=1")
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed (CI installs only pytest+pyyaml)")
    from scripts.lib.m2_live_shadow_guard import SHADOW_ADMIN_DSN, refuse_live_shadow_under_pytest

    dsn = os.environ.get("M2_DSN") or SHADOW_ADMIN_DSN
    try:
        conn = psycopg2.connect(refuse_live_shadow_under_pytest(dsn), connect_timeout=3)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"isolated M2 test database not available: {exc}")
    assert conn.get_dsn_parameters().get("dbname") != "m2_shadow"
    return conn


def _rebuild_base_only(conn) -> None:
    """Production's shape: base tables, no v2 packaging, no uuid-ossp."""
    from scripts.lib.m2_live_shadow_guard import set_isolated_agent_password

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET m2.allow_destructive_reset = 'on'")
        set_isolated_agent_password(cur, is_production=False)
        cur.execute(BASE_TEXT)
        cur.execute("RESET m2.allow_destructive_reset")
        cur.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
    conn.autocommit = False


@pytest.fixture()
def base_only(monkeypatch, tmp_path):
    monkeypatch.setenv(mc.RECEIPTS_ENV, str(tmp_path / "receipts.jsonl"))
    conn = _connect()
    _rebuild_base_only(conn)
    yield conn
    conn.close()


def _db(conn) -> str:
    return conn.get_dsn_parameters()["dbname"]


def _views(conn) -> int:
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'memory_r10_m2' AND c.relkind = 'v'"
        )
        n = cur.fetchone()[0]
    conn.autocommit = False
    return n


def test_dry_run_on_base_only_plans_the_packaging_and_writes_nothing(base_only):
    report = mc.dry_run(base_only)
    assert report["would_apply"] is True
    assert report["post_checks_now"]["healthy"] is False
    assert report["plan"]["run"] > 0 and report["plan"]["refusals"] == []
    assert _views(base_only) == 0


def test_apply_brings_base_only_to_healthy_v2_and_leaves_no_rows(base_only, tmp_path):
    receipt = mc.apply(base_only, confirm=_db(base_only))
    assert receipt["committed"] is True
    assert receipt["post_checks"]["healthy"] is True, receipt["post_checks"]
    assert receipt["smoke"]["ok"] is True, receipt["smoke"]
    assert receipt["smoke"]["row_kinds"] == {"current": 2, "audit": 1}
    assert all(v == 0 for v in receipt["row_counts_after"].values())
    assert (tmp_path / "receipts.jsonl").read_text().count('"committed": true') == 1
    # Idempotent: a second run still commits and adds no trigger/index/table.
    again = mc.apply(base_only, confirm=_db(base_only))
    assert again["committed"] is True
    assert not [e for e in again["executed"] if ":trigger:" in e or ":index:" in e or ":table:" in e]


def test_confirmation_must_name_the_target_database(base_only):
    with pytest.raises(mc.CutoverRefused, match="CONFIRM_MISMATCH"):
        mc.apply(base_only, confirm="trade_ai")
    assert _views(base_only) == 0


def test_existing_memory_rows_refuse_unless_allowed(base_only):
    mc.apply(base_only, confirm=_db(base_only))
    base_only.autocommit = True
    with base_only.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', 't-rows', false)")
        cur.execute(
            "INSERT INTO memory_r10_m2.memory_identity (identity_guid, tenant_id, namespace, identity_kind, "
            "subject_guid, predicate, canonical_key) VALUES (gen_random_uuid(), 't-rows', 'n', 'k', 's', 'p', 'c')"
        )
    base_only.autocommit = False
    with pytest.raises(mc.CutoverRefused, match="SCHEMA_HAS_ROWS"):
        mc.apply(base_only, confirm=_db(base_only))
    assert mc.apply(base_only, confirm=_db(base_only), allow_existing_rows=True)["committed"] is True


def test_a_failed_post_check_rolls_back_every_statement(base_only, monkeypatch):
    monkeypatch.setattr(mc, "post_checks", lambda cur: {"healthy": False, "forced": False})
    with pytest.raises(mc.CutoverRefused, match="POST_CHECK_FAILED"):
        mc.apply(base_only, confirm=_db(base_only))
    assert _views(base_only) == 0
    base_only.autocommit = True
    with base_only.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'uuid-ossp'")
        assert cur.fetchone()[0] == 0
    base_only.autocommit = False
