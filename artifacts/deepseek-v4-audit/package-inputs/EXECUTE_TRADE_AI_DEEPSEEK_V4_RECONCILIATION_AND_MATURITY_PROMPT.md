# OPERATOR EXECUTION PROMPT
## Trade AI — DeepSeek V4 Source Reconciliation, Routing Correction, JSON Contracts, Cost Governance, and Site Maturity

**Execution mode:** evidence-first, staged implementation on a dedicated branch/worktree  
**Repository:** `PatsKiller/tardeai`  
**Target host:** `ms01-lan` / `ms01-openclaw`  
**Input directory:** `/home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03`  
**No production deployment or service restart is authorized by this prompt.**  
**No broker write, order action, approval, 2FA action, or live-trading setting change is authorized.**

---

## 0. Mission

Perform an exhaustive, non-speculative audit and implementation of Trade AI's DeepSeek V4 integration.

You must:

1. reconcile the current server checkout, GitHub, and Google Drive evidence;
2. identify every DeepSeek/model/lane reference across backend, frontend, tests, configs, services, cron/systemd, and documentation;
3. correct the provider integration to use exact current DeepSeek model IDs;
4. make Flash versus Pro selection deterministic, policy-driven, observable, and cost-governed;
5. harden request construction and JSON response validation;
6. remove every silent or misleading fallback;
7. correct frontend labels, readiness, and model controls;
8. prove all changes with unit, integration, contract, route, build, and bounded live-provider tests;
9. produce complete evidence, rollback instructions, and a PR-ready branch;
10. stop without deploying.

Do not claim success based on code inspection alone. Every material claim requires preserved command output, a test, a fixture, or a provider response artifact.

---

## 1. Required input documents

Read these files **in full before editing**:

```text
/home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03/TRADE_AI_DEEPSEEK_V4_ROUTING_AND_SITE_MATURITY_AUDIT_2026-08-03.md
/home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03/TRADE_AI_LLM_MODEL_REGISTRY_PROPOSED.json
/home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03/TRADE_AI_LLM_PROCESS_POLICY_PROPOSED.json
/home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03/SHA256SUMS.txt
```

Treat the audit and proposed JSON as **review inputs, not unquestionable truth**. Verify every externally changeable fact against:

1. the live server;
2. the current repository;
3. the live DeepSeek `/v1/models` response;
4. current official DeepSeek API documentation;
5. existing Trade AI architecture and safety contracts.

When sources conflict, preserve the conflict in the report and use the highest-authority current evidence. Never silently reconcile conflicting evidence.

Verify the uploaded files before reading:

```bash
cd /home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03
sha256sum -c SHA256SUMS.txt
```

Stop if any checksum fails.

---

## 2. Non-negotiable rules

### Safety and authority

- LLMs remain advisory only.
- Do not add an LLM to price truth, account truth, order truth, arithmetic truth, risk enforcement, stop enforcement, eligibility, broker routing, approval, 2FA, kill-switch, or execution.
- Do not queue, submit, modify, or cancel an order.
- Do not request or consume 2FA.
- Do not change production trading flags.
- Do not expose or print any secret.
- Do not `cat`, grep, log, diff, or echo credential files or environment values.
- Do not restart or reload production services.
- Do not deploy.
- Do not push directly to `main`.
- Do not modify the existing `tradeai-wt-cursor-guardrails` worktree for this task.
- Do not touch unrelated dirty files.
- Do not alter cron/systemd schedules without explicit operator approval.
- Do not convert a provider failure into a successful response from another model.
- Do not label another model's output as DeepSeek.

### Evidence and anti-hallucination

- Do not infer that a model is available from a configured string.
- Do not infer that a button is wired because it renders.
- Do not infer that JSON is valid because parsing succeeded once.
- Do not infer that a screenshot captured a requested tab from its filename.
- Do not infer that an interactive-shell API test proves the production service has the key.
- Do not infer that a local commit exists on GitHub.
- Do not state “all pages tested” unless every canonical route/subtab was enumerated, opened, asserted, and recorded.
- Do not use generated prose as evidence for deterministic facts.
- Cite file path, line, commit SHA, test name, command, or artifact for every conclusion.
- Preserve negative results and failed tests.
- If a fact cannot be verified, mark it `UNKNOWN`, not PASS.

### Source precedence

Use this order:

1. current official provider API response/documentation;
2. deployed/runtime evidence tied to an exact SHA;
3. current Git repository content tied to an exact SHA;
4. versioned Trade AI architecture and contracts;
5. generated Drive reports tied to timestamps and SHAs;
6. the input audit and proposed JSON;
7. assumptions — prohibited unless explicitly marked and tested.

---

## 3. Stage 0 — Locate and freeze the correct repository state

Do not assume the repository path.

Search candidate checkouts and identify the one whose remote is `PatsKiller/tardeai`:

```bash
for d in \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild \
  /home/johnclaw/tardeai \
  /home/johnclaw/tradeai \
  /home/johnclaw/tradeai-wt-*; do
  [ -d "$d/.git" ] || [ -f "$d/.git" ] || continue
  printf '\n=== %s ===\n' "$d"
  git -C "$d" remote get-url origin 2>/dev/null || true
  git -C "$d" branch --show-current 2>/dev/null || true
  git -C "$d" rev-parse HEAD 2>/dev/null || true
  git -C "$d" status --short 2>/dev/null | wc -l
done
```

Record:

```bash
git remote -v
git branch --show-current
git rev-parse HEAD
git status --short
git log --oneline --decorate -20
git log --oneline origin/main..HEAD
git diff --stat
git worktree list --porcelain
```

Fetch without modifying the working tree:

```bash
git fetch --all --prune
git rev-parse origin/main
```

Determine whether local commit `72b6ddd2` exists:

```bash
git cat-file -t 72b6ddd2 2>/dev/null || true
git show --stat --oneline 72b6ddd2 2>/dev/null || true
git branch -a --contains 72b6ddd2 2>/dev/null || true
```

Write:

```text
artifacts/deepseek-v4-audit/STAGE0_SOURCE_RECONCILIATION.md
artifacts/deepseek-v4-audit/STAGE0_COMMANDS.txt
artifacts/deepseek-v4-audit/STAGE0_GIT_STATUS.txt
```

The reconciliation report must state:

- canonical checkout path;
- local HEAD;
- `origin/main`;
- deployed SHA if independently verifiable;
- whether `72b6ddd2` exists locally;
- whether it exists on any remote branch;
- dirty-file count and ownership;
- whether GitHub, server, deployed site, and Drive agree;
- exact safe base commit for the implementation branch.

### Stage 0 stop conditions

Stop before editing if:

- the repository remote is not `PatsKiller/tardeai`;
- the safe base commit cannot be identified;
- the local DeepSeek commit is not recoverable;
- unrelated dirty files would be overwritten;
- a dedicated worktree cannot be created;
- the input checksums fail.

---

## 4. Create a dedicated worktree and branch

Use the reconciled safe base. Preferred pattern:

```bash
REPO="<verified canonical checkout>"
BASE="<verified commit containing the recoverable DeepSeek work, or reviewed origin/main>"
WT="/home/johnclaw/tradeai-wt-deepseek-v4-routing"
BRANCH="fix/deepseek-v4-routing"

git -C "$REPO" worktree add -b "$BRANCH" "$WT" "$BASE"
cd "$WT"
git status --short
git rev-parse HEAD
```

If the branch or worktree already exists, inspect it and stop rather than overwriting it.

Read every applicable `AGENTS.md`, `CLAUDE.md`, repository instruction, architecture document, and test/runbook file from root to each target directory before editing.

Copy the three input documents into a non-authoritative evidence directory only if repository policy permits it. Do not edit the originals.

---

## 5. Stage 1 — Full model and lane inventory

Create a machine-readable inventory of every model/lane reference.

Search at minimum:

```bash
rg -n --hidden \
  --glob '!node_modules/**' \
  --glob '!dist/**' \
  --glob '!build/**' \
  --glob '!.git/**' \
  '(deepseek|deepseek-chat|deepseek-reasoner|deepseek-v4|deepseek-v4-flash|deepseek-v4-pro|grok|chatgpt|gemma|ollama|lane_policy|allowed_lanes|reasoning_effort|thinking|response_format)' \
  .
```

Inventory all:

- backend callers;
- central provider clients;
- direct HTTP calls;
- frontend lane types;
- buttons and labels;
- API routes;
- JSON/YAML registries;
- database defaults/migrations;
- cron and systemd definitions;
- health checks;
- usage/cost accounting;
- agents and queues;
- docs and archived copies;
- tests and fixtures;
- environment-variable names;
- model literals and fallback chains.

Generate:

```text
artifacts/deepseek-v4-audit/LLM_REFERENCE_INVENTORY.json
artifacts/deepseek-v4-audit/LLM_REFERENCE_INVENTORY.md
artifacts/deepseek-v4-audit/PROCESS_TO_MODEL_MATRIX.csv
artifacts/deepseek-v4-audit/LEGACY_ALIAS_HITS.txt
artifacts/deepseek-v4-audit/DIRECT_PROVIDER_CALLS.txt
```

Each reference row must include:

```json
{
  "path": "",
  "line": 0,
  "symbol": "",
  "process_id": "",
  "current_lane": "",
  "current_model_literal": "",
  "provider_client": "",
  "structured_output": false,
  "fallback_behavior": "",
  "consumer_surface": "",
  "risk_class": "",
  "recommended_policy": "",
  "evidence": ""
}
```

Do not edit until the inventory is complete.

---

## 6. Stage 2 — Verify current official DeepSeek capabilities

Use only official DeepSeek documentation and the live official API endpoint.

Verify that the currently supported exact model IDs are returned by:

```text
GET https://api.deepseek.com/v1/models
```

Do not print the API key. Use the existing governed secret mechanism. Prefer a small Python probe that logs only:

- HTTP status;
- request ID if available;
- returned model IDs;
- duration;
- sanitized error class.

The probe must test from:

1. the same Unix user as the production application;
2. the same Python environment;
3. the same service environment or an equivalent approved wrapper.

An interactive-shell success alone is insufficient.

Verify and preserve evidence for:

- `deepseek-v4-flash`;
- `deepseek-v4-pro`;
- base URL;
- thinking toggle;
- `reasoning_effort` accepted values;
- JSON response mode;
- tool-call compatibility;
- `reasoning_content` replay requirements;
- context/output limits;
- current pricing.

Store the retrieval date and documentation source names. Do not hard-code prices without an effective date.

Write:

```text
artifacts/deepseek-v4-audit/DEEPSEEK_CAPABILITY_PROBE.json
artifacts/deepseek-v4-audit/DEEPSEEK_CAPABILITY_PROBE.md
artifacts/deepseek-v4-audit/DEEPSEEK_OFFICIAL_DOC_FACTS.json
```

### Credential handling

Canonical target:

```text
DEEPSEEK_API_KEY
```

A legacy `deepseek_tradeai` lookup may be supported temporarily for migration, but:

- never print either value;
- emit a sanitized deprecation warning when the legacy name is used;
- document the Bitwarden item/field name without its value;
- do not modify Bitwarden in this prompt;
- do not copy the key into the repository or shell history.

If the service environment lacks the key, produce the exact operator remediation but do not mutate the service.

---

## 7. Stage 3 — Canonical model registry

Review the proposed registry. Correct it from current evidence.

Implement one authoritative registry, preferably:

```text
config/llm_model_registry.json
```

It must be JSON-schema validated and include:

- registry version;
- effective date;
- provider;
- provider family;
- official base URL;
- auth type;
- governed credential reference;
- canonical env name;
- temporary legacy env name;
- exact model ID;
- display name;
- enabled state;
- context limit;
- output limit;
- JSON support;
- tool support;
- thinking support/default;
- allowed reasoning efforts;
- unsupported parameters in thinking mode;
- latency class;
- price snapshot and effective date;
- concurrency class/limit if used;
- last capability probe;
- kill/disable switch;
- fallback policy.

Logical policies must be separate from exact model IDs:

```text
FAST
FAST_THINK
PRO
PRO_THINK
PRO_MAX
```

The registry, not business code, maps a logical policy to:

- exact provider;
- exact model ID;
- thinking enabled/disabled;
- reasoning effort;
- timeout/output defaults.

Reject unknown policies and unknown model IDs. Never return `available=true` for an unknown lane.

Add:

```text
config/schemas/llm_model_registry.schema.json
tests/fixtures/llm_model_registry.valid.json
tests/fixtures/llm_model_registry.invalid.json
```

---

## 8. Stage 4 — Curate process policy

Review and merge the proposed process-policy JSON into the repository's canonical process registry rather than creating a disconnected second truth source.

Each process must declare:

- process ID and category;
- default logical policy;
- allowed policies;
- default mode: manual/automated;
- response schema ID/version;
- thinking policy;
- escalation target;
- deterministic escalation conditions;
- timeout;
- max input/output;
- daily request cap;
- daily USD cap;
- fallback behavior;
- operator confirmation requirement;
- whether model disagreement is required;
- whether paid Pro is allowed.

At minimum classify:

- routine extraction/classification/summarization → `FAST`;
- moderate contradiction/coherence review → `FAST_THINK`;
- long-context synthesis without hard reasoning → `PRO`;
- CIO/strategy/complex review/incidents → `PRO_THINK`;
- maximum reasoning → `PRO_MAX`, operator-confirmed only.

Do not route a task to Pro solely because Flash is unavailable.

Remove duplicated frontend process-policy constants. The frontend must consume server-authoritative policy.

Add JSON schema and tests for:

- duplicate process IDs;
- unsupported policies;
- missing required schema IDs;
- Pro Max without operator confirmation;
- automated Pro without a USD cap;
- process policy referencing a disabled model.

---

## 9. Stage 5 — Provider client implementation

Build or refactor one canonical DeepSeek provider client.

Required behavior:

### Exact models

Use only:

```text
deepseek-v4-flash
deepseek-v4-pro
```

Legacy aliases must produce a visible migration/configuration error. Do not silently remap them after the migration deadline.

### Request construction

- official base URL;
- canonical key;
- bounded connect/read timeout;
- explicit exact model;
- explicit thinking toggle;
- explicit `reasoning_effort` when thinking;
- omit temperature/top-p/presence/frequency penalties in thinking mode;
- bounded `max_tokens`;
- optional JSON response mode;
- stable user-agent/version;
- request metadata without secrets.

### Response handling

Capture:

- provider request ID;
- exact returned model;
- finish reason;
- content;
- reasoning content where applicable;
- tool calls;
- usage;
- latency;
- HTTP status;
- retry count;
- sanitized error class.

For thinking-mode tool calls, preserve and replay required `reasoning_content` and non-null assistant content exactly as required by the official API.

### Errors

Use typed errors, at minimum:

```text
AUTH_MISSING
AUTH_INVALID
MODEL_NOT_FOUND
RATE_LIMITED
TIMEOUT
PROVIDER_5XX
NETWORK_ERROR
EMPTY_CONTENT
JSON_INVALID
OUTPUT_TRUNCATED
POLICY_BLOCKED
COST_CAP_EXCEEDED
```

Retry only retryable conditions, with bounded exponential backoff and jitter. Do not retry authentication, model-not-found, policy, or schema errors indefinitely.

### No silent fallback

The following are prohibited:

- unknown lane → local Gemma;
- DeepSeek failure → local Gemma while reporting success;
- Pro failure → Flash while reporting Pro;
- provider failure → cached prose without an explicit stale label.

Fallback is permitted only when the process policy explicitly names it, and the response must expose:

```json
{
  "requested_policy": "PRO_THINK",
  "executed_policy": "FAST_THINK",
  "fallback_used": true,
  "fallback_reason": "operator-approved-policy",
  "provider_error": "sanitized code"
}
```

For financial review processes, default to visible failure or deterministic fallback—not model substitution.

---

## 10. Stage 6 — Strict JSON contracts

For every process that expects JSON:

1. define a versioned Pydantic model or JSON Schema;
2. include the word `json` and an exact example in the prompt;
3. set `response_format={"type":"json_object"}`;
4. set a sufficient output limit;
5. parse once;
6. validate against the schema;
7. allow no more than one bounded repair attempt;
8. reject extra prose;
9. handle empty content;
10. handle truncation/length finish reasons;
11. preserve the raw response hash;
12. persist schema ID/version and parser result.

Never regex-extract the first `{...}` block from arbitrary prose and call it valid.

If repair fails, return:

```text
MODEL_OUTPUT_INVALID
```

or a named deterministic fallback. Persist both attempts without exposing secrets or hidden reasoning.

Add fixtures for:

- valid JSON;
- empty content;
- markdown-wrapped JSON;
- extra prose;
- invalid types;
- missing fields;
- unknown fields;
- truncated JSON;
- `finish_reason=length`;
- malformed tool arguments;
- valid thinking response;
- valid tool-call response requiring reasoning replay.

---

## 11. Stage 7 — Consumption and real cost

Correct accounting so paid DeepSeek cost is not represented by character-based relative units.

Persist separately:

- cache-hit input tokens;
- cache-miss input tokens;
- output tokens;
- reasoning tokens if exposed;
- exact model;
- requested/executed policy;
- thinking state;
- reasoning effort;
- price snapshot ID/effective date;
- calculated USD cost;
- provider request ID;
- latency;
- success/error class.

Do not overwrite historical data silently. Use an additive migration and compatibility view if needed.

Add:

- per-process request cap;
- per-process USD cap;
- global daily USD cap;
- Pro and Pro Max operator confirmation;
- spend alert threshold;
- fail-closed behavior when a hard cost cap is exceeded.

Ensure the UI distinguishes:

```text
estimated cost
provider-reported usage
actual billed cost unavailable
```

Do not call an estimate “actual” unless verified.

---

## 12. Stage 8 — Frontend and site maturity

Audit all canonical `/v3` routes and subtabs from the actual router and page components. Generate the route inventory automatically.

Correct:

- “V4”, “V4 R1”, and ambiguous “DeepSeek” labels;
- OAuth-only provider readiness assumptions;
- duplicated TypeScript policy;
- one-button generic DeepSeek testing;
- hidden model substitutions;
- missing error detail;
- missing cost/model/probe provenance.

The UI must show:

- exact model ID;
- Flash versus Pro;
- thinking off/high/max;
- requested and executed policy;
- last capability probe;
- readiness;
- last success/failure;
- sanitized error code;
- latency;
- token usage;
- estimated cost;
- request ID;
- response schema;
- fallback status.

Add separate provider tests:

```text
Test V4 Flash
Test V4 Pro
```

A “Think deeper” action may appear only when allowed by process policy. `PRO_MAX` must show cost impact and require explicit operator confirmation.

Never expose the API key or key-presence details to the browser. The browser receives only a sanitized provider capability state.

### Route/screenshot proof

For each canonical route/subtab:

1. navigate;
2. assert URL;
3. assert the visible page heading;
4. assert the active-tab marker;
5. wait for stable network/UI state;
6. capture screenshot;
7. record status and console errors.

A screenshot filename is not proof. If the expected heading or active tab is absent, the test fails and no PASS screenshot is counted.

Generate:

```text
artifacts/deepseek-v4-audit/V3_ROUTE_INVENTORY.json
artifacts/deepseek-v4-audit/V3_ROUTE_TEST_RESULTS.json
artifacts/deepseek-v4-audit/V3_ROUTE_TEST_RESULTS.md
artifacts/deepseek-v4-audit/screenshots/
```

Flag duplicate or near-identical screenshots and investigate them.

---

## 13. Required tests

Discover and use the repository's authoritative commands first. At minimum, add and run equivalent coverage for:

### Static/configuration

- JSON parsing;
- JSON Schema validation;
- no duplicate process IDs;
- no unsupported policy;
- no legacy model aliases;
- no unknown lane returning available;
- no model literals outside the registry, except fixtures/docs allowlist;
- no production secret in Git;
- frontend/backend policy consistency.

### Provider unit tests

Mock:

- `/v1/models`;
- Flash non-thinking;
- Flash thinking high;
- Pro non-thinking;
- Pro thinking high;
- Pro thinking max;
- 401/403;
- 404 model;
- 429 with retry-after;
- timeout;
- connection error;
- provider 5xx;
- empty content;
- malformed JSON;
- truncated output;
- tool call with reasoning replay;
- mismatched returned model.

### Integration tests

- process policy → logical policy → exact model;
- manual/automated gating;
- cost caps;
- usage logging;
- explicit fallback envelope;
- no silent Gemma fallback;
- server capability endpoint;
- UI readiness endpoint;
- Flash and Pro manual smoke routes;
- structured-output route.

### Frontend

- type-check;
- unit tests;
- build;
- model controls rendered only when policy permits;
- exact model labels;
- offline/auth/model-not-found/error states;
- think-deeper confirmation;
- route/subtab assertions;
- screenshot capture with heading/active-tab assertions.

### Safety regression

- no broker-write path added;
- no order path changed;
- no risk/2FA/execution authority added;
- existing no-broker-write tests;
- current `/v3` build and regression suite.

### Bounded live-provider tests

Only after mocked tests pass and the existing governed key is available to the service runtime:

1. `GET /v1/models`;
2. one tiny Flash non-thinking request;
3. one tiny Flash thinking request;
4. one tiny Pro non-thinking request;
5. one tiny Pro thinking-high request;
6. one strict JSON request per exact model;
7. optionally one controlled tool-call replay test.

Do not run Pro Max without operator confirmation.

Log no prompt containing financial secrets, positions, credentials, or customer data. Use synthetic prompts.

For every live test preserve:

- timestamp;
- exact model;
- thinking/effort;
- HTTP status;
- request ID;
- returned model;
- usage;
- cost estimate;
- latency;
- sanitized output hash;
- pass/fail.

---

## 14. Test commands and evidence

Before implementation, record discovered commands. Expected examples may include:

```bash
python -m pytest -q
python -m pytest -q tests/test_llm_consumption.py
python -m pytest -q tests/test_llm_lane_deepseek.py
python -m pytest -q tests/test_llm_model_registry.py
python -m pytest -q tests/test_llm_json_contracts.py
python -m pytest -q tests/test_no_broker_write.py

jq -e . config/llm_model_registry.json
jq -e . config/llm_process_registry.json

cd apps/command-center-v3
npm ci
npm run typecheck
npm test -- --run
npm run build
```

Use repository-specific equivalents where different.

Save complete output:

```text
artifacts/deepseek-v4-audit/tests/
```

Do not summarize away failures. Redact only secrets.

---

## 15. Implementation sequencing

Commit in reviewable stages:

1. `audit(llm): reconcile DeepSeek source and reference inventory`
2. `feat(llm): add canonical model registry and schemas`
3. `fix(llm): implement exact DeepSeek V4 Flash/Pro provider client`
4. `feat(llm): curate process routing and escalation policy`
5. `fix(llm): enforce strict JSON contracts and typed failures`
6. `feat(llm): add paid-token and cost governance`
7. `fix(ui): expose exact DeepSeek policy, health, cost, and errors`
8. `test(llm): add provider, JSON, routing, UI, and safety coverage`
9. `docs(llm): add operation, rollback, and evidence reports`

After each commit:

```bash
git status --short
git diff --check
git show --stat --oneline HEAD
```

Do not squash away the evidence stages before review.

---

## 16. Acceptance gates

All must pass:

```text
SOURCE SHA RECONCILED: YES
LOCAL/GITHUB/DRIVE DIVERGENCE EXPLAINED: YES
UNOWNED DIRTY FILES IN WORKTREE: 0
LEGACY DEEPSEEK MODEL IDS IN ACTIVE CODE: 0
UNKNOWN LANE RETURNS AVAILABLE: NO
SILENT LOCAL-GEMMA FALLBACK: NO
FLASH REQUEST RETURNS deepseek-v4-flash: YES
PRO REQUEST RETURNS deepseek-v4-pro: YES
THINKING STATE RECORDED: YES
REASONING EFFORT RECORDED: YES
SERVICE-RUNTIME KEY PROBE: PASS
STRICT JSON CONTRACT TESTS: PASS
EMPTY/TRUNCATED JSON HANDLING: PASS
TOOL REASONING REPLAY TEST: PASS
REAL TOKEN/COST ACCOUNTING: PASS
PROCESS POLICY SERVER-AUTHORITATIVE: YES
FRONTEND POLICY DUPLICATION: 0
V3 ROUTE/ACTIVE-TAB ASSERTIONS: PASS
SCREENSHOT FALSE-POSITIVE CHECK: PASS
NO BROKER/ORDER/2FA CHANGE: PASS
BUILD: PASS
REGRESSION: PASS
DEPLOYED: NO
```

Any failed gate makes the final verdict `CONDITIONAL_FAIL` or `FAIL`, never PASS.

---

## 17. Stop conditions

Stop immediately and preserve evidence if:

- a secret is exposed;
- the server/runtime SHA cannot be reconciled;
- a required branch would overwrite existing work;
- official model IDs do not match the proposal;
- the live key is unavailable in the service runtime;
- Pro cannot be invoked by exact model ID;
- JSON validation remains nondeterministic;
- a test touches a broker/order/2FA path;
- a production restart or deploy becomes necessary;
- implementation requires changing trading authority;
- the canonical route inventory cannot be established;
- tests fail and the root cause is not understood.

Write a failure closeout with the exact safe resume command.

---

## 18. Required deliverables

Create:

```text
artifacts/deepseek-v4-audit/FINAL_DEEPSEEK_V4_IMPLEMENTATION_REPORT.md
artifacts/deepseek-v4-audit/SOURCE_RECONCILIATION.md
artifacts/deepseek-v4-audit/LLM_REFERENCE_INVENTORY.json
artifacts/deepseek-v4-audit/PROCESS_TO_MODEL_MATRIX.csv
artifacts/deepseek-v4-audit/DEEPSEEK_CAPABILITY_PROBE.json
artifacts/deepseek-v4-audit/MODEL_POLICY_MATRIX.md
artifacts/deepseek-v4-audit/JSON_CONTRACT_MATRIX.md
artifacts/deepseek-v4-audit/COST_MODEL_AND_CAPS.md
artifacts/deepseek-v4-audit/V3_ROUTE_TEST_RESULTS.json
artifacts/deepseek-v4-audit/SECURITY_AND_AUTHORITY_REVIEW.md
artifacts/deepseek-v4-audit/ROLLBACK.md
artifacts/deepseek-v4-audit/CHANGED_FILES.txt
artifacts/deepseek-v4-audit/TESTS.json
artifacts/deepseek-v4-audit/TEST_LOGS/
```

The final report must include:

- start and end SHAs;
- branch/worktree;
- exact files changed;
- exact model IDs;
- Flash/Pro process matrix;
- thinking policy;
- JSON contract status;
- provider and service-runtime test evidence;
- cost accounting;
- UI/route status;
- all failed/waived tests;
- residual risks;
- rollback;
- PR URL or exact push command;
- deploy status `NO`;
- operator actions still required.

---

## 19. Final closeout format

```text
TASK: DeepSeek V4 routing and site maturity
VERDICT:
CANONICAL REPO:
WORKTREE:
BRANCH:
START SHA:
END SHA:
ORIGIN/MAIN:
LOCAL DEEPSEEK COMMIT RECOVERED:
DIRTY FILES AT START:
DIRTY FILES IN TASK WORKTREE AT END:
MODEL REGISTRY:
PROCESS REGISTRY:
FLASH MODEL:
PRO MODEL:
THINKING POLICIES:
LEGACY ALIASES REMAINING:
SILENT FALLBACKS REMAINING:
JSON CONTRACTS:
SERVICE-RUNTIME AUTH PROBE:
LIVE FLASH SMOKE:
LIVE PRO SMOKE:
REAL COST LOGGING:
V3 ROUTES TESTED:
V3 ROUTES PASSED:
SCREENSHOT ASSERTIONS:
UNIT TESTS:
INTEGRATION TESTS:
FRONTEND TESTS:
BUILD:
SAFETY REGRESSION:
BROKER WRITE:
ORDER QUEUED:
ORDER SUBMITTED:
ORDER MODIFIED:
ORDER CANCELLED:
2FA REQUESTED:
PRODUCTION SECRET PRINTED:
PRODUCTION SERVICE RESTARTED:
DEPLOYED:
COMMITS:
PUSH:
PR:
ROLLBACK:
OPEN RISKS:
OPERATOR NEXT ACTION:
```

End after producing the evidence and PR-ready branch. Do not deploy.
