#!/usr/bin/env python3
"""Hermes Librarian Agent v2 — CLI entry point (Phase 3).

Replaces the autonomous librarian backlog loop with a full curator owning
taxonomy, knowledge graph, freshness, retention, and RAG health.

Safety:
  - dry-run by default, --apply to commit
  - kill switches: HERMES_DISABLED + LIBRARIAN_DISABLED
  - per-scope caps, audit-everything

Usage:
  python scripts/hermes_librarian_agent.py [--apply] [--scope all|taxonomy,graph,...] [--max-rows N] [--deep]
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

KILL_HERMES = ROOT / "data" / "runtime" / "HERMES_DISABLED"
KILL_LIBRARIAN = ROOT / "data" / "runtime" / "LIBRARIAN_DISABLED"


def main():
    parser = argparse.ArgumentParser(description="Hermes Librarian Agent v2")
    parser.add_argument("--apply", action="store_true", help="Apply actions (default: dry-run)")
    parser.add_argument("--scope", default="all",
                        help="Comma-separated scopes: taxonomy,graph,freshness,retention,rag_health,backlog (default: all)")
    parser.add_argument("--max-rows", type=int, default=20, help="Per-scope cap")
    parser.add_argument("--deep", action="store_true", help="Run deep pass (taxonomy backfill + graph + RAG health)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if KILL_HERMES.exists():
        print("ABORT: Kill switch active (data/runtime/HERMES_DISABLED)")
        sys.exit(1)
    if KILL_LIBRARIAN.exists():
        print("ABORT: Kill switch active (data/runtime/LIBRARIAN_DISABLED)")
        sys.exit(1)

    # Deep pass overrides scope
    scope = args.scope
    if args.deep:
        scope = "taxonomy,graph,rag_health"

    from lib.hermes_librarian.librarian import run_librarian
    result = run_librarian(apply=args.apply, scope=scope, max_rows=args.max_rows)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
    else:
        mode = result["mode"]
        print(f"[{mode.upper()}] Librarian v2: {', '.join(result['scopes_run'])}")
        for scope_name, r in result.get("results", {}).items():
            if "error" in r:
                print(f"  {scope_name}: ERROR — {r['error']}")
            elif scope_name == "taxonomy":
                print(f"  taxonomy: {r.get('tagged', 0)} tagged ({r.get('errors', 0)} errors)")
            elif scope_name == "graph":
                print(f"  graph: {r.get('edge_count', 0)} edges, {r.get('pruned_stale', 0)} stale pruned")
            elif scope_name == "rag_health":
                health = r.get("health", {})
                qa_rate = r.get("qa_pass_rate", 0)
                print(f"  rag_health: {health.get('total_embeddings', 0)} embeddings, "
                      f"{health.get('total_orphans', 0)} orphans, "
                      f"QA pass={qa_rate:.0%}")
                if health.get("queue_warning"):
                    print(f"    ⚠  {health.get('queue_message', '')}")
            else:
                summary = {k: v for k, v in r.items() if k not in ("report", "health", "retrieval_qa")}
                print(f"  {scope_name}: {summary}")


if __name__ == "__main__":
    main()
