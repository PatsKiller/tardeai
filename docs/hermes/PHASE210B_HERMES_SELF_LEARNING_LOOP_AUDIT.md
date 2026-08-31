# Phase 210B — Hermes Self-Learning Loop Audit (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:42:19-04:00
Measured at: efcc51365 / not measured

Script: `scripts/audit_hermes_self_learning_loops.py` → `data/hermes/hermes_self_learning_loop_audit_latest.json`.

## Conclusions
- **Closed-loop learning: PARTIAL (by design)** — observe → normalize → evaluate → promote is wired
  (advisory + RAG); **direct scoring changes remain a separate operator-gated graft** (no silent mutation).
- Advisory-only loops: **10/10**. Loops affecting future prompts: **8**. Loops directly affecting scoring: **0**.
- Loops not yet wired: **none** (all 10 have live data).

## Loops (live)
| Loop | Table | Rows | Learns | →prompts | →scoring |
|------|-------|------|--------|----------|----------|
| closed trade outcomes | proposal_outcome_chain | 169 | predicted vs realized | yes | no |
| post-exit edge comparison | trade_edge_comparison | 101 | captured vs potential edge | yes | no |
| trade-close LLM reviews | trade_llm_reviews | 2105 | per-trade lessons | yes | no |
| shadow candidate scoring | candidate_shadow_scores | 57 | shadow tweaks | yes | no |
| shadow efficacy graft gate | candidate_shadow_efficacy | 3 | hit-rate (graft gate) | gated | gated |
| research intelligence | hermes_research_intelligence | 1980 | staged findings | yes | no |
| promotion audit | hermes_promotion_audit | 1980 | promoted findings | yes | no |
| coordination memory | hermes_memory_events | 439 | coordination logs | no | no |
| agent calibration | agent_performance_history | 22 | agent accuracy | yes | no |
| RAG embeddings | content_embeddings | 39955 | promoted knowledge | yes | no |

## Highest-priority gaps
1. Dedicated `hermes_research_backlog` table not created (backlog = tagged rows).
2. External-researcher feedback loop not yet implemented (designed in 210D/G).
3. shadow_efficacy below graft sample (3 rows) — keep advisory until MIN_SAMPLES met.
