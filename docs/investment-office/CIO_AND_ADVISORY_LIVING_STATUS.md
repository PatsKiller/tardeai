# CIO + Advisory — Living Operator Status

| Field | Value |
|---|---|
| **Document name** | `CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Repo path** | `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Worktree copy** | `/home/johnclaw/tradeai-wt-advisory-desk/docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Drive-sync source copy** | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Google Drive file** | [CIO_AND_ADVISORY_LIVING_STATUS.md](https://drive.google.com/file/d/1scL90dCZa7uOK9_sojX-MNBWHfrViWMi/view) |
| **Google Drive folder** | [Trade_AI_Docs_v2 / docs / investment-office](https://drive.google.com/drive/folders/1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8) |
| **Drive parent (docs root)** | [Trade_AI_Docs_v2](https://drive.google.com/drive/folders/1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR) |
| **Revision** | **R1 — 2026-08-18T15:15Z** |
| **Status** | **WORKING / STILL IN PROGRESS** — update + re-sync after each material desk change |
| **Authority** | `READ_ONLY_ADVISORY` — no broker, order, stop, 2FA, or risk-policy mutation |
| **Owner** | Alex desk (`owner_agent: alex`) · operator: John |
| **Live release** | `3290ab0d-main-exact-phase2-20260818-110747` |
| **Live SHA** | `3290ab0dedb0648e71861da6900b882ed50c7e04` (`origin/main`) |
| **UI chip** | `3.14+msysryqp` · `3290ab0d` |
| **Source PRs (this cut)** | [#364](https://github.com/PatsKiller/tardeai/pull/364) + [#365](https://github.com/PatsKiller/tardeai/pull/365) |

> This file is the **operator confirmation sheet** for CIO and Advisory.  
> It is **not** marketing. It records what the live desk actually does today, what is broken or degraded, and the exact config that produces that behavior.  
> We will **rewrite and re-sync** this same filename as work continues so the Drive copy is always the current R* revision.

**How to confirm:** hard-reload `/v3/` and `/v3/cio` and `/v3/advisory`, then tick the checklist at the bottom. If a row disagrees with what you see, that is a bug in this doc or a regression — tell me and we re-probe + re-sync.

---

## 1. One-screen truth

| Surface | Live state (2026-08-18 15:11Z probe) | Grade |
|---|---|---|
| Command Center SPA `/v3/` | 200, chip `3.14+msysryqp`, SHA `3290ab0d` | **WORKING** |
| `/v3/cio` + `GET /api/v3/cio` | 200, `desk@v5`, 12 snapshot plans / 30 plan rows, 15 OPEN actions | **WORKING** (stale actions + missing reconciliation) |
| `/v3/advisory` + `GET /api/v3/advisory` | 200, 58 rows, facts CURRENT, **opinions EXPIRED**, health **DEGRADED** | **WORKING facts / STALE LLM opinions** |
| Agent maturity `/api/v3/agent-maturity` | 200 in **3.02s**, `degraded=true`, 21 agents from **repo evidence** (live Postgres still exceeds 3s) | **BOUNDED / DEGRADED** |
| Trading scanner | 949 tickers; current run **0 GO / 2 WAIT / 881 NOGO**, `RUN_UNDERFILLED` (overnight label `1000` @ 03:54Z) | **WORKING, underfilled run** |
| Journal TRADING / REALIZED | last close **2026-08-07**, 159 trades, 50.9% WR, +$37,613 — STALE 11d is **honest** (no sells in last 20d ingest dry-run) | **HONEST STALE** |
| Memory → verdicts | `MEMORY_BEHAVIOR_INFLUENCE=0` (enforced twice). Desk reports `memory_behavior_influence=0` | **WORKING (influence off)** |
| Broker write | `NONE` | **WORKING** |
| Telegram CIO bot | unit **active**; net `CIO_TELEGRAM_INTERDICT=0` + `ENABLE_TELEGRAM=1`. Situation auto-notify still **yaml false** | **BOT UP / AUTO-NOTIFY OFF** |
| Governed model bridge `:8766` | **active/running** | **WORKING** |
| Watchdog / CIO timers | timers armed; oneshot services idle between fires | **ARMED** |
| inotify | `max_user_instances=128` (root-owned). ENOSPC is host, not disk | **HOST LIMIT** |
| Committed `RELEASE_MANIFEST` | still pins `aa037b73` (2026-08-15) — **lags live `3290ab0d`** | **STALE PIN** |

---

## 2. Authority (does not change unless you say so)

**Contract:** `READ_ONLY_ADVISORY`.

Allowed: detect, plan, enrich, notify, disposition, thesis publish, desk note, Hermes *research* enqueue, UI read.

Forbidden: orders, stop create/move/cancel from chat or situations, risk-limit mutation, 2FA / broker login, unattended auto-trade, authority escalate.

Telegram “ack” = acknowledge and monitor. It is **not** an execution approval.

---

## 3. CIO — features and live behavior

**Thesis pin:** `desk@v5` (published 2026-08-12T14:30Z). Stance `defensive_observe`. Owner `alex`. Intelligence layer `desk_os_v2`.

**Summary (live):** Mature desk OS under a living governing thesis. Every plan and Telegram advisory must reason about fit or tension with this document. Prefer Data Broker multi-domain evidence. Cash is a feature — stage deployment; never force fills. Highest-signal action may be non-action.

**Risk posture (live structured):**

| Knob | Value | Where |
|---|---|---|
| `max_single_name_weight_pct` | 12.0 | thesis + `config/cio_situations.yaml` |
| `concentration_fire_pct` | 16.5 | thesis |
| `cash_band_min_pct` | 20.0 | thesis + yaml `cash_pct_band_min` |
| `deep_dd_threshold_pct` | 25.0 | thesis + yaml `basis_drawdown_pct` |

### 3.1 Working

| Feature | Evidence |
|---|---|
| CIO hub API | `GET /api/v3/cio` 200 in 61ms, `authority=READ_ONLY_ADVISORY` |
| Thesis read | `GET /api/v3/cio/thesis` → `desk@v5`, 8 principles, learning_log n=2 |
| Plans read | `GET /api/v3/cio/plans` count **30**; snapshot embeds 12 |
| Multi-domain snapshot | 15 domains declared; **14 available**; missing **`reconciliation`** |
| Available domains | portfolio, risk, hermes_research, investment_policy, model_portfolio, cost_basis, transactions, sectors, holdings_detail |
| Actions ledger | 15 OPEN (12 LOW system backfills from 2026-08-09; 3 P2) |
| Model path | `model_provider=deepseek-v4-pro`, `fallback=none — fail-closed` |
| Situation catalog S0–S8 | code + `config/cio_situations.yaml` enabled, **shadow=true**, **notify=false** |
| Reactive / delivery / material-scan / defer-revisit / nightly reflection | **systemd timers armed** (oneshot services idle between ticks) |
| Dedicated CIO Telegram unit | `tradeai-cio-telegram.service` **active/running** |
| Governed DeepSeek bridge | `cio-governed-bridge.service` **active** on `127.0.0.1:8766` |
| Programs 1–4 + 3.5 (maturity, durable memory, watchdog, CIO books) | merged to main earlier this cycle; live under exact-main |

### 3.2 Not working / degraded / do not claim

| Item | Reality |
|---|---|
| `GET /api/v3/cio/office` | **404** `unknown_cio_path: office` |
| `GET /api/v3/cio/status` | **404** |
| `GET /api/v3/cio/digest` | **404** (digest is not this path) |
| Snapshot `health.ok` | **false** — `reconciliation` missing |
| Plan statuses | 11 `draft` + 1 `proposed` on the snapshot set — not a closed-loop book |
| Action quality | most OPEN actions are **system backfill** (“Snapshot … domains OK”), not operator work |
| Hermes challenge queue | **205 ENQUEUED** (delegation) — backlog, not a healthy drain |
| Handoffs | 1 BLOCKED + 1 ENQUEUED |
| Situation Telegram auto-notify | **off** (`situation_notify_telegram: false`, yaml `notify: false`) |
| LLM policy | `config/cio_llm_policy.yaml` **`shadow: true`** — material wakes *may* spend budget; not “always-on CIO brain” |
| WhatsApp | runbook only; **not** production-parity |
| MS/Schwab-class IPS / tax / estate / household report | **not a product** (see `docs/cio/ROADMAP_GAPS.md`) |
| Unattended trading | **never** |
| Committed release manifest | `docs/investment-office/RELEASE_MANIFEST.md` still pins **`aa037b73`** (Aug 15). Live CURRENT is **`3290ab0d`**. Do not treat the committed manifest as today’s deploy pin. |

### 3.3 CIO config map

| Knob | File / unit | Live value |
|---|---|---|
| Situations enabled | `config/cio_situations.yaml` | `enabled: true` |
| Situations shadow | same | `shadow: true` |
| Situations notify | same | `notify: false` |
| Dedup / caps | same | `dedup_hours: 12`, `max_plans_per_pass: 5`, `max_notify_per_pass: 3` |
| S1 / S5 / S6 thresholds | same | DD 25%, cash min 20%, concentration 12% |
| Owners | same | S1/S2/S3/S7/S8 alex · S4/S5 steph · S6 morgan |
| LLM policy enabled | `config/cio_llm_policy.yaml` | `enabled: true`, `shadow: true` |
| LLM notify master | same | `situation_notify_telegram: false` |
| Notify types if armed | same | S1, S2, S5, S6, S8 |
| Notify guards | same | once-per-fingerprint, 12h cooldown, 5m min gap |
| Telegram net flags | drop-in `25-cio-only-live.conf` (wins over `20-*.conf`) | `ENABLE_TELEGRAM=1`, `CIO_TELEGRAM_INTERDICT=0`, `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1` |
| Telegram interdict leftover | drop-in `20-exact-sha-release.conf` | still writes `CIO_TELEGRAM_INTERDICT=1` then **overridden** by 25 |
| Daily LLM cap (server) | `20-exact-sha-release.conf` | `LLM_GLOBAL_DAILY_USD_CAP=0.50` |
| Working directory | same | exact-main `3290ab0d-…-110747` |
| Thesis store | `data/cio/cio_theses.jsonl` | 6 events; last publish `desk@v5` |
| Plans / goals / wakes | `data/cio/cio_plans.jsonl`, `cio_goals.jsonl`, `cio_wake_traces.jsonl` | live, recently written |
| Mode script | `scripts/cio_telegram_mode.sh status` | reports live (INTERDICT=0) |

---

## 4. Advisory Desk — features and live behavior

**Operator contract:** `advisory.operator.v1`. Deterministic opinion table over holdings + watchlist + closed journal + allocation. Flash (per-row) + Pro (synthesis) via the governed bridge. **Not** a trader.

**Live desk health:** **DEGRADED**  
Reason: *prior synthesis / Flash opinions are old; facts may still be current.*

| Dimension | State |
|---|---|
| STRUCTURAL_VALIDATION | PASS |
| PLAUSIBILITY | PASS |
| FACT_FRESHNESS | CURRENT |
| SOURCE_COMPLETENESS | HEALTHY |
| **OPINION_FRESHNESS** | **EXPIRED** |
| REENTRY_FRESHNESS | CURRENT |
| WATCH_INTELLIGENCE_FRESHNESS | CURRENT |
| MEMORY_PROVIDER_HEALTH | HEALTHY |

**Rows:** 58 = 29 holding + 12 watchlist + 8 closed_journal + 9 allocation.

**Verdicts (live):** HOLD 19 · WAIT 14 · INSUFFICIENT_DATA 9 · TRIM 8 · RE_ENTER 6 · ADD 2.

### 4.1 Working (just recertified)

| Feature | Evidence |
|---|---|
| Desk API | `GET /api/v3/advisory` 200, cache hit, facts CURRENT |
| Account-scoped lots | SCHD **taxable 406.54** / **IRA 6155.25** (no more 6561 combined) |
| Field-state shares | class-aware `{value,state,source,as_of,freshness,quality,reason}` |
| Lot evidence | `lot_basis` present on evidence bundle (account key `SYMBOL:account`) |
| Watch Intelligence | `watch.intelligence.broker.v1` live join; PLTR/FATN/AMC recerted earlier this session |
| Re-Entry desk | V4 is the live `/reentry` route; N+1 watchlist fetches batched `?symbols=` (80 / 2 workers) |
| Symbol-cards filter | `?symbols=SCHD,PLTR` → 2 cards, ~3 KB |
| Flag | `config/advisory_desk.yaml` `ADVISORY_DESK_V1: true` |
| Cache window | `DEFAULT_MAX_AGE_S=300` (honored; day-old `ok=true` no longer served) |
| Memory / senses attach | durable memory + financial senses **visible**; **do not change verdicts** |
| Shadow / outcome / lessons / notif-broker timers | armed (nightly / hourly) |

### 4.2 Not working / degraded / in progress

| Item | Reality |
|---|---|
| Flash / Pro opinions | **EXPIRED** — facts paint, narratives are old. Desk is honest (DEGRADED), not silent. |
| Holdings `as_of` | field-state shares freshness **EXPIRED** (`as_of` 2026-08-14) even though desk FACT_FRESHNESS is CURRENT |
| SCHD holding period | reported SHORT — lots are 2026 drip/buy lots under the `SYMBOL:account` file key; mixed `lot.account` labels in the file are **ignored** (correct) |
| Agent-maturity live reader | Postgres path still **>3s**; board fail-softs to repo evidence |
| Journal last close | **2026-08-07** — no newer sells; STALE chip is correct |
| Scanner current run | 0 GO / 2 WAIT — underfilled overnight, **not** an empty UI |
| inotify ENOSPC | `max_user_instances=128`; needs root to raise |
| WatchlistHub / ManualTosDesk fat payloads | still pull full `symbol-cards` / `?full=1` on those pages (P2; Re-Entry stampede is fixed) |
| Advisory promotion gate | Phase 7 docs still say **NOT_PROMOTED** pending 30 green shadow sessions — do not call the desk “promoted autonomy” |
| Influence flags vs product | `*_ADVISORY_INFLUENCE=ACTIVE_ADVISORY` attaches evidence. **`MEMORY_BEHAVIOR_INFLUENCE=0` is the load-bearing “does not steer verdicts” switch.** Desk reports `0`. |

### 4.3 Advisory config map

| Knob | File / unit | Live value |
|---|---|---|
| Feature flag | `config/advisory_desk.yaml` | `ADVISORY_DESK_V1: true` |
| Flash | same `routing.lane_preference` | `deepseek-v4-flash` → `:8766`, thinking disabled |
| Pro | same | `deepseek-v4-pro` → `:8766` |
| Local/Ollama fallback | **removed** 2026-08-12 | fail-closed to deterministic opinions |
| Never escalate | same | `deepseek-v4-pro-think`, `pro-max` |
| Cost (informational) | same | `max_model_rows_per_run: 20`, watchlist 12, `daily_usd_cap: 0.30` |
| Authoritative $ caps | bridge + `llm_process_registry` + Postgres | **not** this yaml |
| Cache buckets | same | weight 0.1pp, pnl 0.5pp, mv 0.5%, conf 0.05 |
| Desk cache | `scripts/lib/data_broker/advisory_desk.py` | `DEFAULT_MAX_AGE_S=300` |
| Runtime artifacts | `data/runtime/advisory_desk_latest.json`, `advisory_opinions_latest.json` | latest snapshot + opinions |
| AIF FS shadow | drop-in `26-aif-fs-shadow.conf` | `AIF_FINANCIAL_SENSES_SHADOW=1`, `MEMORY_BEHAVIOR_INFLUENCE=0`, `AGENT_RUN_TRACE=1` |
| Lesson / senses influence | `27-advisory-influence-shadow.conf` | both `ACTIVE_ADVISORY` (attach only) |
| Durable memory | `28-durable-memory-shadow.conf` | `MEMORY_PROVIDER=durable`, `MEMORY_SHADOW=1`, `MEMORY_BEHAVIOR_INFLUENCE=0`, `GOVERNED_MEMORY_ADVISORY_INFLUENCE=ACTIVE_ADVISORY` |
| Agent read API | `agent-operator.env` + `10-agent-read-api.conf` | `AGENT_RUNTIME_READ_API=1` (DSN in env, not in this doc) |
| Agent connect bound | live code | `psycopg2.connect(..., connect_timeout=2)` + 3s handle bound + repo fail-soft |

---

## 5. Shared Command Center / host

| Item | Live |
|---|---|
| CURRENT | `/home/johnclaw/trade-ai-releases/portfolio-server/3290ab0d-main-exact-phase2-20260818-110747` |
| SHA files | `BUILD_SHA` = `SOURCE_COMMIT` = `GIT_SHA` = `3290ab0d…` |
| systemd | `portfolio-server.service` active |
| Deploy | `scripts/cio_phase2_exact_main_deploy.sh` prepare/promote; receipt `~/.local/state/cio-phase2-exact-main/deploy_receipt.json` |
| Last promote | 2026-08-18T15:08:33Z, PR **365**, health ok + `/v3/cio=200` |
| UI | Vite `3.14+msysryqp`, `ui_version` merged (no longer clobbered) |
| Dashboard semaphore | health + `/api/v3/agent-maturity` **exempt** |
| Canonical data | `CURRENT/data/portfolios/state` → rebuild state; `data/cio` → rebuild cio |
| Drive sync | hourly cron `scripts/sync-docs-to-drive.sh` from **rebuild tree** → `Trade_AI_Docs_v2` |
| Drive account | `john@jwwhiting.com` via `gog` |

---

## 6. Feature inventory (CIO + Advisory)

Legend: **ON** live and truthful · **DEG** live but degraded/honest · **OFF** present but not claimed · **NO** forbidden / not a product.

### CIO product

| Feature | State |
|---|---|
| Living thesis `desk@vN` | **ON** (`v5`) |
| Situation detector S0–S8 | **ON** (shadow, notify off) |
| Durable plans + dispositions | **ON** |
| Plan enrichment (LLM or template) | **ON** (shadow policy) |
| Desk note / office snapshot | **ON** (14/15 domains) |
| Capital / cash as optionality | **ON** (thesis) |
| Telegram converse bot | **ON** (unit up; auto-notify off) |
| Signed Tailscale action links | **ON** (code; confirm in UI) |
| Nightly reflection | **ARMED** (timer; no auto-promote) |
| Material scan + delivery workers | **ARMED** |
| WhatsApp | **OFF** |
| Autonomous execution | **NO** |

### Advisory product

| Feature | State |
|---|---|
| Deterministic desk + 8 verdicts | **ON** |
| Operator field-state + desk health | **ON** |
| Account-scoped tax lots | **ON** (fixed this cut) |
| Watch Intelligence broker | **ON** |
| Re-Entry V4 book | **ON** (payload stampede fixed) |
| Flash opinions | **DEG** (expired) |
| Pro synthesis | **DEG** (expired) |
| Financial Senses attach | **ON** (no verdict steer) |
| Durable / governed memory attach | **ON** (influence 0) |
| Ratified lesson attach | **ON** (influence 0) |
| Morning advisory digest | **ARMED** (timer path) |
| Promotion to autonomy | **OFF** (not promoted) |

### Platform (this week)

| Feature | State |
|---|---|
| Exact-main immutable releases | **ON** |
| CC first-paint / Trading scanner | **ON** (underfilled run ≠ empty) |
| Maturity 3s bound + repo fail-soft | **ON / DEG** |
| Journal STALE honesty | **ON** |
| Re-Entry `?symbols=` batch | **ON** |
| Symbol-cards `?symbols=` filter | **ON** |

---

## 7. Still working on (do not mark done)

1. **Live agent-maturity Postgres** — why the reader still exceeds 3s; board is usable via repo fail-soft.
2. **Advisory Flash/Pro refresh** — opinions EXPIRED; facts are current. Need a clean governed-bridge run, not a fake “fresh” stamp.
3. **Holdings mark freshness** — shares `as_of` 2026-08-14 vs desk FACT_FRESHNESS CURRENT.
4. **Committed RELEASE_MANIFEST** — regenerate to `3290ab0d` when you want pin/docs/CI to match live CURRENT.
5. **Telegram drop-in contradiction** — `20-exact-sha-release.conf` still sets INTERDICT=1; `25-cio-only-live.conf` clears it. Net is live, but the pair is easy to misread.
6. **Hermes challenge backlog (205)** + snapshot `reconciliation` missing.
7. **inotify 128** — host sysctl; not a code fix.
8. **P2 payload caps** on WatchlistHub / ManualTosDesk `full=1`.
9. **This document** — living. Next material desk change → bump R2 and re-sync Drive.

---

## 8. Operator confirmation checklist

Tick against a **hard reload** of `/v3/`, `/v3/cio`, `/v3/advisory`.

- [ ] Chip shows `3.14+msysryqp` (or newer R*) · SHA starts `3290ab0d`
- [ ] `/v3/cio` loads; thesis line is `desk@v5` / defensive observe
- [ ] `/v3/advisory` loads; SCHD **taxable lots ≈ 407**, IRA ≈ 6155 (not 6561)
- [ ] Advisory health chip is **DEGRADED** (opinions old) — not a crashed page
- [ ] Trading scanner is a full list (hundreds of names), not empty chrome
- [ ] TRADING/REALIZED STALE mentions last close **2026-08-07**, not “UI dead”
- [ ] Agent maturity page paints in ~3s (may say degraded / repo evidence)
- [ ] No order / stop / 2FA controls appeared
- [ ] Drive file below opens and matches this revision header (**R1**)

---

## 9. How we update and sync

| Step | What happens |
|---|---|
| 1. Edit | Same path: `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| 2. Bump | Revision **R2, R3, …** + UTC timestamp at the top. Do not mint a new filename. |
| 3. Mirror | Copy into the rebuild tree (hourly Drive cron source). |
| 4. Push Drive | `gog drive upload` into folder `1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8` (replace-in-place when an ID exists). |
| 5. Hourly safety net | `scripts/sync-docs-to-drive.sh` (cron :05) re-mirrors `docs/**` → `Trade_AI_Docs_v2`. |
| 6. Confirm | You open the Drive link and tick §8. |

Related packets (deeper, not the status sheet):

- `docs/cio/README.md` — architect packet index  
- `docs/cio/CIO_DESK_OPERATING_PACKET.md` — older pin packet (`desk@v4`, stale vs live `v5`)  
- `docs/cio/AUTHORITY.md` — authority contract  
- `docs/cio/ROADMAP_GAPS.md` — explicit non-goals  
- `docs/advisory/desk-v1/README.md` — Advisory phase index  
- `docs/investment-office/CIO_OPERATOR_PRODUCT.md` — Alex Telegram product notes  

---

## 10. Revision log

| Rev | UTC | What changed |
|---|---|---|
| **R1** | 2026-08-18T15:15Z | First living sheet after #364/#365 exact-main promote. Lots, maturity bound, payload batch, STALE honesty recerted. CIO `desk@v5`. Advisory opinions EXPIRED. |

*End of R1. Next sync overwrites this same Drive filename.*
