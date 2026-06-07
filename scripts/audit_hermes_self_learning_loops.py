#!/usr/bin/env python3
"""audit_hermes_self_learning_loops.py — map Hermes/TradeAI self-learning loops (Phase 210B/213). Read-only.
Output: data/hermes/hermes_self_learning_loop_audit_latest.json"""
import os, json
from pathlib import Path
import psycopg2

for ln in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip())

# loop definitions. status_col = column distinguishing queued vs completed (None = append-only log).
# steps = the process stages (for drill-down). drill_col = timestamp column for recent-items drill-down.
LOOPS = [
    {"loop": "closed_trade_outcomes", "table": "proposal_outcome_chain", "what_learned": "predicted vs realized trade outcome",
     "prompts": True, "scoring": False, "advisory": True, "approval": True, "page": "Journal/Backtesting",
     "status_col": "status", "steps": ["trade closes", "match proposal→outcome", "score prediction vs realized", "feed advisory"]},
    {"loop": "post_exit_edge_comparison", "table": "trade_edge_comparison", "what_learned": "captured vs potential edge (MFE/left-on-table)",
     "prompts": True, "scoring": False, "advisory": True, "approval": True, "page": "Backtesting",
     "status_col": None, "steps": ["post-exit price path", "compute MFE/MAE vs captured", "store edge gap", "surface advisory"]},
    {"loop": "trade_close_llm_reviews", "table": "trade_llm_reviews", "what_learned": "per-trade lessons (strengths/weaknesses)",
     "prompts": True, "scoring": False, "advisory": True, "approval": True, "page": "Journal/AI Trade Eval",
     "status_col": "status", "steps": ["closed trade queued", "build context", "LLM review (gemma3)", "store lesson", "feed RAG"]},
    {"loop": "shadow_candidate_scoring", "table": "candidate_shadow_scores", "what_learned": "shadow scores for candidate tweaks",
     "prompts": True, "scoring": False, "advisory": True, "approval": True, "page": "(shadow)",
     "status_col": None, "steps": ["candidate tweak proposed", "shadow-score offline", "record score", "await graft gate"]},
    {"loop": "shadow_efficacy_graft_gate", "table": "candidate_shadow_efficacy", "what_learned": "hit-rate of shadow scores (graft gate MIN 20/0.60)",
     "prompts": False, "scoring": "gated", "advisory": True, "approval": True, "page": "(shadow)",
     "status_col": None, "steps": ["accumulate shadow outcomes", "compute hit-rate", "check MIN_SAMPLES=20/HITRATE=0.60", "operator graft gate"]},
    {"loop": "research_intelligence", "table": "hermes_research_intelligence", "what_learned": "staged research findings + status",
     "prompts": True, "scoring": False, "advisory": True, "approval": False, "page": "/v3/hermes",
     "status_col": "status", "steps": ["agent researches", "stage finding", "librarian routes", "embed/promote/backlog"]},
    {"loop": "promotion_audit", "table": "hermes_promotion_audit", "what_learned": "which findings promoted (advisory)",
     "prompts": True, "scoring": False, "advisory": True, "approval": False, "page": "/v3/hermes",
     "status_col": None, "steps": ["promotion-review decision", "record audit", "publish to RAG"]},
    {"loop": "coordination_memory", "table": "hermes_memory_events", "what_learned": "coordinator/agent coordination logs",
     "prompts": False, "scoring": False, "advisory": True, "approval": False, "page": "/v3/hermes",
     "status_col": None, "steps": ["agent emits event", "append memory log"]},
    {"loop": "agent_calibration", "table": "agent_performance_history", "what_learned": "agent accuracy/calibration snapshots",
     "prompts": True, "scoring": False, "advisory": True, "approval": False, "page": "Agents",
     "status_col": None, "steps": ["agent makes call", "compare to outcome", "snapshot calibration", "feed advisory weighting"]},
    {"loop": "rag_embeddings", "table": "content_embeddings", "what_learned": "promoted knowledge → RAG context",
     "prompts": True, "scoring": False, "advisory": True, "approval": True, "page": "Intelligence",
     "status_col": None, "steps": ["finding promoted", "embed", "publish to content_embeddings", "RAG context at prompt-time"]},
    {"loop": "external_researcher_feedback", "table": "hermes_external_research", "what_learned": "external lane recommendation usefulness vs outcome",
     "prompts": True, "scoring": False, "advisory": True, "approval": True, "page": "/v3/hermes (LLM Auth)",
     "status_col": "status", "steps": ["external lane queried (operator)", "store recommendation", "score usefulness vs outcome (gemma3)", "per-lane usefulness → advisory lane routing"]},
]


def main():
    c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                         user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    cur = c.cursor()

    def has_col(t, col):
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (t, col))
        return bool(cur.fetchone())

    def stat(t, status_col):
        try:
            cur.execute(f"SELECT count(*) FROM {t}"); n = cur.fetchone()[0]
            last = None
            if has_col(t, "created_at"):
                cur.execute(f"SELECT max(created_at) FROM {t}"); last = str(cur.fetchone()[0])
            queued = completed = None
            if status_col and has_col(t, status_col):
                cur.execute(f"SELECT count(*) FROM {t} WHERE lower(coalesce({status_col}::text,'')) "
                            f"IN ('pending','queued','open','staged','new')"); queued = cur.fetchone()[0]
                completed = n - (queued or 0)
            return {"exists": True, "rows": n, "last": last, "queued": queued, "completed": completed}
        except Exception:
            c.rollback(); return {"exists": False}

    rows = []
    for d in LOOPS:
        s = stat(d["table"], d.get("status_col"))
        rows.append({"loop": d["loop"], "table": d["table"], **s, "what_learned": d["what_learned"],
                     "affects_future_prompts": d["prompts"], "affects_scoring": d["scoring"],
                     "advisory_only": d["advisory"], "human_approval_required": d["approval"], "v3_page": d["page"],
                     "status_col": d.get("status_col"), "process_steps": d["steps"],
                     "wired": s.get("exists") and (s.get("rows", 0) > 0)})
    advisory_cnt = sum(1 for r in rows if r["advisory_only"])
    prompt_cnt = sum(1 for r in rows if r["affects_future_prompts"] is True)
    scoring_cnt = sum(1 for r in rows if r["affects_scoring"] is True)
    not_wired = [r["loop"] for r in rows if not r["wired"]]
    out = {"generated_note": "Phase 210B/213 self-learning loop audit (drill-down enabled)",
           "closed_loop_status": "PARTIAL — observe/normalize/evaluate/promote wired (advisory + RAG); "
                                 "scoring changes remain a separate operator-gated graft (by design)",
           "loop_count": len(rows), "advisory_only_loops": advisory_cnt,
           "loops_affecting_prompts": prompt_cnt, "loops_affecting_scoring_directly": scoring_cnt,
           "loops_not_yet_wired": not_wired,
           "highest_priority_gaps": ["dedicated research_backlog table not created",
                                     "shadow-efficacy below graft sample — keep advisory until MIN 20/0.60"],
           "loops": rows}
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_self_learning_loop_audit_latest.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: out[k] for k in ("closed_loop_status", "loop_count", "advisory_only_loops",
          "loops_affecting_prompts", "loops_affecting_scoring_directly", "loops_not_yet_wired")}, indent=2))
    print("loops:", [(r["loop"], r.get("rows"), r["wired"]) for r in rows])
    c.close()


if __name__ == "__main__":
    main()
