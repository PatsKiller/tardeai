"""redeploy_plan_db — persist Phase B institutional plans + legs (advisory only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION_A = PROJECT_ROOT / "migrations" / "2026_07_15_redeploy_phase_a_data_truth.sql"
MIGRATION_B = PROJECT_ROOT / "migrations" / "2026_07_16_redeploy_phase_b_plans.sql"


def ensure_plan_tables(cur) -> None:
    if MIGRATION_A.is_file():
        cur.execute(MIGRATION_A.read_text())
    if MIGRATION_B.is_file():
        cur.execute(MIGRATION_B.read_text())


def _next_plan_version(cur, deploy_event_id: int) -> int:
    cur.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM deploy_plans WHERE deploy_event_id=%s",
        (deploy_event_id,),
    )
    return int(cur.fetchone()[0])


def persist_institutional_plans(cur, event_id: int, event: dict[str, Any]) -> dict[str, Any]:
    ensure_plan_tables(cur)
    bundle = (event.get("metadata") or {}).get("phase_b") or {}
    plans = bundle.get("plans") or []
    if not plans:
        return {"ok": True, "persisted": 0}

    version = _next_plan_version(cur, event_id)
    input_hash = bundle.get("input_hash")
    policy_version = bundle.get("policy_version")
    generator_version = bundle.get("generator_version")
    persisted_ids: list[int] = []

    for plan in plans:
        cur.execute(
            """INSERT INTO deploy_plans
               (deploy_event_id, version, plan_archetype, plan_type, tags, objective,
                total_deployable_usd, reserve_usd, deploy_pct_of_net, confidence,
                evidence_factor_count, operator_status, oversight_status, composite_rank,
                rejected_alternatives, unmet_exposure, advantages, compromises, risks,
                hermes_narrative, scenarios, policy_version, generator_version, input_hash,
                redeploy_plan, impact, status, advice)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
               RETURNING id""",
            (
                event_id,
                version,
                plan.get("plan_archetype"),
                plan.get("plan_type"),
                plan.get("tags") or [],
                plan.get("objective"),
                plan.get("total_deployable_usd"),
                plan.get("reserve_usd"),
                plan.get("deploy_pct_of_net"),
                plan.get("confidence"),
                plan.get("evidence_factor_count"),
                plan.get("operator_status") or "draft",
                plan.get("oversight_status") or "pending",
                plan.get("composite_rank"),
                json.dumps(bundle.get("rejected_alternatives") or []),
                json.dumps(plan.get("unmet_exposure") or {}),
                plan.get("advantages") or [],
                plan.get("compromises") or [],
                plan.get("risks") or [],
                plan.get("hermes_narrative"),
                json.dumps(plan.get("scenarios") or {}),
                policy_version,
                generator_version,
                input_hash,
                json.dumps(plan.get("legs") or []),
                json.dumps({"net_proceeds_usd": plan.get("net_proceeds_usd")}),
                plan.get("operator_status") or "draft",
                plan.get("objective"),
            ),
        )
        plan_id = cur.fetchone()[0]
        persisted_ids.append(plan_id)
        for idx, leg in enumerate(plan.get("legs") or []):
            cur.execute(
                """INSERT INTO redeploy_plan_legs
                   (deploy_plan_id, leg_index, ticker, security_name, account,
                    allocation_pct_of_net, target_dollars, target_shares, is_reserve, is_actionable,
                    current_price, price_as_of, price_stale, preferred_entry, entry_range_low,
                    entry_range_high, do_not_chase, stage_1_pct, stage_1_price, stage_1_shares,
                    stage_1_dollars, stage_2_pct, stage_2_price, stage_2_shares, stage_2_dollars,
                    stage_3_pct, stage_3_price, stage_3_shares, stage_3_dollars,
                    expected_yield_pct, thesis, invalidation, overlap_note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    plan_id, idx,
                    leg.get("ticker"),
                    leg.get("security_name"),
                    leg.get("account"),
                    leg.get("allocation_pct_of_net"),
                    leg.get("target_dollars"),
                    leg.get("target_shares"),
                    bool(leg.get("is_reserve")),
                    bool(leg.get("is_actionable", True)),
                    leg.get("current_price"),
                    leg.get("price_as_of"),
                    bool(leg.get("price_stale")),
                    leg.get("preferred_entry"),
                    leg.get("entry_range_low"),
                    leg.get("entry_range_high"),
                    leg.get("do_not_chase"),
                    leg.get("stage_1_pct"),
                    leg.get("stage_1_price"),
                    leg.get("stage_1_shares"),
                    leg.get("stage_1_dollars"),
                    leg.get("stage_2_pct"),
                    leg.get("stage_2_price"),
                    leg.get("stage_2_shares"),
                    leg.get("stage_2_dollars"),
                    leg.get("stage_3_pct"),
                    leg.get("stage_3_price"),
                    leg.get("stage_3_shares"),
                    leg.get("stage_3_dollars"),
                    leg.get("expected_yield_pct"),
                    leg.get("thesis"),
                    leg.get("invalidation"),
                    leg.get("overlap_note"),
                ),
            )

    meta = dict(event.get("metadata") or {})
    meta["phase_b_persisted_version"] = version
    meta["phase_b_plan_ids"] = persisted_ids
    cur.execute(
        "UPDATE deploy_events SET metadata=%s::jsonb, updated_at=NOW() WHERE id=%s",
        (json.dumps(meta), event_id),
    )
    return {"ok": True, "version": version, "persisted": len(persisted_ids), "plan_ids": persisted_ids}


def list_plans_for_event(cur, event_id: int, *, version: int | None = None) -> list[dict[str, Any]]:
    ensure_plan_tables(cur)
    if version is not None:
        cur.execute(
            """SELECT id, version, plan_archetype, plan_type, tags, objective,
                      total_deployable_usd, reserve_usd, deploy_pct_of_net, confidence,
                      operator_status, oversight_status, composite_rank, advantages, compromises,
                      risks, hermes_narrative, unmet_exposure, rejected_alternatives, scenarios,
                      redeploy_plan
               FROM deploy_plans WHERE deploy_event_id=%s AND version=%s
               ORDER BY composite_rank DESC""",
            (event_id, version),
        )
    else:
        cur.execute(
            """SELECT id, version, plan_archetype, plan_type, tags, objective,
                      total_deployable_usd, reserve_usd, deploy_pct_of_net, confidence,
                      operator_status, oversight_status, composite_rank, advantages, compromises,
                      risks, hermes_narrative, unmet_exposure, rejected_alternatives, scenarios,
                      redeploy_plan
               FROM deploy_plans WHERE deploy_event_id=%s
               AND version = (SELECT MAX(version) FROM deploy_plans WHERE deploy_event_id=%s)
               ORDER BY composite_rank DESC""",
            (event_id, event_id),
        )
    cols = [d[0] for d in cur.description]
    plans = []
    for row in cur.fetchall():
        p = dict(zip(cols, row))
        for jf in ("unmet_exposure", "rejected_alternatives", "scenarios", "redeploy_plan"):
            if isinstance(p.get(jf), str):
                try:
                    p[jf] = json.loads(p[jf])
                except Exception:
                    pass
        legs = p.pop("redeploy_plan", None) or []
        if isinstance(legs, list) and legs:
            p["legs"] = legs
        else:
            cur.execute(
                """SELECT leg_index, ticker, account, target_dollars, target_shares, is_reserve,
                          is_actionable, current_price, price_as_of, price_stale, preferred_entry,
                          entry_range_low, entry_range_high, do_not_chase,
                          stage_1_pct, stage_1_price, stage_1_shares, stage_1_dollars,
                          stage_2_pct, stage_2_price, stage_2_shares, stage_2_dollars,
                          stage_3_pct, stage_3_price, stage_3_shares, stage_3_dollars,
                          thesis, invalidation
                   FROM redeploy_plan_legs WHERE deploy_plan_id=%s ORDER BY leg_index""",
                (p["id"],),
            )
            lcols = [d[0] for d in cur.description]
            p["legs"] = [dict(zip(lcols, r)) for r in cur.fetchall()]
        plans.append(p)
    return plans


def fetch_deploy_event(cur, event_id: int) -> dict[str, Any] | None:
    cur.execute(
        """SELECT id, event_key, symbol, account, proceeds_usd, cash_visible_usd,
                  proxy_symbol, instrument_type, metadata
           FROM deploy_events WHERE id=%s""",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    ev = dict(zip(cols, row))
    if isinstance(ev.get("metadata"), str):
        try:
            ev["metadata"] = json.loads(ev["metadata"])
        except Exception:
            ev["metadata"] = {}
    return ev


def fetch_institutional_plan(
    cur,
    event_id: int,
    *,
    plan_id: int | None = None,
    archetype: str | None = None,
    version: int | None = None,
) -> dict[str, Any] | None:
    ensure_plan_tables(cur)
    if plan_id:
        cur.execute(
            """SELECT id, deploy_event_id, version, plan_archetype, plan_type, objective,
                      operator_status, oversight_status, redeploy_plan
               FROM deploy_plans WHERE id=%s AND deploy_event_id=%s""",
            (plan_id, event_id),
        )
    else:
        arch = (archetype or "F").upper()[:1]
        if version is not None:
            cur.execute(
                """SELECT id, deploy_event_id, version, plan_archetype, plan_type, objective,
                          operator_status, oversight_status, redeploy_plan
                   FROM deploy_plans
                   WHERE deploy_event_id=%s AND version=%s AND plan_archetype=%s""",
                (event_id, version, arch),
            )
        else:
            cur.execute(
                """SELECT id, deploy_event_id, version, plan_archetype, plan_type, objective,
                          operator_status, oversight_status, redeploy_plan
                   FROM deploy_plans
                   WHERE deploy_event_id=%s AND plan_archetype=%s
                   AND version = (SELECT MAX(version) FROM deploy_plans WHERE deploy_event_id=%s)
                   LIMIT 1""",
                (event_id, arch, event_id),
            )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    plan = dict(zip(cols, row))
    legs = plan.pop("redeploy_plan", None)
    if isinstance(legs, str):
        try:
            legs = json.loads(legs)
        except Exception:
            legs = []
    plan["legs"] = legs or []
    return plan


def get_plan_by_id(cur, plan_id: int) -> dict[str, Any] | None:
    ensure_plan_tables(cur)
    cur.execute(
        """SELECT id, deploy_event_id, version, plan_archetype, plan_type, tags, objective,
                  total_deployable_usd, reserve_usd, deploy_pct_of_net, confidence,
                  evidence_factor_count, operator_status, oversight_status, composite_rank,
                  advantages, compromises, risks, hermes_narrative, unmet_exposure,
                  scenarios, locked_at, locked_by, redeploy_plan
           FROM deploy_plans WHERE id=%s""",
        (plan_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    plan = dict(zip(cols, row))
    for jf in ("unmet_exposure", "scenarios"):
        if isinstance(plan.get(jf), str):
            try:
                plan[jf] = json.loads(plan[jf])
            except Exception:
                pass
    legs = plan.pop("redeploy_plan", None)
    if isinstance(legs, str):
        try:
            legs = json.loads(legs)
        except Exception:
            legs = []
    plan["legs"] = legs or []
    return plan


def event_lock_state(cur, event_id: int) -> dict[str, Any]:
    cur.execute(
        """SELECT plan_locked_at, locked_plan_id, locked_plan_version, operator_status
           FROM deploy_events WHERE id=%s""",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        return {}
    return {
        "plan_locked_at": str(row[0])[:19] if row[0] else None,
        "locked_plan_id": row[1],
        "locked_plan_version": row[2],
        "operator_status": row[3],
    }