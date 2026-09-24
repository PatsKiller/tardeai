"""CIO envelope → bitemporal MemoryFactVersion@v2 (cognitive only).

Canonical module. CLI: scripts/cio_memory_integration.py
Isolated DSN :55432 only. Production :5432 refused.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.adjudication_receipt import build_receipt
from scripts.lib.memory_fact import subject_from_security
from scripts.lib.memory_m2_benchmark import (
    DEFAULT_DSN,
    SQL_PATH,
    _assert_isolated_dsn,
    conn_targets_production,
)
from scripts.lib.memory_namespace import DEFAULT_TENANT, require_tenant

AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_V2 = ROOT / "sql" / "trade-ai-bitemporal-schema-v2.sql"

FORBIDDEN_OBJECT_KEYS = frozenset({
    "cash", "cash_usd", "balance", "position", "shares", "qty", "quantity",
    "size_usd", "recommended_delta_usd", "order", "stop", "limit",
    "target_weight_pct", "account_number", "broker_account",
})

SINGLE_VALUED_PREDICATES = frozenset({
    "thesis", "investment_thesis", "strategic_thesis", "operating_principle",
    "executive_priority", "held_view", "advisor_stance",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _refuse_financial_payload(obj: dict[str, Any]) -> None:
    bad = FORBIDDEN_OBJECT_KEYS.intersection(obj.keys())
    if bad:
        raise RuntimeError(f"FINANCIAL_TRUTH_REFUSED: cognitive memory cannot store {sorted(bad)}")


def _assert_isolated_conn(conn) -> None:
    """The docstring below has always claimed 'isolated DSN only', but nothing
    enforced it — the caller just handed in a connection. Since apply opts in to
    a destructive schema reset, verify it here rather than trusting the caller.

    Shares conn_targets_production() with the benchmark module so the two cannot
    drift apart. Both fail closed; the unverifiable case keeps its own message
    because "I could not read the DSN" and "this is production" call for
    different responses when diagnosing a cutover."""
    try:
        conn.get_dsn_parameters()
    except Exception:  # pragma: no cover - psycopg2 always provides this
        raise RuntimeError("M2_DSN_UNVERIFIABLE: refusing destructive apply") from None
    if conn_targets_production(conn):
        raise RuntimeError("M2_DSN_PRODUCTION_PORT_FORBIDDEN")


def apply_bitemporal_schema_v2(conn) -> dict[str, Any]:
    """Apply base M2 SQL then v2 packaging delta. Isolated DSN only (enforced)."""
    _assert_isolated_conn(conn)
    base = SQL_PATH.read_text(encoding="utf-8")
    delta = SCHEMA_V2.read_text(encoding="utf-8")
    # Strip leading comment-only banner from delta for clarity; execute whole file.
    with conn.cursor() as cur:
        # Opt in to the base file's destructive reset — never for production,
        # even once production memory is authorized. Belt and braces with the
        # SQL file's own isolated-database allowlist. The LIVE shadow is refused
        # too unless explicitly opted in: pytest reached this through the
        # m2_conn fixture and dropped live memory on every run (M5 audit 09-23).
        from scripts.lib.m2_live_shadow_guard import destructive_reset_permitted  # noqa: PLC0415

        if destructive_reset_permitted(conn, is_production=conn_targets_production(conn)):
            cur.execute("SET m2.allow_destructive_reset = 'on'")
        cur.execute(base)
        cur.execute(delta)
        # Was hardcoded to m2_shadow, so it silently granted nothing useful on
        # any other database. Grant on whichever database we are actually in.
        from scripts.lib.memory_m2_v2 import _grant_connect_current_db  # noqa: PLC0415

        _grant_connect_current_db(cur)
        cur.execute(
            """
            SELECT
              to_regclass('memory_r10_m2.memory_identity') IS NOT NULL AS identity_ok,
              to_regclass('memory_r10_m2.memory_fact_version') IS NOT NULL AS fact_ok,
              to_regclass('memory_r10_m2.adjudication_receipt') IS NOT NULL AS adj_ok,
              to_regclass('memory_r10_m2.provenance_edge') IS NOT NULL AS prov_ok,
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
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fact_single_valued_current_excl'
              ) AS excl_ok
            """
        )
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


class CIOEnvelopeIntegrator:
    """Wake / thesis envelopes → bitemporal cognitive facts."""

    def __init__(self, *, dsn: str | None = None, tenant_id: str = DEFAULT_TENANT):
        self.dsn = _assert_isolated_dsn(dsn or os.getenv("M2_DSN") or DEFAULT_DSN)
        self.tenant_id = require_tenant(tenant_id)
        self._conn = None

    def connect(self):
        import psycopg2

        if self._conn is None or self._conn.closed:
            from scripts.lib.m2_live_shadow_guard import refuse_live_shadow_under_pytest  # noqa: PLC0415

            self._conn = psycopg2.connect(refuse_live_shadow_under_pytest(self.dsn))
            self._conn.autocommit = True
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def _set_tenant(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (self.tenant_id,))

    def _resolve_subject(self, envelope: dict[str, Any]) -> dict[str, str | None]:
        symbol = envelope.get("symbol") or envelope.get("ticker")
        subject_key = envelope.get("subject_key") or ""
        if isinstance(subject_key, str) and ":" in subject_key:
            symbol = symbol or subject_key.split(":", 1)[-1]
        ids = subject_from_security(symbol=str(symbol) if symbol else None)
        if envelope.get("subject_guid"):
            ids["subject_guid"] = str(envelope["subject_guid"])
        if not ids.get("subject_guid"):
            sk = subject_key or envelope.get("topic") or "unknown"
            ids["subject_guid"] = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:cognitive:{self.tenant_id}:{sk}")
            )
        return ids

    def _scan_conflicts(
        self,
        conn,
        *,
        identity_guid: str,
        predicate: str,
        valid_period: str,
    ) -> list[str]:
        if predicate not in SINGLE_VALUED_PREDICATES:
            return []
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT memory_version_id::text
                  FROM memory_r10_m2.memory_fact_version
                 WHERE tenant_id = %s
                   AND identity_guid = %s::uuid
                   AND predicate = %s
                   AND upper_inf(tx_period)
                   AND temporal_policy = 'SINGLE_VALUED_CURRENT'
                   AND valid_period && %s::tstzrange
                """,
                (self.tenant_id, identity_guid, predicate, valid_period),
            )
            return [r[0] for r in cur.fetchall()]

    def integrate_envelope(
        self,
        envelope: dict[str, Any],
        *,
        apply: bool = False,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        if apply:
            dry_run = False
        if dry_run and not apply:
            apply = False

        obj = dict(envelope.get("object") or envelope.get("payload") or {})
        for k in list(obj.keys()):
            if k in FORBIDDEN_OBJECT_KEYS:
                raise RuntimeError(f"FINANCIAL_TRUTH_REFUSED: key={k}")
        _refuse_financial_payload(obj)

        predicate = str(envelope.get("predicate") or "thesis")
        claim = str(
            envelope.get("claim")
            or envelope.get("summary")
            or obj.get("text")
            or obj.get("thesis")
            or ""
        )
        if not claim and not obj:
            obj = {"note": "empty_envelope", "wake_id": envelope.get("wake_job_id")}
        if claim and "text" not in obj:
            obj["text"] = claim

        ids = self._resolve_subject(envelope)
        subject_guid = str(ids["subject_guid"])
        temporal_policy = (
            "SINGLE_VALUED_CURRENT"
            if predicate in SINGLE_VALUED_PREDICATES
            else "MULTI_VALUED"
        )
        valid_from = str(envelope.get("valid_from") or _now_iso())
        valid_to = envelope.get("valid_to")
        valid_period = f"[{valid_from},{valid_to if valid_to else ''})"

        receipt: dict[str, Any] = {
            "schema": "CIOEnvelopeIntegration@v1",
            "authority": AUTHORITY,
            "mbi_behavior": MBI_BEHAVIOR,
            "financial_action": False,
            "dry_run": not apply,
            "tenant_id": self.tenant_id,
            "subject_guid": subject_guid,
            "issuer_guid": ids.get("issuer_guid"),
            "security_guid": ids.get("security_guid"),
            "listing_guid": ids.get("listing_guid"),
            "predicate": predicate,
            "temporal_policy": temporal_policy,
            "valid_period": valid_period,
            "writer": "save_bitemporal_fact_version",
            "adjudication": None,
            "memory_version_id": None,
            "suppressed": False,
        }

        if not apply:
            receipt["would_write"] = {
                "object_keys": sorted(obj.keys()),
                "claim_fp": hashlib.sha256(claim.encode()).hexdigest()[:16],
            }
            return receipt

        conn = self.connect()
        self._set_tenant(conn)
        ident = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"m2:{self.tenant_id}:{subject_guid}:{predicate}",
            )
        )
        key = f"{subject_guid}|{predicate}"
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_r10_m2.memory_identity
                  (identity_guid, tenant_id, namespace, identity_kind, subject_guid,
                   predicate, canonical_key, issuer_guid, security_guid, listing_guid)
                VALUES (%s,%s,'COGNITIVE',%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, canonical_key) DO NOTHING
                """,
                (
                    ident,
                    self.tenant_id,
                    "security" if ids.get("security_guid") else "cognitive",
                    subject_guid,
                    predicate,
                    key,
                    ids.get("issuer_guid"),
                    ids.get("security_guid"),
                    ids.get("listing_guid"),
                ),
            )
            cur.execute(
                """
                SELECT identity_guid FROM memory_r10_m2.memory_identity
                 WHERE tenant_id=%s AND canonical_key=%s
                """,
                (self.tenant_id, key),
            )
            row = cur.fetchone()
            identity_guid = str(row[0] if row else ident)

        conflicts = self._scan_conflicts(
            conn,
            identity_guid=identity_guid,
            predicate=predicate,
            valid_period=valid_period,
        )
        if conflicts and temporal_policy == "SINGLE_VALUED_CURRENT":
            adj = build_receipt(
                tenant_id=self.tenant_id,
                subject_guid=subject_guid,
                predicate=predicate,
                candidate_fact_ids=conflicts + ["pending_new"],
                selected_fact_id=conflicts[0],
                rejected_fact_ids=["pending_new"],
                policy="exclusive_current_short_circuit",
                conflict_id=f"overlap:{identity_guid}:{predicate}",
                evidence_refs=conflicts,
                trace_id=str(envelope.get("wake_job_id") or envelope.get("trace_id") or ""),
            )
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_r10_m2.adjudication_receipt (
                      adjudication_id, tenant_id, subject_guid, predicate, conflict_id,
                      candidate_fact_ids, selected_fact_id, rejected_fact_ids,
                      deterministic_policy, policy_version, evidence_refs, trace_id,
                      chain_of_thought
                    ) VALUES (
                      %s::uuid,%s,%s,%s,%s,%s::uuid[],%s::uuid,%s::uuid[],%s,%s,%s,%s,false
                    )
                    """,
                    (
                        adj["adjudication_id"],
                        self.tenant_id,
                        subject_guid,
                        predicate,
                        adj["conflict_id"],
                        conflicts,
                        conflicts[0],
                        [],
                        adj["policy"],
                        adj["policy_version"],
                        conflicts,
                        adj.get("trace_id"),
                    ),
                )
            receipt["adjudication"] = adj
            receipt["suppressed"] = True
            receipt["reason"] = "SINGLE_VALUED_OVERLAP_ADJUDICATED"
            return receipt

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT memory_r10_m2.save_bitemporal_fact_version(
                    %s, %s::uuid, %s, %s, %s::jsonb, %s::tstzrange, %s, %s,
                    'cio_envelope', %s, %s, NULL::vector
                )
                """,
                (
                    self.tenant_id,
                    identity_guid,
                    subject_guid,
                    predicate,
                    json.dumps(obj),
                    valid_period,
                    str(envelope.get("status") or "CANDIDATE"),
                    temporal_policy,
                    str(envelope.get("wake_job_id") or envelope.get("source_id") or "wake"),
                    (claim or str(obj))[:240],
                ),
            )
            receipt["memory_version_id"] = str(cur.fetchone()[0])
        return receipt


def integrate_wake_envelope(envelope: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
    integ = CIOEnvelopeIntegrator()
    try:
        return integ.integrate_envelope(envelope, apply=apply, dry_run=not apply)
    finally:
        integ.close()
