# Hermes Phase P0 Install Report — Trade AI v12

**Date:** 2026-05-30
**Status:** PHASE 0 COMPLETE — install verified, no DB writes, no services

---

## Install Summary

| Item | Value |
|------|-------|
| Hermes installed | **YES** |
| Version | hermes-agent **0.15.2** (2026.5.29.2) |
| Python | 3.13.7 |
| Install method | `pip install hermes-agent` into isolated venv |
| Install path | `hermes_sidecar/install/.venv/` |
| HERMES_HOME | `hermes_sidecar/.hermes/` |
| `~/.hermes` created | **NO** — global home is clean |
| Config | `hermes_sidecar/.hermes/config.yaml` (local Ollama only) |
| Wrapper | `hermes_sidecar/run_hermes_readonly.sh` |

---

## Verification Results

### Version Check
```
Hermes Agent v0.15.2 (2026.5.29.2)
Python: 3.13.7
OpenAI SDK: 2.24.0
Up to date
```

### Doctor Check

| Category | Status |
|----------|--------|
| Python environment | PASS |
| Required packages | PASS (all installed) |
| Directory structure | PASS (all under hermes_sidecar/.hermes/) |
| Memory provider | PASS (built-in file memory) |
| Security advisories | PASS (none active) |
| Config version | 24 (current) |
| External tools | git, ripgrep, Node.js available |
| Optional packages not installed | python-telegram-bot, discord.py (intentional) |
| External API keys | None configured (intentional — Ollama only) |

### Global Config Check
```
~/.hermes: does NOT exist — PASS
```

### Ollama Health (unchanged)

| Model | Size | Available |
|-------|------|-----------|
| gemma3:12b | 7.6GB | YES |
| gemma3:4b | 3.1GB | YES |
| gemma3:27b | 16.2GB | YES |
| gemma3-overnight | 16.2GB | YES |
| nomic-embed-text | 0.3GB | YES |
| qwen3-embedding:8b | 4.4GB | YES |

Ollama version: 0.24.0 — unchanged.

### Trade AI Safety (unchanged)

| Setting | Value |
|---------|-------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |

### Service/Cron Check

| Check | Result |
|-------|--------|
| Hermes systemd units | NONE |
| Hermes cron entries | NONE |
| Hermes daemon processes | NONE |

---

## Files Created by Install

All files are contained within `hermes_sidecar/`:

```
hermes_sidecar/
├── .hermes/
│   ├── .update_check
│   ├── SOUL.md                    (auto-generated persona)
│   ├── auth.lock
│   ├── config.yaml                (our custom config)
│   ├── cron/                      (empty)
│   ├── logs/
│   │   ├── agent.log
│   │   └── errors.log
│   ├── memories/                  (empty)
│   ├── sessions/                  (empty)
│   └── skills/                    (empty)
├── install/
│   └── .venv/                     (Python venv with hermes-agent)
├── project_memory/                (empty)
├── reports/                       (empty)
└── run_hermes_readonly.sh         (sidecar wrapper)
```

No files created outside `hermes_sidecar/`.

---

## Config

```yaml
model:
  provider: custom
  default: gemma3:12b
  base_url: http://127.0.0.1:11434/v1
  api_mode: openai

terminal:
  backend: local
  cwd: /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
  timeout: 180
  env_passthrough:
    - OLLAMA_HOST

memory:
  provider: file
```

No external API keys. No cloud providers. Local Ollama only.

---

## Rollback Verified

```bash
rm -rf hermes_sidecar/
```

Single command removes all Hermes artifacts. No global state to clean.

---

## Safety Confirmation

| Item | Status |
|------|--------|
| DB writes | **ZERO** |
| DB migrations | **ZERO** |
| hermes_* tables created | **NO** |
| Production table writes | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** |
| Journal mutations | **ZERO** |
| Broker access | **ZERO** |
| Cron changes | **ZERO** |
| .env changes | **ZERO** |
| Model routing changes | **ZERO** |
| Systemd services created | **ZERO** |
| Daemon started | **NO** |
| External API keys configured | **ZERO** |
| OpenClaw changes | **ZERO** |
| Dashboard code changes | **ZERO** |

---

## Phase 1 Readiness

Phase 1 (database staging tables) is a separate approval:

1. Create `hermes_readonly` PostgreSQL role
2. Create 6 `hermes_*` staging tables per `HERMES_DATABASE_FIRST_INTEGRATION_ARCHITECTURE.md`
3. Grant SELECT on all + INSERT/UPDATE on hermes_* only
4. Build read-only API endpoints for Hermes data access
5. Run first Hermes research agent against live Trade AI data

**Operator approval required before Phase 1.**
