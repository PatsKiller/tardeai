#!/usr/bin/env python3
"""Operator-approved one-shot: one Maria + one CIO governed Flash review for Intelligence Board proof.

Usage (from repo root, after explicit operator approval):
  AGENT_JOBS_P0_CONTAINED=0 \\
  AGENT_JOBS_P0_CONTAINMENT_FLAG=/tmp/intel_proof_absent_$$ \\
  .venv/bin/python scripts/run_watchlist_intelligence_proof_reviews.py --symbol CECO

Does NOT clear the host containment flag. Writes immutable artifacts under
data/runtime/watchlist_intelligence/artifacts/ with full provenance fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ARTIFACT_DIR = ROOT / "data" / "runtime" / "watchlist_intelligence" / "artifacts"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_context(symbol: str) -> dict:
    from lib.watchlist_intelligence import detail_intelligence
    return detail_intelligence(symbol)


def maria_prompt(ctx: dict) -> str:
    card = ctx.get("card") or {}
    identity = ctx.get("identity") or {}
    street = ctx.get("street") or {}
    trade = ctx.get("trade_ai") or {}
    tech = ctx.get("technicals") or {}
    cats = (ctx.get("catalysts") or {}).get("timeline") or []
    cat_txt = "; ".join(
        str(c.get("headline") or c.get("type") or "") for c in cats[:4]
    ) or "none listed"
    return f"""You are Maria, Trade AI research narrative agent. Advisory only. Do not create trade mechanics.

Symbol: {ctx.get('symbol')}
Company: {card.get('company')}
What it does: {identity.get('what_the_company_does') or identity.get('description') or card.get('company_summary')}
Sector/Industry: {card.get('sector')} / {card.get('industry')}
Street rating: {street.get('rating') or card.get('street_rating')} · analysts {street.get('analyst_count')} · target {street.get('target_mean')}
Last price: {card.get('last')} day_change_pct: {card.get('day_change_pct')}
Trade AI state: {trade.get('primary_state')} proposal_allowed={trade.get('proposal_allowed')}
Technicals: trend={tech.get('trend')} RSI={tech.get('rsi')} support={tech.get('support')} resistance={tech.get('resistance')}
Catalysts: {cat_txt}
Operator meaning: {trade.get('operator_meaning')}

Return concise JSON with keys:
verdict, summary, thesis, counter_thesis, catalysts (array), risks (array),
evidence_gaps (array), what_changes_the_decision
No prices invented. No READY override. Advisory only.
"""


def cio_prompt(ctx: dict, maria_summary: str | None) -> str:
    card = ctx.get("card") or {}
    street = ctx.get("street") or {}
    trade = ctx.get("trade_ai") or {}
    return f"""You are Trade AI CIO synthesis (watchlist_steph_flash_narrative). Advisory only.

Reconcile Street consensus, deterministic Trade AI state, and Maria narrative.
Never create entry/stop/target mechanics. Never override deterministic FAIL to READY.

Symbol: {ctx.get('symbol')} {card.get('company')}
Street: {street.get('rating') or card.get('street_rating')} · target {street.get('target_mean')} · upside {street.get('implied_upside_pct')}
Trade AI primary_state: {trade.get('primary_state')}
proposal_allowed: {trade.get('proposal_allowed')}
operator_meaning: {trade.get('operator_meaning')}
allowed_action_now: {trade.get('allowed_action_now')}
held: {card.get('held')}
Maria narrative (may be null): {maria_summary or 'NOT RUN'}

Return concise JSON with keys:
verdict, summary, thesis, counter_thesis, risks (array), what_changes_the_decision,
next_review_trigger
"""


def parse_jsonish(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    # extract first {...}
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return {"summary": text[:800], "verdict": None}


def write_artifact(agent_id: str, symbol: str, result: dict, parsed: dict, *, input_hash: str, started: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    completed = _now()
    body = {
        "agent_id": agent_id,
        "agent_version": "watchlist-intelligence-proof-v1",
        "status": "COMPLETE" if result.get("success") else "FAILED",
        "process_id": result.get("process_id"),
        "provider": result.get("provider"),
        "model": result.get("model_used") or result.get("returned_model"),
        "requested_policy": result.get("requested_policy"),
        "executed_policy": result.get("executed_policy") or result.get("requested_policy"),
        "fallback_used": bool(result.get("fallback_used")),
        "provider_request_id": result.get("provider_request_id"),
        "request_id": result.get("provider_request_id"),
        "request_id_present": bool(result.get("provider_request_id")),
        "started_at": started,
        "completed_at": completed,
        "input_snapshot_id": f"intel-snap-{symbol}-{agent_id}",
        "input_hash": input_hash,
        "artifact_id": f"intel-{agent_id}-{symbol}-{uuid.uuid4().hex[:12]}",
        "prompt_tokens": (result.get("tokens") or {}).get("prompt_tokens") or 0,
        "completion_tokens": (result.get("tokens") or {}).get("completion_tokens") or 0,
        "estimated_cost_usd": float(result.get("cost_estimate") or 0),
        "reconciliation_status": "ADVISORY_COMPLETE" if result.get("success") else "FAILED",
        "verdict": parsed.get("verdict"),
        "summary": parsed.get("summary"),
        "thesis": parsed.get("thesis"),
        "counter_thesis": parsed.get("counter_thesis"),
        "catalysts": parsed.get("catalysts") or [],
        "risks": parsed.get("risks") or [],
        "evidence_gaps": parsed.get("evidence_gaps") or [],
        "what_changes_the_decision": parsed.get("what_changes_the_decision") or parsed.get("next_review_trigger"),
        "evidence_references": [],
        "raw_response": result.get("response"),
        "run_id": result.get("run_id"),
        "evidence_hash": result.get("evidence_hash"),
        "latency": result.get("latency"),
        "operator_approved": True,
        "approval_scope": "watchlist_intelligence_v3_proof_maria_and_cio",
    }
    body["artifact_hash"] = _sha(json.dumps(body, sort_keys=True, default=str))
    path = ARTIFACT_DIR / f"{symbol.upper()}_{agent_id}.json"
    path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="CECO")
    ap.add_argument("--maria-only", action="store_true")
    ap.add_argument("--cio-only", action="store_true")
    args = ap.parse_args()
    symbol = args.symbol.upper()

    # Process-scoped containment override only (never delete host flag)
    os.environ.setdefault("AGENT_JOBS_P0_CONTAINED", "0")
    if not os.environ.get("AGENT_JOBS_P0_CONTAINMENT_FLAG") or "tradeai/AGENT_JOBS" in os.environ.get(
        "AGENT_JOBS_P0_CONTAINMENT_FLAG", ""
    ):
        os.environ["AGENT_JOBS_P0_CONTAINMENT_FLAG"] = f"/tmp/intel_proof_absent_{os.getpid()}"
    os.environ.setdefault("AGENT_FLASH_MAX_CALLS_PER_RUN_TOTAL", "2")
    os.environ.setdefault("AGENT_FLASH_MAX_CALLS_PER_PROCESS", "2")
    os.environ.setdefault("AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN", "0.10")

    from lib.agent_flash_governance import governed_flash_call, reset_run_budget, run_budget_snapshot

    run_id = reset_run_budget(f"intel_proof_{symbol}_{int(datetime.now().timestamp())}")
    print(json.dumps({"phase": "start", "symbol": symbol, "run_id": run_id}, indent=2))

    ctx = build_context(symbol)
    if not ctx.get("ok"):
        print(json.dumps({"error": "detail_unavailable", "ctx": ctx}, indent=2))
        return 2

    maria_path = None
    cio_path = None
    maria_summary = None

    do_maria = not args.cio_only
    do_cio = not args.maria_only

    if do_maria:
        prompt = maria_prompt(ctx)
        ih = _sha(prompt)
        started = _now()
        print(json.dumps({"phase": "maria_call", "process_id": "watchlist_maria_flash_narrative"}, indent=2))
        res = governed_flash_call(
            prompt,
            task_type="agent_narrative",
            max_tokens=700,
            job_key=f"intel-maria-{symbol}",
            metadata={"symbol": symbol, "agent": "maria", "operator_approved": True},
            allow_fast_think=False,
        )
        print(json.dumps({
            "phase": "maria_result",
            "success": res.get("success"),
            "error": res.get("error"),
            "model": res.get("model_used"),
            "process_id": res.get("process_id"),
            "request_id": res.get("provider_request_id"),
            "cost": res.get("cost_estimate"),
            "contained": res.get("contained"),
        }, indent=2))
        if not res.get("success"):
            return 3
        parsed = parse_jsonish(res.get("response") or "")
        maria_summary = parsed.get("summary")
        maria_path = write_artifact("maria", symbol, res, parsed, input_hash=ih, started=started)
        print(json.dumps({"phase": "maria_artifact", "path": str(maria_path)}, indent=2))

    if do_cio:
        prompt = cio_prompt(ctx, maria_summary)
        ih = _sha(prompt)
        started = _now()
        print(json.dumps({"phase": "cio_call", "process_id": "watchlist_steph_flash_narrative"}, indent=2))
        res = governed_flash_call(
            prompt,
            task_type="cio_synthesis",
            max_tokens=700,
            job_key=f"intel-cio-{symbol}",
            metadata={"symbol": symbol, "agent": "cio", "operator_approved": True},
            allow_fast_think=False,
        )
        print(json.dumps({
            "phase": "cio_result",
            "success": res.get("success"),
            "error": res.get("error"),
            "model": res.get("model_used"),
            "process_id": res.get("process_id"),
            "request_id": res.get("provider_request_id"),
            "cost": res.get("cost_estimate"),
            "contained": res.get("contained"),
        }, indent=2))
        if not res.get("success"):
            return 4
        parsed = parse_jsonish(res.get("response") or "")
        cio_path = write_artifact("cio", symbol, res, parsed, input_hash=ih, started=started)
        print(json.dumps({"phase": "cio_artifact", "path": str(cio_path)}, indent=2))

    # Prove projection
    from lib.watchlist_intelligence import reviews_intelligence, detail_intelligence
    rev = reviews_intelligence(symbol)
    det = detail_intelligence(symbol)
    print(json.dumps({
        "phase": "projection",
        "provider_calls_api": rev.get("provider_calls"),
        "complete_count": rev.get("complete_count"),
        "maria_status": (det.get("maria_review") or {}).get("status"),
        "maria_model": (det.get("maria_review") or {}).get("model"),
        "cio_status": (det.get("cio_review") or {}).get("status"),
        "cio_model": (det.get("cio_review") or {}).get("model"),
        "budget": run_budget_snapshot(),
        "artifacts": [str(p) for p in (maria_path, cio_path) if p],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
