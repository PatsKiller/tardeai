# Hermes Maturity Audit Remediation — 2026-06-24

**Date:** 2026-06-24  
**Status:** REMEDIATION COMPLETE  
**Related:** Hermes Maturity Dashboard, Operator Directive B, Embedding Pipeline, Global Profiles

## Executive Summary

A full maturity audit of Hermes (as integrated sidecar for Trade AI) identified several operational gaps. The following six prioritized remediations were executed:

1. **Embedding failures** — Primary issue was repeated timeouts in `hermes_embedding_worker.py` (723 failed rows, all `'timed out'`).
2. **openai-codex provider** — Interactive Hermes profiles (`hermes chat`, tradeai profile) were defaulting to a deactivated ChatGPT codex backend (repeated 402 errors).
3. **Backpressure** — Auto-promote could outrun embedding throughput; no guard against backlog growth.
4. **Cleanup / hygiene** — Large retired sidecar artifacts (355MB+) and migration snapshots left behind.
5. **Tests** — Lacked basic smoke/integration coverage for coordinator + promotion paths.
6. **Directive B visibility** — "Challenger wall open" state (ungated promote + RAG) was not clearly surfaced in live tooling.

## Changes Delivered

### 1. Embedding Robustness
- Increased `EMBED_TIMEOUT` from 30s → 120s in `scripts/hermes_embedding_worker.py`.
- Added 3-attempt retry with exponential backoff in `get_embedding()`.
- Raised default `--limit` to 15; synced coordinator caps (`CAP_EMBED=15`, reset=20).
- Ran live recovery batches (`--reset-failed --retry-failed --apply`).
- **Impact**: Failed count reduced, throughput improved. Still recommend monitoring Ollama `nomic-embed-text` / `qwen3-embedding:8b` latency.

### 2. Interactive Provider Fix
- Updated `~/.hermes/auth.json`: `active_provider` changed from `openai-codex` to `xai-oauth`.
- Added explicit comments in:
  - `~/.hermes/config.yaml`
  - `~/.hermes/profiles/tradeai/config.yaml`
  - `~/.hermes/profiles/tradeai12b/config.yaml`
- Codex path is now deprioritized. Local Ollama (gemma3) + xAI proxy are preferred.

### 3. Backpressure on Auto-Promote
- Added dynamic throttling logic in `auto_promote()` inside `scripts/hermes_coordinator.py`:
  - `pending > 150` → effective cap reduced to ~½
  - `pending > 80` → modest reduction
- Log messages now indicate when throttled.
- Updated `hermes_maturity_dashboard.py` caps for consistency.

### 4. Hygiene Cleanup
- Removed retired artifacts:
  - `hermes_sidecar/install.RETIRED_20260606_2140/` (~355 MB)
  - `.hermes.RETIRED_*` markers
  - `~/.hermes/migration_from_tradeai_sidecar_20260606/`
- Added `scripts/hermes_hygiene_cleanup.sh` (safe, documented, executable) for future runs.
- Focused on retired sidecar material only; live profiles/state untouched.

### 5. Smoke & Integration Tests
- Created `scripts/test_hermes_coordinator_promotion_smoke.py` (follows project `test_*.py` convention in scripts/).
- Covers:
  - Imports + caps
  - Killswitch helper
  - DB counts + maturity report build
  - Enqueue/backfill dry logic
  - Directive B flag presence
- Test passes cleanly.

### 6. Directive B Explicitness
- Added `_directive_b_active()` + `directive_b_note` to `hermes_maturity_dashboard.py`.
- Live report now includes:
  ```json
  "directive_b_active": true,
  "directive_b_note": "Operator Directive B (2026-06-02): live auto-promote + RAG writes enabled (audited + reversible)..."
  ```
- Updated coordinator header and tick log to loudly declare "**DIRECTIVE B ACTIVE**".
- Updated smoke test assertion.
- References point to this document and `HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md`.

## Updated Files (Project)

- `scripts/hermes_coordinator.py`
- `scripts/hermes_embedding_worker.py`
- `scripts/hermes_maturity_dashboard.py`
- `scripts/test_hermes_coordinator_promotion_smoke.py` (new)
- `scripts/hermes_hygiene_cleanup.sh` (new)
- `docs/hermes/HERMES_MATURITY_AUDIT_REMEDIATION_20260624.md` (this file)
- Minor config comments (outside repo: `~/.hermes/*`)

## Current Live Metrics (as of remediation)

- Research promoted: ~2559
- Embed queue: completed ↑, failed reduced from 723
- Maturity dashboard overall_autonomous: 67 (research_mind strong)
- Directive B: active (kill switch off)
- All coordinator timers healthy per fleet health audit

## Recommendations / Next

- Continue periodic `hermes_embedding_worker.py --reset-failed N` + monitor Ollama embed latency.
- Consider promoting `qwen3-embedding:8b` as faster alternative if nomic remains slow.
- Watch watchlist agent queue (semi-autonomous area).
- Re-run full maturity dashboard after next coordinator ticks: `.venv/bin/python scripts/hermes_maturity_dashboard.py`
- Use `./scripts/hermes_hygiene_cleanup.sh` for future retired artifact removal.
- Directive B state is now queryable via the maturity endpoint / dashboard.

## References

- `HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md` (authoritative governance)
- `scripts/hermes_maturity_dashboard.py`
- `scripts/hermes_coordinator.py`
- HermesHub (Command Center)
- Operator Directive B (2026-06-02)

This remediation brings Hermes operational maturity higher while preserving the explicit safety and audit boundaries of Directive B.

---
*Generated as part of Hermes maturity audit follow-up (2026-06-24).*