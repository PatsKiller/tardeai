#!/usr/bin/env python3
"""phase2g_hybrid_canary_retrieval.py — Canary-guarded hybrid retrieval for approved offline workflows.
Enforces Phase 2G policy before any retrieval. Does NOT change production RAG routing.

Usage:
    .venv/bin/python scripts/phase2g_hybrid_canary_retrieval.py \
        --workflow risk_synthesis --query "RTX recovery evidence" --symbol RTX --verbose
"""
import argparse, json, sys, time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from phase2g_hybrid_canary_policy import load_policy, assert_canary_allowed, get_retrieval_config

def log(msg):
    from datetime import datetime
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2g-canary] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser(description="Phase 2G canary-guarded hybrid retrieval")
    p.add_argument("--workflow", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--symbol", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    policy = load_policy(args.config)

    # Enforce canary policy
    try:
        assert_canary_allowed(args.workflow, policy)
    except RuntimeError as e:
        result = {"status": "BLOCKED", "workflow": args.workflow, "reason": str(e)}
        if args.verbose:
            log(f"BLOCKED: {e}")
        if args.output_json:
            Path(args.output_json).write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        sys.exit(1)

    if args.verbose:
        log(f"Workflow '{args.workflow}' ALLOWED by canary policy")

    if args.dry_run:
        result = {"status": "DRY_RUN", "workflow": args.workflow, "query": args.query,
                  "symbol": args.symbol, "would_run": "hybrid_retrieval"}
        print(json.dumps(result, indent=2))
        return

    # Run hybrid retrieval
    from hybrid_rag_context_adapter import get_hybrid_context
    rc = get_retrieval_config(policy)

    start = time.monotonic()
    hybrid = get_hybrid_context(
        query=args.query, symbol=args.symbol, workflow=args.workflow,
        final_k=rc.get("final_k", 10),
        top_k_baseline=rc.get("top_k_nomic", 10),
        top_k_candidate=rc.get("top_k_qwen3", 10))
    elapsed = round((time.monotonic() - start) * 1000, 1)

    m = hybrid.get("metrics", {})
    result = {
        "status": "OK", "workflow": args.workflow, "query": args.query,
        "symbol": args.symbol, "canary_phase": "phase2g",
        "total_latency_ms": elapsed,
        "nomic_latency_ms": m.get("baseline_latency_ms"),
        "qwen3_latency_ms": m.get("candidate_latency_ms"),
        "source_diversity": m.get("source_type_count"),
        "nomic_only": m.get("nomic_only_count"), "qwen3_only": m.get("qwen3_only_count"),
        "consensus": m.get("consensus_count"), "fallback_used": m.get("fallback_used"),
        "result_count": len(hybrid.get("results", [])),
        "context_preview": (hybrid.get("final_context_text") or "")[:300],
    }

    if args.verbose:
        log(f"OK: sources={m.get('source_type_count')} nomic={m.get('nomic_only_count')} "
            f"qwen3={m.get('qwen3_only_count')} consensus={m.get('consensus_count')} "
            f"lat={elapsed}ms fallback={m.get('fallback_used')}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
