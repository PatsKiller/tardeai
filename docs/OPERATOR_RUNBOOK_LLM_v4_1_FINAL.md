# Operator Runbook — LLM Fleet v4.1 Final Execution Pack

Status:      ACTIVE
as_of:       2026-06-02T21:03:40-04:00
Measured at: efcc51365 / not measured

> **⚠️ Model policy (validated 2026-06-02):** gemma3:12b = primary chat, gemma3:4b = fallback, gemma3:27b = overnight; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** Any reference below to qwen3:14b as an active chat/generation model is superseded — see `MASTER_SYSTEM_DOCUMENTATION.md` §12.


**Server:** `ms01-openclaw`  
**SSH:** `johnclaw@192.168.50.16`  
**Project root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`  
**Execution status:** Phase 0 may proceed after gates pass. Phases 1-4 require separate explicit approval.

---

## 1. Files in this execution pack

Copy these files to the project server under `docs/`:

1. `LLM_FLEET_STRATEGY_v4_1_FINAL.md`
2. `CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md`
3. `OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md`

Recommended server destination:

```bash
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/
```

---

## 2. SCP copy commands

### Option A — Windows PowerShell, individual files

Run this from the folder where the files are saved locally:

```powershell
scp .\LLM_FLEET_STRATEGY_v4_1_FINAL.md .\CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md .\OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md johnclaw@192.168.50.16:/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/
```

### Option B — Windows PowerShell, ZIP pack

```powershell
scp .\LLM_Fleet_v4_1_Final_Execution_Pack.zip johnclaw@192.168.50.16:/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/
```

Then SSH in and unzip:

```powershell
ssh johnclaw@192.168.50.16
```

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p docs/llm_fleet_v4_1_final
unzip -o docs/LLM_Fleet_v4_1_Final_Execution_Pack.zip -d docs/llm_fleet_v4_1_final
cp docs/llm_fleet_v4_1_final/*.md docs/
ls -l docs/*v4_1_FINAL*.md docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md
```

### Option C — Linux / WSL / macOS

```bash
scp LLM_FLEET_STRATEGY_v4_1_FINAL.md \
    CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md \
    OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md \
    johnclaw@192.168.50.16:/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/
```

---

## 3. Server-side verification after copy

SSH to the server:

```bash
ssh johnclaw@192.168.50.16
```

Then verify:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
pwd
ls -lh docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md \
       docs/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md \
       docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md
```

Optional checksum capture:

```bash
sha256sum docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md \
          docs/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md \
          docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md \
  | tee docs/llm_fleet_v4_1_final_checksums.txt
```

---

## 4. Operator commands before Claude Code changes anything

These are operator-only checks. Run them yourself before telling Claude Code to begin.

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

git status --short
git log -1 --oneline

python3 -c "
import json
p='data/portfolios/state/holdings.json'
d=json.load(open(p))
v=d['portfolio_totals']['total_value']
n=len(d.get('holdings', []))
print(f'Holdings: ${v:,.0f} across {n} positions')
assert v > 1_000_000
assert n > 0
print('Holdings guard: PASSED')
"

grep -E '^(ALPACA_MODE|LIVE_TRADING|LLM_DISABLE_LIVE_EXECUTION)=' .env
curl -sf http://localhost:11434/api/tags >/tmp/ollama_tags.json && echo 'Ollama: alive'
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c 'SELECT 1;'
```

Required safety state:

```text
ALPACA_MODE=paper
LIVE_TRADING=false
LLM_DISABLE_LIVE_EXECUTION=true
```

If `LLM_DISABLE_LIVE_EXECUTION=true` is missing, do not guess. Have Claude Code document the mismatch and propose the safest way to add or verify the equivalent guard.

---

## 5. Backup requirement before Phase 0

Claude Code must not run backups. The operator runs the backup, then Claude Code verifies that a recent backup exists.

First inspect the live backup flags:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python scripts/full_system_backup.py --help
```

Use the command supported by the live script. If the script supports `--tag`, use a phase tag such as:

```bash
.venv/bin/python scripts/full_system_backup.py --tag llm_v4_1_phase_0
```

If `--tag` is not supported, run the documented backup command from `--help`, then record the resulting path in:

```bash
docs/v4_1_deployment_log.md
```

Claude Code should verify backup recency with:

```bash
PHASE=0
find data backups docs/backups ~/db_backups -type f 2>/dev/null \
  | grep -E "llm_v4_1_phase_${PHASE}|trade_ai|backup" \
  | xargs -r ls -lt \
  | head -20
```

---

## 6. Claude Code launch command

From the project root:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
claude
```

If Claude Code is launched differently on your server, use your normal launcher, but make sure it starts in the project root.

---

## 7. Paste this into Claude Code

Paste the following as the initial Claude Code instruction:

```text
Read these files in full before making any changes:

1. docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md
2. docs/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md
3. docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md

Begin Phase 0 only.

You are authorized to run Phase 0 discovery gates and prepare Phase 0 changes only after every gate passes. You are not authorized to run backups, model pulls, full RAG re-index, broker actions, trading actions, holdings changes, cron-wide refactors, or Phase 1-4 work.

Before editing any file, do the following:

- Confirm you read the strategy and execution prompt.
- Create docs/v4_1_discovery/.
- Run all Gate 0 discovery commands from the execution prompt.
- Verify git status, holdings guard, paper mode, Ollama health, DB connectivity, backup recency, provider map, and existing local_llm_config.py/local_llm.py ownership.
- If any gate fails or the live system differs materially from the plan, stop and write the discrepancy to docs/v4_1_deployment_log.md.

For Phase 0, your goals are:

1. Preserve local_llm_config.py/local_llm.py as the source of truth unless live code proves otherwise.
2. Add or extend a process-type routing layer without creating a competing config hub.
3. Add live provider verification.
4. Add LLM audit logging with JSONL fallback.
5. Add GPU lifecycle status/warmup/cooldown/OOM detection.
6. Add /api/v2/gpu-status only if the API integration point is clear.
7. Register GPU/OOM/warmup-failure alert path through the central alert dispatcher if available.
8. Produce docs/v4_1_deployment_log.md and a script-routing migration list.

Do not begin Phase 1. Phase 1 remains optional/high-risk and requires me to explicitly say: Begin Phase 1.
```

---

## 8. Phase authorization language

Use exact language when approving phases:

```text
Begin Phase 0.
```

Do not say `Begin Phase 1` until Phase 0 has clean telemetry and you are ready to test `gemma3:27b` as an overnight-only pilot.

---

## 9. Does this address which scripts use which local LLM?

Yes, but intentionally through process types rather than hardcoded script/model pairs.

The execution pack requires Phase 0 to discover every current model reference and direct Ollama caller, then classify scripts by process type. Known initial mapping:

| Workflow | Going-forward routing |
|---|---|
| Active-hours agent analysis, watchlist jobs, topic curation, morning briefs | STANDARD / REALTIME → `qwen3:14b` |
| Long overnight strategy classification and weekly strategy review | BATCH_OVERNIGHT → `gemma3-overnight`, only after Phase 1 approval and pilot testing |
| RAG embeddings | EMBEDDING → keep `nomic-embed-text` until Phase 2 A/B passes; then `qwen3-embedding:8b` |
| Report/prose/media summarization | MEDIA_CONTENT → `gemma4:e4b`, only after Phase 3 pilot approval |
| Retirement, Roth, SSDI, IRMAA, tax-critical, CIO-critical reasoning | CRITICAL_CLOUD → cloud-only, fail loud, no local fallback |

Important: the pack does **not** authorize mass-refactoring every script in one pass. It forces a migration list first, pilots only selected scripts, and prevents new hardcoded model names.

---

## 10. Stop conditions

Stop immediately if any of these happen:

- Holdings guard fails or holdings value drops below $1M.
- `.env` is not paper-only.
- Backup cannot be verified.
- Ollama is not reachable.
- DB connectivity fails.
- Existing LLM config ownership is unclear.
- Claude Code finds direct local-LLM callers that require a larger refactor than Phase 0 allows.
- GPU OOM occurs and qwen cannot be restored.
- Any change would affect broker execution, holdings, orders, live trading, or non-LLM cron behavior.

