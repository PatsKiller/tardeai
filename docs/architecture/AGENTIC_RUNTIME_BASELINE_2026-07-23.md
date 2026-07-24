# Trade AI Agentic Runtime Baseline — 2026-07-23

**Status:** implementation baseline; host verification pending; no activation authorization  
**Branch:** `feat/agentic-mvl-runtime-foundation`  
**Source base:** `main` at `98ee288ec387b6513a270bafc51380404844e9e5`  
**Controlling architecture:** `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md`

## 1. Executive finding

Trade AI has substantial deterministic automation and many named prompt personas, but it does not yet have the durable, governed reflective-agent runtime defined by the canonical architecture.

The repository currently contains:

- deterministic request routing (`scripts/agent_router.py`);
- prompt-call context sharing and handoff logging (`scripts/agent_collab.py`);
- scheduled outcome matching and calibration (`scripts/agent_outcome_scorer.py`);
- named-agent configuration and OpenClaw directory references (`config/agents.json`, `docs/AGENT_ROSTER.md`);
- local/OAuth model lanes and Watch ticket-review code elsewhere in the repository.

These are useful capabilities. They are not by themselves durable agents because run state, immutable artifacts, checkpoints, cancellation, tool decisions, independent review, and complete scoring are not represented by one governed lifecycle.

## 2. Evidence-backed gaps

### Durable run state

Current prompt-call workflows generally write domain results or logs. A canonical agent run with immutable envelope, checkpoint sequence, retrieval record, model/tool provenance, cancellation state, review, and score is not yet the common runtime contract.

### Retrieval-before-reasoning

Repository agents may receive context assembled by individual scripts, but the runtime does not universally prove retrieval before every eligible reflective reasoning call.

### Tool authority

Existing scripts determine their own data and write behavior. There is not yet one deterministic allow/deny policy binding every reflective tool call to agent, environment, run, arguments hash, and result hash.

### Independent review and scoring

The outcome scorer measures recommendations, but the existing system does not universally prevent an agent from validating or scoring its own artifact. It also writes calibration text into an intelligence-rules table, which must not become autonomous production promotion under the new constitution.

### OpenClaw and Hermes

OpenClaw is documented as an interface layer and several agent homes are named. Hermes-related workflows exist in documentation and Active Trader governance. The live installed versions, homes, services, permissions, channels, profiles, and isolation boundaries have not been verified in this implementation session.

### Model and embedding drift

`docs/AGENT_ROSTER.md` contains a warning that `gemma3:12b` is primary and `qwen3-embedding:8b` is active, while its detailed rows still name `qwen3:14b`. The live Ollama inventory and actual embedding rows must be measured rather than inferred from documentation.

### Secret policy drift

Some legacy scripts read database credentials from `.env`. The controlling architecture requires Bitwarden Secrets Manager and prohibits raw secrets from agent context. This branch does not migrate credentials; it prevents secret-like fields from entering the new MVL runtime and records legacy migration as remaining work.

## 3. Foundation implemented on this branch

### Governed contracts

- LAB/SHADOW-only run envelopes;
- agent versions, owners, allowed job types, allowlisted and denied tools;
- hard-denied broker, order, trade, execution, approval, 2FA, secret, production write, config promotion, shell, and service authorities;
- immutable artifacts bound to input hash, deterministic-validation hash, retrieval refs, prompt version, provider family, model, and payload hash;
- independent review and scoring contracts;
- model/tool/cost budgets;
- secret-like-field rejection.

### Durable shadow journal

- append-only JSONL journal for lab and replay tests;
- SHA-256 event hash chain;
- 0600 run files in a 0700 directory;
- checkpoint, status, resume, and cancellation reconstruction;
- refusal of production-looking paths.

The file journal is not the production target. It exists to prove the runtime semantics before applying the additive Postgres schema in an isolated lab.

### Additive MVL schema

Exactly eight first-phase tables under a separate `agentic_runtime` schema:

1. `agent_runs`
2. `agent_artifacts`
3. `agent_tool_calls`
4. `agent_reviews`
5. `agent_scores`
6. `kb_lessons`
7. `kb_cases`
8. `kb_chunks`

Evidence tables are append-only. Reviewer and scorer independence is enforced by database checks. Embedding fields require provider, model, and version together. The environment is restricted to LAB or SHADOW.

### OpenClaw boundary

The first operator contract supports only:

- `status`
- `explain`
- `cancel`
- `resume`

There is no arbitrary shell, broker action, production database write, approval, 2FA, secret read, service restart, or config promotion command.

### Hermes boundary

Hermes may preregister a frozen shadow hypothesis with success metrics, failure metrics, evaluation plan, and rollback plan. Promotion is intentionally unrepresentable and raises a permission error.

## 4. Not completed or claimed

- no migration applied to any database;
- no OpenClaw or Hermes installation, upgrade, restart, or configuration change;
- no production or shadow service created;
- no live channel connected;
- no production database role created;
- no embedding model selected or re-embedding performed;
- no KB corpus imported;
- no Watch ticket routed through the new runtime;
- no Sentinel population acceptance performed;
- no Darwin production scorecard produced;
- no nightly reflection scheduled;
- no agent promoted to OPERATIONAL;
- no broker, account, order, approval, 2FA, Moomoo, or Active Trader path touched.

## 5. Required host verification

Run read-only on `ms01-openclaw` and preserve exact output before activation or package changes:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

git rev-parse HEAD
git status --short

.venv/bin/python - <<'PY'
import openai
print("openai", openai.__version__)
PY

~/.local/bin/hermes --version || true
~/.local/share/hermes-agent-venv/bin/pip show hermes-agent || true
openclaw --version
node --version
npm --version
ollama list

psql -Atc "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
systemctl --user status openclaw-gateway --no-pager || true
systemctl status moomoo-opend --no-pager || true
```

Also inventory:

- OpenClaw homes, gateway ports, channels and inherited environment;
- Hermes homes, profiles, MCP tools, auto-graft/config behavior and Python environment;
- active agent-related crons and systemd units;
- canonical model registry and capability probes;
- live embedding model and embedding provenance by table;
- agent prompts, tools, output schemas, scores and owners;
- database roles available for a read-only shadow runtime and lab schema writes.

Do not upgrade anything during the baseline.

## 6. Activation decision

This foundation may progress through tests and review as a draft PR. It must remain unactivated until the host baseline, permission matrix, isolated database proof, and rollback plan are reviewed.
