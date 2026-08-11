# Runtime truth — host verification (P0 ops)

**Verified at:** 2026-08-11T15:16:05Z (host local ~11:16 ET)  
**Branch:** `feature/advisory-desk-v1`  
**SHA:** `d124b227b480a93d30d84cc8ee60dfec8670020e`  
**Authority:** READ_ONLY_ADVISORY  

Honest pass/fail only. No marketing.

---

## Layout

| Item | Value |
|---|---|
| Live primary tree | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` |
| Timer WorkingDirectory (agent_runtime, cio-reactive, advisory, backup) | **same primary tree** |
| portfolio-server CURRENT | `/home/johnclaw/trade-ai-releases/portfolio-server/20260811-094957` |
| Data truth links on CURRENT | `data/portfolios/state`, `state/data_broker`, `data/runtime`, `data/health`, **`data/cio`** → canonical |

Phase 2a tip commits present:

```
d124b227 docs(cio): Situation Catalog v1 operator guide (Phase 2a)
912ccc35 feat(cio): situation detector skeleton S1–S8 + SpaceX fixture tests
0241722b feat(cio): action plan store + situations config (Phase 2a)
```

---

## Checks

| # | Check | Result |
|---|---|---|
| 1 | `git log -1` Phase 2a at/after d124b227 | **PASS** `d124b227` |
| 2 | Scoped units not failed: agent_runtime@alex/morgan/steph, tradeai-advisory-*, cio-reactive, backup-enforcer, bridge | **PASS** (timers/services active; alex/morgan/steph oneshot **inactive** after success, not failed) |
| 3 | alex/morgan/steph `--once` | **PASS** each COMPLETED 1, exit 0 |
| 4 | Situation detector SHADOW | **PASS** `shadow=true` `notify=false`; SpaceX fixture created S1+S2 plans; live heartbeat pass: 8 candidates, 7 plans, 0 errors |
| 5 | Plan store writable | **PASS** `data/cio/cio_plans.jsonl` + projection; `list_open_plans` ≥ 2 |
| 6 | `backup_enforcer --status` | **PASS** local count **1**, compliant |

### Agent --once (proof)

```
agent=alex  COMPLETED 1  exit=0
agent=morgan COMPLETED 1  exit=0
agent=steph  COMPLETED 1  exit=0
```

Provider env: `AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime_live_providers` (no inline comment).

### Detector (SHADOW)

```
config: enabled=true shadow=true notify=false dedup_hours=6
version: situation-catalog-v1.0.0
empty evidence: candidates=0 errors=[]
SpaceX fixture: candidates=2 plans_created=[S1,S2] errors=[]
heartbeat live: candidates=8 plans_created=7 dedup_skipped=1 errors=[]
```

Notify left **off**. No broker path.

### Reactive cycle

```
cio_reactive_cycle --once → enabled=True errors=0 exit=0
tradeai-cio-reactive.timer: active
```

### Heartbeat

Import path fixed (project root on `sys.path`) so `scripts.lib.*` resolves under timer PYTHONPATH.  
`cio_heartbeat.py --once` → exit 0, situations block non-empty, model_calls=0.

---

## Unrelated host failures (out of P0 scope)

Still failed on host (not advisory/alex-morgan-steph scoped):

- hermes-autonomous-loop, hermes-deep-research-local  
- mcporter-token-refresh  
- tradeai-agent-runtime-health / producer  
- other agent_runtime@* (aegis, atlas, …) not in P0 set  
- portfolio cadence / governance pilots  

These were **not** cleared by this deploy; leave as-is unless separately owned.

---

## Flags (leave as-is)

| Flag | Value |
|---|---|
| `config/cio_situations.yaml` shadow | true |
| notify | false |
| `CIO_SITUATIONS_NOTIFY` | unset / 0 |
| Desk promotion | NOT_PROMOTED (unchanged) |

---

## Commands used

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git checkout feature/advisory-desk-v1 && git pull --ff-only
git log -1 --oneline   # d124b227
systemctl --user daemon-reload
systemctl --user restart tradeai-cio-reactive.timer tradeai-backup-enforcer.timer \
  tradeai-agent-runtime@alex.timer tradeai-agent-runtime@morgan.timer tradeai-agent-runtime@steph.timer
source ~/.config/tradeai/agent-operator.env
PYTHONPATH=scripts .venv/bin/python -m scripts.agent_runtime.agents.run_once --agent alex --once
# … morgan, steph
.venv/bin/python scripts/cio_reactive_cycle.py --once
.venv/bin/python scripts/cio_heartbeat.py --once
.venv/bin/python scripts/backup_enforcer.py --status
```

---

*P0 host point complete. SHADOW only. Not fully autonomous. Not production fleet activation.*

---

## P2b short soak (2026-08-11T15:58–15:59Z)

**SHA:** `8592abc2` (includes `f9a7b971` enrichment)  
**Result:** **PASS** (fail-closed template path under process cap; no crashes)

### Flags at soak

| Flag | Value |
|---|---|
| `CIO_LLM_ENRICH` | unset (default on) |
| `CIO_SITUATION_NOTIFY` | 0 / config notify false |
| situations `shadow` | true |
| `TELEGRAM_CIO_BOT_TOKEN` | **unset** (dedicated CIO bot not provisioned) |
| `TELEGRAM_CHAT_ID` | set (Maria/general only) |
| `LLM_GLOBAL_DAILY_USD_CAP` | 0.25 |
| alex process cap (bridge) | **0.02 USD** — already at spent ~0.004, further calls **COST_CAP_EXCEEDED** |

### Checks

| Step | Result |
|---|---|
| Heartbeat `--once` | exit 0; situations candidates=8, plans_created=0 (dedup 8), errors=[] |
| Reactive `--once` | exit 0; errors=0 |
| Bridge | active; POST → **COST_CAP_EXCEEDED** (process scope) |
| Open plans store | **9** open plans in `data/cio/` |
| Enrich 3 material plans | all `llm=blocked_cap`, `narrative_source=template`, “LLM deferred”, **no crash** |
| Invented numbers vs evidence | **none** on sampled summaries |
| Non-material `system.heartbeat_ok` | `llm=skipped_non_material` |
| `/cio plans` + portfolio | zero-LLM OK (portfolio snapshot live) |
| Telegram free-text live | **SKIP** — no `TELEGRAM_CIO_BOT_TOKEN`; dry-run converse path **handled** |
| Scoped unit crash loop | **none** |
| backup_enforcer | dumps **1**, compliant |

### Wake sample log

```
soak:plan_b299ae8acecf S4_SECTOR_ROTATION llm=blocked_cap narrative=template
soak:plan_77e48566970e S6_CONCENTRATION_OR_DISPOSITION llm=blocked_cap narrative=template
soak:plan_79fe9e72f2d4 S6_CONCENTRATION_OR_DISPOSITION llm=blocked_cap narrative=template
```

Artifact: `data/cio/p2b_soak_wakes.json`

### Observations (not retuned this soak)

- **S6 on CASH / high weights** (e.g. SPCX ~42%, SCHD ~16.5%) may be noisy vs cash/ETF policy — review `concentration_weight_pct` later, not in this soak.
- **LLM invoked path not proven live** this window because alex process cost cap (0.02) blocks further synthesis; fail-closed template path **was** proven (acceptance B).
- To observe `narrative_source=llm` later: raise process cap for `alex_cio_synthesis` or wait for daily reset; keep notify off.

### Pass criteria map

| Criterion | Status |
|---|---|
| No unit crash loop | PASS |
| Enrichment fail-closed on block | PASS |
| No invented numbers (sampled) | PASS |
| Converse dry + slash | PASS (live CIO bot token missing) |
| RUNTIME_TRUTH updated | PASS |

---

## Provision follow-up (same day, post-soak)

| Item | Status |
|---|---|
| Git tip (pre this note) | `4f15f869` / P2b at `8592abc2` |
| `alex_cio_synthesis` daily_cost_cap_usd | **0.15** (was 0.02) — DB + registry |
| `~/.config/tradeai/cio-telegram.env` | allowlist set (2 chats); **TELEGRAM_CIO_BOT_TOKEN missing** |
| Token provision script | `scripts/ops/provision_cio_telegram_token.sh` |
| Unit `tradeai-cio-telegram` | installed; **not enabled** until token |
| P3 thesis store | **not implemented** (next feature track) |

After BotFather token:
```bash
printf '%s' '<token>' | bash scripts/ops/provision_cio_telegram_token.sh
systemctl --user enable --now tradeai-cio-telegram.service
.venv/bin/python scripts/cio_telegram_bot.py --once --json
```
