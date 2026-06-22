# Documentation Drift Report

## 2026-06-22 — A1A consolidation (live-facts pointers)

**Policy change:** Canonical active docs no longer hard-code scale counts. Use `docs/LIVE_SYSTEM_FACTS.md`
+ `scripts/generate_system_facts.py`. Drift detector tightened (no CHANGELOG/_archive scans; fewer false positives).

| Prior stale claim | Resolution |
|---|---|
| 330–426 tables in MASTER/CHEAT_SHEET/COST_MODEL | → `database.table_count` pointer |
| 184–306 crons | → `codebase.cron_job_count` pointer |
| 26 vs 23 strategies | → 23 live; pointer in MASTER + EXECUTIVE |
| 401 vs 989 Python scripts | → `codebase.python_script_count` pointer |

Closeout: `docs/project/DOCS_CONSOLIDATION_2026_06_22.md`

---

## 2026-06-02 (original audit)

Doc claims vs **live** system (validated read-only). Source-of-truth commands in parentheses.

## Count drift (corrected in MASTER)
| Claim | Stale value(s) in docs | **Live (validated)** | Action |
|---|---|---|---|
| DB tables | 330 / 333 / 334 / 341 / 344 / 392 | **426 tables + 23 views** (`information_schema`) | MASTER fixed; others = historical snapshots (archive) |
| Cron jobs | 53 / 85 / 118 / 152 / 176 / 181 / 187 | **184 non-comment** (`crontab -l`) | MASTER fixed |
| Strategies | 23 / 24 | **26** (`config/strategies/*.yaml`) | MASTER fixed |
| Dashboard | "v2, 61/70+ pages" | **v3 canonical** (11 hubs, ~37/39 tabs); v2 frozen | MASTER fixed |

Older numbers are not "wrong" — they are point-in-time snapshots. Policy: phase/audit reports keep
their historical numbers (they are records); only **authoritative** docs carry live-validated counts.

## Model-policy drift (qwen3)
**Live (`ollama list`):** gemma3:12b (primary chat), gemma3:4b (fallback), gemma3:27b/overnight,
qwen3-embedding:8b (**embeddings — present**), nomic-embed-text. **qwen3:14b (chat) is absent /
disabled / uninstalled.** Many "qwen3" doc refs are about the *embedding* model and are CORRECT; only
"qwen3:14b active chat model" claims are stale.

| Doc | qwen3 refs | Disposition |
|---|---|---|
| `LLM_FLEET_STRATEGY_v4_1_FINAL.md` | 56 | Mostly embedding A/B (correct) — banner added |
| `AGENT_ROSTER.md` | 18 | chat-routing refs stale — banner added |
| `APPENDIX_E_SCRIPT_ROUTING_MATRIX.md` | 8 | routing refs stale — banner added |
| `ARCHITECTURE_OVERVIEW.md` | 6 | already index-ARCHIVED — **moved to _archive** |
| `RESTORE_GUIDE.md` | 3 | banner added |
| `LLM_DATA_DICTIONARY.md` | 2 | banner added |
| `OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md` | 2 | banner added |
| `COST_MODEL.md`, `GPU_OLLAMA_SETUP.md`, `AGENT_PAGES_DETAIL.md` | 1 each | banner added |

Banner points readers to MASTER §12 for the authoritative, validated model policy. Full per-line
rewrite of routing matrices deferred (low risk; banner resolves the conflict for readers).

## Duplicate architecture docs (resolved)
- `ARCHITECTURE_OVERVIEW.md` (root, stale) → `_archive/`
- `project/SYSTEM_ARCHITECTURE_COMPLETE.md` + `atm_audit_2026_05_26/SYSTEM_ARCHITECTURE_COMPLETE.md`
  → exact/near duplicates; non-canonical copies flagged for delete/archive (see delete_list).
- **MASTER_SYSTEM_DOCUMENTATION.md is the only technical canon.**

## Safety posture (validated — no drift)
`ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, `ENABLE_ALPACA_PAPER=true`, Level 7 prohibited,
`tradeai-portfolio-server.service` active. ✓
