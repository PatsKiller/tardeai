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
- **remaining risks**: 2.1 (instrument live material wakes) was completed in the independent-review remediation (see "Final Independent Review Remediation" below); 2.5 (dry replay harness) done in Phase 2.5.
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
  1. **watch-review scope**: RESOLVED — `tradeai-wt-watch-review-automation` is now a separately-approved component with its own pinned SHA (`cbabd9fe`), so the audit treats it as clean. See `ADDITIONAL_APPROVED_COMPONENTS` in `cio_topology_audit.py`.
  2. **`$PROJ`/`$PY` blind spot**: DEFERRED as a separate plan — see `docs/agent-intelligence/PLAN_crontab_proj_migration.md`. The crontab header `PROJ=/home/johnclaw/trade-ai-v12-rebuild/...` routes ~347 jobs (incl. ~13 CIO-matching) to the old tree invisibly to the audit's literal-path matching. Not touched in Phase 0.
- **topology final result**: **0 violations (PASS)** — `TOPO_VERSION 1.6.0`. Active processes (portfolio-server, bridge, telegram), all CIO cron hardcoded paths, and systemd units (system + user) now resolve to `968dafb6` (or the separately-approved watch-review SHA).
- **rollback**: portfolio-server rollback via `cio_phase2_exact_main_deploy.sh rollback`; bridge unit backup at `/tmp/cio-governed-bridge.service.pre-topo-*`; crontab backup at `/tmp/crontab.backup.*`; systemd `daemon-reload` re-applies.

---

## Phase 3 — Read-only MCP Gateway

- **date/time**: 2026-08-17T03:00Z (UTC)
- **base SHA**: `d12f26f8` · **head SHA**: `9ff65382`
- **files changed**: `scripts/lib/mcp_read_only_gateway.py`, `scripts/lib/mcp_provider_adapters.py`, `tests/test_mcp_read_only_gateway.py`, `tests/test_mcp_security.py`, `docs/agent-intelligence/MCP_READ_ONLY_GATEWAY.md`, `MCP_SECURITY_MODEL.md`, `ADR/003-mcp-read-only-gateway.md` (all new).
- **design decisions**: internal gateway over direct agent→MCP connections; allowlist of 13 read-only tools + denylist substrings that always win; SSRF guard (localhost/RFC1918/link-local/metadata denied + safe-host allowlist); path-traversal guard; response size bound; sensitive-value redaction; per-call receipts bound to wake_id/trace_id. Server-side read-only, not readOnlyHint.
- **tests run**: `pytest tests/test_mcp_read_only_gateway.py tests/test_mcp_security.py` → 32 passed.
- **remaining risks**: external calendar/documents backends NOT_CONFIGURED (no external auth material). Timeout + rate/budget governance implemented in the remediation (see "Final Independent Review Remediation").
- **deployment/rollback status**: additive; not wired to production.

## Phase 4 — Memory Abstraction + Mem0 Shadow Pilot

- **date/time**: 2026-08-17T03:05Z (UTC)
- **base SHA**: `9ff65382` · **head SHA**: `f7df00d8`
- **files changed**: `scripts/lib/agent_memory_provider.py`, `agent_memory_governance.py`, `agent_mem0_provider.py`, `tests/test_agent_memory_governance.py`, `tests/test_agent_mem0_provider.py`, `docs/agent-intelligence/MEMORY_GOVERNANCE_AND_MEM0.md`, `MEMORY_ADMISSION_POLICY.md`, `ADR/004`, `ADR/006` (all new).
- **design decisions**: MemoryProvider protocol (search/add_candidate/get/dispute/expire/health); MemoryRecord@v1 with deterministic digest + provenance requirement + token rejection; admission policy (ACTIVE only for explicit operator/commitment/durable case); NEVER-admit authoritative fields (price/cash/shares/risk/policy); conflict rules (truth wins, newer explicit supersedes, disputed visible, expired excluded). Mem0 NOT_CONFIGURED (self-hosted preferred). Shadow posture MEMORY_SHADOW=1, BEHAVIOR_INFLUENCE=0.
- **tests run**: `pytest tests/test_agent_memory_governance.py tests/test_agent_mem0_provider.py` → 36 passed.
- **remaining risks**: Mem0 backend not configured; provider scope/plan filters hardened later (see Phase 9 fix + plan_id fix).
- **deployment/rollback status**: additive; shadow-only.

## Phase 6 — Autonomous Office Initiative

- **date/time**: 2026-08-17T03:10Z (UTC)
- **base SHA**: `f7df00d8` · **head SHA**: `7b33832d`
- **files changed**: `scripts/lib/agent_wake_taxonomy.py`, `agent_followup.py`, `tests/test_agent_wake_taxonomy.py`, `tests/test_agent_followup.py`, `docs/agent-intelligence/AUTONOMOUS_OFFICE_INITIATIVE.md` (all new).
- **design decisions**: 16-trigger canonical wake taxonomy; allowed/denied autonomous-action sets (advisory only); notification policy (unchanged replay suppressed, prior REJECT reopens only on changed evidence); durable next-review binding (TIME/CONDITION/DATA_FRESHNESS/EVENT + revisit_id + lineage); advisory message uses memory only when decision-relevant.
- **tests run**: `pytest tests/test_agent_wake_taxonomy.py tests/test_agent_followup.py` → 50 passed.
- **deployment/rollback status**: additive; not wired to live wakes.

## Phase 7 — Learning Loop Integration + Phase 8 — LangGraph Gate

- **date/time**: 2026-08-17T03:15Z (UTC)
- **base SHA**: `7b33832d` · **head SHA**: `e2103e09`
- **files changed**: `scripts/lib/agent_learning_linkage.py`, `langgraph_complexity_gate.py`, `tests/test_agent_learning_linkage.py`, `tests/test_langgraph_complexity_gate.py`, `docs/agent-intelligence/ORCHESTRATION_AND_LANGGRAPH_DECISION.md`, `ADR/005` (all new).
- **design decisions**: lineage wake→trace→decision→case→feedback→follow-up→outcome→darwin→reflection→lesson; feedback-vs-outcome invariant (REJECT≠loss, ACK≠win, DONE≠win, RATE≠alpha); reflection must propose_memory_write (CANDIDATE, no direct mutation). LangGraph gate defaults NOT_REQUIRED (a success); Letta DEFERRED.
- **tests run**: `pytest tests/test_agent_learning_linkage.py tests/test_langgraph_complexity_gate.py` → 25 passed.
- **deployment/rollback status**: additive.

## Phase 5 — Context-Aware Agent Integration (shadow-only)

- **date/time**: 2026-08-17T03:20Z (UTC)
- **base SHA**: `e2103e09` · **head SHA**: `34f29af4`
- **files changed**: `scripts/lib/agent_context_integration.py`, `tests/test_agent_context_integration.py`, `docs/agent-intelligence/AGENT_INTELLIGENCE_FOUNDATION_ARCHITECTURE.md` (all new).
- **design decisions**: specialist sub-envelopes scoped per role (guardian/steph/maria/ledger, unknown fail-closed); parent wake/trace linkage; retrieval-before-reasoning honesty markers; deterministic budget (truth never truncated); shadow_compare diff report.
- **tests run**: `pytest tests/test_agent_context_integration.py` → 23 passed.
- **deployment/rollback status**: additive adapters only; no live behavior change.

## Phase 2.5 — Dry Replay Harness

- **date/time**: 2026-08-17T03:25Z (UTC)
- **base SHA**: `34f29af4` · **head SHA**: `b720c730`
- **files changed**: `scripts/lib/agent_replay_harness.py`, `tests/test_agent_replay_harness.py`, `docs/agent-intelligence/EVALUATION_AND_SHADOW_TEST_PLAN.md` (all new).
- **design decisions**: read-only replay over 397 real wakes; never resends Telegram (notify callback never invoked). Measures trace coverage/completeness, lineage breaks, context build failures; notification metrics only when a decision loader yields payloads.
- **dry-run evidence**: real corpus → trace_coverage=1.00, lineage_breaks=0, context_failures=0; notification metrics zero on real corpus (no decision payloads) and exercised via synthetic fixtures.
- **tests run**: `pytest tests/test_agent_replay_harness.py` → 10 passed.
- **deployment/rollback status**: additive.

## Phase 9 — Security / Threat Model / Red Team (+ memory scope fix)

- **date/time**: 2026-08-17T03:30Z (UTC)
- **base SHA**: `b720c730` · **head SHA**: `2d0a4cf6`
- **files changed**: `tests/test_agent_intelligence_adversarial.py`, `docs/agent-intelligence/THREAT_MODEL.md`, `PRIVACY_AND_REDACTION.md` (new); `scripts/lib/agent_memory_provider.py` (scope enforcement fix).
- **failures found / fixed**: red-team found `LocalTestMemoryProvider` accepted `scope` but did not filter by it → **fixed** via `_scope_matches`; pinned by `test_local_provider_scope_isolation_enforced`.
- **tests run**: `pytest tests/test_agent_intelligence_adversarial.py` → 26 passed; hard counters unauthorized=0, truth-override=0, leak=0.
- **remaining risks**: prompt-injection text still reaches model context (execution blocked, not stripped; structural UNTRUSTED_DATA envelope added, AIF-24 downgraded to PARTIAL); regex redaction not exhaustive. Memory provenance/admission now enforced end-to-end and retention TTL implemented in the remediation (see "Final Independent Review Remediation").

## Phase 10 — Comprehensive Test Program + plan_id contract fix

- **date/time**: 2026-08-17T03:35Z (UTC)
- **base SHA**: `2d0a4cf6` · **head SHA**: `9f41cfe6` (+ fix `aee95c77`)
- **files changed**: `tests/test_agent_intelligence_failure_injection.py`, `tests/test_agent_intelligence_integration.py`, `scripts/lib/agent_perf_bench.py`, `tests/test_agent_perf_bench.py` (new); `scripts/lib/agent_memory_provider.py` + `tests/test_agent_context_envelope.py` (plan_id contract fix).
- **failures found / fixed**: `get_context_for_agent` passed `plan_id=` into `provider.search()` but the provider protocol lacked it → RETRIEVAL_ERROR with the shipped local provider → **fixed** (added `plan_id` to protocol + providers + `_plan_matches` filter). Regression test added.
- **tests run**: `pytest tests/test_agent_intelligence_failure_injection.py tests/test_agent_intelligence_integration.py tests/test_agent_perf_bench.py` → 21 passed.
- **performance (local CPU baseline, not budgets)**: context build ~0.017ms, memory retrieval ~0.014ms, MCP read ~0.122ms, trace append ~0.038ms.

## Phase 12 — Controlled Read-Only Activation (feature flags + runbooks)

- **date/time**: 2026-08-17T03:40Z (UTC)
- **base SHA**: `9f41cfe6` · **head SHA**: `550472a5`
- **files changed**: `scripts/lib/agent_feature_flags.py`, `tests/test_agent_feature_flags.py`, `docs/agent-intelligence/DEPLOYMENT_RUNBOOK.md`, `ROLLBACK_RUNBOOK.md` (all new).
- **design decisions**: conservative defaults (all 0; MEMORY_PROVIDER=null); rollback_flags() = conservative config; activation_scope_check() denies memory-changing holdings/cash/risk, order creation, MCP writes, LangGraph broker authority, learning auto-promotion.
- **tests run**: `pytest tests/test_agent_feature_flags.py` → 37 passed.
- **deployment/rollback status**: defaults OFF; not activated.

## Phase 11 — Shadow Acceptance + Promotion Gate

- **date/time**: 2026-08-17T03:45Z (UTC)
- **base SHA**: `550472a5` · **head SHA**: `2bd478b7`
- **files changed**: `scripts/lib/agent_shadow_acceptance.py`, `tests/test_agent_shadow_acceptance.py` (new).
- **design decisions**: shadow_compare_wakes (baseline vs augmented, shadow only); promotion_gate fail-closed — PROMOTED requires affirmative measured decision-level evidence (payloads available, comparisons completed, zero truth overrides, zero unauthorized actions, zero critical memory false positives, measured operator recall above threshold, trace coverage ≥ 99%, MCP write denial rate 100%, P0/P1 == 0, influence explicitly enabled). Missing evidence fails closed.
- **dry-run evidence**: real 397-wake corpus → trace_coverage=1.0, context_failures=0, truth_overrides=0, verdict NOT_PROMOTED (influence off; no decision payloads in wake traces).
- **tests run**: `pytest tests/test_agent_shadow_acceptance.py` → 6 passed (initial); expanded to fail-closed coverage in the remediation (see below).

## Final Independent Review Remediation (bounded pass)

- **date/time**: 2026-08-17 (remediation after PR #341 draft)
- **base SHA**: `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4` · **start head**: `76800c24aeca1aa7e41e407c61f6f641c607b381`
- **scope**: close the independent-review findings only; NOT a new feature; no merge/deploy/behavior-influence; READ_ONLY_ADVISORY.
- **files changed**:
  - `scripts/lib/agent_runtime_instrumentation.py` (new) — flag-gated `instrument_material_wake`; `scripts/lib/cio_material_scan.py` (`_instrument_scan` hook).
  - `scripts/lib/mcp_read_only_gateway.py` — timeout + `MCPRateGovernor`; new `TIMEOUT`/`LIMITED` statuses.
  - `scripts/lib/agent_trace_retention.py` (new) — bounded JSONL retention/rotation.
  - `scripts/lib/agent_untrusted_data.py` (new) — UNTRUSTED_DATA envelope + partition guard.
  - `scripts/lib/agent_shadow_acceptance.py` — promotion gate fail-closed.
  - `scripts/lib/agent_context_envelope.py` — NOT_CONFIGURED/UNAVAILABLE/ERROR propagation.
  - `scripts/lib/agent_memory_provider.py` + `agent_learning_linkage.py` — provenance/admission enforced end-to-end.
  - `scripts/lib/agent_mem0_provider.py` — removed split-brain runtime flags.
  - `scripts/lib/agent_followup.py` — `reopen_after_reject` identity semantics.
  - `scripts/lib/agent_run_trace.py` — `query_traces(case_id=...)` top-level fallback.
  - `.github/workflows/agent-intelligence-foundation-ci.yml` (new).
  - `docs/agent-intelligence/PHASE_ACCEPTANCE.md`, `IMPLEMENTATION_LOG.md`, `THREAT_MODEL.md`, `PRIVACY_AND_REDACTION.md`, `DEPLOYMENT_RUNBOOK.md`, `ROLLBACK_RUNBOOK.md` (sync).
- **tests run**: full AIF manifest 383 passed locally (see final result packet for exact count); targeted regressions per finding.
- **remaining risks**: AIF exact-head CI authored but its green run on the final PR head pending; Mem0 + external MCP NOT_CONFIGURED; behavior influence NOT_PROMOTED; AIF-24 PARTIAL.

## True Final Exact-Head Integrity Remediation (narrow pass)

- **date/time**: 2026-08-17 (second exact-head review remediation)
- **base SHA**: `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4` · **start head**: `26c6fa71a6c146e35e9dc613c08a02ae61446d06`
- **scope**: close the 5 remaining P1s + P2s only; NOT a redesign; no merge/deploy/behavior-influence; READ_ONLY_ADVISORY; no CRLF mass normalization.
- **P1 fixes**:
  - **Real dual-path decision shadow** — `shadow_compare_wakes()` now invokes a `decision_evaluator(wake, context, mode)` twice (baseline + augmented contexts); a copied/same-object result can no longer satisfy decision evidence; each packet carries baseline/augmented context + decision digests, `decision_id`, `evaluator_version`, `comparison_completed`; `dual_path_executed` is a new fail-closed lineage marker required by `promotion_gate`; `memory_attributable_action_flips` is derived from real baseline-vs-augmented diffs and the gate also checks the derived value (not only external metrics).
  - **MCP true timeout** — `_call_with_timeout()` now runs the provider on a daemon thread and returns at the deadline without waiting for executor shutdown; measured-elapsed latency is asserted.
  - **MCP default rate governor structural** — `call_mcp_tool(governor=None)` now uses a shared `_DEFAULT_GOVERNOR`; governance can no longer be bypassed by omitting the governor; `reset_default_governor()`/`get_default_governor()` added; `agent_perf_bench.benchmark()` resets the governor for determinism.
  - **Wall-clock trace retention** — `agent_trace_retention.py` now ages rows against `now` (injectable) instead of the newest record; no-timestamp rows cannot live forever under an active age policy; receipt exposes `removed_valid`/`removed_invalid`/`removed_total`/`valid_rows_before`/`invalid_rows`.
  - **Forced memory admission privilege fields** — `LocalTestMemoryProvider.add_candidate()` now FORCES `authority_class=NON_AUTHORITATIVE_CONTEXT` and recomputes `status` via the canonical `admit_status()` (caller ACTIVE on an inferred type is downgraded to CANDIDATE; lifecycle downgrades preserved); `search()` applies defense-in-depth `_retrievable()` filtering (authority/provenance/forbidden-subject).
  - **AIF CI watches the production hook** — `agent-intelligence-foundation-ci.yml` push/pull paths now include `scripts/lib/cio_material_scan.py`.
- **P2 fixes**: retention invalid-row accounting (above); AIF-24 stays PARTIAL and docs now state the UNTRUSTED_DATA utility is NOT auto-wired through the context envelope / MCP gateway; CRLF executable/shebang scan clean (0 executable risks; 71 changed files carry CRLF, deferred to a separate mechanical PR).
- **tests run**: full AIF manifest 409 passed locally (23 files); targeted CIO/release/no-broker-write regressions green; no executable/shebang CRLF risk.

## Spot-Review Exact-Head Remediation (resource governance + P2 correctness)

- **date/time**: 2026-08-17 (third exact-head spot review remediation)
- **base SHA**: `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4` · **start head**: `233b379c3d4ab2bb2372c20952c7f1a1bc8cd415`
- **scope**: close 1 P1 + 3 P2 only; NOT a redesign; no merge/deploy/behavior-influence; READ_ONLY_ADVISORY; no CRLF mass normalization.
- **P1 — globally bounded MCP timed-worker + governor wake state**:
  - `_call_with_timeout()` now acquires a global in-flight slot (`MAX_IN_FLIGHT_TIMED_CALLS=8`) before spawning a daemon worker; a timed-out worker keeps its slot until it returns, so a hung provider cannot accumulate unbounded threads — once saturated, further timed calls return a new `SATURATED` status (fail closed). `in_flight_timed_calls()` exposes the count.
  - `MCPRateGovernor` now bounds its own state: `max_tracked_wakes` (LRU) + `wake_ttl_ms` (TTL) evict stale/overflowing wake buckets, so a long-running process cannot accumulate unbounded per-wake/tool counters. `wake_cardinality()` exposes the count.
- **P2 — invalid-only trace removal physically rewrites**: `enforce_trace_retention()` rewrites the file whenever invalid JSON is dropped, even when `removed_valid == 0`, so the receipt's `removed_invalid` is physically honored.
- **P2 — memory admission status fully canonicalized**: `_forced_status()` now returns the canonical `admit_status()` result for every non-lifecycle status; unknown/lowercase/whitespace/`REJECT` caller statuses are normalized away rather than persisted.
- **P2 — shadow flip metric renamed**: the derived `critical_memory_false_positives` counter is renamed to `memory_attributable_action_flips` (it proves a memory-attributable action change, not an adjudicated false positive); the promotion gate check is `shadow_memory_attributable_flips`.
- **tests run**: full AIF manifest 416 passed locally (23 files); CIO/release/no-broker-write regressions green.

## Cross-phase notes

- **Total AIF test manifest** (pinned in `agent-intelligence-foundation-ci.yml`): 416 tests across 23 files after the spot-review remediation.
- **Known unrelated failures** (carried, not in this program's scope): 8 × `tests/test_agent_runtime_host_proof_wrapper.py` (credential-handoff subsystem) — pre-existing, environment-dependent, proven to also fail on base `968dafb6`.
