# Phase 2A — A1A Documentation Scope

**Date:** 2026-05-14
**Phase:** 2A — Embedding A/B Baseline & RAG Discovery
**A1A Status:** ACTIVE — Phase 2 touches LLM, memory, RAG, embeddings, scripts, and documentation.

---

## 1. Why A1A Is Active

Phase 2 modifies embedding infrastructure. Per docs/A1A.md, any change to agents, LLM, memory, RAG, schema, or orchestration requires the full 8-step A1A documentation protocol.

Phase 2A specifically:
- Creates new scripts (embedding_ab_baseline.py)
- Documents current RAG architecture (new discovery doc)
- Creates Phase 2B/2C/2D design documents
- Updates deployment log and project index

Phase 2A does NOT:
- Change production embeddings
- Change production RAG routing
- Delete or overwrite nomic-embed-text embeddings
- Promote qwen3-embedding:8b to production

## 2. Active Documents Potentially Affected

| Document | Phase 2A Impact |
|----------|----------------|
| docs/project/PROJECT_DOC_INDEX.md | UPDATE — add Phase 2 doc entries |
| docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md | READ ONLY — Phase 2 source of truth |
| docs/APPENDIX_E_SCRIPT_ROUTING_MATRIX.md | DEFER — no routing change in 2A |
| docs/LLM_DATA_DICTIONARY.md | DEFER — no schema change in 2A |
| docs/MASTER_SYSTEM_DOCUMENTATION.md | DEFER — no production architecture change |
| docs/SYSTEM_ARCHITECTURE_COMPLETE.md | DEFER — no production architecture change |
| docs/ARCHITECTURE_OVERVIEW.md | DEFER — no production architecture change |
| docs/CHEAT_SHEET.md | DEFER — no new operational commands yet |
| docs/RESTORE_GUIDE.md | DEFER — no new production tables or cron |
| docs/v4_1_deployment_log.md | UPDATE — Phase 2A entry |

## 3. Documents Updated in Phase 2A

- `docs/v4_1_deployment_log.md` — Phase 2A preflight and results
- `docs/project/PROJECT_DOC_INDEX.md` — new Phase 2 document entries

## 4. Documents Left Untouched

Master architecture docs (MASTER_SYSTEM_DOCUMENTATION, SYSTEM_ARCHITECTURE_COMPLETE, ARCHITECTURE_OVERVIEW) are not updated because Phase 2A makes no production change. These will be updated in Phase 2D if/when production promotion is approved.

## 5. Authoritative Documents for Phase 2

| Document | Authority |
|----------|-----------|
| docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md | Phase 2 design, model selection, A/B requirements |
| docs/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md | Execution gates, hard rules |
| docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md | Operator verification steps |
| docs/v4_1_phase1_final_closeout_report.md | Phase 1→2 transition requirements |
