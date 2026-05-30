# Hermes Install Execution Plan — Trade AI v12

**Date:** 2026-05-29  
**Status:** PLAN ONLY — DO NOT INSTALL  
**Target:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/hermes_sidecar`

---

## Non-Negotiable Install Gate

Do not install Hermes until the operator explicitly says:

```text
Approve Hermes sidecar install.
```

Anything short of that is not approval.

---

## Purpose

Install Hermes as a project-scoped, read-only sidecar for Trade AI research memory and challenge analysis.

Hermes is **not**:

- a trading worker
- a proposal generator
- a broker client
- a DB writer
- a cron owner
- a replacement for Claude Code
- a replacement for Trade AI agents
- the system of record

Trade AI remains the source of truth and only execution authority. Claude Code remains the implementation tool for operator-approved changes.

---

## Pre-Install Gate 0 — Missing Doc Review

Before installation, Claude Code must read these live-server docs:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
sed -n '1,240p' docs/hermes/Hermes_Sidecar_Strategy_for_Trade_AI_v4.md
sed -n '1,240p' docs/hermes/Hermes_Project_Memory_Notes_v4.md
sed -n '1,240p' docs/project/MEMORY_NOTES_FOR_NEXT_SESSION_2026_05_29_FINAL.md
sed -n '1,240p' docs/project/NEXT_SESSION_RUNBOOK_2026_05_29_FINAL.md
sed -n '1,240p' docs/drive_cleanup_2026_05_30/DRIVE_CLEANUP_AUDIT_REPORT.md 2>/dev/null || true
```

If any required Hermes memory/runbook doc is missing, stop and ask the operator.

---

## Pre-Install Gate 1 — Safety and State Discovery

Run only read-only commands:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p docs/hermes/discovery

pwd | tee docs/hermes/discovery/pwd.txt
git status --short | tee docs/hermes/discovery/git_status_short.txt
git log -1 --oneline | tee docs/hermes/discovery/git_head.txt

command -v hermes | tee docs/hermes/discovery/hermes_path.txt || true
hermes version | tee docs/hermes/discovery/hermes_version.txt || true
ls -la ~/.hermes 2>&1 | tee docs/hermes/discovery/home_hermes_listing.txt || true
find . -maxdepth 4 -iname '*hermes*' -print | tee docs/hermes/discovery/project_hermes_find.txt

systemctl --user list-units --type=service --type=timer \
  | grep -Ei 'hermes|openclaw|trade|portfolio|aegis|ollama' \
  | tee docs/hermes/discovery/user_units.txt || true

systemctl list-units --type=service --type=timer \
  | grep -Ei 'hermes|openclaw|trade|portfolio|ollama' \
  | tee docs/hermes/discovery/system_units.txt || true

curl -s http://localhost:11434/api/tags \
  | tee docs/hermes/discovery/ollama_tags.json || true
```

Stop if:

- Hermes is already active as a gateway/service
- working tree contains unexpected changes that would be confused with install artifacts
- Ollama is unhealthy
- current LLM routing docs conflict with live config

---

## Pre-Install Gate 2 — No Credential Exposure

Hermes pilot must not receive Trade AI secrets.

Do **not** pass through:

- `DB_PASSWORD`
- `ALPACA_*`
- `FINVIZ_*`
- `FMP_API_KEY`
- `FINNHUB_API_KEY`
- `POLYGON_API_KEY`
- `NEWSAPI_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `XAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Allowed for model-health testing only:

```text
OLLAMA_HOST=http://127.0.0.1:11434
```

---

## Recommended Install Strategy

### Preferred path: sidecar Git install with isolated home

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p hermes_sidecar/{install,bin,reports,project_memory,.hermes/memories,.hermes/logs}

# Install command only after approval:
# HERMES_HOME="$PWD/hermes_sidecar/.hermes" \
#   curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

If the upstream installer insists on `~/.hermes`, stop and switch to manual Git clone inside `hermes_sidecar/install/hermes-agent` rather than polluting the operator home.

### Manual fallback path

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/hermes_sidecar/install
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
./setup-hermes.sh
```

Only use after confirming where it writes config and venv state.

---

## Sidecar Wrapper

Create after install approval only:

```bash
cat > hermes_sidecar/run_hermes_readonly.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
export HERMES_HOME="$ROOT/hermes_sidecar/.hermes"
export HERMES_CONFIG="$HERMES_HOME/config.yaml"
export OLLAMA_HOST="http://127.0.0.1:11434"
unset DB_PASSWORD ALPACA_API_KEY ALPACA_SECRET_KEY ALPACA_BASE_URL
unset FINVIZ_COOKIE FINVIZ_USER_AGENT FMP_API_KEY FINNHUB_API_KEY POLYGON_API_KEY NEWSAPI_KEY
unset OPENAI_API_KEY ANTHROPIC_API_KEY XAI_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
cd "$ROOT"
exec hermes "$@"
SH
chmod +x hermes_sidecar/run_hermes_readonly.sh
```

---

## Initial Config Target

Use custom local endpoint only:

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

If Hermes rejects `gemma3:12b` due to context limit, do not change production model routing. Record the failure and evaluate one of these later, with operator approval:

1. Ollama Modelfile/context adjustment for `gemma3:12b` if safe
2. local llama.cpp endpoint using offline Gemma4 31B, but only outside production hours
3. external challenger model, but not during first pilot

---

## Local Model Health Check

Allowed health checks only:

```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool
curl -s http://localhost:11434/v1/models | python3 -m json.tool || true
```

No generation call unless operator approves. If a generation smoke test is approved, use one short prompt and log start/end time.

---

## What Not To Enable During Install

Do not enable:

- `hermes gateway setup`
- `hermes gateway install`
- `hermes gateway start`
- Hermes cron scheduler
- Telegram/WhatsApp/Slack/Discord
- Nous Portal
- OpenRouter
- Anthropic/OpenAI/xAI
- browser/cloud tools
- MCP servers that write to Drive/Gmail/Calendar
- shell tools with write permission outside sidecar

---

## First Post-Install Validation

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
./hermes_sidecar/run_hermes_readonly.sh version
./hermes_sidecar/run_hermes_readonly.sh doctor
./hermes_sidecar/run_hermes_readonly.sh config check
find hermes_sidecar -maxdepth 4 -type f | sort > docs/hermes/discovery/post_install_files.txt
```

Expected:

- Hermes launches
- config lives under sidecar
- memory lives under sidecar
- no global gateway is installed
- no systemd unit is created
- no cron entries are created
- no Trade AI files modified outside `docs/hermes/` and `hermes_sidecar/`

---

## Rollback Plan

### Sidecar-only rollback

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
hermes gateway stop || true
systemctl --user disable --now hermes-gateway 2>/dev/null || true
rm -rf hermes_sidecar
```

### Global install rollback, only if global install was approved

```bash
hermes uninstall
```

### Manual cleanup

```bash
rm -f ~/.local/bin/hermes
# Only remove ~/.hermes if it did not exist before this project or operator approves:
# rm -rf ~/.hermes
```

---

## Documentation Commit Checklist

Before claiming complete:

- `docs/hermes/HERMES_COMPATIBILITY_AUDIT.md` exists
- `docs/hermes/HERMES_INSTALL_EXECUTION_PLAN.md` exists
- `docs/hermes/HERMES_READ_ONLY_PILOT_PLAN.md` exists
- `docs/project/PROJECT_DOC_INDEX.md` is updated per A1A
- discovery outputs are saved under `docs/hermes/discovery/`
- no code, DB, `.env`, broker, cron, or journal files changed

---

## Install Approval Required

Operator approval required before install: **YES**
