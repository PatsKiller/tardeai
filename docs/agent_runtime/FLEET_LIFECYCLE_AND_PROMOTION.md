# Agent-Runtime Fleet — Lifecycle & Promotion (why only 4 of 16 are SHADOW)

Answers "why are all of these not SHADOW?" for the `/v3/agents` Maturity scoreboard,
and records the per-agent promotion assessment. **Nothing here promotes an agent** —
promotion requires evidence none of the DESIGNED agents currently have.

## The lifecycle model (states are earned, not assigned)

| State | Meaning | Authority |
|-------|---------|-----------|
| **DESIGNED** | The agent is specified (or only cataloged) but **not enabled**. Its prerequisites are visible; it runs nothing. | none |
| **SHADOW** | Enabled **inside LAB/SHADOW only**. It may research/critique/score/stage advisory drafts; it is independently reviewed and scored. | `CRITIQUE_AND_STAGE_ONLY`, zero financial authority |
| **OPERATIONAL** | Not reachable through this runtime. Cannot be claimed without full acceptance evidence + human promotion. | — |

`SHADOW` is a **claim that the agent has met the promotion contract**, so it cannot
be set by hand. Flipping DESIGNED→SHADOW without the evidence below would fake exactly
the readiness this board exists to prove.

### The promotion contract (DESIGNED → SHADOW)
An agent qualifies only with **all** of: a governed runtime spec (artifact schema,
triggers, budget, retrieval policy); an **independent reviewer ≠ scorer ≠ producer**;
an owner + disable/rollback control; connected **fixtures / known-bad set**; and
**measured acceptance evidence** — the 12 `maturity_gates` (`min_artifact_population
≥ 100`, retrieval/review/score coverage = 1.0, contradiction/unsupported-claim rates,
`operator_usefulness ≥ 0.7`, `rollback_test_passed`, `authority_violations = 0`).

## Current fleet — per-agent status

**SHADOW (4) — enabled wave-1 reflective critics**

| Agent | Role | Runtime evidence | Eligibility |
|-------|------|------------------|-------------|
| sentinel | decision-integrity / contradiction review | RUNTIME_EVIDENCE, 120 reviewed | NOT_ELIGIBLE (own critiques not yet independently reviewed; gates unmeasured) |
| darwin | scoring / calibration | RUNTIME_EVIDENCE, 120 scored | NOT_ELIGIBLE (same) |
| iris | knowledge / lesson lifecycle | none yet | not eligible (has not run) |
| reflection | case→lesson / hypothesis generation | none yet | not eligible (has not run) |

**DESIGNED with a runtime spec (4) — "wave-2", disabled pending wave-1 acceptance**

| Agent | Independent reviewer/scorer | Missing for SHADOW |
|-------|-----------------------------|--------------------|
| maria (fundamental/catalyst critic) | iris / darwin | **acceptance evidence** — 0 runs, 0 reviewed artifacts, 12 gates NOT_YET_MEASURED; fixtures not connected; gated behind wave-1 acceptance |
| vega (technical-structure critic) | sentinel / darwin | same |
| risk_agent / Guardian Risk (risk-evidence critic) | iris / darwin | same |
| aegis (incident/remediation critic) | sentinel / darwin | same |

**DESIGNED, catalog-only — no runtime spec yet (8)**

`alex` (CIO synthesis), `argus` (population integrity scan), `atlas` (workflow
orchestration), `concierge` (OpenClaw operator interface), `hermes` (hypothesis
discovery), `pulse` (Moomoo microstructure), `steph` (portfolio/allocation),
`tax_agent` (tax/wash-sale). **These have no governed runtime spec in the fleet at
all** — before promotion is even applicable, each needs a spec authored in
`scripts/agent_runtime/agents/definitions.py` (schema, triggers, budget, independent
reviewer≠scorer), *then* the acceptance evidence above. The runner refuses any agent
not in the fleet, so they cannot be enabled today regardless.

*(The board also lists `broker_cloud_oversight`, `defense_adjudication`, `hermes`,
`concierge` as observability rows for deterministic subsystems — they are read-visible
context, not reflective SHADOW agents, and show `UNKNOWN` because they use a different
framework.)*

## Assessment: can any DESIGNED agent be promoted now?

**No.** Every DESIGNED agent has **zero acceptance evidence** (0 runs under its id,
`evidence` empty in `config/agent_maturity_catalog.json`). The 4 wave-2 agents are
spec-complete but unmeasured and explicitly gated behind wave-1 acceptance; the 8
catalog-only agents lack a runtime spec entirely. Promoting any would violate the
promotion contract. **Enable nothing** — re-assess per agent once it has measured,
independently-reviewed evidence.

## What it takes to move the fleet forward (in order)
1. **Run wave-1 for real** — the governed dispatch backend (PR #264) + an operator
   provider module (real LLM + real inputs) + root-enabled timers. See
   `SHADOW_ACTIVATION_RUNBOOK.md`.
2. **Close wave-1 eligibility** — have a peer (iris/reflection) independently review +
   score sentinel's/darwin's own critiques (moves them off `NOT_RUN`), and measure the
   12 gates.
3. **Then wave-2** — only after wave-1 is accepted, and only per-agent as each meets
   the contract with tests.
4. **Catalog-only agents** — author runtime specs first; they are not promotable until
   they exist in the fleet.

## Runtime panel — connected, with a known follow-up
The **Runtime** tab now reads the live same-origin read API (PR #267): the top badge
shows LIVE/SHADOW with real run counts instead of `FIXTURE`. The per-agent **detail
desks** (Run-queue timeline, Artifact review desk, Knowledge/learning, MVL acceptance
badges) are still honestly-labelled **"contract preview"** placeholders — wiring them
to the per-run detail endpoints (`/api/v3/agent-runtime/runs/{id}/artifacts`,
`/reviews`, `/scores`) is the remaining follow-up.
