"""redeploy_oversight — PR-4 plan lock, multi-LLM oversight, analysis (advisory only)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from lib.entry_planner_adapter import assess_export_readiness
from lib.redeploy_data_truth import (
    OPERATOR_READY_MIN_CONFIDENCE,
    OPERATOR_READY_MIN_EVIDENCE_FACTORS,
    POLICY_VERSION,
    _as_float,
)
from lib.redeploy_monitor import ensure_monitor_tables, get_monitoring_state
from lib.redeploy_plan_db import ensure_plan_tables, fetch_institutional_plan, get_plan_by_id

MIGRATION_LOCK = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "migrations" / "2026_07_18_redeploy_oversight_lock.sql"
GENERATOR_VERSION = "oversight_1.0.0"


def ensure_oversight_schema(cur) -> None:
    ensure_plan_tables(cur)
    ensure_monitor_tables(cur)
    if MIGRATION_LOCK.is_file():
        cur.execute(MIGRATION_LOCK.read_text())


def _audit(cur, event_id: int, action: str, payload: dict, *, idempotency_key: str | None = None) -> None:
    ensure_monitor_tables(cur)
    cur.execute(
        """INSERT INTO redeploy_monitor_audit (deploy_event_id, action, idempotency_key, payload)
           VALUES (%s, %s, %s, %s::jsonb)
           ON CONFLICT (action, idempotency_key) DO NOTHING""",
        (event_id, action, idempotency_key, json.dumps(payload, default=str)),
    )


def build_analysis_payload(event: dict[str, Any], *, monitoring: dict | None = None) -> dict[str, Any]:
    meta = event.get("metadata") or {}
    pa = meta.get("phase_a") or {}
    pb = meta.get("phase_b") or {}
    recon = pa.get("reconciliation") or {}
    exposure = pa.get("exposure_loss") or {}
    ctx = pa.get("portfolio_context") or {}
    plans = pb.get("plans") or []
    primary = pb.get("primary_archetype")
    primary_plan = next((p for p in plans if p.get("plan_archetype") == primary), plans[0] if plans else None)

    before = {
        "sold_symbol": event.get("symbol"),
        "account": event.get("account"),
        "net_proceeds_usd": recon.get("net_proceeds_usd") or event.get("proceeds_usd"),
        "exposure_sectors": exposure.get("sectors") or [],
        "income_status": exposure.get("income_status"),
        "is_major_sale": ctx.get("is_major_sale"),
    }
    after = {
        "deployable_cash_usd": recon.get("deployable_cash_usd"),
        "reconciliation_status": recon.get("reconciliation_status"),
        "primary_plan": {
            "archetype": primary_plan.get("plan_archetype") if primary_plan else None,
            "deploy_pct": primary_plan.get("deploy_pct_of_net") if primary_plan else None,
            "reserve_usd": primary_plan.get("reserve_usd") if primary_plan else None,
        } if primary_plan else None,
        "restoration_pct": (monitoring or {}).get("restoration_metrics", {}).get("restoration_pct"),
        "fills_recorded": (monitoring or {}).get("fill_summary", {}).get("fill_count", 0),
    }
    return {
        "advisory_only": True,
        "event_id": event.get("id"),
        "before": before,
        "after": after,
        "portfolio_context": ctx,
        "exposure_loss": exposure,
        "reconciliation": recon,
        "plan_count": len(plans),
        "export_readiness": (meta.get("phase_c") or {}).get("export_readiness"),
        "monitoring": monitoring,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_event_analysis(cur, event_id: int) -> dict[str, Any]:
    ensure_oversight_schema(cur)
    cur.execute(
        """SELECT id, event_key, symbol, account, sold_at, proceeds_usd, status, metadata,
                  plan_locked_at, locked_plan_id, locked_plan_version, operator_status,
                  reconciliation_status
           FROM deploy_events WHERE id=%s""",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "event_not_found"}
    cols = [d[0] for d in cur.description]
    event = dict(zip(cols, row))
    meta = event.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    event["metadata"] = meta
    monitoring = get_monitoring_state(cur, event_id)
    analysis = build_analysis_payload(event, monitoring=monitoring if monitoring.get("ok") else None)
    analysis["ok"] = True
    analysis["lock"] = {
        "plan_locked_at": str(event.get("plan_locked_at") or "")[:19] or None,
        "locked_plan_id": event.get("locked_plan_id"),
        "locked_plan_version": event.get("locked_plan_version"),
        "operator_status": event.get("operator_status"),
    }
    return analysis


def lock_deploy_plan(cur, event_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Lock operator-selected plan version — optimistic concurrency via expected_version."""
    ensure_oversight_schema(cur)
    plan_id = body.get("plan_id")
    archetype = str(body.get("plan_archetype") or body.get("archetype") or "").upper()[:1]
    expected_version = body.get("expected_version")
    locked_by = str(body.get("locked_by") or "operator")[:64]
    idem = str(body.get("idempotency_key") or f"lock:{event_id}:{plan_id or archetype}:{expected_version or ''}")[:120]

    cur.execute("SELECT plan_locked_at, locked_plan_id FROM deploy_events WHERE id=%s", (event_id,))
    ev = cur.fetchone()
    if not ev:
        return {"ok": False, "error": "event_not_found"}
    if ev[0]:
        return {"ok": False, "error": "already_locked", "locked_plan_id": ev[1]}

    if plan_id:
        cur.execute(
            """SELECT id, deploy_event_id, version, plan_archetype, operator_status
               FROM deploy_plans WHERE id=%s AND deploy_event_id=%s""",
            (int(plan_id), event_id),
        )
    else:
        if not archetype:
            return {"ok": False, "error": "plan_id or plan_archetype required"}
        if expected_version is not None:
            cur.execute(
                """SELECT id, deploy_event_id, version, plan_archetype, operator_status
                   FROM deploy_plans WHERE deploy_event_id=%s AND plan_archetype=%s AND version=%s""",
                (event_id, archetype, int(expected_version)),
            )
        else:
            cur.execute(
                """SELECT id, deploy_event_id, version, plan_archetype, operator_status
                   FROM deploy_plans WHERE deploy_event_id=%s AND plan_archetype=%s
                   AND version = (SELECT MAX(version) FROM deploy_plans WHERE deploy_event_id=%s)
                   LIMIT 1""",
                (event_id, archetype, event_id),
            )
    prow = cur.fetchone()
    if not prow:
        return {"ok": False, "error": "plan_not_found"}
    pid, _, version, arch, op_status = int(prow[0]), prow[1], int(prow[2]), prow[3], prow[4]
    if expected_version is not None and int(expected_version) != version:
        return {"ok": False, "error": "version_conflict", "expected": expected_version, "actual": version}

    now = datetime.now(timezone.utc)
    cur.execute(
        "UPDATE deploy_plans SET locked_at=%s, locked_by=%s WHERE id=%s AND locked_at IS NULL",
        (now, locked_by, pid),
    )
    if cur.rowcount == 0:
        return {"ok": False, "error": "plan_already_locked"}

    cur.execute(
        """UPDATE deploy_events SET plan_locked_at=%s, locked_plan_id=%s, locked_plan_version=%s,
           operator_status='reviewing', updated_at=NOW() WHERE id=%s""",
        (now, pid, version, event_id),
    )

    cur.execute("SELECT metadata FROM deploy_events WHERE id=%s", (event_id,))
    meta_row = cur.fetchone()
    meta = meta_row[0] if meta_row else {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    meta = dict(meta or {})
    meta["plan_lock"] = {
        "plan_id": pid,
        "version": version,
        "plan_archetype": arch,
        "locked_at": now.isoformat(),
        "locked_by": locked_by,
        "idempotency_key": idem,
    }
    cur.execute("UPDATE deploy_events SET metadata=%s::jsonb WHERE id=%s", (json.dumps(meta), event_id))
    _audit(cur, event_id, "lock_plan", {"plan_id": pid, "version": version, "archetype": arch}, idempotency_key=idem)

    return {
        "ok": True,
        "advisory_only": True,
        "event_id": event_id,
        "plan_id": pid,
        "plan_version": version,
        "plan_archetype": arch,
        "operator_status": "reviewing",
        "locked_at": now.isoformat(),
        "idempotency_key": idem,
    }


def _oversight_prompt(event: dict[str, Any], plan: dict[str, Any]) -> str:
    meta = event.get("metadata") or {}
    pa = meta.get("phase_a") or {}
    recon = pa.get("reconciliation") or {}
    sold = event.get("symbol")
    arch = plan.get("plan_archetype")
    legs = [l for l in plan.get("legs") or [] if not l.get("is_reserve")]
    leg_lines = "\n".join(
        f"- {l.get('ticker')}: ${l.get('target_dollars')} ({l.get('thesis', '')[:80]})"
        for l in legs[:8]
    )
    return (
        f"You are reviewing an ADVISORY redeploy plan (no broker execution). "
        f"Sold {sold} for ${recon.get('net_proceeds_usd') or event.get('proceeds_usd')}; "
        f"deployable ${recon.get('deployable_cash_usd')}; status {recon.get('reconciliation_status')}.\n"
        f"Plan {arch} ({plan.get('plan_type')}): {plan.get('objective')}\n"
        f"Deploy ${plan.get('total_deployable_usd')}, reserve ${plan.get('reserve_usd')}.\n"
        f"Legs:\n{leg_lines}\n"
        "Reply JSON only: {\"verdict\":\"pass\"|\"fail\"|\"needs_review\", \"summary\":\"...\", \"risks\":[\"...\"]}"
    )


def _parse_verdict(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"verdict": "needs_review", "summary": (text or "")[:400], "parsed": False}
    try:
        data = json.loads(m.group(0))
        v = str(data.get("verdict") or "needs_review").lower()
        if v not in ("pass", "fail", "needs_review"):
            v = "needs_review"
        return {"verdict": v, "summary": data.get("summary"), "risks": data.get("risks") or [], "parsed": True}
    except Exception:
        return {"verdict": "needs_review", "summary": text[:400], "parsed": False}


def _run_lane(lane: str, prompt: str) -> dict[str, Any]:
    try:
        import llm_lane
        if not llm_lane.available(lane):
            return {"ok": False, "lane": lane, "error": "lane_unavailable"}
        text = llm_lane.generate(prompt, lane=lane, timeout=45)
        parsed = _parse_verdict(text)
        return {"ok": True, "lane": lane, "answer": text, **parsed}
    except Exception as e:
        return {"ok": False, "lane": lane, "error": str(e)[:160]}


def run_deploy_oversight(cur, body: dict[str, Any]) -> dict[str, Any]:
    """PR-4 — Grok + ChatGPT oversight lanes; manual fallback when OAuth unavailable."""
    ensure_oversight_schema(cur)
    event_id = int(body.get("event_id") or body.get("id") or 0)
    if not event_id:
        return {"ok": False, "error": "event_id required"}

    plan_id = body.get("plan_id")
    archetype = str(body.get("plan_archetype") or body.get("archetype") or "").upper()[:1]
    plan = None
    if plan_id:
        plan = get_plan_by_id(cur, int(plan_id))
    else:
        plan = fetch_institutional_plan(cur, event_id, archetype=archetype or "F")
    if not plan:
        return {"ok": False, "error": "plan_not_found"}
    if plan.get("id"):
        full = get_plan_by_id(cur, int(plan["id"]))
        if full:
            plan = full

    cur.execute(
        "SELECT id, symbol, account, proceeds_usd, metadata, locked_plan_id FROM deploy_events WHERE id=%s",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "event_not_found"}
    cols = [d[0] for d in cur.description]
    event = dict(zip(cols, row))
    meta = event.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    event["metadata"] = meta

    prompt = _oversight_prompt(event, plan)
    lanes = body.get("lanes") or ["grok", "chatgpt"]
    results = []
    for lane in lanes:
        lane = str(lane).lower()
        if lane not in ("grok", "chatgpt"):
            continue
        res = _run_lane(lane, prompt)
        verdict = res.get("verdict") or ("needs_review" if res.get("ok") else "manual_required")
        cur.execute(
            """INSERT INTO deploy_oversight_runs
               (deploy_event_id, lane, verdict, answer, model, ok, error)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                event_id,
                lane,
                verdict,
                (res.get("answer") or res.get("summary") or res.get("error") or "")[:8000],
                lane,
                bool(res.get("ok")),
                res.get("error"),
            ),
        )
        run_id = cur.fetchone()[0]
        res["run_id"] = int(run_id)
        results.append(res)

    if not results:
        results.append({
            "ok": False,
            "lane": "manual",
            "verdict": "manual_required",
            "summary": "OAuth lanes unavailable — operator pastes prompt in Grok/ChatGPT",
            "prompt": prompt[:4000],
        })

    ok_runs = [r for r in results if r.get("ok")]
    verdicts = [r.get("verdict") for r in ok_runs if r.get("verdict")]
    if "fail" in verdicts:
        oversight_status = "failed"
    elif verdicts and all(v == "pass" for v in verdicts):
        oversight_status = "passed"
    elif verdicts and any(v == "pass" for v in verdicts):
        oversight_status = "pending"
    else:
        oversight_status = "pending"

    pid = plan.get("id")
    if pid:
        cur.execute(
            "UPDATE deploy_plans SET oversight_status=%s WHERE id=%s",
            (oversight_status, int(pid)),
        )

    # Promote operator_ready when gates pass (non-major skips oversight per plan engine)
    ctx = (meta.get("phase_a") or {}).get("portfolio_context") or {}
    is_major = bool(ctx.get("is_major_sale"))
    confidence = _as_float(plan.get("confidence"))
    evidence = int(plan.get("evidence_factor_count") or 0)
    export_ready = assess_export_readiness([plan]).get("export_allowed", False)
    operator_status = plan.get("operator_status") or "draft"
    if (
        oversight_status == "passed"
        and confidence >= OPERATOR_READY_MIN_CONFIDENCE
        and evidence >= OPERATOR_READY_MIN_EVIDENCE_FACTORS
        and export_ready
        and (not is_major or oversight_status == "passed")
    ):
        operator_status = "operator_ready"
        if pid:
            cur.execute(
                "UPDATE deploy_plans SET operator_status=%s WHERE id=%s",
                (operator_status, int(pid)),
            )

    meta = dict(meta)
    meta["oversight"] = {
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "oversight_status": oversight_status,
        "lanes": [r.get("lane") for r in results],
        "operator_status": operator_status,
        "policy_version": POLICY_VERSION,
        "generator_version": GENERATOR_VERSION,
    }
    cur.execute("UPDATE deploy_events SET metadata=%s::jsonb, updated_at=NOW() WHERE id=%s", (json.dumps(meta), event_id))
    _audit(cur, event_id, "oversight", {"plan_id": pid, "oversight_status": oversight_status, "results": len(results)})

    return {
        "ok": True,
        "advisory_only": True,
        "event_id": event_id,
        "plan_id": pid,
        "oversight_status": oversight_status,
        "operator_status": operator_status,
        "is_major_sale": is_major,
        "export_ready": export_ready,
        "results": results,
        "manual_prompt": prompt if not ok_runs else None,
    }