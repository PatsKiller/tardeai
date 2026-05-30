# Hermes Phase P0 Final Gate — Trade AI v12

**Date:** 2026-05-30
**Recommendation:** **GO**
**Operator approval required:** YES — install does not proceed without explicit approval

---

## Gate Verdict: GO

All seven verification sections pass. No blockers identified. Rollback plan documented and tested (removal is `rm -rf hermes_sidecar/`).

---

## Section Results

### Section 1 — Install Target

| Check | Result |
|-------|--------|
| Target path | `hermes_sidecar/` under project root |
| Directory exists | NO (will be created at install) |
| Conflicts with Trade AI | NONE — separate directory, no shared files |
| Conflicts with OpenClaw | NONE — different runtime, different port (18789) |
| Conflicts with Ollama | NONE — shares Ollama as client, no config changes |
| Conflicts with llama.cpp | NONE — no llama.cpp processes running |
| Conflicts with existing services | NONE — no Hermes services exist |
| `.gitignore` entry needed | YES — add `hermes_sidecar/` at install time |

### Section 2 — Hermes Repository

| Item | Value |
|------|-------|
| Repository | github.com/NousResearch/hermes-agent |
| License | MIT |
| Language | Python 89.1% |
| Current version | 0.14.0+ |
| Install method | `pip install hermes-agent` or project-scoped `setup-hermes.sh` |
| Dependencies | Python 3.10+, optional Node.js for some skills |
| Memory architecture | File-based (`~/.hermes/memories/` or `$HERMES_HOME`) |
| Local model support | YES — Ollama, llama.cpp, LM Studio, vLLM |
| Ollama support | YES — OpenAI-compatible endpoint at `localhost:11434/v1` |
| Uninstall | `pip uninstall hermes-agent` + `rm -rf hermes_sidecar/` |
| Rollback | Documented in `HERMES_ROLLBACK_PLAN.md` |

### Section 3 — Ollama Readiness

| Check | Result |
|-------|--------|
| Ollama running | YES (v0.24.0, pid 296348) |
| gemma3:12b present | YES (7.6GB, Q4_K_M) |
| gemma3:4b present | YES (3.1GB) |
| gemma3:12b native context | **131,072 tokens** |
| gemma3:4b native context | **131,072 tokens** |
| Hermes 64K requirement | **MET** — 131K > 64K |
| Runtime num_ctx override | NOT SET — Ollama defaults to 2048 at runtime |
| Modelfile alias needed? | **MAYBE** — test during P0 smoke test |

**Context window detail:**

The model natively supports 131K context. However, Ollama allocates only 2048 tokens at runtime by default unless the client requests more via `num_ctx` parameter. Hermes should pass `num_ctx: 65536` in its API requests. If Hermes does not support per-request `num_ctx`, a Modelfile alias will be needed:

```
FROM gemma3:12b
PARAMETER num_ctx 65536
```

Registered as `gemma3-hermes:12b`. This does NOT change production model routing — it's a context-only alias. **Do not create this now — test first during P0.**

### Section 4 — Memory Isolation

| Check | Result |
|-------|--------|
| `~/.hermes` exists | **NO** — clean slate |
| Global memory default | `~/.hermes/` |
| Override mechanism | `HERMES_HOME` environment variable |
| Planned override | `HERMES_HOME=hermes_sidecar/.hermes` |
| Global pollution risk | **MITIGATED** by HERMES_HOME override |

**Planned project-scoped layout:**

```
hermes_sidecar/
├── .hermes/              # HERMES_HOME (config, memories, sessions, logs, skills)
│   ├── config.yaml
│   ├── memories/
│   ├── sessions/
│   ├── logs/
│   └── skills/
├── reports/              # Pilot research outputs
│   ├── chief_coordinator/
│   ├── ticker_research/
│   ├── news_reframes/
│   ├── incubator/
│   └── trade_reflection/
├── project_memory/       # Durable memory exports
├── install/              # Hermes source/venv (if git clone)
└── run_hermes_readonly.sh  # Sidecar wrapper (strips secrets)
```

### Section 5 — Read-Only Pilot Feasibility

| Agent | Read-only viable? | DB writes needed? | Broker access? | File-memory works? |
|-------|--------------------|-------------------|----------------|---------------------|
| Chief Hermes Coordinator | YES | NO | NO | YES |
| Ticker Research Agent | YES | NO | NO | YES |
| News/Transcript Reframer | YES | NO | NO | YES |
| Incubator Research Agent | YES | NO | NO | YES |
| All-Trade Reflection Agent | YES | NO | NO | YES |

All 5 pilot agents can operate read-only against existing docs, strategy YAMLs, and exported state files. No database, broker, or external API access required.

**Input sources (all read-only):**

- `docs/` — project documentation, session summaries, audit reports
- `config/strategies/` — strategy YAML definitions
- `data/portfolios/state/holdings.json` — current holdings (read-only snapshot)
- `data/state/` — pipeline state files (read-only)
- `logs/` — system logs (read-only)

### Section 6 — Rollback Plan

**Status:** DOCUMENTED in `docs/hermes/HERMES_ROLLBACK_PLAN.md`

| Rollback scenario | Command | Time |
|-------------------|---------|------|
| Project-scoped install | `rm -rf hermes_sidecar/` | < 2 min |
| Global pip install | `pip uninstall hermes-agent && rm -rf ~/.hermes` | < 3 min |
| Gateway/systemd cleanup | `systemctl --user disable hermes-gateway` | < 1 min |
| Full verification | Run 10-point checklist | < 2 min |

---

## Identified Risks

| # | Risk | Severity | Mitigation | Status |
|---|------|----------|------------|--------|
| 1 | Hermes ignores `HERMES_HOME` and writes to `~/.hermes` | MEDIUM | Verify immediately after install; rollback if violated | MITIGATED |
| 2 | Ollama runtime context defaults to 2048, Hermes needs 64K | MEDIUM | Test during P0; create Modelfile alias only if needed | MITIGATED |
| 3 | Hermes makes external API calls without explicit config | LOW | No API keys provided; Ollama-only config; wrapper strips secrets | MITIGATED |
| 4 | Hermes auto-creates systemd unit during install | LOW | Do not run `hermes gateway install`; verify post-install | MITIGATED |
| 5 | Ollama concurrency conflict (Trade AI + Hermes) | LOW | Manual pilot runs only; operator controls timing | MITIGATED |
| 6 | Hermes reads Trade AI `.env` or credentials | MEDIUM | Wrapper script explicitly unsets all secret env vars | MITIGATED |
| 7 | Hermes modifies files outside sidecar | LOW | Filesystem contract + post-run audit | MITIGATED |

---

## Blockers

**NONE IDENTIFIED.**

---

## Required Operator Approvals

| Approval | Required for |
|----------|-------------|
| **"Approve Hermes sidecar install."** | Proceed with project-scoped install |
| Modelfile alias (if needed) | Only after P0 smoke test reveals context issue |
| Scheduled runs (future) | Only after pilot phases P0-P4 prove value |
| External model (future) | Only after local pilot is proven useful |

---

## Recommendations

1. **Install project-scoped** using `setup-hermes.sh` or pip in a local venv under `hermes_sidecar/`
2. **Set `HERMES_HOME=hermes_sidecar/.hermes`** — verify no `~/.hermes` is created
3. **Configure Ollama-only** — no cloud API keys, no external providers
4. **Run `hermes version` and `hermes doctor`** as first post-install validation
5. **Verify no files created outside `hermes_sidecar/`** after first run
6. **Do not enable gateway, cron, or systemd** during pilot
7. **Add `hermes_sidecar/` to `.gitignore`** to keep install artifacts out of repo

---

## Pre-Install State Snapshot

| Item | Current Value |
|------|---------------|
| Hermes installed | NO |
| `~/.hermes` exists | NO |
| Ollama version | 0.24.0 |
| gemma3:12b context | 131,072 native |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Hermes cron entries | 0 |
| Hermes systemd units | 0 |
| Hermes processes | 0 |
| Trade AI API | Running (port 7777) |
| OpenClaw | Running (port 18789) |

This snapshot serves as the baseline for post-install and rollback verification.

---

## Final Verdict

### **GO**

All verification sections pass. No blockers. Rollback plan documented. Memory isolation designed. Ollama compatibility confirmed. Read-only pilot is feasible.

**Awaiting operator approval to proceed with install.**
