"""Idempotent heal for bitemporal v2 *packaging* on isolated M2 only.

After a destructive ``r10_m2_isolated_benchmark.sql`` rebuild, base tables may
exist while ``trade-ai-bitemporal-schema-v2.sql`` aliases/views/triggers are
gone. This module re-applies **only** the v2 packaging delta — never a full
CASCADE reset, never production ``:5432``.

Used by ``scripts/init_bitemporal_db.sh``, ``memory_m2_*.apply_schema``, and
correctness tests after opt-in r10 rebuilds.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.lib.memory_m2_benchmark import (
    DEFAULT_DSN,
    _assert_isolated_dsn,
    conn_targets_production,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_V2 = ROOT / "sql" / "trade-ai-bitemporal-schema-v2.sql"

_HEALTH_SQL = """
SELECT
  to_regclass('memory_r10_m2.memory_identity') IS NOT NULL AS identity_ok,
  to_regclass('memory_r10_m2.memory_fact_version') IS NOT NULL AS fact_ok,
  to_regclass('memory_r10_m2.adjudication_receipt') IS NOT NULL AS adj_ok,
  to_regclass('memory_r10_m2.provenance_edge') IS NOT NULL AS prov_ok,
  EXISTS (
    SELECT 1 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'memory_r10_m2'
      AND c.relkind = 'v'
      AND c.relname = 'MemoryFactVersion@v2'
  ) AS view_fact_ok,
  EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'memory_r10_m2'
      AND p.proname = 'save_bitemporal_fact_version'
  ) AS save_fn_ok,
  EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'memory_r10_m2'
      AND p.proname = 'block_bitemporal_manipulation'
  ) AS block_fn_ok,
  EXISTS (
    SELECT 1 FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'memory_r10_m2'
      AND c.relname = 'memory_fact_version'
      AND t.tgname = 'trg_block_fact_manipulation'
      AND NOT t.tgisinternal
  ) AS block_trg_ok,
  EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fact_single_valued_current_excl'
  ) AS excl_ok,
  EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'memory_r10_m2'
      AND p.proname = 'supersede_single_valued_fact'
  ) AS supersede_fn_ok,
  EXISTS (
    SELECT 1 FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'memory_r10_m2'
      AND c.relname = 'MemoryFactVersion@v2'
      AND a.attname = 'row_kind'
      AND NOT a.attisdropped
  ) AS view_row_kind_ok
"""


#: Public name for the packaging health query. The production cutover
#: (scripts/lib/memory_prod_cutover.py) asserts the same signals before commit,
#: so the heal and the cutover cannot drift apart on what "healthy" means.
PACKAGING_HEALTH_SQL = _HEALTH_SQL


def _assert_isolated_conn(conn) -> None:
    try:
        conn.get_dsn_parameters()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("M2_DSN_UNVERIFIABLE: refusing schema heal") from exc
    if conn_targets_production(conn):
        raise RuntimeError("M2_DSN_PRODUCTION_PORT_FORBIDDEN")


def check_bitemporal_packaging_health(conn) -> dict[str, Any]:
    """Return per-signal health for v2 packaging (views/fns/trigger/excl)."""
    _assert_isolated_conn(conn)
    with conn.cursor() as cur:
        cur.execute(_HEALTH_SQL)
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    out = dict(zip(cols, row, strict=True))
    out["healthy"] = all(bool(out[k]) for k in out)
    out["schema_v2_path"] = str(SCHEMA_V2)
    return out


def ensure_bitemporal_packaging_v2(conn) -> dict[str, Any]:
    """If packaging is incomplete, apply ``trade-ai-bitemporal-schema-v2.sql`` only.

    Idempotent: healthy → no DDL. Does **not** run r10 (no CASCADE).
    """
    _assert_isolated_conn(conn)
    if not SCHEMA_V2.is_file():
        raise FileNotFoundError(f"SCHEMA_V2_MISSING: {SCHEMA_V2}")
    before = check_bitemporal_packaging_health(conn)
    if before["healthy"]:
        return {
            "action": "skip",
            "reason": "HEALTHY",
            "before": before,
            "after": before,
        }
    delta = SCHEMA_V2.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(delta)
    after = check_bitemporal_packaging_health(conn)
    if not after["healthy"]:
        raise RuntimeError(f"BITEMPORAL_PACKAGING_HEAL_FAILED: {after}")
    return {
        "action": "applied",
        "reason": "MISSING_OR_STRIPPED",
        "before": before,
        "after": after,
    }


def resolve_isolated_dsn(explicit: str | None = None) -> str:
    """Default isolated DSN; refuse production port in the string form."""
    import os

    dsn = explicit or os.getenv("M2_DSN") or os.getenv("TEST_DB_DSN") or DEFAULT_DSN
    return _assert_isolated_dsn(dsn)
