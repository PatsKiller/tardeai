#!/usr/bin/env python3
"""audit_hermes_self_learning_loops.py — map Hermes/TradeAI self-learning loops (Phase 210B). Read-only.
Output: data/hermes/hermes_self_learning_loop_audit_latest.json"""
import os, json
from pathlib import Path
import psycopg2

for ln in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip())

# loop definitions: (name, table, what_learned, affects_prompts, affects_scoring, advisory_only, human_approval, v3_page)
LOOPS = [
    ("closed_trade_outcomes", "proposal_outcome_chain", "predicted vs realized trade outcome", True, False, True, True, "Journal/Backtesting"),
    ("post_exit_edge_comparison", "trade_edge_comparison", "captured vs potential edge (MFE/left-on-table)", True, False, True, True, "Backtesting"),
    ("trade_close_llm_reviews", "trade_llm_reviews", "per-trade lessons (strengths/weaknesses)", True, False, True, True, "Journal/AI Trade Eval"),
    ("shadow_candidate_scoring", "candidate_shadow_scores", "shadow scores for candidate signal/strategy tweaks", True, False, True, True, "(shadow)"),
    ("shadow_efficacy_graft_gate", "candidate_shadow_efficacy", "hit-rate of shadow scores (graft gate MIN 20/0.60)", False, "gated", True, True, "(shadow)"),
    ("research_intelligence", "hermes_research_intelligence", "staged research findings + status", True, False, True, False, "/v3/hermes"),
    ("promotion_audit", "hermes_promotion_audit", "which findings promoted (advisory)", True, False, True, False, "/v3/hermes"),
    ("coordination_memory", "hermes_memory_events", "coordinator/agent coordination logs", False, False, True, False, "/v3/hermes"),
    ("agent_calibration", "agent_performance_history", "agent accuracy/calibration snapshots", True, False, True, False, "Agents"),
    ("rag_embeddings", "content_embeddings", "promoted knowledge → RAG context", True, False, True, True, "Intelligence"),
]


def main():
    c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                         user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    cur = c.cursor()
    def stat(t):
        try:
            cur.execute(f"SELECT count(*) FROM {t}"); n = cur.fetchone()[0]
            last = None
            cur.execute(f"SELECT 1 FROM information_schema.columns WHERE table_name='{t}' AND column_name='created_at'")
            if cur.fetchone():
                cur.execute(f"SELECT max(created_at) FROM {t}"); last = str(cur.fetchone()[0])
            return {"exists": True, "rows": n, "last": last}
        except Exception:
            c.rollback(); return {"exists": False}
    rows = []
    for (name, table, learned, prompts, scoring, advisory, approval, page) in LOOPS:
        s = stat(table)
        rows.append({"loop": name, "table": table, **s, "what_learned": learned,
                     "affects_future_prompts": prompts, "affects_scoring": scoring,
                     "advisory_only": advisory, "human_approval_required": approval, "v3_page": page,
                     "wired": s.get("exists") and (s.get("rows", 0) > 0)})
    advisory_cnt = sum(1 for r in rows if r["advisory_only"])
    prompt_cnt = sum(1 for r in rows if r["affects_future_prompts"] is True)
    scoring_cnt = sum(1 for r in rows if r["affects_scoring"] is True)
    not_wired = [r["loop"] for r in rows if not r["wired"]]
    out = {"generated_note": "Phase 210B self-learning loop audit",
           "closed_loop_status": "PARTIAL — observe/normalize/evaluate/promote wired (advisory + RAG); "
                                 "scoring changes remain a separate operator-gated graft (by design)",
           "loop_count": len(rows), "advisory_only_loops": advisory_cnt,
           "loops_affecting_prompts": prompt_cnt, "loops_affecting_scoring_directly": scoring_cnt,
           "loops_not_yet_wired": not_wired,
           "highest_priority_gaps": ["dedicated research_backlog table not created",
                                     "external-researcher feedback loop not yet implemented",
                                     "shadow-efficacy below graft sample (3 rows) — keep advisory"],
           "loops": rows}
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_self_learning_loop_audit_latest.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: out[k] for k in ("closed_loop_status", "loop_count", "advisory_only_loops",
          "loops_affecting_prompts", "loops_affecting_scoring_directly", "loops_not_yet_wired")}, indent=2))
    print("loops:", [(r["loop"], r.get("rows"), r["wired"]) for r in rows])
    c.close()


if __name__ == "__main__":
    main()
