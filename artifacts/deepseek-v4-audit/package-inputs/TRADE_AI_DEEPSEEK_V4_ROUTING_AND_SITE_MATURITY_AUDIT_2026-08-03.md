# Trade AI DeepSeek V4 Routing and Site Maturity Audit
**Date:** 2026-08-03  
**Mode:** Read-only due-diligence review  
**Scope:** Connected GitHub repository, current Google Drive runtime reports, canonical LLM routing/configuration files, provider documentation, route inventory, LLM/Consumption screenshots, and existing test evidence.

## Executive verdict

**Verdict: CONDITIONAL FAIL for production-mature paid-LLM routing.**

DeepSeek is present in the current local/runtime work, but the implementation is not yet reconciled with GitHub, the paid model taxonomy is incorrect, the process registry is still Grok/ChatGPT-centric, cost accounting is not real billing, and structured-output handling is not mature enough for reliable agent workflows.

The immediate Pro problem has a concrete root cause:

- The local patch maps the logical lane `deepseek-v4` to legacy model ID `deepseek-reasoner`.
- `deepseek-reasoner` is not V4 Pro. It was a compatibility alias for **V4 Flash in thinking mode**.
- The current official model IDs are:
  - `deepseek-v4-flash`
  - `deepseek-v4-pro`
- The legacy IDs `deepseek-chat` and `deepseek-reasoner` were scheduled for retirement on 2026-07-24.

Therefore the developer is not actually invoking DeepSeek V4 Pro, even when the UI says “V4”, “V4 R1”, or “Pro”.

## Evidence reconciliation

### GitHub

The connected GitHub default branch is at commit:

`ddef4613ec362e6c32307160aba8f4a56b835a20`

At that ref:

- `scripts/llm_lane.py` supports only Grok, ChatGPT, and local Gemma.
- Unknown lanes return available=True and fall through to local Gemma.
- `config/llm_process_registry.json` has only Grok/ChatGPT policy vocabulary.
- Frontend lane types and buttons are hard-coded to Grok/ChatGPT.
- Existing tests do not prove provider model IDs, JSON contracts, error handling, or no-silent-fallback behavior.

### Google Drive / local runtime

The latest runtime reports say:

- local runtime Git: `main @ 72b6ddd2`
- working tree: 173 dirty files
- local DeepSeek commit: `72b6ddd2 DeepSeek: fix silent local-gemma fallback, wire frontend, dry-test, screenshots`
- 94 frontend pages
- 1709 Python scripts
- 54 JSON configs
- 472 cron jobs
- `deep_overnight_llm_queue` pending: 1928

The local DeepSeek audit says a patch was applied and dry-tested, but it also says the process registry still needs to be updated. The local commit is not present in the connected GitHub repository.

**Consequence:** the deployed/local state is ahead of, and materially different from, the recoverable GitHub source of truth. No additional production LLM changes should be made until that divergence is reconciled.

## Site maturity findings

### Positive

- The canonical `/v3` site has broad operator coverage across portfolio, risk, trading, Active Trader, agents, intelligence, Hermes, journal, system, health, consumption, and other hubs.
- A 145-view screenshot inventory exists.
- The local DeepSeek patch added provider visibility and manual controls.
- The architecture correctly keeps LLMs advisory and outside deterministic execution authority.

### Material gaps

1. **Screenshot count is not route proof.**  
   Files named `system__llm_health.png` and `system__oauth.png` both show the Crons tab. The capture job saved filenames without asserting that the intended tab was active.

2. **Consumption UI is semantically stale.**  
   It labels the paid lanes “Flash / V4-R1”, shows both DeepSeek cards offline, exposes one generic “Test DeepSeek” button, and does not display exact model ID, thinking state, reasoning effort, request ID, error class, token split, real cost, or last capability probe.

3. **Frontend duplicates backend policy.**  
   Process policy is embedded in TypeScript as well as JSON. These can drift.

4. **Provider readiness is conflated with OAuth readiness.**  
   DeepSeek is an API-key provider and should be reported by a generic provider/model capability endpoint, not an OAuth-only hook.

5. **JSON response handling is fragile.**  
   One real health-agent test returned extra text around JSON and fell back to deterministic diagnosis. This is acceptable as containment, but not mature structured-output integration.

6. **Billing is inaccurate.**  
   Character-based “relative units” are stored in a field named `estimated_cost_usd`. Paid DeepSeek calls require actual cache-hit input, cache-miss input, output, and reasoning-token accounting.

7. **The process registry has no Flash/Pro decision policy.**  
   It cannot centrally determine model tier, thinking mode, escalation, timeout, output schema, or cost cap.

## Required model taxonomy

Separate **model tier** from **thinking mode**.

| Logical policy | Exact model | Thinking | Effort | Purpose |
|---|---|---:|---:|---|
| `FAST` | `deepseek-v4-flash` | disabled | n/a | High-volume extraction, classification, summarization, routine narratives |
| `FAST_THINK` | `deepseek-v4-flash` | enabled | high | Moderate ambiguity, contradiction checks, structured planning |
| `PRO` | `deepseek-v4-pro` | disabled | n/a | Long-context, high-quality synthesis without expensive reasoning |
| `PRO_THINK` | `deepseek-v4-pro` | enabled | high | CIO synthesis, complex strategy and trade review, incident analysis |
| `PRO_MAX` | `deepseek-v4-pro` | enabled | max | Operator-approved premium escalation only |

Do not expose or store a generic `deepseek-v4` lane. It is ambiguous.

## When to use each tier

### No LLM

Never place an LLM in:

- price/account/order truth
- arithmetic
- risk-limit enforcement
- stop/protection enforcement
- broker routing
- approval/2FA
- fire, kill-switch, or latency-critical execution paths

### Flash, non-thinking

Default for:

- entity and field extraction
- topic/category classification
- summarization
- routine portfolio/journal Q&A
- standard report sections
- health/event narrative generation
- batch enrichment
- first-pass Watch and research narratives
- UI explanation text

### Flash, thinking/high

Use for:

- one-symbol contradiction review
- plan coherence checks
- moderate multi-source reconciliation
- structured ticket critique after deterministic validation
- first-pass agent tool planning
- schema repair after a non-thinking result fails

### Pro, non-thinking

Use for:

- very long-context synthesis where attention and prose quality matter
- monthly/quarterly reports
- large evidence-pack summaries
- multi-document research synthesis without difficult decisions

### Pro, thinking/high

Use for:

- CIO synthesis
- strategy planner
- complex trade/post-trade reviews
- Sentinel high-risk or exception review
- conflicting analyst/model evidence
- P1/P2 incident root-cause analysis
- hypothesis and experiment design
- architecture or security review

### Pro, thinking/max

Use only when:

- the operator explicitly selects “Think deeper”
- expected cost is shown and confirmed
- the task is high-value and materially ambiguous
- Flash/Pro-high produced unresolved contradictions
- multiple independent reviewers disagree
- a critical incident or architecture decision warrants maximum effort

Never use Pro Max as a silent fallback.

## Escalation policy

Promote from Flash to Pro only when one or more deterministic conditions apply:

- unresolved contradiction count > 0
- two independent reviewers disagree
- material risk/notional exceeds configured threshold
- input context exceeds configured size or source count
- evidence quality is stale, weak, or conflicting
- task severity is P1/P2
- Flash returns `INSUFFICIENT_EVIDENCE`
- JSON/schema validation fails twice
- operator explicitly requests deeper analysis

Provider failure is not an escalation reason. A failed model call must remain visible as a failed model call.

## Rectification plan

### Phase 0 — Freeze and reconcile source control

1. Record:
   - `git status --short`
   - `git rev-parse HEAD`
   - `git log --oneline origin/main..HEAD`
   - `git diff --stat`
2. Do not modify remote `main`.
3. Create a clean worktree/branch from local `72b6ddd2`, e.g.:
   `fix/deepseek-v4-routing`
4. Commit or quarantine the 173 dirty-file changes by ownership.
5. Push the DeepSeek implementation and open a reviewed PR.
6. Require local, GitHub, deployed, and Drive SHAs to match before promotion.

### Phase 1 — Replace model aliases

Replace:

- `deepseek-chat`
- `deepseek-reasoner`
- logical `deepseek-v4`

with exact current IDs:

- `deepseek-v4-flash`
- `deepseek-v4-pro`

Add an explicit migration error for legacy aliases rather than silently mapping them.

### Phase 2 — Introduce one canonical model registry

Create `config/llm_model_registry.json` with:

- provider
- exact model ID
- API route
- credential slot
- capabilities
- context/output limits
- structured output support
- tool support
- thinking default
- allowed efforts
- latency class
- current pricing snapshot/effective date
- enabled state
- last capability probe
- rollback/disable switch

No business-code model literals.

### Phase 3 — Curate process policies

Update `config/llm_process_registry.json` so each process declares:

- default logical policy
- allowed policies
- thinking policy
- escalation conditions
- response schema ID/version
- max input/output
- timeout
- daily request and USD caps
- fallback policy
- operator confirmation requirement

The frontend must fetch this policy from the server. Remove the duplicated TypeScript policy catalog.

### Phase 4 — Harden the provider client

Implement:

- canonical env: `DEEPSEEK_API_KEY`
- temporary legacy env fallback: `deepseek_tradeai`, with a warning
- official base URL: `https://api.deepseek.com`
- exact-model availability check via `/v1/models`
- explicit thinking toggle and reasoning effort
- no temperature/top-p in thinking mode
- preservation of `reasoning_content` in tool-call turns
- typed errors for auth, model-not-found, 429, timeout, JSON invalid, and provider 5xx
- bounded retry only for retryable failures
- no silent local fallback
- request/response provenance and hashes

The secret must be rendered by Bitwarden into the service runtime. Test through the same systemd user/environment as the portfolio server, not only an interactive shell.

### Phase 5 — Make JSON a contract

For every structured task:

1. Send `response_format={"type":"json_object"}`.
2. Include the word `json` and a schema example in the prompt.
3. Validate with Pydantic or JSON Schema.
4. Reject extra prose; do not regex-strip the response.
5. Permit one bounded repair retry.
6. Handle empty content and `finish_reason=length`.
7. Return `MODEL_OUTPUT_INVALID` or deterministic fallback after retry.
8. Persist:
   - raw response hash
   - parsed payload
   - schema ID/version
   - exact model ID
   - thinking/effort
   - request ID
   - usage and real cost
   - latency and finish reason

### Phase 6 — Correct billing and observability

Use provider usage fields to separate:

- cache-hit input tokens
- cache-miss input tokens
- output tokens
- reasoning tokens
- actual USD cost

Do not write character “relative units” into `estimated_cost_usd`.

The UI must show exact model, mode, last probe, latency, token usage, actual cost, request ID, and sanitized failure reason.

### Phase 7 — Correct the UI

- Rename “DeepSeek V4/R1” to “DeepSeek V4 Pro”.
- Show separate Flash and Pro health/smoke tests.
- Add a policy-driven “Think deeper” action only on eligible high-value surfaces.
- Never expose API-key presence to the browser.
- Disable unsupported model buttons per endpoint/process policy.
- Show `MODEL_NOT_FOUND`, `AUTH_MISSING`, `AUTH_INVALID`, `HTTP_429`, `TIMEOUT`, and `JSON_INVALID` clearly.
- Show exact default/allowed model policy in the process table.

### Phase 8 — Test and promote

Required tests:

- registry JSON-schema validation
- exact model-ID tests
- provider request/response fixtures
- Flash non-thinking, Flash thinking, Pro high, Pro max
- JSON empty, malformed, extra prose, truncation
- 401/403, 404 model, 429, timeout, 5xx
- tool-call reasoning-content replay
- no-silent-Gemma-fallback assertion
- route/process-to-model matrix for every registered process
- actual cost calculation
- all `/v3` routes and sub-tabs with visible-heading assertions
- screenshots only after active route/tab assertion
- no LLM-to-execution authority regression

Promote through lab/shadow, then a bounded canary. Roll back by disabling the provider/model policy, never by disguising another model as DeepSeek.

## Acceptance gates

- [ ] local, GitHub, deployed, and Drive SHAs reconcile
- [ ] clean or fully owned working tree
- [ ] `/v1/models` contains both exact V4 model IDs
- [ ] no legacy DeepSeek model IDs remain
- [ ] Pro requests return `deepseek-v4-pro`
- [ ] Flash requests return `deepseek-v4-flash`
- [ ] thinking mode and effort are recorded
- [ ] no silent fallback
- [ ] JSON schema suite passes
- [ ] real cost is logged
- [ ] service-runtime key probe passes
- [ ] UI shows exact model/readiness/error
- [ ] process registry is server-authoritative
- [ ] route/tab smoke assertions pass
- [ ] LLM authority remains advisory only

## Immediate developer instruction

The first safe change is not another UI patch. It is:

1. reconcile and push the local DeepSeek commit;
2. replace the legacy model aliases with exact V4 Flash/Pro IDs;
3. add the canonical registry and process policy;
4. test the API key inside the production service environment;
5. add strict JSON/provider contract tests;
6. only then enable Pro on selected high-value processes.
