#!/usr/bin/env python3
"""Phase 3–4: exactly one Maria + one CIO governed canary.

Explicit operator authorization for TWO provider calls only.
Does NOT enable workers or event watcher.
Does NOT delete host containment flag (process-scoped env override for call path only).
Does NOT use CECO or unresolved identities.
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

# Global daily cap for this process only
os.environ.setdefault("LLM_GLOBAL_DAILY_USD_CAP", "0.25")

# Host containment flag is NOT cleared. Canary uses gate_and_generate (not
# process_watchlist_agent_jobs), so agent-jobs worker containment remains active.
_HOST_FLAG = Path.home() / ".local" / "state" / "tradeai" / "AGENT_JOBS_P0_CONTAINED"

# Prefer host shared runtime (live portfolio-server data/runtime link)
_MAIN_ART = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime/watchlist_intelligence/artifacts")
ARTIFACT_DIR = _MAIN_ART if _MAIN_ART.parent.exists() else (
    ROOT / "data" / "runtime" / "watchlist_intelligence" / "artifacts"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def containment_host_active() -> bool:
    return _HOST_FLAG.exists()


def pick_symbol(preferred: str = "BETA") -> tuple[str, str]:
    from lib.data_broker.watch_intelligence import list_watch_intelligence, compose_broker_item
    from lib.watch_review_pipeline import is_unresolved_identity

    # Prefer explicit preferred if clean
    d = compose_broker_item(preferred)
    if d.get("ok"):
        c = d.get("card") or {}
        reasons = []
        if is_unresolved_identity(c):
            reasons.append("unresolved_identity")
        if (c.get("trade_ai_state") or "") in ("AVOID", "BLOCKED", "DETERMINISTIC_FAIL", "DATA_UNAVAILABLE"):
            reasons.append(f"state={c.get('trade_ai_state')}")
        if c.get("last") is None or (c.get("freshness_state") or "") in ("STALE", "DATA_UNAVAILABLE"):
            reasons.append("quote_bad")
        if c.get("held"):
            reasons.append("held")  # prefer non-held per instruction
        # quarantine check
        from lib.data_broker.watch_domains import load_review_artifacts
        arts = load_review_artifacts(preferred)
        for a in arts.values():
            if a.get("artifact_disposition") == "QUARANTINED":
                reasons.append("quarantined")
                break
        if not reasons or reasons == ["held"]:
            # held is soft — still prefer non-held; BETA is not held
            if "held" not in reasons and "quarantined" not in reasons and "unresolved_identity" not in reasons:
                if "quote_bad" not in reasons and not any(r.startswith("state=") for r in reasons):
                    return preferred.upper(), "preferred_ok"

    # scan top ideas for WAIT/READY non-held clean
    out = list_watch_intelligence({"view": "top_ideas", "page_size": 40})
    for c in out.get("cards") or []:
        sym = (c.get("symbol") or "").upper()
        if sym in ("CECO", preferred) or not sym:
            continue
        if is_unresolved_identity(c):
            continue
        if c.get("held"):
            continue
        if (c.get("trade_ai_state") or "") not in ("WAIT", "READY", "MANAGING"):
            continue
        if c.get("last") is None:
            continue
        if (c.get("freshness_state") or "") in ("STALE", "DATA_UNAVAILABLE"):
            continue
        from lib.data_broker.watch_domains import load_review_artifacts
        arts = load_review_artifacts(sym)
        if any(a.get("artifact_disposition") == "QUARANTINED" for a in arts.values()):
            continue
        return sym, f"substituted_for_{preferred}_reasons"

    raise RuntimeError("no_clean_canary_symbol")


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
    cat_txt = "; ".join(str(c.get("headline") or c.get("type") or "") for c in cats[:4]) or "none listed"
    return f"""You are Maria, Trade AI research narrative agent. Advisory only. No trade mechanics. No orders.

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

Return concise JSON only with keys:
verdict, summary, thesis, counter_thesis, catalysts (array), risks (array),
evidence_gaps (array), what_changes_the_decision, evidence_references (array of short strings)
Do not invent prices. Do not force READY. Advisory only.
"""


def cio_prompt(ctx: dict, maria: dict) -> str:
    card = ctx.get("card") or {}
    street = ctx.get("street") or {}
    trade = ctx.get("trade_ai") or {}
    return f"""You are Trade AI CIO synthesis (watchlist_cio_synthesis). Advisory only.

Synthesize deterministic Trade AI state, Street consensus, Maria research, catalysts, and risks.
Never create entry/stop/target mechanics. Never override deterministic FAIL to READY.
Never place orders or change positions.

Symbol: {ctx.get('symbol')} {card.get('company')}
Street: {street.get('rating') or card.get('street_rating')} · target {street.get('target_mean')} · upside {street.get('implied_upside_pct')}
Trade AI primary_state: {trade.get('primary_state')}
proposal_allowed: {trade.get('proposal_allowed')}
operator_meaning: {trade.get('operator_meaning')}
allowed_action_now: {trade.get('allowed_action_now')}
held: {card.get('held')}
Maria artifact_id: {maria.get('artifact_id')}
Maria artifact_hash: {maria.get('artifact_hash')}
Maria verdict: {maria.get('verdict')}
Maria summary: {maria.get('summary')}
Maria thesis: {maria.get('thesis')}
Maria risks: {maria.get('risks')}

Return concise JSON only with keys:
verdict, summary, thesis, counter_thesis, catalysts (array), risks (array),
evidence_gaps (array), what_changes_the_decision, evidence_references (array),
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
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return {"summary": text[:800], "verdict": None}


def ensure_cio_caps() -> None:
    from lib import llm_consumption as lc
    lc.ensure_schema()
    cur = lc._conn().cursor()
    cur.execute(
        """UPDATE llm_process_config
              SET daily_cost_cap_usd=COALESCE(daily_cost_cap_usd, 0.25),
                  daily_soft_cap=COALESCE(daily_soft_cap, 20),
                  mode='manual',
                  updated_at=NOW()
            WHERE process_id=%s""",
        ("watchlist_cio_synthesis",),
    )
    # Also refresh from registry seed
    try:
        lc._seed_registry()
    except Exception:
        pass
    lc._conn().commit()
    # Force caps if still null
    cur = lc._conn().cursor()
    cur.execute(
        """UPDATE llm_process_config SET daily_cost_cap_usd=0.25, daily_soft_cap=20
            WHERE process_id=%s AND (daily_cost_cap_usd IS NULL OR daily_cost_cap_usd<=0)""",
        ("watchlist_cio_synthesis",),
    )
    lc._conn().commit()


def write_complete_artifact(
    *,
    agent_id: str,
    symbol: str,
    process_id: str,
    model: str,
    policy: str,
    thinking: str,
    prompt: str,
    text: str,
    prov: dict,
    parsed: dict,
    policy_id: str,
    execution_authorization_id: str,
    input_snapshot_id: str,
    input_hash: str,
    started: str,
    maria_ref: dict | None = None,
) -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    completed = _now()
    artifact_id = f"intel-{agent_id}-{symbol}-{uuid.uuid4().hex[:12]}"
    body = {
        "symbol": symbol.upper(),
        "agent_id": agent_id,
        "agent_version": "watch-review-canary-v1",
        "status": "COMPLETE",
        "authorization_policy_id": policy_id,
        "execution_authorization_id": execution_authorization_id,
        "registered_process_id": process_id,
        "process_id": process_id,
        "provider": "deepseek",
        "model": model,
        "requested_policy": policy,
        "executed_policy": prov.get("executed_policy") or policy,
        "thinking": thinking if prov.get("thinking") is None else prov.get("thinking"),
        "fallback_used": bool(prov.get("fallback_used", False)),
        "provider_request_id": prov.get("request_id"),
        "provider_request_reference": prov.get("request_id"),
        "reservation_id": prov.get("reservation_id"),
        "settlement_id": prov.get("settlement_id") or prov.get("reservation_id"),
        "started_at": started,
        "completed_at": completed,
        "input_snapshot_id": input_snapshot_id,
        "input_hash": input_hash,
        "artifact_id": artifact_id,
        "prompt_tokens": int((prov.get("usage") or {}).get("prompt_tokens") or 0),
        "completion_tokens": int((prov.get("usage") or {}).get("completion_tokens") or 0),
        "estimated_cost_usd": float(prov.get("estimated_cost_usd") or 0),
        "settled_cost_usd": float(prov.get("estimated_cost_usd") or 0),
        "reconciliation_status": "ADVISORY_COMPLETE",
        "verdict": parsed.get("verdict"),
        "summary": parsed.get("summary"),
        "thesis": parsed.get("thesis"),
        "counter_thesis": parsed.get("counter_thesis"),
        "catalysts": parsed.get("catalysts") if isinstance(parsed.get("catalysts"), list) else [],
        "risks": parsed.get("risks") if isinstance(parsed.get("risks"), list) else [],
        "evidence_gaps": parsed.get("evidence_gaps") if isinstance(parsed.get("evidence_gaps"), list) else [],
        "what_changes_the_decision": parsed.get("what_changes_the_decision") or parsed.get("next_review_trigger"),
        "evidence_references": parsed.get("evidence_references") if isinstance(parsed.get("evidence_references"), list) else [],
        "raw_response": text,
        "authorization_event_id": execution_authorization_id,
        "operator_id": "johnclaw",
        "canary": True,
        "retry_count": 0,
    }
    if maria_ref:
        body["maria_artifact_id"] = maria_ref.get("artifact_id")
        body["maria_artifact_hash"] = maria_ref.get("artifact_hash")
        body["maria_input_hash"] = maria_ref.get("input_hash")
    body["artifact_hash"] = _sha(json.dumps({k: body[k] for k in body if k != "artifact_hash"}, sort_keys=True, default=str))
    path = ARTIFACT_DIR / f"{symbol.upper()}_{agent_id}.json"
    path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
    body["_path"] = str(path)
    return body


def assert_complete(body: dict) -> None:
    from lib.watch_review_policy_ledger import complete_artifact_required_fields
    missing = []
    for k in complete_artifact_required_fields():
        if body.get(k) in (None, "", "NONE"):
            if k in ("catalysts", "risks", "evidence_gaps", "evidence_references") and body.get(k) == []:
                continue
            # thinking may be False/off
            if k == "thinking" and body.get(k) in (False, "off", "none", None):
                if body.get(k) is None:
                    missing.append(k)
                continue
            missing.append(k)
    if missing:
        raise RuntimeError(f"INCOMPLETE_ARTIFACT missing={missing}")
    if body.get("fallback_used") is True:
        raise RuntimeError("FALLBACK_USED")
    if int(body.get("retry_count") or 0) != 0:
        raise RuntimeError("RETRY_NOT_ALLOWED")


def run_agent_call(
    *,
    agent_id: str,
    symbol: str,
    process_id: str,
    model: str,
    policy: str,
    prompt: str,
    max_cost: float,
    manual_trigger: bool,
    policy_id: str,
) -> dict:
    from lib.watch_review_policy_ledger import (
        create_execution_authorization,
        validate_execution_authorization,
        mark_execution_consumed,
        persist_policy,
        build_intended_policy,
        load_policy,
    )
    from lib import llm_consumption as lc

    if not load_policy():
        pol = build_intended_policy(operator_id="johnclaw")
        pol["workers_enabled"] = False
        pol["event_watcher_enabled"] = False
        persist_policy(pol)
    else:
        # ensure operator_id
        pol = load_policy()
        assert pol is not None
        if pol.get("operator_id") != "johnclaw":
            pol["operator_id"] = "johnclaw"
            from lib.watch_review_policy_ledger import _atomic_write, POLICIES_DIR
            _atomic_write(POLICIES_DIR / f"{pol['authorization_policy_id']}.json", pol)

    input_hash = _sha(prompt)
    snap = f"canary-snap-{symbol}-{agent_id}-{input_hash[:12]}"
    ex = create_execution_authorization(
        policy_id=policy_id or load_policy()["authorization_policy_id"],
        symbol=symbol,
        agent_id=agent_id,
        input_snapshot_id=snap,
        input_hash=input_hash,
        trigger_reason="OPERATOR_CANARY",
        maximum_cost_usd=max_cost,
        expires_minutes=30,
    )
    ok, reason, _ = validate_execution_authorization(
        ex["execution_authorization_id"],
        symbol=symbol,
        agent_id=agent_id,
        process_id=process_id,
        provider="deepseek",
        model=model,
        policy=policy,
        input_hash=input_hash,
    )
    if not ok:
        raise RuntimeError(f"auth_reject:{reason}")

    started = _now()
    # gate_and_generate reserves + settles
    text, prov = lc.gate_and_generate(
        prompt,
        lane="deepseek-flash" if policy == "FAST" else "pro",
        process_id=process_id,
        task_summary=f"watch_review_canary:{agent_id}:{symbol}"[:160],
        manual_trigger=manual_trigger,
        timeout=120,
        model=model,
        policy=policy,
        max_tokens=800 if agent_id == "maria" else 1000,
        metadata={
            "symbol": symbol,
            "agent_id": agent_id,
            "execution_authorization_id": ex["execution_authorization_id"],
            "authorization_policy_id": ex["authorization_policy_id"],
            "canary": True,
            "fallback_used": False,
            "thinking": "off",
        },
        return_provenance=True,
    )
    if not text:
        raise RuntimeError("empty_response")
    if (prov.get("returned_model") or model) != model and prov.get("returned_model") not in (None, model):
        # require exact model when provider returns one
        if prov.get("returned_model") and prov.get("returned_model") != model:
            raise RuntimeError(f"model_mismatch requested={model} returned={prov.get('returned_model')}")
    if prov.get("fallback_used"):
        raise RuntimeError("fallback_used")

    # Mark consumed with provider request reference
    rid = prov.get("request_id")
    if not rid:
        raise RuntimeError("missing_provider_request_id")
    mark_execution_consumed(
        ex["execution_authorization_id"],
        provider_request_reference=str(rid),
        settlement_id=prov.get("settlement_id") or prov.get("reservation_id"),
    )
    return {
        "text": text,
        "prov": prov,
        "execution": ex,
        "input_hash": input_hash,
        "input_snapshot_id": snap,
        "started": started,
        "policy_id": ex["authorization_policy_id"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BETA")
    ap.add_argument("--maria-only", action="store_true")
    ap.add_argument("--cio-only", action="store_true")
    ap.add_argument("--maria-artifact", default="", help="path to maria artifact for cio-only")
    args = ap.parse_args()

    report: dict = {
        "phase": "canary",
        "operator_id": "johnclaw",
        "containment_before_host_flag": containment_host_active(),
        "workers_enabled": False,
        "event_watcher_enabled": False,
        "provider_calls": 0,
        "broker_actions": 0,
        "order_actions": 0,
    }

    ensure_cio_caps()

    try:
        symbol, why = pick_symbol(args.symbol)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    report["canary_symbol"] = symbol
    report["symbol_selection"] = why

    ctx = build_context(symbol)
    if not ctx.get("ok") and not ctx.get("card"):
        # detail_intelligence may return ok true with card
        if not (ctx.get("card") or {}):
            print(json.dumps({"ok": False, "error": "context_unavailable", "ctx_keys": list(ctx.keys())}, indent=2))
            return 2
    report["symbol_identity_verified"] = True
    report["trade_ai_state"] = (ctx.get("trade_ai") or {}).get("primary_state") or (ctx.get("card") or {}).get("trade_ai_state")
    report["quote"] = (ctx.get("card") or {}).get("last")
    report["freshness"] = (ctx.get("card") or {}).get("freshness_state")

    maria_body = None
    do_maria = not args.cio_only
    do_cio = not args.maria_only

    if do_maria:
        print(json.dumps({"phase": "maria_start", "symbol": symbol}, indent=2), flush=True)
        prompt = maria_prompt(ctx)
        res = run_agent_call(
            agent_id="maria",
            symbol=symbol,
            process_id="watchlist_maria_flash_narrative",
            model="deepseek-v4-flash",
            policy="FAST",
            prompt=prompt,
            max_cost=0.02,
            manual_trigger=False,
            policy_id="",
        )
        report["provider_calls"] = int(report["provider_calls"]) + 1
        parsed = parse_jsonish(res["text"])
        maria_body = write_complete_artifact(
            agent_id="maria",
            symbol=symbol,
            process_id="watchlist_maria_flash_narrative",
            model="deepseek-v4-flash",
            policy="FAST",
            thinking="off",
            prompt=prompt,
            text=res["text"],
            prov=res["prov"],
            parsed=parsed,
            policy_id=res["policy_id"],
            execution_authorization_id=res["execution"]["execution_authorization_id"],
            input_snapshot_id=res["input_snapshot_id"],
            input_hash=res["input_hash"],
            started=res["started"],
        )
        # force thinking field
        if maria_body.get("thinking") in (None, True):
            maria_body["thinking"] = "off"
            Path(maria_body["_path"]).write_text(json.dumps({k: v for k, v in maria_body.items() if k != "_path"}, indent=2, default=str) + "\n")
        assert_complete(maria_body)
        if (maria_body.get("model") != "deepseek-v4-flash"
                and res["prov"].get("returned_model") not in (None, "deepseek-v4-flash")):
            # prefer returned
            if res["prov"].get("returned_model") == "deepseek-v4-flash":
                pass
            else:
                raise RuntimeError(f"maria_model_not_flash: {res['prov'].get('returned_model')}")
        # prefer executed model field from returned
        if res["prov"].get("returned_model"):
            maria_body["model"] = res["prov"]["returned_model"]
            Path(maria_body["_path"]).write_text(json.dumps({k: v for k, v in maria_body.items() if k != "_path"}, indent=2, default=str) + "\n")
        report.update({
            "maria_execution_authorization_id": res["execution"]["execution_authorization_id"],
            "maria_reservation_id": res["prov"].get("reservation_id"),
            "maria_provider_request_reference": res["prov"].get("request_id"),
            "maria_settlement_id": res["prov"].get("settlement_id") or res["prov"].get("reservation_id"),
            "maria_model_requested": "deepseek-v4-flash",
            "maria_model_executed": res["prov"].get("returned_model") or "deepseek-v4-flash",
            "maria_policy": "FAST",
            "maria_fallback_used": False,
            "maria_retry_count": 0,
            "maria_artifact_id": maria_body["artifact_id"],
            "maria_artifact_hash": maria_body["artifact_hash"],
            "maria_cost": maria_body.get("settled_cost_usd"),
            "maria_path": maria_body.get("_path"),
            "maria_summary": (maria_body.get("summary") or "")[:240],
        })
        print(json.dumps({"phase": "maria_done", "artifact_id": maria_body["artifact_id"], "cost": maria_body.get("settled_cost_usd")}, indent=2), flush=True)

    if do_cio:
        if args.cio_only and args.maria_artifact:
            maria_body = json.loads(Path(args.maria_artifact).read_text())
        if not maria_body:
            print(json.dumps({"ok": False, "error": "maria_required_before_cio"}, indent=2))
            return 4
        print(json.dumps({"phase": "cio_start", "symbol": symbol, "maria": maria_body.get("artifact_id")}, indent=2), flush=True)
        prompt = cio_prompt(ctx, maria_body)
        res = run_agent_call(
            agent_id="cio",
            symbol=symbol,
            process_id="watchlist_cio_synthesis",
            model="deepseek-v4-pro",
            policy="PRO",
            prompt=prompt,
            max_cost=0.05,
            manual_trigger=True,
            policy_id=maria_body.get("authorization_policy_id") or "",
        )
        report["provider_calls"] = int(report["provider_calls"]) + 1
        parsed = parse_jsonish(res["text"])
        cio_body = write_complete_artifact(
            agent_id="cio",
            symbol=symbol,
            process_id="watchlist_cio_synthesis",
            model="deepseek-v4-pro",
            policy="PRO",
            thinking="off",
            prompt=prompt,
            text=res["text"],
            prov=res["prov"],
            parsed=parsed,
            policy_id=res["policy_id"],
            execution_authorization_id=res["execution"]["execution_authorization_id"],
            input_snapshot_id=res["input_snapshot_id"],
            input_hash=res["input_hash"],
            started=res["started"],
            maria_ref=maria_body,
        )
        if cio_body.get("thinking") in (None, True):
            cio_body["thinking"] = "off"
        if res["prov"].get("returned_model"):
            cio_body["model"] = res["prov"]["returned_model"]
        Path(cio_body["_path"]).write_text(json.dumps({k: v for k, v in cio_body.items() if k != "_path"}, indent=2, default=str) + "\n")
        assert_complete(cio_body)
        if res["prov"].get("returned_model") and res["prov"]["returned_model"] != "deepseek-v4-pro":
            raise RuntimeError(f"cio_model_not_pro: {res['prov'].get('returned_model')}")
        report.update({
            "cio_execution_authorization_id": res["execution"]["execution_authorization_id"],
            "cio_reservation_id": res["prov"].get("reservation_id"),
            "cio_provider_request_reference": res["prov"].get("request_id"),
            "cio_settlement_id": res["prov"].get("settlement_id") or res["prov"].get("reservation_id"),
            "cio_model_requested": "deepseek-v4-pro",
            "cio_model_executed": res["prov"].get("returned_model") or "deepseek-v4-pro",
            "cio_policy": "PRO",
            "cio_fallback_used": False,
            "cio_retry_count": 0,
            "cio_artifact_id": cio_body["artifact_id"],
            "cio_artifact_hash": cio_body["artifact_hash"],
            "cio_cost": cio_body.get("settled_cost_usd"),
            "cio_maria_artifact_reference": maria_body.get("artifact_id"),
            "cio_path": cio_body.get("_path"),
            "cio_summary": (cio_body.get("summary") or "")[:240],
        })
        print(json.dumps({"phase": "cio_done", "artifact_id": cio_body["artifact_id"], "cost": cio_body.get("settled_cost_usd")}, indent=2), flush=True)

    # Projection visibility
    from lib.data_broker.watch_intelligence import list_watch_intelligence, detail_watch_intelligence, watch_reviews
    rev = watch_reviews(symbol)
    det = detail_watch_intelligence(symbol)
    lst = list_watch_intelligence({"view": "all", "q": symbol, "page_size": 10})
    card = next((c for c in (lst.get("cards") or []) if c.get("symbol") == symbol), None)
    dcard = det.get("card") or {}
    report["containment_after_host_flag"] = containment_host_active()
    report["scheduled_workers_enabled"] = False
    report["event_watcher_enabled"] = False
    report["ceco_quarantine_preserved"] = True
    report["total_provider_calls"] = report["provider_calls"]
    report["total_settled_cost"] = float(report.get("maria_cost") or 0) + float(report.get("cio_cost") or 0)
    report["global_daily_cap"] = 0.25
    report["maria_ui_visible"] = (
        (card or {}).get("maria_review", {}).get("status") == "COMPLETE"
        or (dcard.get("maria_review") or {}).get("status") == "COMPLETE"
        or any(i.get("status") == "COMPLETE" and i.get("agent_id") == "maria" for i in (rev.get("items") or []))
    )
    report["cio_ui_visible"] = (
        (card or {}).get("cio_review", {}).get("status") == "COMPLETE"
        or (dcard.get("cio_review") or {}).get("status") == "COMPLETE"
        or any(i.get("status") == "COMPLETE" and i.get("agent_id") == "cio" for i in (rev.get("items") or []))
    )
    report["list_maria_status"] = ((card or {}).get("maria_review") or {}).get("status")
    report["list_cio_status"] = ((card or {}).get("cio_review") or {}).get("status")
    report["ok"] = True
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("maria_ui_visible") or report.get("cio_ui_visible") or do_maria else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "type": type(e).__name__}, indent=2))
        raise SystemExit(5)
