# Hermes Read-Only Pilot Plan — Trade AI v12

**Date:** 2026-05-29  
**Status:** PLAN ONLY — DO NOT RUN PILOT UNTIL INSTALL IS APPROVED  
**Mode:** file-memory, read-only, no cron, no gateway, no DB writes, no broker access

---

## Pilot Purpose

Hermes will act as Trade AI's near-24/7 research desk, second brain, memory layer, and independent challenger.

Hermes will **not**:

- execute trades
- submit or approve orders
- mutate proposals
- mutate `paper_trades`
- mutate journals
- write to PostgreSQL
- change cron
- change `.env`
- change LLM routing
- call external LLMs
- use broker credentials

---

## Pilot Operating Model

```text
Trade AI = system of record + execution authority
Claude Code = implementation authority after operator approval
Hermes = read-only research/memory/challenge sidecar
Operator = final decision authority
```

Hermes outputs are advisory notes only. They must be reviewed by the operator and, if implementation is needed, converted into a Claude Code prompt.

---

## Pilot Filesystem Contract

### Allowed read paths

```text
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/strategies/
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/holdings.json
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/state/
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/  # read only
```

### Allowed write paths

```text
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/hermes_sidecar/.hermes/
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/hermes_sidecar/project_memory/
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/hermes_sidecar/reports/
```

### Denied paths

```text
.env
.env.*
scripts/
apps/
sql/
config/ except read-only strategy review
crontab files
paper_trades mutation paths
journal mutation paths
proposal mutation paths
broker adapters
```

---

## Pilot Agents

These are Hermes roles/personas, not separate Trade AI workers.

### 1. Chief Hermes Coordinator

**Purpose:** maintain Hermes' work queue, daily memory, and challenge map.

**Inputs:** docs, prior Hermes reports, operator-approved watch topics.

**Outputs:**

```text
hermes_sidecar/reports/chief_coordinator/YYYY-MM-DD.md
hermes_sidecar/project_memory/HERMES_DAILY_MEMORY.md
```

**Rules:**

- never recommend direct execution
- label every conclusion as evidence-backed, hypothesis, or question
- convert implementation ideas into Claude Code prompt drafts, not code changes

### 2. Ticker Research Agent

**Purpose:** analyze a ticker's story, catalysts, risk, and missing evidence.

**Inputs:** available Trade AI docs, public research only if separately approved later, local files.

**Outputs:**

```text
hermes_sidecar/reports/ticker_research/SYMBOL_YYYY-MM-DD.md
```

**Template:**

```markdown
# SYMBOL Hermes Research Note

## Verdict
Advisory only: WATCH / RESEARCH_MORE / CHALLENGE_EXISTING_THESIS

## Evidence Reviewed

## Bull Case

## Bear Case

## What Trade AI May Be Missing

## Questions for Steph/Aegis/Operator

## Suggested Claude Code Prompt, if implementation is needed
```

### 3. News/Transcript Reframer

**Purpose:** reframe news and transcripts into concise agent-usable research notes.

**Outputs:**

```text
hermes_sidecar/reports/news_reframes/YYYY-MM-DD_TOPIC.md
```

**Rules:**

- summarize, do not ingest into DB
- identify source, date, relevance, and uncertainty
- never update RAG directly

### 4. Incubator Research Agent

**Purpose:** independently challenge incubator candidates and identify evidence gaps.

**Inputs:** read-only incubator summaries, strategy YAMLs, existing reports.

**Outputs:**

```text
hermes_sidecar/reports/incubator/SYMBOL_YYYY-MM-DD.md
```

**Rules:**

- no promotion/demotion mutation
- no proposal creation
- no score changes
- output only: challenge memo and evidence gap list

### 5. All-Trade Reflection Agent

**Purpose:** review closed trade patterns and operator lessons from exported/read-only records.

**Outputs:**

```text
hermes_sidecar/reports/trade_reflection/YYYY-MM-DD.md
```

**Rules:**

- no journal mutation
- no outcome correction
- no DB writes
- all suggested corrections must become operator-reviewed tasks

---

## Pilot Phases

### Phase P0 — Dry Context Test

Goal: confirm Hermes can read sidecar memory and project docs without writing elsewhere.

Allowed:

- `hermes version`
- `hermes doctor`
- one interactive session asking it to summarize the sidecar rules

Not allowed:

- generation against Trade AI data beyond a tiny sidecar rules prompt
- external tools
- cron/gateway

Success:

- no files written outside sidecar
- no config written to global home unexpectedly
- no external API requests

### Phase P1 — One Ticker Research Note

Goal: produce one read-only ticker memo from existing files.

Allowed output:

```text
hermes_sidecar/reports/ticker_research/TEST_SYMBOL_YYYY-MM-DD.md
```

Success:

- advisory-only output
- no mutation paths touched
- report clearly separates facts, hypotheses, questions

### Phase P2 — One Incubator Challenge Memo

Goal: review one incubator candidate from read-only exports.

Success:

- no promotion/demotion
- no scoring mutation
- useful evidence-gap list

### Phase P3 — All-Trade Reflection Dry Run

Goal: reflect on exported trade journal/read-only records only.

Success:

- no journal mutation
- action items are framed as operator tasks

### Phase P4 — Daily Read-Only Desk Trial

Goal: run manually once per day for 3 sessions.

Still not allowed:

- cron
- gateway
- DB writes
- external APIs
- model-routing changes

Success:

- operator finds the notes useful
- no safety boundary violations
- memory remains concise and auditable

---

## Memory Design

### MEMORY.md

Purpose: environment facts and Hermes operating rules.

Initial contents should include:

```markdown
Hermes is a read-only Trade AI sidecar. Trade AI remains the system of record and only execution authority. Claude Code implements only operator-approved changes. Hermes does not mutate DB, broker, proposals, paper_trades, journals, cron, .env, or model routing. Hermes writes only under hermes_sidecar/ unless the operator explicitly approves a docs update.
```

### USER.md

Purpose: operator preferences.

Initial contents should include:

```markdown
The operator prefers direct, evidence-backed recommendations, clear risks, and implementation ideas converted into Claude Code prompts. Do not bluff. Mark uncertainty clearly.
```

### Project memory export

Hermes memory should be periodically copied into:

```text
hermes_sidecar/project_memory/HERMES_PROJECT_MEMORY_EXPORT.md
```

Do not auto-merge Hermes memory into Trade AI docs.

---

## Model Recommendation

### First choice

```text
gemma3:12b via Ollama custom OpenAI-compatible endpoint
```

Rationale:

- aligns with current production runtime policy
- avoids new provider keys
- avoids Grok/xAI defaulting
- avoids model-routing changes

### Constraint

Hermes requires 64K context. If current `gemma3:12b` cannot satisfy that safely, stop.

### Do not use initially

- `gemma3:4b` as primary, unless only for smoke tests
- `Gemma4 31B` unless offline/deep reviewer path is separately approved
- `Grok/xAI`, except later as external challenger
- `qwen3:14b`, because it is disabled/not production per current Hermes policy

---

## External Model Recommendation

First pilot: **none**.

Later optional challenger:

```text
Grok/xAI as external challenger only, never default Hermes brain
```

Gate before external model:

- operator approval
- budget cap
- no secrets leakage
- no automatic fallback to paid providers
- every external call logged

---

## Safety Checklist Before Each Manual Run

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

git status --short
crontab -l | grep -i hermes && echo 'STOP: Hermes cron exists' || true
systemctl --user list-units --type=service --type=timer | grep -i hermes && echo 'CHECK: Hermes service exists' || true
find hermes_sidecar -maxdepth 3 -type f | sort | tail -50
```

Confirm:

- no `.env` change
- no cron change
- no systemd gateway unless explicitly approved
- no writes outside sidecar
- no Trade AI DB or broker credentials passed through

---

## Pilot Success Criteria

Hermes pilot is successful only if:

- all reports stay advisory-only
- no unauthorized writes occur
- no external model/API calls occur
- no cron/gateway is enabled
- no LLM routing changes occur
- operator finds at least 3 research notes useful enough to convert into Claude Code prompts or Trade AI review tasks

---

## Pilot Failure Criteria

Stop and rollback if:

- Hermes writes outside sidecar
- Hermes tries to access `.env`
- Hermes asks for broker/API credentials
- Hermes creates/changes cron
- Hermes mutates code or docs outside approved report files
- Hermes cannot use local model due context limits
- Hermes requires cloud login for basic local operation

---

## Final Pilot Recommendation

Start with:

1. Chief Hermes Coordinator
2. One Ticker Research Agent memo
3. One News/Transcript Reframer memo
4. One Incubator Research Agent memo
5. One All-Trade Reflection memo

Keep it manual, read-only, file-memory based, and sidecar-isolated until the operator approves the next step.
