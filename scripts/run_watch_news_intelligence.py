#!/usr/bin/env python3
"""Watch News Intelligence worker — DeepSeek FAST (+ deferred oversight).

Usage:
  # Deterministic refresh only (no LLM): write freshness from DB
  PYTHONPATH=scripts python3 scripts/run_watch_news_intelligence.py --symbols BETA,CECO --deterministic-only

  # One governed DeepSeek canary (paid)
  LLM_GLOBAL_DAILY_USD_CAP=0.25 PYTHONPATH=scripts \\
    python3 scripts/run_watch_news_intelligence.py --symbols BETA --canary --limit 1

Never intended for page-load. Advisory only. No broker authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("LLM_GLOBAL_DAILY_USD_CAP", "0.25")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode()).hexdigest()


def process_symbol(symbol: str, *, use_llm: bool, company: str | None = None) -> dict:
    from lib.data_broker.news_intelligence import (
        PROCESS_ID,
        WORKER_MODEL,
        WORKER_POLICY,
        build_worker_prompt,
        compute_freshness,
        load_db_catalysts,
        load_db_headlines,
        parse_worker_json,
        run_oversight_stub,
        write_news_artifact,
    )

    sym = symbol.upper()
    headlines = load_db_headlines(sym)
    catalysts = load_db_catalysts(sym)
    source_mix = []
    for h in headlines:
        if h.get("source") and h["source"] not in source_mix:
            source_mix.append(h["source"])
    for c in catalysts:
        if c.get("source") and c["source"] not in source_mix:
            source_mix.append(str(c["source"]))

    base_as_of = None
    if headlines:
        base_as_of = headlines[0].get("published_at")
    if catalysts and not base_as_of:
        base_as_of = catalysts[0].get("at")

    payload = {
        "symbol": sym,
        "as_of": _now_iso(),
        "source_mix": source_mix or ["none"],
        "headlines": headlines[:8],
        "status": "NO_MATERIAL",
        "catalyst_summary": None,
        "catalyst_type": "none",
        "severity": "low",
        "catalyst_as_of": base_as_of,
        "catalyst_freshness": compute_freshness(base_as_of),
        "worker": None,
        "oversight": {"status": "SKIPPED", "notes": "deterministic_only", "at": _now_iso()},
        "input_hash": _sha(json.dumps({"h": headlines, "c": catalysts}, default=str)),
        "provider_calls": 0,
    }

    if not use_llm:
        # Promote best DB headline as summary when present
        if catalysts:
            payload["catalyst_summary"] = catalysts[0].get("headline")
            payload["catalyst_type"] = catalysts[0].get("type") or "news"
            payload["severity"] = catalysts[0].get("severity") or "low"
            payload["status"] = "COMPLETE" if payload["catalyst_summary"] else "NO_MATERIAL"
        elif headlines:
            payload["catalyst_summary"] = headlines[0].get("title")
            payload["catalyst_type"] = "news"
            payload["status"] = "COMPLETE"
        payload["catalyst_freshness"] = compute_freshness(payload.get("catalyst_as_of"))
        if not payload.get("catalyst_summary"):
            payload["catalyst_freshness"] = "MISSING"
            payload["status"] = "NO_MATERIAL"
        path = write_news_artifact(payload)
        payload["path"] = str(path)
        return payload

    # LLM path
    from lib import llm_consumption as lc

    prompt = build_worker_prompt(sym, company, headlines, catalysts)
    text, prov = lc.gate_and_generate(
        prompt,
        lane="deepseek-flash",
        process_id=PROCESS_ID,
        task_summary=f"watch_news_intel:{sym}"[:160],
        manual_trigger=False,
        timeout=90,
        model=WORKER_MODEL,
        policy=WORKER_POLICY,
        max_tokens=450,
        metadata={"symbol": sym, "agent": "news_intelligence", "fallback_used": False},
        return_provenance=True,
    )
    parsed = parse_worker_json(text)
    material = bool(parsed.get("material", True))
    summary = parsed.get("catalyst_summary")
    if not material or not summary:
        payload["status"] = "NO_MATERIAL"
        payload["catalyst_summary"] = summary or "No material catalyst in recent window"
        payload["catalyst_type"] = "none"
        payload["severity"] = "low"
    else:
        payload["status"] = "COMPLETE"
        payload["catalyst_summary"] = str(summary)[:200]
        payload["catalyst_type"] = parsed.get("catalyst_type") or "news"
        payload["severity"] = parsed.get("severity") or "med"
    # Agent synthesis time drives FRESH chip; retain source headline times in headlines[]
    payload["source_headline_as_of"] = base_as_of
    payload["catalyst_as_of"] = _now_iso()
    payload["catalyst_freshness"] = compute_freshness(payload["catalyst_as_of"])
    payload["worker"] = {
        "process_id": PROCESS_ID,
        "model": prov.get("returned_model") or WORKER_MODEL,
        "policy": WORKER_POLICY,
        "thinking": "off",
        "fallback_used": bool(prov.get("fallback_used", False)),
        "request_id": prov.get("request_id") or prov.get("client_request_id"),
        "reservation_id": prov.get("reservation_id"),
        "settlement_id": prov.get("settlement_id") or prov.get("reservation_id"),
        "cost": prov.get("estimated_cost_usd"),
        "completed_at": _now_iso(),
    }
    payload["parsed"] = {
        "what_changed": parsed.get("what_changed"),
        "risks": parsed.get("risks") or [],
        "evidence_refs": parsed.get("evidence_refs") or [],
    }
    payload["oversight"] = run_oversight_stub(parsed)
    payload["provider_calls"] = 1
    if payload["worker"].get("fallback_used"):
        raise RuntimeError("fallback_not_allowed")
    path = write_news_artifact(payload)
    payload["path"] = str(path)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="Comma symbols; default small priority set")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--deterministic-only", action="store_true")
    ap.add_argument("--canary", action="store_true", help="Allow paid DeepSeek calls")
    args = ap.parse_args()

    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        syms = ["BETA", "CECO", "FTH", "DXCM", "V"]
    syms = syms[: max(1, args.limit)]

    use_llm = bool(args.canary) and not args.deterministic_only
    if use_llm:
        # seed process config
        from lib import llm_consumption as lc
        lc.ensure_schema()
        try:
            lc._seed_registry()
        except Exception:
            pass

    results = []
    for sym in syms:
        try:
            r = process_symbol(sym, use_llm=use_llm)
            results.append({
                "symbol": sym,
                "status": r.get("status"),
                "freshness": r.get("catalyst_freshness"),
                "summary": (r.get("catalyst_summary") or "")[:120],
                "provider_calls": r.get("provider_calls", 0),
                "path": r.get("path"),
            })
            print(json.dumps(results[-1], indent=2))
        except Exception as e:
            results.append({"symbol": sym, "error": str(e), "provider_calls": 0})
            print(json.dumps(results[-1], indent=2))

    print(json.dumps({
        "ok": True,
        "mode": "llm" if use_llm else "deterministic",
        "n": len(results),
        "total_provider_calls": sum(int(r.get("provider_calls") or 0) for r in results),
        "results": results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
