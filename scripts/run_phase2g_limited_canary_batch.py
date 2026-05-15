#!/usr/bin/env python3
"""run_phase2g_limited_canary_batch.py — Run Phase 2G canary batch across approved workflows.
Compares nomic-only vs hybrid evidence quality. Does NOT change production RAG routing.

Usage:
    .venv/bin/python scripts/run_phase2g_limited_canary_batch.py --dry-run --limit 25 --verbose
    .venv/bin/python scripts/run_phase2g_limited_canary_batch.py --limit 25 --verbose \
        --output-json docs/llm_fleet/phase2_embedding_ab/v4_1_phase2g_limited_canary_results.json \
        --output-md docs/llm_fleet/phase2_embedding_ab/v4_1_phase2g_limited_canary_report.md
"""
import argparse, json, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from phase2g_hybrid_canary_policy import load_policy, is_workflow_allowed, get_retrieval_config, get_limits

# Canary test queries by workflow
CANARY_QUERIES = {
    "risk_synthesis": [
        ("RTX", "Find risk evidence and stop placement for RTX"),
        ("AVAV", "Show risk synthesis and unprotected position evidence for AVAV"),
        ("LMT", "What prior risk synthesis evidence exists for LMT"),
    ],
    "recovery_watch_review": [
        ("RTX", "What evidence supports recovery or re-entry for RTX"),
        ("IRDM", "Show recovery watch evidence and prior exit reasons for IRDM"),
        ("TDG", "Find recovery watch and re-entry evidence for TDG"),
    ],
    "closed_trade_review": [
        ("None", "Find closed trades where MFE was high but realized profit was low"),
        ("None", "Show closed trades with early exit patterns"),
        ("None", "Find closed trades that followed their plan vs deviated"),
    ],
    "manual_journal_review": [
        ("None", "Find journal evidence about stop placement decisions"),
        ("None", "Show manual journal entries about position sizing"),
    ],
    "proposal_review": [
        ("BLBD", "Find proposal evidence and prior outcomes for BLBD"),
        ("RKLB", "Show proposal review context and risk for RKLB"),
        ("None", "Find proposals that were approved but had negative outcomes"),
    ],
    "rag_content_curation": [
        ("None", "Find low-quality RAG content that should be curated out"),
        ("None", "Show RAG content with high relevance to defense sector rotation"),
    ],
}

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2g-batch] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser(description="Phase 2G canary batch")
    p.add_argument("--config", default=None)
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--workflows", default=None, help="Comma-separated workflow filter")
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    policy = load_policy(args.config)
    if not policy.get("enabled"):
        log("ABORT: Canary not enabled"); sys.exit(1)

    rc = get_retrieval_config(policy)
    wf_filter = set(args.workflows.split(",")) if args.workflows else None

    # Build query list from approved workflows
    queries = []
    for wf, qs in CANARY_QUERIES.items():
        if wf_filter and wf not in wf_filter:
            continue
        if not is_workflow_allowed(wf, policy):
            continue
        for sym, q in qs:
            queries.append({"workflow": wf, "symbol": sym if sym != "None" else None, "query": q})

    queries = queries[:args.limit]
    log(f"Canary batch: {len(queries)} queries across {len(set(q['workflow'] for q in queries))} workflows")

    if args.dry_run:
        log("DRY RUN — would run these queries:")
        for i, q in enumerate(queries, 1):
            log(f"  {i}. [{q['workflow']}] {q.get('symbol', '')} — {q['query'][:60]}")
        return

    from hybrid_rag_context_adapter import get_hybrid_context

    results = []
    start = time.monotonic()

    for i, q in enumerate(queries, 1):
        try:
            r = get_hybrid_context(query=q["query"], symbol=q.get("symbol"),
                                   workflow=q["workflow"], final_k=rc.get("final_k", 10),
                                   top_k_baseline=rc.get("top_k_nomic", 10),
                                   top_k_candidate=rc.get("top_k_qwen3", 10))
            m = r.get("metrics", {})
            entry = {
                "query": q["query"], "workflow": q["workflow"], "symbol": q.get("symbol"),
                "status": "ok", "source_diversity": m.get("source_type_count"),
                "nomic_only": m.get("nomic_only_count"), "qwen3_only": m.get("qwen3_only_count"),
                "consensus": m.get("consensus_count"), "fallback_used": m.get("fallback_used"),
                "total_latency_ms": m.get("total_latency_ms"),
                "nomic_latency_ms": m.get("baseline_latency_ms"),
                "qwen3_latency_ms": m.get("candidate_latency_ms"),
            }
            if args.verbose:
                log(f"  [{i}/{len(queries)}] {q['workflow']} {q.get('symbol','')} — "
                    f"div={m.get('source_type_count')} nomic={m.get('nomic_only_count')} "
                    f"qwen3={m.get('qwen3_only_count')} consensus={m.get('consensus_count')} "
                    f"lat={m.get('total_latency_ms',0):.0f}ms fb={m.get('fallback_used')}")
        except Exception as e:
            entry = {"query": q["query"], "workflow": q["workflow"], "status": "error", "error": str(e)}
            if args.verbose:
                log(f"  [{i}/{len(queries)}] FAILED: {e}")
        results.append(entry)

    elapsed = round(time.monotonic() - start, 1)

    # Aggregate
    ok = [r for r in results if r.get("status") == "ok"]
    agg = {
        "total": len(results), "ok": len(ok), "errors": len(results) - len(ok),
        "elapsed_s": elapsed,
        "avg_diversity": round(sum(r.get("source_diversity", 0) for r in ok) / max(len(ok), 1), 1),
        "avg_nomic_only": round(sum(r.get("nomic_only", 0) for r in ok) / max(len(ok), 1), 1),
        "avg_qwen3_only": round(sum(r.get("qwen3_only", 0) for r in ok) / max(len(ok), 1), 1),
        "avg_consensus": round(sum(r.get("consensus", 0) for r in ok) / max(len(ok), 1), 1),
        "avg_latency_ms": round(sum(r.get("total_latency_ms", 0) for r in ok) / max(len(ok), 1), 0),
        "fallback_count": sum(1 for r in ok if r.get("fallback_used")),
        "workflows_tested": list(set(r["workflow"] for r in ok)),
    }

    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "phase": "phase2g_limited_canary",
              "aggregate": agg, "results": results, "production_changed": False}

    log(f"Batch complete: {agg['ok']}/{agg['total']} ok, {agg['errors']} errors, {elapsed}s")
    log(f"Diversity: {agg['avg_diversity']}, Nomic: {agg['avg_nomic_only']}, "
        f"Qwen3: {agg['avg_qwen3_only']}, Consensus: {agg['avg_consensus']}, "
        f"Fallback: {agg['fallback_count']}, Latency: {agg['avg_latency_ms']}ms")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        lines = ["# Phase 2G Limited Canary Report", f"\n**Date:** {datetime.now().strftime('%Y-%m-%d')}",
                 f"\n## Aggregate\n", f"| Metric | Value |", f"|--------|-------|",
                 f"| Queries | {agg['total']} |", f"| OK | {agg['ok']} |",
                 f"| Errors | {agg['errors']} |", f"| Elapsed | {elapsed}s |",
                 f"| Avg diversity | {agg['avg_diversity']} |",
                 f"| Avg nomic-only | {agg['avg_nomic_only']} |",
                 f"| Avg qwen3-only | {agg['avg_qwen3_only']} |",
                 f"| Avg consensus | {agg['avg_consensus']} |",
                 f"| Avg latency | {agg['avg_latency_ms']}ms |",
                 f"| Fallbacks | {agg['fallback_count']} |",
                 f"| Workflows | {', '.join(agg['workflows_tested'])} |",
                 f"\n## Production Impact\n\nNone. Production RAG routing unchanged.\n"]
        Path(args.output_md).write_text("\n".join(lines))

if __name__ == "__main__":
    main()
