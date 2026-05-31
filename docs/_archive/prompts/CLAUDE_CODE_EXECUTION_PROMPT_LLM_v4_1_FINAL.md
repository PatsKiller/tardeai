# Claude Code Execution Prompt — LLM Fleet v4.1 Final Execution Revision

**For:** Claude Code running on `ms01-openclaw`
**Reference:** `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` (mandatory pre-read; supersedes unannotated v4.1 for execution)
**Companion doc:** Open alongside the strategy doc before executing anything
**Date:** 2026-05-11
**Supersedes:** `CLAUDE_CODE_PROMPT_LLM_v4_0.md`, earlier v4.1 drafts, and the unannotated v4.1 execution prompt for implementation safety purposes

---

## FINAL REVISION HEADER

This final prompt is the execution source for Claude Code and the original developer. It keeps the same strategic direction but adds guardrails required by the current project state:

- Phase 0 may proceed only after gates pass.
- Phase 1 is optional/high-risk and is not automatically approved.
- Existing `local_llm_config.py` / `local_llm.py` must be reconciled before creating any new config layer.
- Backup flags, backup paths, service names, and provider model names must be live-detected.
- RAG embedding migration requires A/B retrieval testing before default switch.
- GPU/OOM failures must use the central alert dispatcher if available.

---

## ROLE

You are Claude Code, executing the LLM Fleet v4.1 final upgrade on `ms01-openclaw` per `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md`. You are authorized for specific phases and steps only. You are NOT authorized for model pulls, RAG re-index runs, or system backups. You are NOT authorized to touch trading-system code, cron entries outside scope, holdings, broker orders, or Telegram alert dispatchers.

This is a phased rollout. You do not advance past an operator gate without explicit operator approval. **You are approved to prepare Phase 0 only after all gates pass. Phases 1-4 require separate approval and should not be treated as pre-approved.**

---

## KEY CHANGES FROM PRIOR DRAFTS

1. **Phase 1 default model is `gemma3:27b`**, NOT `gemma4:26b-a4b`. gemma4 is deferred to 2026-08-11 (see Appendix D of strategy doc).
2. **No freeze window gate** — replaced by backup verification
3. **Backup is Step 0** of every phase — operator runs it, you verify it exists
4. **GPU lifecycle subsystem** required in Phase 0 (`gpu_lifecycle.py`)
5. **Daytime test protocol** explicit in Phase 1 — 3-tier (weekend / pre-market / active-hours-override)
6. **Phase 1 includes 8K-context OOM test** before observation begins
7. **Observation windows shortened** for low-risk phases
8. **Existing config reconciliation added** — `llm_config.py` must wrap/extend current config hub, not compete with it
9. **Backup command discovery added** — verify live script flags before requiring a backup command
10. **RAG A/B validation added** — no embedding default switch on 100% reindex alone
11. **Service-name detection added** — no guessed systemd unit names
12. **GPU alert-dispatch integration added** — OOM/warmup failures must route to central alerting if available

---

## PRE-EXECUTION GATES — ALL MUST PASS

### Gate 0 — Live environment discovery before code changes

Run these discovery commands and save outputs before editing any file:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p docs/v4_1_discovery

# Current git/system state
pwd | tee docs/v4_1_discovery/pwd.txt
git status --short | tee docs/v4_1_discovery/git_status_short.txt
git log -1 --oneline | tee docs/v4_1_discovery/git_head.txt

# Backup script capabilities
.venv/bin/python scripts/full_system_backup.py --help | tee docs/v4_1_discovery/full_system_backup_help.txt || true

# LLM/model references before changes
grep -R "qwen3:\|gemma\|grok\|claude\|gpt-\|OLLAMA\|local_llm" \
  scripts apps config .env* \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=dist \
  | tee docs/v4_1_discovery/llm_reference_scan_before.txt || true

# Existing config and router files
ls -l scripts/*llm* scripts/*router* 2>/dev/null | tee docs/v4_1_discovery/llm_files.txt || true

# Service names — detect, do not assume
systemctl --user list-units --type=service --type=timer \
  | grep -Ei 'trade|portfolio|openclaw|aegis|ollama' \
  | tee docs/v4_1_discovery/user_units.txt || true
systemctl list-units --type=service --type=timer \
  | grep -Ei 'trade|portfolio|openclaw|ollama' \
  | tee docs/v4_1_discovery/system_units.txt || true
```

If these commands reveal that the live system differs materially from this prompt, STOP and write the discrepancy to `docs/v4_1_deployment_log.md`.

### Gate 1 — Documentation read

State in your first response:

```text
Gate 1: I have read LLM_FLEET_STRATEGY_v4_1_FINAL.md. I understand that
Phase 0 is conditionally approved after gates pass, while Phase 1 remains
optional/high-risk and requires separate operator approval. I will reconcile
existing local_llm_config.py/local_llm.py before creating any new config hub. I
will verify backup script flags, provider names, service units, and current model
references from the live system before changes. I will not run model pulls,
full RAG re-index, backups, or phase advancement. I will refuse to deploy any
file change without a verified recent backup.
```

### Gate 2 — Working directory and clean tree

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
pwd
git status
git log -1 --oneline
```

Working tree must be clean. If not, STOP.

### Gate 3 — Holdings integrity

```bash
python3 -c "
import json
p='data/portfolios/state/holdings.json'
d = json.load(open(p))
v = d['portfolio_totals']['total_value']
n = len(d.get('holdings', []))
print(f'Holdings: ${v:,.0f} across {n} positions')
assert v > 1_000_000, f'Holdings total too low: {v}'
assert n > 0
print('Gate 3: PASSED')
"
```

If fails, STOP. Trading system compromised — alert operator immediately.

### Gate 4 — Paper mode

```bash
grep -E '^(ALPACA_MODE|LIVE_TRADING|LLM_DISABLE_LIVE_EXECUTION)=' .env
```

Required:

```text
ALPACA_MODE=paper
LIVE_TRADING=false
LLM_DISABLE_LIVE_EXECUTION=true
```

If different, STOP.

### Gate 5 — Backup verification using live-supported command

First, verify supported flags:

```bash
.venv/bin/python scripts/full_system_backup.py --help
```

Then verify a phase-tagged backup exists and is less than 4 hours old. Search multiple known locations; do not assume only `data/backups`.

```bash
PHASE=${PHASE:-0}
find data backups docs/backups ~/db_backups -type f 2>/dev/null \
  | grep -E "llm_v4_1_phase_${PHASE}|trade_ai|backup" \
  | xargs -r ls -lt \
  | head -20
```

If no recent backup exists, STOP and tell the operator the exact supported backup command based on `--help`. Do not invent unsupported flags.

### Gate 6 — Ollama alive

```bash
curl -sf http://localhost:11434/api/tags > /tmp/ollama_tags.json && echo "Ollama: alive" || { echo "Ollama: DOWN"; exit 1; }
```

### Gate 7 — Database connectivity

```bash
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) \
  psql -h localhost -U trade_ai -d trade_ai -c "SELECT 1;" > /dev/null && \
  echo "DB: connected" || { echo "DB: FAILED"; exit 1; }
```

### Gate 8 — Provider map reconciliation

Before changing `.env`, create or run provider verification that prints:

- current STANDARD/REALTIME model
- current local Ollama model(s)
- cloud provider names and model IDs from `.env`
- current fallback order from existing config
- whether critical cloud calls fail loud

If provider names in the original plan do not exist in `.env`, use the live names and document the deviation.

### Gate 9 — Existing config hub decision

Inspect:

```bash
sed -n '1,260p' scripts/local_llm_config.py 2>/dev/null || true
sed -n '1,260p' scripts/local_llm.py 2>/dev/null || true
```

Decision rule:

| Finding | Required action |
|---|---|
| `local_llm_config.py` is current model hub | extend it or create wrapper only |
| `local_llm.py` is current execution path | keep it as execution path |
| multiple routers exist | document which one owns production calls before edits |
| direct Ollama callers exist | list them; do not mass-refactor in Phase 0 |

### Gate 10 — Operator authorization

Operator must explicitly say **"Begin Phase N"** for each phase.

## HARD RULES — ABSOLUTE

| # | Rule |
|---|---|
| HR-1 | No new hardcoded model names. All new references through `.env` and existing config hub/wrapper. |
| HR-2 | No new script bypasses `local_llm.execute()`. No new direct `requests.post(OLLAMA_URL)` calls. |
| HR-3 | You do not run `ollama pull` for any model. Operator only. |
| HR-4 | You do not run `rag_indexer.py --full-reindex`. Operator only. |
| HR-5 | You do not run any backup script. Operator only. |
| HR-6 | You do not modify cron entries except the 3 approved Phase 0.7 GPU lifecycle entries. |
| HR-7 | You do not touch holdings, broker code, Telegram sending code, or paper-trade execution. Alert-dispatch integration is limited to registering GPU/OOM event types through the existing central dispatcher if available. |
| HR-8 | You do not change `LLM_DISABLE_LIVE_EXECUTION`. Stays `true`. |
| HR-9 | You do not delete `qwen3:1.7b` at any point in v4.1. |
| HR-10 | You do not delete `nomic-embed-text` until 48h after Phase 2 completes AND operator says to delete it. |
| HR-11 | You do not deploy any file change without verifying backup <4 hours old using live-supported backup command/locations. |
| HR-12 | Every BATCH_OVERNIGHT script you create or modify must call `gate_batch_overnight()` or run inside an approved batch-window lifecycle wrapper. |
| HR-13 | Every model load you write must go through `gpu_lifecycle.warmup()` or the approved lifecycle wrapper. |
| HR-14 | `gemma4:26b-a4b` is NOT deployed in v4.1. If requested, refuse and reference Appendix D. |
| HR-15 | Daytime tests use the `daytime_test()` context manager only. Manual model loads during active hours are forbidden. |
| HR-16 | You do not advance phases without operator approval. |
| HR-17 | You do not invent or improvise steps. If live discovery conflicts with this prompt, stop and log the deviation. |
| HR-18 | Every change writes a deviation log entry to `docs/v4_1_deployment_log.md`. |
| HR-19 | You verify rollback commands use detected service names, not assumed service names. |
| HR-20 | `scripts/llm_config.py`, if created, must be a wrapper/extension of current config, not a competing source of truth. |
| HR-21 | No production embedding default switch until A/B retrieval baseline passes. |
| HR-22 | Phase 1 begins with a pilot script set only. Do not mass-refactor all overnight scripts. |
| HR-23 | Do not persist `LLM_OVERRIDE_ACTIVE_HOURS=true` in `.env`. One-shot shell env only. |

## AUTHORIZED STEPS

### Phase 0 — Foundation + GPU Lifecycle

**Pre-step (operator):** Run verified backup with tag `llm_v4_1_phase_0`. You verify via Gate 5.

| Step | Action | Tool |
|---|---|---|
| 0.0a | Save backup help, LLM scan, service unit scan, and current config inspection under `docs/v4_1_discovery/` | bash |
| 0.0b | Decide config strategy: extend `local_llm_config.py` or create wrapper `llm_config.py`; document decision | read/str_replace |
| 0.1 | Create `llm_routing_audit` table via SQL migration only if missing | bash (psql) |
| 0.2 | Add process type constants through existing config hub or wrapper | create_file/str_replace |
| 0.3 | Modify `scripts/local_llm.py` only if it is current execution path; add async batched audit writes with JSONL fallback | str_replace |
| 0.4 | Create `scripts/gpu_lifecycle.py` with `warmup`, `cooldown`, `status`, `can_load`, `is_active_hours`, `gate_batch_overnight`, `check_oom`, and `daytime_test` | create_file |
| 0.5 | Create `scripts/verify_llm_providers.py`; must print live provider/model map and fallback order | create_file |
| 0.6 | Update `.env` additively only; Phase 0 must not change production model assignments | str_replace |
| 0.7 | Add 3 GPU lifecycle cron entries only after crontab backup is verified | bash (crontab edit) |
| 0.8 | Add read-only `GET /api/v2/gpu-status` endpoint | str_replace |
| 0.8a | Integrate GPU OOM / qwen warmup failure / active-hours override audit with central alert dispatcher if present; otherwise log TODO and do not create direct Telegram sender | str_replace |
| 0.9 | Document restoration drill procedure using actual backup format and detected restore path | create_file |
| 0.10 | Operator runs restoration drill; you verify operator-recorded result only | Operator |
| 0.11 | Run provider verifier; must exit 0 | bash |
| 0.12 | Report Phase 0 complete. STOP. Wait for 24h observation. | — |

**Phase 0 critical implementation notes:**

- Do not create a competing LLM config hub.
- Do not flip `LLM_BATCH_OVERNIGHT`, `LLM_MEDIA_CONTENT`, or `LLM_EMBEDDING` during Phase 0.
- `gpu_lifecycle.status()` should prefer Ollama `/api/ps` and gracefully degrade if unavailable.
- OOM check should not spam Telegram; it should go through existing dispatcher/dedup if available.
- All new logs should live under `logs/` and all discovery docs under `docs/v4_1_discovery/`.

### Phase 1 — Overnight Reasoning (gemma3:27b) — OPTIONAL/HIGH RISK

**Do not start Phase 1 unless:** Phase 0 observed clean for 24h AND operator says `Begin Phase 1`.

**Pre-step (operator):**
1. Run backup with tag `llm_v4_1_phase_1`
2. `ollama pull gemma3:27b`
3. Create `gemma3-overnight` Modelfile with `keep_alive=0` and `num_ctx=8192`
4. Verify backup with Gate 5

| Step | Action | Tool |
|---|---|---|
| 1.3 | Prepare `.env` change but do not apply until pilot scripts/tests are ready | str_replace |
| 1.4 | Pilot only: refactor `multi_strategy_classifier.py` and `strategy_weekly_review.py` first | str_replace per file |
| 1.5 | Create `scripts/gemma3_8k_oom_test.py`; 8K required, 16K optional, 32K separate benchmark only | create_file |
| 1.6 | Create `docs/v4_1_phase_1_test_protocol.md` with 3-tier daytime protocol | create_file |
| 1.7 | Operator runs 8K OOM test | Operator validation |
| 1.8 | Operator runs VRAM swap test | Operator validation |
| 1.9 | Operator runs one full overnight pilot at natural overnight window | Operator validation |
| 1.10 | Document results in deployment log | str_replace |
| 1.11 | Report Phase 1 ready. STOP. Wait for 7-day observation. | — |

**Pilot refactor pattern:**

```python
from scripts.gpu_lifecycle import gate_batch_overnight, warmup, cooldown
from scripts.local_llm import execute
from scripts.llm_config import BATCH_OVERNIGHT

def main():
    gate_batch_overnight()
    warmup("gemma3-overnight")
    try:
        result = execute(
            process_type=BATCH_OVERNIGHT,
            prompt=prompt,
            script="multi_strategy_classifier.py",
            cron_job_name="overnight_strategy_classify",
        )
    finally:
        cooldown("gemma3-overnight")
        warmup("qwen3:14b")
```

**FINAL IMPLEMENTATION NOTE:** If multiple jobs run as one batch group, prefer one lifecycle wrapper around the group rather than loading/unloading for every script.

### Phase 2 — Embedding Upgrade — QUALITY-GATED

**Do not start Phase 2 unless:** operator says `Begin Phase 2`.

| Step | Action | Tool |
|---|---|---|
| 2.0 | Operator backup includes DB/RAG state | Operator |
| 2.1 | Operator pulls `qwen3-embedding:8b` | Operator |
| 2.2 | Create `scripts/embedding_ab_baseline.py` with 20 known-good queries and expected useful top results | create_file |
| 2.3 | Operator runs baseline against current `nomic-embed-text`; save output | Operator |
| 2.4 | Design parallel embedding namespace/table/index if schema supports it; otherwise STOP before destructive reindex | analysis/doc |
| 2.5 | Operator runs new embedding A/B comparison | Operator |
| 2.6 | Only after A/B pass: update `.env`: `LLM_EMBEDDING=qwen3-embedding:8b` | str_replace |
| 2.7 | Report Phase 2 ready. STOP. Wait for 48h observation. | — |
| 2.8 | Delete `nomic-embed-text` only after explicit operator instruction | Operator |

### Phase 3 — Media/Content

**Phase 3 can be considered before Phase 1 after Phase 0 if operator wants the lower-risk model coexistence improvement first.**

| Step | Action | Tool |
|---|---|---|
| 3.0 | Operator backup | Operator |
| 3.1 | Operator pulls `gemma4:e4b` | Operator |
| 3.2 | Update `.env`: `LLM_MEDIA_CONTENT=gemma4:e4b` | str_replace |
| 3.3 | Pilot one or two MEDIA_CONTENT scripts only | str_replace |
| 3.4 | Operator verifies coexistence through `/api/v2/gpu-status` | Operator |
| 3.5 | Report Phase 3 ready. STOP. Wait for 24h observation. | — |

### Phase 4 — Cloud Fallback (LiteLLM)

**Do not start Phase 4 unless:** provider map is reconciled and operator chooses SDK or proxy.

- Pin LiteLLM version.
- Test each configured provider individually.
- Confirm budget enforcement and fail-loud CRITICAL_CLOUD behavior.
- Do not alter fallback order unless operator approves the live provider map.

## FORBIDDEN STEPS

| Step | Why Forbidden |
|---|---|
| `ollama pull <any model>` | HR-3 |
| `ollama pull gemma4:26b-a4b` | HR-14 — deferred to 2026-08-11 |
| `ollama rm <any model>` | Operator only |
| `python3 scripts/rag_indexer.py --full-reindex` | HR-4 |
| `python3 scripts/full_system_backup.py` | HR-5 |
| Manual `ollama run` during active hours | HR-15 — use `daytime_test()` |
| Creating a second independent LLM config hub | HR-20 |
| Assuming `portfolio-server.service` or any other service name | HR-19 |
| Switching embedding default without A/B baseline | HR-21 |
| Mass-refactoring all overnight scripts in Phase 1 | HR-22 |
| Persisting `LLM_OVERRIDE_ACTIVE_HOURS=true` in `.env` | HR-23 |
| Burn-in B or `queue_shadow` mode | Deferred to Phase 5 |
| Remove `fcntl` toll gate | Deferred to Phase 5 |
| Delete `qwen3:1.7b` | HR-9 |
| Delete `nomic-embed-text` (before 48h post-Phase 2 + operator OK) | HR-10 |
| Modify crons outside Phase 0.7 scope | HR-6 |
| Touch holdings/broker/Telegram/paper-trade code | HR-7 |
| Change `LLM_DISABLE_LIVE_EXECUTION` | HR-8 |
| Persist `LLM_OVERRIDE_ACTIVE_HOURS=true` in `.env` | HR-12 |
| Skip a phase | HR-16 |
| Deploy without recent backup | HR-11 |

---

## PER-STEP DELIVERABLES

Every step produces:

1. **File changes** — committed to branch `feature/llm_fleet_v4_1_annotated_phase_N`
2. **Deviation log entry** in `docs/v4_1_deployment_log.md`:
   ```markdown
   ## Phase N Step X — <description> — 2026-MM-DD HH:MM

   **Backup verified:** <filename, age, location, command used>
   **Live discovery artifacts:** <backup help, service units, LLM scan, provider map>
   **Files changed:** <list>
   **Validation performed:** <what you checked>
   **Rollback layer:** <1-4 per strategy doc section 16>
   **Rollback command:** <exact command, dry-run verified>
   **Operator action required:** <yes/no, and what>
   **Status:** READY_FOR_OPERATOR | BLOCKED | DONE
   ```
3. **Audit query** (where applicable):
   ```sql
   SELECT script, process_type, resolved_model, status, COUNT(*)
   FROM llm_routing_audit
   WHERE timestamp > NOW() - INTERVAL '1 hour'
   GROUP BY 1, 2, 3, 4;
   ```

---

## PHASE COMPLETION REPORT FORMAT

```
=== PHASE N COMPLETE ===

Backup verified: data/backups/llm_v4_1_phase_N_<timestamp>.tar.gz (age: Xh)
Steps executed: <list>
Files changed: <count> (<list>)
DB changes: <list or none>
Cron changes: <list or none>

GPU status (current):
<paste curl /api/v2/gpu-status output>

Provider map:
<paste verify_llm_providers.py output>

Detected service units:
<paste relevant units; do not assume names>

Model-reference scan summary:
<count direct Ollama callers, hardcoded model names, migration list>

Audit table activity (last hour):
<paste SELECT query result>

Verification commands the operator should run:
1. <command>
2. <command>
3. <command>

Rollback procedure if regression detected (Layered, see strategy doc section 16):
Layer 1 (env edit, <30s): <exact command>
Layer 2 (kill switch, 1-2 min): <exact command>
Layer 3 (git revert, 5-10 min): <exact command>
Layer 4 (backup restore, 10-30 min): <exact command>

Status: READY_FOR_OPERATOR_VALIDATION
Observation window: <24h | 48h | 7d>

NEXT: Operator must say "Begin Phase N+1" to proceed.
```

---

## FAILURE MODES

### Gate failure
```
GATE FAILURE: Gate N — <name>
Details: <what failed>
Recommendation: <what operator should do>
```

### Step partial completion
```
STEP FAILURE: Phase N Step X
Partial completion: <what got done>
Rollback layer used: <1-4>
Rollback executed: <command>
Rollback verified: <yes/no>
Recommendation: <next action>
```

### Hard rule conflict
```
HARD RULE CONFLICT: HR-X
Instruction: <what was asked>
Reason for refusal: <which rule and why>
Recommendation: <alternative if any>
```

### gemma4:26b request
```
HARD RULE CONFLICT: HR-14
Instruction: <operator or pipeline mentioned gemma4:26b-a4b>
Reason for refusal: gemma4:26b-a4b is deferred to 2026-08-11 per Appendix D.
                    v4.1 Final uses gemma3:27b for BATCH_OVERNIGHT.
Recommendation: If operator wants to revisit early, formally invoke the
                Appendix D evaluation procedure rather than skip it.
```

### Phase 1 8K-context OOM test FAILS
```
PHASE 1 BLOCKED: gemma3:27b cannot handle 8K context on this GPU.
OOM event recorded at: <timestamp>
Peak VRAM observed: <X.X GB>
Recommendation: Reduce num_ctx in Modelfile OR abort Phase 1 and keep
                qwen3:14b for BATCH_OVERNIGHT. Operator decision required.
```

### Existing bug noted
```
EXISTING BUG NOTED (not fixed): <description>
Location: <file:line>
Severity: <low/medium/high>
Recommendation: <create issue / separate session>
```

---

## EXAMPLE OPENING RESPONSE

```text
Gate 1: I have read LLM_FLEET_STRATEGY_v4_1_FINAL.md. I understand Phase 0
is conditionally approved after gates pass, while Phase 1 remains optional and
requires separate approval. I will reconcile existing local_llm_config.py and
local_llm.py before creating any new config layer. I will verify backup flags,
provider names, service units, and model references from the live system before
changes. I will not run model pulls, full RAG re-index, backups, or phase
advancement. I will refuse to deploy any file change without a verified recent
backup.

Running gates 0-9...

[gate-by-gate output]

Gates status: <pass/fail summary>

Ready to begin Phase 0 only on operator command "Begin Phase 0" and verified
backup within last 4 hours.
```


---

## DEPLOYMENT SUMMARY

```
v4.1 FINAL PHASES
-----------------
Phase 0: Foundation + GPU lifecycle    [24h observation]
Phase 1: Overnight reasoning (gemma3)  [OPTIONAL/HIGH RISK, 7d observation, 8K-context test required]
Phase 2: Embedding upgrade             [QUALITY-GATED, A/B retrieval required, 48h observation]
Phase 3: Media/content                 [LOWER RISK, 24h observation]
Phase 4: Cloud fallback (LiteLLM)      [Manual sign-off]
Phase 5: Hardening                     [DEFERRED]
Phase 6: gemma4:26b re-evaluation      [SCHEDULED 2026-08-11]

Total: ~10 days (vs ~31 days in v4.0)

HARD RULES: HR-1 through HR-19
GATES: 1-8 (all must pass)
BACKUP: Mandatory <4h old before any phase
ROLLBACK: 4 layers (env / kill switch / git revert / backup restore)
DAYTIME TESTING: 3-tier protocol with daytime_test() auto-restore
```

---

**Document version:** 4.1 Final — Final Execution Revision
**Last updated:** 2026-05-11
**For execution by:** Claude Code on ms01-openclaw
**Authorization:** John (operator) only
**Calendar reminder set:** 2026-08-11 (gemma4:26b-a4b re-evaluation)

---

# Appendix E — Initial Script Routing Matrix

This matrix answers the operational question: “Which local-LLM scripts should use which model going forward?” It is an initial routing map, not permission to mass-refactor. Claude Code must validate it with the Phase 0 hardcoded-reference scan and live source inspection before changing any specific file.

## Core rule

Scripts should not name models directly. Scripts should declare a process type, and the existing config hub/wrapper should resolve the model from `.env`.

```python
from scripts.local_llm import execute
from scripts.llm_config import STANDARD  # or REALTIME / BATCH_OVERNIGHT / etc.

result = execute(prompt, process_type=STANDARD, script="script_name.py")
```

## Initial routing map

| Script / workflow | Process type | Model policy after rollout | Phase | Notes |
|---|---:|---|---:|---|
| `scripts/process_watchlist_agent_jobs.py` | STANDARD | `qwen3:14b` | Phase 0 | Main backend agent processor. Keep fast/local and compatible with active-hours operation. Do not move this wholesale to gemma3. |
| Maria / Steph / Risk backend analysis through shared job processor | STANDARD | `qwen3:14b` | Phase 0 | Existing two-pass and peer/RAG context path should stay on resident active-hours model unless later benchmark proves otherwise. |
| `scripts/incubator_llm_screener.py` | STANDARD | `qwen3:14b` | Phase 0 | Runs around premarket/evening; keep stable. Do not make it depend on gemma3 until pilot data exists. |
| `scripts/topic_curator.py` | STANDARD | `qwen3:14b` | Phase 0 | Daily curation and query improvement. Morning path should not trigger large-model GPU swaps. |
| `scripts/llm_intelligence_enrichment.py` | STANDARD | `qwen3:14b` | Phase 0 | Daily intelligence narratives. Keep stable during initial rollout. |
| `scripts/aegis_morning_brief_delivery.py` | STANDARD / REALTIME | `qwen3:14b` | Phase 0 | Morning operator-facing brief. Must remain reliable and quick. |
| `scripts/local_llm.py` | Execution path | no direct model; resolve from config | Phase 0 | Add audit/gating here only if this is confirmed as current execution path. |
| `scripts/local_llm_config.py` | Config hub | source of truth / extended hub | Phase 0 | Do not replace silently. New `llm_config.py`, if created, must wrap or extend this. |
| `scripts/multi_strategy_classifier.py` | BATCH_OVERNIGHT | `gemma3-overnight` after Phase 1 approval | Phase 1 pilot | First pilot candidate only. Must call `gate_batch_overnight()` or run under batch-window wrapper. |
| `scripts/strategy_weekly_review.py` | BATCH_OVERNIGHT | `gemma3-overnight` after Phase 1 approval | Phase 1 pilot | Second pilot candidate. Must restore/warm qwen before premarket. |
| `scripts/weekly_incubator_builder.py --llm` | BATCH_OVERNIGHT candidate | Candidate for `gemma3-overnight` after pilot passes | Later Phase 1 expansion | Do not change during initial pilot unless explicitly approved. |
| Overnight synthesis / long-form batch classifiers | BATCH_OVERNIGHT candidate | Candidate for `gemma3-overnight` | Later Phase 1 expansion | Group jobs behind one lifecycle wrapper where possible to avoid GPU thrash. |
| `scripts/rag_indexer.py` and embedding calls | EMBEDDING | `qwen3-embedding:8b` only after Phase 2 A/B pass | Phase 2 | `nomic-embed-text` remains default until retrieval-quality A/B passes and 48h observation is clean. |
| RAG retrieval query embedding helpers | EMBEDDING | `qwen3-embedding:8b` after Phase 2 | Phase 2 | Must never call cloud. |
| Report/document prose generation such as weekly/monthly summaries | MEDIA_CONTENT candidate | `gemma4:e4b` only after Phase 3 approval | Phase 3 pilot | Pilot one or two scripts first. Do not move all prose scripts at once. |
| YouTube/transcript summarization or article summarization workflows | MEDIA_CONTENT candidate | `gemma4:e4b` after Phase 3 pilot | Phase 3 | Keep qwen until coexistence and throughput tests pass. |
| Alex retirement, Roth, SSDI, IRMAA, complex tax decisions | CRITICAL_CLOUD | Cloud-only, fail loud | Existing/Phase 0 verified | No local fallback for critical retirement/tax decisions. Use live provider map from `.env`. |
| CIO synthesis or high-impact portfolio decisions | CRITICAL_CLOUD or cloud escalation | Cloud-required if policy says so | Existing/Phase 0 verified | Provider names must be discovered from live config. |
| Any direct `requests.post(...11434...)` Ollama caller found by grep | Migration list | no new direct calls; migrate gradually | Phase 0 inventory | Record in migration list. Do not mass-refactor in Phase 0. |

## What this does and does not do

This document does address the current local-LLM routing question, but it deliberately does it through a process-type migration pattern rather than hardcoding every script to a model. Phase 0 creates the live inventory and routing/audit layer. Phase 1 changes only pilot batch scripts. Phase 2 changes embeddings only after A/B retrieval validation. Phase 3 changes only pilot media/content scripts.

