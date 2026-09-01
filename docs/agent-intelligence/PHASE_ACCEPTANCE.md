# Agent Intelligence Foundation — Phase Acceptance

Status:      ACTIVE
as_of:       2026-08-17T12:17:37-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY`. This records the acceptance profile
(`AGENT_INTELLIGENCE_FOUNDATION_ACCEPTANCE`) and each phase's gates.

Status vocabulary:

- **PASS** — proven by tests and/or dry-run evidence.
- **NOT_CONFIGURED** — external prerequisite absent (never "passed", never fabricated).
- **NOT_REQUIRED** — gate is satisfied by a measured non-trigger (a success, not a failure).
- **NOT_PROMOTED** — shadow-only posture; behavior influence intentionally OFF.
- **PARTIAL** — proven for the program scope, with an explicit caveat.

## AIF gates (1–30)

| Gate | Requirement | Status | Evidence |
|------|-------------|--------|----------|
| AIF-1 | exact-main deployment / no mixed CIO runtime | PASS | Phase 0 promote; `CURRENT` == origin/main `968dafb6` |
| AIF-2 | topology current ownership | PASS | topology audit = 0 code-provenance violations |
| AIF-3 | ContextEnvelope schema | PASS | `test_agent_context_envelope.py` |
| AIF-4 | canonical truth outranks memory | PASS | `test_agent_intelligence_adversarial.py` (cash/risk override blocked) |
| AIF-5 | AgentRunTrace completeness | PASS | `test_agent_run_trace.py` |
| AIF-6 | trace secret redaction | PASS | `sanitize_trace` + redaction tests |
| AIF-7 | MCP allowlist only | PASS | `test_mcp_read_only_gateway.py` |
| AIF-8 | MCP server-side read-only enforcement | PASS | allowlist/denylist (not readOnlyHint) |
| AIF-9 | MCP SSRF/path safety | PASS | `test_mcp_security.py` |
| AIF-10 | MCP trace receipts | PASS | `call_mcp_tool` binds wake/trace ids |
| AIF-11 | MemoryProvider abstraction | PASS | protocol + Null/LocalTest providers |
| AIF-12 | Mem0 shadow works or honestly NOT_CONFIGURED | **NOT_CONFIGURED** | `mem0` not installed; self-hosted preferred |
| AIF-13 | memory provenance required | PASS | `build_memory_record` rejects no-source |
| AIF-14 | memory conflict/supersession | PASS | `resolve_conflict` |
| AIF-15 | no memory truth override | PASS | forbidden-authoritative admission + red-team |
| AIF-16 | retrieval-before-reasoning | PASS | `record_retrieval_before_reasoning` |
| AIF-17 | specialist trace linkage | PASS | `build_specialist_sub_envelope` parent ids |
| AIF-18 | notification duplicate suppression | PASS | `evaluate_notification` + `reopen_after_reject` |
| AIF-19 | durable next-review linkage | PASS | `build_durable_next_review` (revisit_id + lineage) |
| AIF-20 | operator rejection recall | PASS | unchanged REJECT suppressed; changed evidence reopens |
| AIF-21 | feedback != measured investment outcome | PASS | `classify_feedback_vs_outcome` |
| AIF-22 | reflection proposes, never auto-promotes | PASS | `propose_memory_write` (CANDIDATE, no write) |
| AIF-23 | LangGraph conditional gate | PASS (**NOT_REQUIRED**) | complexity gate default |
| AIF-24 | external content treated as untrusted data | **PARTIAL** | `agent_untrusted_data.py` UNTRUSTED_DATA envelope + delimiter + partition guard; residual model-level prompt-injection risk acknowledged |
| AIF-25 | provider outage fail-soft | PASS | `test_agent_intelligence_failure_injection.py` |
| AIF-26 | historical replay complete | PASS | 397 real wakes replayed |
| AIF-27 | shadow comparison complete | PASS (context-level) | `shadow_compare_wakes`; wake traces carry no decision payloads |
| AIF-28 | behavior-influence promotion justified | **NOT_PROMOTED** | influence=0; fail-closed gate requires measured decision-level evidence |
| AIF-29 | zero broker/order/stop/2FA/risk-policy mutation | PASS | no such code path; adversarial counters = 0 |
| AIF-30 | READ_ONLY_ADVISORY | PASS | authority constant throughout |

## Phase acceptance summary

| Phase | Gates | Result |
|-------|-------|--------|
| 0 | P0-A…P0-G | PASS (topology 0) |
| 1 | AI-1…AI-6 | PASS |
| 2 | trace coverage, 0 secrets, follow-up binding | PASS (real corpus: coverage 1.00) |
| 3 | MCP-1…MCP-7 | PASS (external NOT_CONFIGURED) |
| 4 | memory authority/admission/conflict | PASS (Mem0 NOT_CONFIGURED) |
| 5 | context-before-reasoning, truth preserved | PASS (shadow-only) |
| 6 | duplicate suppression, durable next review | PASS |
| 7 | feedback/outcome separation, propose-only | PASS |
| 8 | conditional gate | PASS (NOT_REQUIRED) |
| 9 | unauthorized=0, truth-override=0, leak=0 | PASS |
| 10 | unit/integration/failure-injection/perf | PASS |
| 11 | shadow comparison + promotion gate | PASS (NOT_PROMOTED) |
| 12 | conservative flags + rollback | PASS (defaults off) |

## Overall

**Implementation is complete; the program remains in a shadow-only,
behavior-influence-OFF posture** (every feature flag defaults to `0`,
`MEMORY_PROVIDER=null`, `promotion_gate()` fails closed and returns
`NOT_PROMOTED` without measured decision-level evidence).

Independent-review remediation closed (this branch):

- **Runtime instrumentation** is now flag-gated and additive
  (`agent_runtime_instrumentation.py` + `cio_material_scan._instrument_scan`):
  flags OFF ⇒ exact pre-AIF parity; `AGENT_CONTEXT_ENVELOPE=1` builds
  ContextEnvelope@v1; `AGENT_RUN_TRACE=1` propagates one wake/trace lineage and
  appends a redacted AgentRunTrace; hooks fail soft. No host activation.
- **AIF exact-head CI** exists (`agent-intelligence-foundation-ci.yml`) and runs
  the full AIF manifest; it complements (does not replace) `cio-hardening` and
  `release-readiness`.
- **Promotion gate fails closed** and requires measured decision-level evidence
  (payloads available, comparisons completed, zero truth overrides, zero
  unauthorized actions, zero critical memory false positives, measured operator
  recall above threshold, trace coverage ≥ 99%, MCP write denial rate 100%).
- **`NOT_CONFIGURED`/`UNAVAILABLE`/`ERROR`** propagate honestly end to end and
  are never normalized to `EMPTY`.
- **Memory provenance/admission** is enforced end to end via one governed path.
- **Single feature-flag source of truth** in `agent_feature_flags.py`.
- **MCP timeout + rate/budget governance** implemented (`MCPRateGovernor`,
  `TIMEOUT`/`LIMITED` statuses).
- **Trace retention/rotation** implemented (`agent_trace_retention.py`, dry-run
  default, governed paths only, atomic rotation).

Notable honest caveats (not "PASS"):

- **Mem0** and **external calendar/documents MCP** are `NOT_CONFIGURED` (no
  packages installed, no external credentials); local test doubles are used.
- **Behavior influence is NOT_PROMOTED** by design; wake traces carry no
  decision payloads, so shadow comparison is context-level, not notification-level.
- **AIF-24 external-content trust is PARTIAL**: the `UNTRUSTED_DATA` envelope +
  partition utilities exist (`agent_untrusted_data.py`), but they are NOT
  automatically enforced by `agent_context_envelope.py` or
  `mcp_read_only_gateway.py`; this is structural typing, not a model-level
  prompt-injection defense, and external calendar/documents providers remain
  `NOT_CONFIGURED`. No claim is made that all external content is automatically
  wrapped.
- **AIF exact-head CI** is authored but its green run on the final PR head is
  still pending at the time of this writing (see IMPLEMENTATION_LOG).
- Pre-existing `test_agent_runtime_host_proof_wrapper.py` failures are unrelated
  to this program (credential-handoff subsystem) and carried as
  `known_unrelated_failures` (proven to also fail on base `968dafb6`).
