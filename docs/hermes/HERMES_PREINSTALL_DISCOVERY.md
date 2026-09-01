# Hermes Preinstall Discovery — 2026-05-30

Status:      ACTIVE
as_of:       2026-05-29T23:33:07-04:00
Measured at: efcc51365 / not measured

## Status: PREINSTALL ONLY — Hermes is NOT installed

---

## 1. Hermes Installation Status

| Check | Result |
|-------|--------|
| `which hermes` | Not found |
| npm global | Not installed |
| pip / dpkg | Not installed |
| `~/.hermes` directory | Does not exist |
| Hermes systemd units | None |
| Hermes cron entries | None |
| Hermes processes | None (see note below) |
| Hermes files outside project | Only `~/hermes_sidecar_upload/` (staging folder from design package upload) |

**Note:** A tmux session named `Hermes` exists (created 2026-05-29 22:36) — this is the operator's terminal session for this work, not a Hermes daemon.

**Conclusion: Hermes is not installed anywhere on this system.**

---

## 2. Ollama Health

| Check | Result |
|-------|--------|
| Ollama API | Responding on `127.0.0.1:11434` |
| Ollama version | 0.24.0 |
| Models loaded | None currently loaded (idle) |
| Available models | 6 total |

### Available Models

| Model | Size | Hermes Role |
|-------|------|-------------|
| `gemma3:12b` | 7.6GB | Primary research/analysis |
| `gemma3:4b` | 3.1GB | Quick summaries, fallback |
| `gemma3:27b` | 16.2GB | Available but NOT production |
| `gemma3-overnight:latest` | 16.2GB | Overnight deep queue alias |
| `nomic-embed-text:latest` | 0.3GB | Embeddings (Trade AI RAG) |
| `qwen3-embedding:8b` | 4.4GB | Embeddings (hybrid RAG, offline only) |

### Model Policy Alignment

| v4 Strategy Requirement | Current System | Status |
|-------------------------|---------------|--------|
| gemma3:12b for normal research | Available | READY |
| gemma3:4b for quick summaries | Available | READY |
| Gemma4 31B via llama.cpp for deep review | Validated in canary (not Ollama) | READY (off-hours only) |
| qwen3:14b disabled | Not installed in Ollama | COMPLIANT |
| Gemma4 e2b/e4b disabled | Not installed | COMPLIANT |
| gemma3:27b not production | Available but not routed | COMPLIANT |
| Max concurrent: 1 | Enforced by Ollama config | COMPLIANT |

---

## 3. Trade AI Safety Mode

| Setting | Value | Status |
|---------|-------|--------|
| `ALPACA_MODE` | `paper` | SAFE — no real broker orders |
| `LLM_DISABLE_LIVE_EXECUTION` | `true` | SAFE — LLM cannot trigger execution |

**Conclusion: Trade AI safety mode is unchanged and correct.**

---

## 4. Trade AI Services

| Service | Port | Status |
|---------|------|--------|
| Trade AI API (python) | 7777 | Running (pid 4703) |
| DOF Auction / secondary (python3) | 7776 | Running (pid 3220) |
| Ollama | 11434 | Running, healthy |

---

## 5. Cron/Service Impact Assessment

| Item | Change Needed for Hermes Phase 1? |
|------|-----------------------------------|
| Existing Trade AI crons | NO — no changes |
| Existing systemd services | NO — no changes |
| Ollama service | NO — already running, models available |
| `.env` | NO — no changes for read-only pilot |
| Database schema | NO — Hermes Phase 1 is file-based only |
| Broker config | NO — Hermes never touches broker |
| Model routing | NO — Hermes uses same models via same Ollama |

**Conclusion: No cron, service, or config changes are needed for Hermes Phase 1.**

---

## 6. Design Documents Present

| Document | Path | Status |
|----------|------|--------|
| Hermes v4 Strategy | `docs/hermes/Hermes_Sidecar_Strategy_for_Trade_AI_v4.md` | Present (24KB) |
| Project Memory Notes | `docs/hermes/Hermes_Project_Memory_Notes_v4.md` | Present (2.2KB) |
| Strategy PDF | `docs/hermes/Hermes_Sidecar_Strategy_for_Trade_AI_v4.pdf` | Present (331KB) |
| Strategy DOCX | `docs/hermes/Hermes_Sidecar_Strategy_for_Trade_AI_v4.docx` | Present (47KB) |
| Package ZIP | `docs/hermes/Hermes_Sidecar_Strategy_v4_Package.zip` | Present (174KB) |

### Planning Documents

| Document | Purpose | Status |
|----------|---------|--------|
| `HERMES_INSTALL_EXECUTION_PLAN.md` | Step-by-step install plan with gates | Present |
| `HERMES_READ_ONLY_PILOT_PLAN.md` | Phase 1 read-only pilot plan | Present |
| `HERMES_COMPATIBILITY_AUDIT.md` | Audit Hermes tool compatibility | TO BE CREATED |

---

## 7. Key Findings from v4 Strategy Review

### What Hermes Is (per v4 design)

- Near-24/7 research desk, second brain, memory layer, independent challenger
- 6 pods, 24 logical agents (target)
- Phase 1: 5 agents only (Coordinator, Ticker, News, Incubator, All-Trade Reflection)
- File-based memory first (`data/hermes_memory/`)
- Local LLM only (gemma3:12b primary, gemma3:4b fallback)
- Read-only access to Trade AI data

### What Hermes Is NOT

- Not a trading bot, broker, approval engine, or execution path
- Not a replacement for Trade AI
- Not allowed to mutate proposals, trades, journal, cron, .env, or model routing

### Hermes Safety Boundary

Hermes may: read APIs/exports, write advisory JSONL memory, write Markdown reports, write recommendation queue items, flag missing evidence, ask for operator review.

Hermes must never: place orders, approve/reject proposals, mutate paper_trades/journal, change .env/cron/model routing, run arbitrary shell commands.

### Phase 1 Inputs Needed (read-only)

- Latest 25 closed trades
- Current open trades
- Current incubator items
- Latest 50 news articles + related news
- Latest YouTube transcripts
- Latest rejected/expired/missed proposals
- Latest portfolio/retirement holdings
- Latest tax/rebalance watchlist
- Latest internal tickets

### Phase 1 Outputs

- Daily Hermes Research Brief
- Ticker dossiers, incubator watch, trade lessons
- Missed opportunity report, research debt list
- One strategy hypothesis
- All output to files — no DB writes, no mutations

---

## 8. Open Questions for Compatibility Audit

The v4 strategy references "Hermes" as a tool/system to install. Before proceeding, the compatibility audit must determine:

1. **What is Hermes?** — Is this a specific open-source tool, a custom build, or a design pattern to implement from scratch within Trade AI?
2. **Install behavior** — If a tool: what does it install? Global config? Daemon? Background service?
3. **Memory storage** — File-based JSONL per v4 design, or does the tool impose its own storage?
4. **Local model support** — Can it route to local Ollama? Or does it require cloud APIs?
5. **External API calls** — Does it phone home, call OpenAI/Anthropic by default, or stay local?
6. **Project scoping** — Can it be scoped to this project only, or is it system-wide?
7. **Sandboxing** — Can it be restricted to read-only Trade AI access?
8. **Claude Code conflict** — Does it conflict with the running Claude Code session?
9. **Rollback/uninstall** — Clean removal path?

**These questions must be answered before any install is approved.**

---

## 9. Preinstall Checklist Summary

| Check | Status |
|-------|--------|
| Hermes not installed | CONFIRMED |
| No `~/.hermes` global config | CONFIRMED |
| Ollama healthy | CONFIRMED (v0.24.0, responding) |
| gemma3:12b available | CONFIRMED |
| gemma3:4b available | CONFIRMED |
| Trade AI safety mode unchanged | CONFIRMED (paper mode, LLM execution disabled) |
| No cron changes needed | CONFIRMED |
| No service changes needed | CONFIRMED |
| No .env changes needed | CONFIRMED |
| No DB writes performed | CONFIRMED |
| No broker access | CONFIRMED |
| No external API setup | CONFIRMED |
| No Hermes daemon started | CONFIRMED |
| Design documents present | CONFIRMED (5 files in docs/hermes/) |

---

## 10. Recommended Next Step

Create the **Hermes Compatibility Audit** (`HERMES_COMPATIBILITY_AUDIT.md`) to answer the 9 open questions in Section 8. This determines whether Hermes is a tool to install or a system to build from scratch within Trade AI's existing architecture.

No install until the audit is complete and operator-approved.
