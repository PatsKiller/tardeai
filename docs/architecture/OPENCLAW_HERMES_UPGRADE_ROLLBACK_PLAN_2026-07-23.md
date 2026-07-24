# OpenClaw and Hermes Shadow Upgrade / Rollback Plan — 2026-07-23

**Status:** plan only; live versions and installation layout must be verified first  
**Prohibition:** no production in-place upgrade and no reuse of production homes, channels, secrets, ports or mutable state.

## 1. Preconditions

Before downloading, installing or changing a package:

1. record production Git/deployed SHA and dirty state;
2. record exact OpenClaw and Hermes versions and package provenance;
3. inventory production homes, services, ports, channels and environment variables;
4. inventory Ollama models, OpenAI SDK, embedding model and pgvector;
5. prove a separate LAB/SHADOW database identity;
6. approve this plan and the tool-permission matrix;
7. preserve current service definitions and package hashes for rollback.

## 2. Side-by-side target

Recommended isolated layout:

```text
/opt/trade-ai/runtime/openclaw/<candidate-version>/
/opt/trade-ai/runtime/hermes/<candidate-version>/
/var/lib/trade-ai-shadow/openclaw/
/var/lib/trade-ai-shadow/hermes/
/run/trade-ai-shadow/secrets/
```

Candidate environment:

```text
OPENCLAW_HOME=/var/lib/trade-ai-shadow/openclaw
HERMES_HOME=/var/lib/trade-ai-shadow/hermes
TRADE_AI_ENV=SHADOW
```

Requirements:

- separate Unix identity where practical;
- separate gateway port;
- test channel or outbound disabled;
- read-only canonical database views;
- staging-only schema for MVL artifacts;
- no production Bitwarden machine token;
- no broker credentials;
- no production agent workspace import by mutable reference;
- no auto-graft or config promotion;
- no service name collision.

## 3. Candidate validation

### OpenClaw

- version and package hash;
- separate home and gateway port;
- channel isolation;
- OAuth route behavior without inherited production sessions;
- governed MCP tool enumeration;
- status, explain, cancel and resume only;
- checkpoint reconstruction after process restart;
- prompt-injection denial tests;
- no production environment or secret inheritance;
- bounded cost and latency display;
- graceful failure when Hermes, a model lane or the KB is unavailable.

### Hermes

- version, Python and package hash;
- separate home and memory;
- profile import into shadow, never production mutation;
- tool allowlist and denied authority;
- MCP isolation;
- retrieval before experiment design;
- preregistered frozen hypothesis artifact;
- success/failure metrics and rollback present before evaluation;
- promotion method absent/denied;
- no auto-graft, automatic threshold update or production config write;
- model-route and cost provenance.

### Integrated MVL

- one Watch artifact enters Sentinel after deterministic validation;
- retrieval is recorded;
- local/OAuth reviews are bound independently;
- deterministic reconciler preserves disagreements and hard failures;
- artifact is scored by Darwin, not Sentinel;
- Nightly Reflection writes only candidates;
- Iris/operator adjudication remains separate;
- cancellation and restart resume are proven;
- every tool call has allow/deny evidence.

## 4. Promotion boundary

Candidate success does not authorize production promotion.

A later promotion requires:

- reviewed baseline and compatibility reports;
- 100 reviewed Watch artifacts;
- at least 20 known-bad fixtures;
- retrieval on at least 95% of eligible Sentinel runs;
- scored output on at least 95% of artifacts;
- zero deterministic failures released;
- measured false-positive rate, cost and latency;
- security review;
- explicit architecture-owner approval;
- one-step operational rollback;
- post-promotion observation plan.

## 5. Atomic promotion design

Only after approval:

```text
/opt/trade-ai/runtime/openclaw/current -> <approved-version>
/opt/trade-ai/runtime/hermes/current  -> <approved-version>
```

Service definitions reference `current`; they do not overwrite the previous version. Database migration uses additive schema and compatibility reads. No destructive cleanup occurs in the promotion window.

## 6. Rollback

Rollback steps:

1. stop candidate/shadow service only;
2. disable candidate timer/channel;
3. restore previous `current` pointer if a promotion occurred;
4. restore prior service definition/environment file;
5. restart prior version;
6. verify prior port, channel and status;
7. leave immutable candidate evidence for incident review;
8. apply `migrations/agentic_runtime/0001_mvl.down.sql` only in the isolated target when complete schema removal is explicitly approved;
9. confirm no production table, agent config, broker state, approval, 2FA or order was touched.

Do not delete the previous version, home snapshot or service file until the observation window closes.

## 7. Stop conditions

Stop and do not promote when any of the following occurs:

- production secret or channel inheritance;
- ungoverned tool exposure;
- a model or Hermes can alter deterministic facts or financial authority;
- run state cannot survive restart;
- cancellation is not terminal;
- an agent can review/score itself;
- retrieval or model provenance is missing;
- a local lane silently falls back to cloud;
- cost cannot be bounded and attributed;
- previous version cannot be restored in one controlled step.
