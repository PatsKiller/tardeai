# Agent Intelligence Foundation — Implementation Log

Phase-by-phase record of the Agent Intelligence Foundation program
(READ_ONLY_ADVISORY). Each entry records base/head SHA, files changed,
design decisions, tests run, dry-run evidence, failures found and fixed,
remaining risks, and deployment/rollback status.

---

## Phase 0 — Release Truth, PR1 Merge, Exact-Main Deployment & Topology Convergence

- **date/time**: 2026-08-17T01:44Z (UTC)
- **base SHA (pre-merge main)**: `6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6`
- **PR #339 head**: `9ea407cb8d6046990dc18d16acb62c437b6d47c8`
- **merge SHA**: `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4`
- **merge strategy**: merge commit ("Merge pull request #339")
- **prepared release**: `~/trade-ai-releases/portfolio-server/968dafb6-main-exact-phase2-20260816-215459`
- **files changed**: none (merge of previously-reviewed PR1 Decision Truth scope; 19 files, 4 commits)
- **design decisions**:
  - Preflight confirmed PR #339 mergeable (MERGEABLE/CLEAN), exact-head CI green (backend, cio-hardening, frontend, release-readiness), 0 behind.
  - Deployed-tree truth: live `origin/main` and `CURRENT` both resolved to `6f700979` before merge.
  - Topology audit (v1.3.0) reported 30 code-provenance violations: 4 process, 16 cron, 10 user systemd. 0 artifact false-positives.
- **tests run**: `gh pr checks 339` (all green); operator product acceptance (PASS).
- **dry-run evidence**: n/a (no advisory traffic generated).
- **failures found**: none new. Known unrelated canary mismatch (DELIVERY_INTERDICTED vs DELIVERY_BLOCKED_CREDENTIALS) remains documented.
- **remaining risks**: `promote` (live `systemctl --user restart portfolio-server`) and topology convergence pending operator go-ahead; 30 topology violations not yet zero.
- **deployment/rollback status**: release PREPARED, NOT promoted. `cio_phase2_exact_main_deploy.sh rollback` remains available for the current release.

### Acceptance (P0-A … P0-G)
| Gate | Status |
|------|--------|
| P0-A PR1 merged at reviewed head | ✅ `968dafb6` |
| P0-B origin/main exact | ✅ `968dafb6` |
| P0-C deployed CURRENT exact main | ⏳ pending promote |
| P0-D all CIO writers/readers current | ❌ 30 violations |
| P0-E topology violations = 0 | ❌ 30 |
| P0-F READ_ONLY_ADVISORY intact | ✅ |
| P0-G broker/order/stop/2FA/risk-policy mutations = 0 | ✅ |

---

## Phase 1 — Agent Intelligence Foundation Schemas

- **date/time**: 2026-08-17T01:56Z (UTC)
- **base SHA**: `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4` (origin/main)
- **head SHA**: (uncommitted; branch `feature/agent-intelligence-foundation`)
- **files changed**:
  - `scripts/lib/agent_context_envelope.py` (new) — ContextEnvelope@v1 + `get_context_for_agent()`
  - `scripts/lib/agent_run_trace.py` (new) — AgentRunTrace@v1 + append-only JSONL trace store
  - `tests/test_agent_context_envelope.py` (new)
  - `tests/test_agent_run_trace.py` (new)
- **design decisions**:
  - Dict-based schemas (not dataclasses) to match existing `scripts/lib` conventions and stay JSON-serializable.
  - Stable content digest excludes timestamps (`created_at`/`built_at`) and the digest field itself → materially-identical envelopes hash identically; any material change yields a new digest.
  - Memory is a sibling section (`episodic_memory`), never folded into `office_truth`; `governance.memory_authority` is hard-coded `NON_AUTHORITATIVE_CONTEXT`.
  - Missing providers are represented explicitly (`NOT_CONFIGURED` / `UNAVAILABLE` / `ERROR`), never silently "empty but consulted".
  - `get_context_for_agent()` is the single chokepoint; memory is consulted via a narrow duck-typed protocol (`health()` + `search()`) so Phase 4 can drop in Null/Mem0 providers without signature change.
  - AgentRunTrace reuses the existing `wake_id`/`trace_id`/JSONL-append pattern from `cio_wake_traces.py`; storage is `data/cio/agent_run_traces.jsonl`.
  - Chain-of-thought fields are stripped, secrets redacted before persist.
- **tests run**: `pytest tests/test_agent_context_envelope.py tests/test_agent_run_trace.py` → 44 passed.
- **dry-run evidence**: fixture envelopes for SCHD REJECT, cash WAIT, re-entry WAIT built and validated; no decision/truth mutation observed.
- **failures found / fixed**:
  - `SECTION_GOVENANCE` typo in validation → fixed.
  - Unused `hashlib` import in `agent_run_trace.py` → removed.
- **remaining risks**: no live entrypoint migrated yet (Phase 5); trace store is additive, no retention policy applied (Phase 10).
- **deployment/rollback status**: additive code only; not wired to production.

---

## Phase 2 — Lightweight Observability Instrumentation (primitives)

- **date/time**: 2026-08-17T02:02Z (UTC)
- **base SHA**: `cc692bd4` (Phase 1 head)
- **head SHA**: `328be9df`
- **files changed**:
  - `scripts/lib/agent_tool_trace.py` (new) — governed tool-call trace (2.2)
  - `scripts/lib/agent_notification_intelligence.py` (new) — notification reasoning + follow-up binding (2.3/2.4)
  - `tests/test_agent_observability.py` (new)
- **design decisions**:
  - Tool-call trace stores redacted request/response **digests**, never raw payloads; capability class + read/write classification from the tool name.
  - Notification reasoning models `same_identity` vs `same_decision` + `evidence_changed` separately: an exact unchanged replay is suppressed, but the same decision with new evidence may reopen a prior REJECT with `WHAT CHANGED SINCE YOUR REJECT`.
  - Durable next-review: `build_next_review()` degrades a missing schedule to an explicit `NEXT_REVIEW_UNAVAILABLE` + reason; `validate_next_review()` rejects blank/unknown kinds. No bare `NEXT REVIEW`.
- **tests run**: `pytest tests/test_agent_observability.py tests/test_agent_context_envelope.py tests/test_agent_run_trace.py` → 63 passed; existing `test_cio_decision_quality_pr1.py` → 44 passed (no regression).
- **dry-run evidence**: notification suppression/reopen exercised with fixed fixtures.
- **failures found / fixed**:
  - `evaluate_notification` conflated `same_generation` (dedupe-key) with `same_decision`; reworked to separate identity vs decision+evidence change → fixed reopen-on-new-evidence case.
  - `build_next_review()` default incorrectly asserted as invalid in a test; clarified that a bare schedule degrades to an explicit-unavailable record (valid), while a truly blank dict is rejected.
- **remaining risks**: 2.1 (instrument live material wakes) and 2.5 (dry replay harness) not yet done — both touch existing production paths; deferred pending Phase 0 promote/topology go-ahead.
- **deployment/rollback status**: additive code only; not wired to production.

---

## Phase 0 — Exact-main promote + topology convergence (partial)

- **date/time**: 2026-08-17T02:25Z (UTC)
- **merged main**: `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4` (PR #339 merged)
- **base SHA**: `328be9df` (Phase 2 primitives head)
- **deployment**:
  - `cio_phase2_exact_main_deploy.sh promote` → `CURRENT` now resolves to `968dafb6-...-phase2-20260816-215459`; portfolio-server restarted, `/v3/cio` = 200.
  - `cio-governed-bridge.service` repointed `WorkingDirectory` → `CURRENT` + restarted (was 124 commits behind on old tree); healthy (REAL/canary, caller map intact).
  - `tradeai-cio-telegram.service` restarted onto `CURRENT` — it had been silently running the **stale** `6f700979` release (pre-PR339) because promote only restarts portfolio-server. This was the "one truthful decision across web + Telegram" gap.
  - 4 inactive oneshot/timer services repointed `WorkingDirectory` → `CURRENT`: `tradeai-cio-reactive`, `tradeai-advisory-outcome-scorer`, `tradeai-maturity-feeds`, `tradeai-agent-runtime@` (template).
- **audit fixes (2 bugs found during convergence)**:
  - `cio_topology_audit.py` now treats the venv Python interpreter as **runtime**, not code ownership (the `trade-ai-v12-rebuild/.venv` has no editable install / egg-link; `scripts.__file__ is None`). Removed 8 false-positive violations.
  - `resolve_checkout()` now falls back to `BUILD_SHA` for copied release trees (which have **no `.git`**); without this, a stale-release process (Telegram on `6f700979`) evaded the CDQ-25 SHA-mismatch check. `TOPO_VERSION` → `1.5.0`.
  - `tests/test_cio_decision_quality_pr1.py` → 46 passed (added `test_topology_interpreter_is_runtime_not_code`, `test_topology_build_sha_fallback_detects_stale_release`).
- **cron convergence**:
  - Repointed 15 CIO cron entries (hardcoded `cd`/watchdog paths) from the deprecated old tree → `CURRENT`. Full crontab backed up to `/tmp/crontab.backup.*`.
  - Left untouched: `PROJ`/`PY` header, the `reconcile_alpaca_paper_options.sh` broker reconciler, and all non-CIO (Hermes/watchpool/finviz) jobs.
- **topology result**: 30 → **2** violations. Remaining 2 are the `tradeai-wt-watch-review-automation` worktree (`feat/watch-review-automation`, SHA `cbabd9fe`) — a **separate repo**, not the CIO main tree.
- **remaining risks / open decisions**:
  1. **watch-review scope**: `run_watch_review_workers.py` lives in a separate repo, not in `CURRENT`; repointing it into the CIO tree is impossible. Needs an operator decision: (a) treat as a separate approved component with its own expected SHA, or (b) exclude from CIO topology scope.
  2. **`$PROJ`/`$PY` blind spot**: the crontab header `PROJ=/home/johnclaw/trade-ai-v12-rebuild/...` means ~13 CIO-matching cron entries (and 347 total) run old-tree code invisibly to the audit's literal-path matching. The old tree is the system-wide runtime (936-line crontab, 482 old-tree references). Full convergence is a separate, larger migration.
- **rollback**: portfolio-server rollback via `cio_phase2_exact_main_deploy.sh rollback`; bridge unit backup at `/tmp/cio-governed-bridge.service.pre-topo-*`; crontab backup at `/tmp/crontab.backup.*`; systemd `daemon-reload` re-applies.
