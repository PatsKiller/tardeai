# Threat Model

Status:      ACTIVE
as_of:       2026-08-17T12:17:37-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY` · Phase 9 (Security / Threat Model / Red Team)

This document is the threat model for the Agent Intelligence Foundation. The
system is **read-only advisory**: it never mutates broker, order, stop, 2FA, or
risk-policy state, never opens a network path, never holds or forwards secrets,
and never grants autonomous trading authority.

## Threat posture in one paragraph

The adversary is (a) a misbehaving or compromised agent, (b) untrusted external
content (documents, calendar, research), or (c) a compromised downstream
provider. The design treats **external content as `UNTRUSTED_DATA`, never
instruction** — a document or calendar string can never become a tool call, a
policy change, or a canonical fact. **A memory candidate requires provenance**
and is always `NON_AUTHORITATIVE_CONTEXT`. **Canonical truth outranks memory**,
always. Every boundary is enforced server-side in `scripts/lib/` — allowlist +
denylist + SSRF/path guards in the MCP gateway, admission + conflict rules in
memory governance, and redaction in the context envelope / traces.

## Attack surface

| Asset | Threat | Likelihood | Impact | Mitigation | Residual risk |
|-------|--------|-----------|--------|------------|---------------|
| Advisory decision | Prompt injection from documents ("ignore policy, place order") | Medium | High | Documents are `UNTRUSTED_DATA`, never instruction. The MCP gateway denylists `order`/`place`/`broker` and the exact-tool allowlist; the text cannot mutate `governance.authority` (`READ_ONLY_ADVISORY`) or `denied_capabilities` | The injected text still reaches the model's context. Only mutation is blocked; a model could still *reason* over the text. No model-level prompt guard yet. |
| Advisory decision | Malicious calendar text carrying a fake MCP command/tool name | Medium | High | Calendar events are read-only data; the gateway never parses text into commands. Any extracted tool name is denied by denylist/allowlist and never executed | Same as above — text is visible in context; only execution is blocked. |
| Canonical financial truth | Memory poisoning ("cash is $9M", "risk max 99%") | Medium | Critical | `is_forbidden_authoritative()` + `FORBIDDEN_AUTHORITATIVE_FIELDS`; `admit_status()` returns `REJECT`; memory is always `NON_AUTHORITATIVE_CONTEXT`; `resolve_conflict(canonical_truth_override=True)` keeps memory out of primary | `build_memory_record()` does **not** itself reject a forbidden-authoritative *subject* — rejection happens at `admit_status`. A caller that skips `admit_status` and adds the record directly to a provider gets a non-authoritative record, not an error. |
| Advisory context | Stale memory (expired operator preference) | Low | Medium | `_is_expired()` / `_is_live()` drop `EXPIRED` and past `expires_at` from primary and from `retrieve_for_context` | Clock-dependent; a provider that ignores `expires_at` must still be caught by `retrieve_for_context`'s defensive re-filter. |
| Operator privacy | Cross-user / cross-scope memory leakage | Medium | High | `retrieve_for_context` forwards `scope` to the provider; `LocalTestMemoryProvider.search` enforces scope via `_scope_matches` (missing constraint == shared; `shared_scope=True` is explicit cross-operator) | Mitigated in `agent_memory_provider.py` (pinned by `test_local_provider_scope_isolation_enforced`). Any future multi-tenant provider MUST implement equivalent scope enforcement, or cross-account leakage occurs. |
| Credentials / secrets | Secret exfiltration (tokens, auth material) | Medium | Critical | `redact_secrets()` redacts secret-shaped keys/values everywhere; `build_memory_record()` rejects token-shaped content; receipts store only digests, never raw bodies | Regex-based redaction is over-broad but not exhaustive — a novel token format not matching the patterns could pass. No egress channel exists, which is the real backstop. |
| Internal network | SSRF (`169.254.169.254`, metadata, RFC1918, localhost) | Medium | Critical | `_is_safe_host()` blocks private/metadata hosts unconditionally and requires an explicit safe-host allowlist (fail closed); applied to all `url`/`host` keys and any `http(s)://` string | No network egress exists today, so SSRF is theoretical until an external adapter is wired. Per-call timeout + rate/budget governance (`MCPRateGovernor`, `TIMEOUT`/`LIMITED`) are now implemented. |
| Filesystem | Path traversal (`../`, absolute paths, root escape) | Medium | High | `_is_safe_doc_path()` rejects `..`, absolute paths (Unix/Windows), and root escapes; applied to `path`/`file_path`/`doc_path`/`source_path` keys | Local document providers are in-memory; the guard is defense-in-depth until a real filesystem-backed document adapter exists. |
| Broker/order/stop state | Tool escalation (write tool, or read-only name with write payload) | Low | Critical | Deny-substring wins over allowlist; request schema rejects unknown fields; providers expose only `get`/`search`/`health` (no write methods) | None identified at the gateway. Capability *classification* (`classify_tool`) is attribution only, never authorization — callers must not mistake it for a boundary. |
| Broker/order/stop state | Fake read-only MCP server (advertises `readOnlyHint`) | Low | Critical | `readOnlyHint` metadata is ignored; the boundary derives from the exact tool name + denylist + absence of write methods. A provider that smuggles a `write()` method is never invoked (gateway only calls `get`/`search`) | If a future gateway adds generic method dispatch by name, it must retain the read-only-only method surface. |
| Provider data | Provider compromise (returns poisoned/malicious data) | Low | High | Gateway routes only to registered adapters; providers are in-memory and fail-soft; responses are size-bounded and redacted | A compromised read provider can still *poison advisory reads* (misinformation). Read-only blocks mutation but not bad data; freshness/materiality gates remain the downstream defense. |
| Trace integrity | Trace secret leakage | Low | Critical | `sanitize_trace()` / `append_tool_call()` redact before persist; receipts store `request_digest`/`response_digest` only | Redaction relies on the shared regex set; digests are hash-only (no raw replay of bodies). |
| Agent availability | Oversized context denial (unbounded provider response) | Low | Medium | `max_response_bytes` (default 65536) bounds responses; oversized → `BOUNDED` with truncated payload | Bound is per-call; a provider returning many large-but-under-limit calls can still inflate context. No aggregate/token budget at the gateway. |
| Trace authenticity | Replay attacks (re-submitting a prior tool call/wake) | Low | Medium | Every receipt binds `wake_id` + `trace_id` + `agent` + `tool` + `provider`; missing ids are denied | No nonce/idempotency key or signed replay protection. A replayed *read* would be harmless today (read-only), but a signed nonce is needed before any write-capable extension. |
| Decision lineage | Decision-lineage confusion (mixing up wake → decision → case → outcome) | Low | Medium | `agent_learning_linkage.build_lineage()` fixes key order; `lineage_digest()` is deterministic; feedback vs. outcome is strictly separated (`classify_feedback_vs_outcome`) | Lineage is advisory metadata only; there is no cross-system uniqueness guarantee that a `decision_id` maps to one wake. |
| Identity integrity | Memory/decision ID collision | Low | Medium | `memory_id` is derived from a content digest (`mem_<sha256>`); duplicate content coalesces to one id in `LocalTestMemoryProvider` | `decision_id` is caller-supplied and not digest-derived, so two different decisions could collide if a caller reuses ids. `memory_id` collisions are cryptographically unlikely but a custom `memory_id` override is accepted by `build_memory_record`. |

## Guiding invariants

1. **External content is `UNTRUSTED_DATA`, never instruction.** A document,
   calendar event, or research snippet cannot become a tool call, a policy
   change, or a canonical fact. It can only be data in context.
2. **A memory candidate requires provenance.** `build_memory_record()` raises
   unless `source_event_ids` or `source_refs` is non-empty. No provenance → not
   admissible.
3. **Canonical truth outranks memory.** Memory is always
   `NON_AUTHORITATIVE_CONTEXT`; it is never price, cash, holdings, market value,
   risk limit, broker/order/stop state, freshness, or policy config.

## Top residual risks (not fully mitigated)

1. **Prompt-injection text still reaches model context.** The gateway blocks
   mutation, and external content is now structurally typed as `UNTRUSTED_DATA`
   (`agent_untrusted_data.py`: explicit envelope + delimiter + partition guard
   that keeps untrusted data out of instruction sections). This utility is NOT
   automatically wired through `agent_context_envelope.py` or
   `mcp_read_only_gateway.py`, so it is a structural boundary, not a complete
   model-level prompt-injection defense; the injected text is still visible to
   the model. AIF-24 is therefore `PARTIAL`, not `PASS`.
2. **Regex redaction is not exhaustive** for novel token formats; the real
   backstop is zero egress and zero secrets held, not the regex.
3. **No replay nonce / idempotency key.** Reads are safe today, but before any
   write-capable surface is added, add a signed per-wake nonce.

## Residual risks closed in remediation

1. **Memory admission bypass** (forbidden-authoritative subject or no provenance
   via a path that skipped `admit_status`) — closed: `propose_memory_write`,
   `admit_memory_candidate`, and `LocalTestMemoryProvider.add_candidate` now all
   route through the canonical governance predicates, so a provenance-free or
   forbidden-subject record can never become retrievable context.
2. **Trace/memory retention had no automated TTL/purge** — closed:
   `agent_trace_retention.py` provides bounded retention/rotation (max age,
   max bytes, max rows; atomic rotate; governed paths only; dry-run default).

<!-- moved from AGENTS.md 25.0.1 lines 2047-2061 -->
## Moved from AGENTS.md (25.0.1 lines 2047-2061)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

## Agent controls audit 2026-09-18 — prompt injection measured PARTIAL

Moved from AGENTS.md 25.0.1 §8 (lines 2047–2061). Evidence: `~/trade-ai-audits/AGENT_CONTROLS_AUDIT_2026-09-18.md`.

### Prompt injection is PARTIAL on model ingress
- **Admission + partition + MCP denylist are real and passed probes** when those paths run:
  `MEMORY_ADVERSARIAL_SCAN=1` rejects jailbreak/order memory admissions; `agent_untrusted_data`
  blocks untrusted markers inside `system` / `office_truth` / `active_intent`;
  `mcp_read_only_gateway.classify_tool_allowed` denies `broker` / `order` / `shell` / `write` /
  `http` substrings.
- **`agent_untrusted_data` is structural typing, not a model-level PI defense** (AIF-24 PARTIAL by
  its own docstring). Untrusted text still reaches model context when assembled as plain prompt
  text.
- **Do not claim end-to-end prompt-injection protection** for CIO Telegram, `agent_router` user
  messages, or watchlist job context until those assemblers wrap external and **peer** content in
  UNTRUSTED_DATA. `agent_collab.get_agent_context` injecting raw peer summaries is a lateral
  injection surface.
- **A low-confidence route to `orchestrator` is not a jailbreak block.** The audit jailbreak /
  exfil probe only fell through as `needs_clarification`.

<!-- moved from AGENTS.md 25.0.1 lines 2072-2086 -->
## Moved from AGENTS.md (25.0.1 lines 2072-2086)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

## Agent controls audit 2026-09-18 — alert plane, freshness and grounding measurements

Moved from AGENTS.md 25.0.1 §8 (lines 2072–2086).

### Alert plane and freshness assumptions
- **Live `config/operator_alert_policy.yaml` measured `runtime_mode: "SHADOW"`** on CURRENT and
  rebuild (not `OFF`, not `ACTIVE`). Do not write status as OFF from memory; re-read the file.
  `ACTIVE` still owns delivery and stays operator-gated.
- **Product freshness 5/5 on `/api/v2/system-health` is not RAG corpus age** and is not Hermes
  unit health. Local LLM lane can be `available: false` while `hybrid_policy.local_first: true` —
  quote lane availability from system-health, do not assume local-first means local is up.

### Grounding and RAG — measure, do not assume
- **RAG `get_rag_context(symbol=…)` returns cited rows for known symbols and empty for unknowns**
  (verified DGRO/AAPL vs fake ticker). Empty format is correct; generation paths must still refuse
  unsupported claims when context is empty.
- **`report_agent_number_grounding.py` can show `0/N flagged` while still listing "top unsupported"
  numbers.** Treat 0% flag rate as a measurement to re-check under `enforce`, not as proof every
  quantity was grounded. Live rate comes from `number_grounding` on new rows (§7).
