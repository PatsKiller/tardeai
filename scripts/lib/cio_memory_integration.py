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


SUPERSEDE_POLICY = "latest_assertion_supersedes_overlap"
SUPERSEDE_POLICY_VERSION = "v2"


def _source_sha() -> str | None:
    """Code SHA of the running release (SOURCE_COMMIT/BUILD_SHA), when stamped."""
    for name in ("SOURCE_COMMIT", "BUILD_SHA"):
        p = ROOT / name
        if p.is_file():
            parts = p.read_text(encoding="utf-8").strip().split()
            if parts:
                return parts[0]
    return None


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
        from scripts.lib.m2_live_shadow_guard import (  # noqa: PLC0415
            destructive_reset_permitted,
            set_isolated_agent_password,
        )

        if destructive_reset_permitted(conn, is_production=conn_targets_production(conn)):
            cur.execute("SET m2.allow_destructive_reset = 'on'")
        set_isolated_agent_password(cur, is_production=conn_targets_production(conn))
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
            self._heal_packaging(self._conn)
        return self._conn

    @staticmethod
    def _heal_packaging(conn) -> None:
        """Bring v2 packaging (incl. supersede_single_valued_fact) up to date.

        Additive and idempotent; refused for production, where the cutover is
        an operator step and a missing writer must surface as an error."""
        if conn_targets_production(conn):
            return
        from scripts.lib.bitemporal_schema_heal import ensure_bitemporal_packaging_v2  # noqa: PLC0415

        ensure_bitemporal_packaging_v2(conn)

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def _set_tenant(self, conn, *, local: bool = False) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, %s)", (self.tenant_id, local))

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
        obj: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """CURRENT single-valued versions overlapping ``valid_period``, oldest first.

        Each row says whether it already asserts ``obj`` over the whole of
        ``valid_period`` (``same_and_covers``) — a re-assertion, not a change.

        No ``FOR UPDATE``: that needs UPDATE privilege, and the production writer
        role (m2_agent) has SELECT only on memory_fact_version by design — every
        write goes through the SECURITY DEFINER functions. The 2026-09-24 16:00
        production cycle failed on exactly that (InsufficientPrivilege).
        Concurrent writers for the same (tenant, identity, predicate) are
        serialized instead by ``_lock_identity_predicate`` (a transaction-scoped
        advisory lock taken before this read)."""
        if predicate not in SINGLE_VALUED_PREDICATES:
            return []
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT memory_version_id::text,
                       (object_value = %s::jsonb AND valid_period @> %s::tstzrange) AS same_and_covers
                  FROM memory_r10_m2.memory_fact_version
                 WHERE tenant_id = %s
                   AND identity_guid = %s::uuid
                   AND predicate = %s
                   AND upper_inf(tx_period)
                   AND temporal_policy = 'SINGLE_VALUED_CURRENT'
                   AND valid_period && %s::tstzrange
                 ORDER BY version_seq
                """,
                (json.dumps(obj or {}), valid_period, self.tenant_id, identity_guid, predicate, valid_period),
            )
            return [{"memory_version_id": r[0], "same_and_covers": bool(r[1])} for r in cur.fetchall()]

    def _lock_identity_predicate(self, conn, *, subject_guid: str, predicate: str) -> None:
        """Serialize writers for one (tenant, subject, predicate) until commit.

        ``pg_advisory_xact_lock`` needs no table privilege and releases at the
        end of the transaction, so it replaces the old ``SELECT … FOR UPDATE``
        row lock without widening m2_agent's grants. The key is the same
        canonical key the identity row uses, so every path that writes this
        belief takes the same lock."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"m2:{self.tenant_id}:{subject_guid}|{predicate}",),
            )

    def _insert_adjudication(self, conn, adj: dict[str, Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_r10_m2.adjudication_receipt (
                  adjudication_id, tenant_id, subject_guid, predicate, conflict_id,
                  candidate_fact_ids, selected_fact_id, rejected_fact_ids,
                  deterministic_policy, policy_version, provider, model, prompt_version,
                  evidence_refs, trace_id, source_sha, chain_of_thought
                ) VALUES (
                  %s::uuid,%s,%s,%s,%s,%s::uuid[],%s::uuid,%s::uuid[],%s,%s,%s,%s,%s,%s,%s,%s,false
                )
                """,
                (
                    adj["adjudication_id"],
                    adj["tenant_id"],
                    adj["subject_guid"],
                    adj["predicate"],
                    adj["conflict_id"],
                    adj["candidate_fact_ids"],
                    adj["selected_fact_id"],
                    adj["rejected_fact_ids"],
                    adj["policy"],
                    adj["policy_version"],
                    adj.get("provider"),
                    adj.get("model"),
                    adj.get("prompt_version"),
                    adj["evidence_refs"],
                    adj.get("trace_id"),
                    adj.get("source_sha"),
                ),
            )

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
        # One transaction: identity, adjudication receipt and fact version land
        # together or not at all, and the receipt is written BEFORE the memory
        # state it decides (M5 Module 2.2). The connection is autocommit for
        # everything else; switch it off only for this unit of work.
        conn.autocommit = False
        try:
            receipt = self._apply_in_transaction(
                conn, envelope, receipt, obj=obj, claim=claim, subject_guid=subject_guid,
                ids=ids, predicate=predicate, temporal_policy=temporal_policy, valid_period=valid_period,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = True
        return receipt

    def _apply_in_transaction(
        self,
        conn,
        envelope: dict[str, Any],
        receipt: dict[str, Any],
        *,
        obj: dict[str, Any],
        claim: str,
        subject_guid: str,
        ids: dict[str, str | None],
        predicate: str,
        temporal_policy: str,
        valid_period: str,
    ) -> dict[str, Any]:
        self._set_tenant(conn, local=True)
        self._lock_identity_predicate(conn, subject_guid=subject_guid, predicate=predicate)
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

        status = str(envelope.get("status") or "CANDIDATE")
        source_id = str(envelope.get("wake_job_id") or envelope.get("source_id") or "wake")
        summary = (claim or str(obj))[:240]
        trace_id = str(envelope.get("wake_job_id") or envelope.get("trace_id") or "")

        if temporal_policy != "SINGLE_VALUED_CURRENT":
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT memory_r10_m2.save_bitemporal_fact_version(
                        %s, %s::uuid, %s, %s, %s::jsonb, %s::tstzrange, %s, %s,
                        'cio_envelope', %s, %s, NULL::vector
                    )
                    """,
                    (
                        self.tenant_id, identity_guid, subject_guid, predicate, json.dumps(obj),
                        valid_period, status, temporal_policy, source_id, summary,
                    ),
                )
                receipt["memory_version_id"] = str(cur.fetchone()[0])
            return receipt

        conflicts = self._scan_conflicts(
            conn,
            identity_guid=identity_guid,
            predicate=predicate,
            valid_period=valid_period,
            obj=obj,
        )
        same = next((c for c in conflicts if c["same_and_covers"]), None)
        if same is not None:
            # The current belief already says exactly this for the whole period.
            # Nothing to adjudicate and no new version (the hourly cycle would
            # otherwise mint an identical version every run).
            receipt["memory_version_id"] = same["memory_version_id"]
            receipt["reason"] = "IDENTICAL_REASSERTION_NOOP"
            return receipt

        prior_ids = [c["memory_version_id"] for c in conflicts]
        new_id = str(uuid.uuid4())
        if prior_ids:
            # Deterministic, no LLM: the newer assertion wins for the overlap and
            # the priors keep their non-overlapping valid time as current
            # remnants. provider/model/prompt_version stay null because nothing
            # non-deterministic decided this.
            adj = build_receipt(
                tenant_id=self.tenant_id,
                subject_guid=subject_guid,
                predicate=predicate,
                candidate_fact_ids=prior_ids + [new_id],
                selected_fact_id=new_id,
                rejected_fact_ids=prior_ids,
                policy=SUPERSEDE_POLICY,
                policy_version=SUPERSEDE_POLICY_VERSION,
                conflict_id=f"overlap:{identity_guid}:{predicate}",
                evidence_refs=prior_ids,
                trace_id=trace_id,
                source_sha=_source_sha(),
            )
            self._insert_adjudication(conn, adj)
            receipt["adjudication"] = adj
            receipt["superseded"] = prior_ids
            receipt["reason"] = "SINGLE_VALUED_SUPERSEDED"
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT memory_r10_m2.supersede_single_valued_fact(
                    %s, %s::uuid, %s, %s, %s::jsonb, %s::tstzrange, %s,
                    'cio_envelope', %s, %s, %s::uuid
                )
                """,
                (
                    self.tenant_id, identity_guid, subject_guid, predicate, json.dumps(obj),
                    valid_period, status, source_id, summary, new_id,
                ),
            )
            receipt["memory_version_id"] = str(cur.fetchone()[0])
        receipt["writer"] = "supersede_single_valued_fact"
        return receipt


def integrate_wake_envelope(envelope: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
    integ = CIOEnvelopeIntegrator()
    try:
        return integ.integrate_envelope(envelope, apply=apply, dry_run=not apply)
    finally:
        integ.close()
