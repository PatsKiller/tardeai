# M2 Canary Stage-2/3 Handoff — m2-canary-20260907

**As of:** 2026-09-08T23:07Z  
**Campaign:** `/home/johnclaw/trade-ai-campaigns/m2-canary-20260907/`  
**Verdict:** Stage-2 **COMPLETE**. Stage-3 **ORGANIC SOAK IN PROGRESS** (not sealed). Full M2 PASS: **NOT YET**. Full Phase F / Stage-4: **NOT DONE**.

---

## 1. Executive answer

| Question | Answer |
|---|---|
| Implementation-wide complete? | **No** — A–D done; E open; F interim only |
| Claim M2 / Stage-3 PASS now? | **No.** Success bar is Stage-3 organic soak seal. |
| Live now? | Pin `340aaf831d0f982afb06e318876b50f05ca069cc` / release `340aaf831-main-exact-phase2-20260908-185931`; poller on CURRENT; gateway stamp re-proof SETTLED pmid **51022**; DT-09 **PASS**; soak collector on new pin since 23:02:40Z; wakes=1 |

---

## 2. Identity (served)

| Field | Value |
|---|---|
| Served pin / SOURCE_COMMIT | `340aaf831d0f982afb06e318876b50f05ca069cc` |
| CURRENT release id | `340aaf831-main-exact-phase2-20260908-185931` |
| PR #926 | Merged 2026-09-08T22:58:29Z — delivery_owner → `provider_coordinates` |
| Prior Stage-2 pin/release | `aaa9115cbc2745b34a6d0a48cbdbd012c0ac6816` / `aaa9115cb-main-exact-phase2-20260908-171709` |
| Epoch started | `2026-09-08T21:08:30Z` |
| ORGANIC_ONLY deadline | `2026-09-10T21:08:30Z` |
| API health | `http://127.0.0.1:7777` ok |

---

## 3. Phase status

| Phase | Status | Notes |
|---|---|---|
| **A** Claim universe | **DONE** | `evidence/claim_universe_remediation_20260908/` |
| **B** Dry / hermetic | **DONE** | DT-09 / I-SCHEMA-V2 **PASS** — `evidence/phase_f_prep_20260908/DT09_MIGRATION_V2.json` |
| **C** Deploy | **DONE** | Live on `…185931` after #926 promote |
| **D** Activate | **DONE** | Cron CURRENT-resolved; inbound OK; negatives PASS; controlled gateway |
| **E** Organic soak | **IN PROGRESS** | `consecutive_known_trigger_wakes=1` (23:00Z); collector since 23:02:40Z |
| **F** Independent revalidation | **INTERIM only** | PASS 24 / OPEN_E 8 / RESIDUAL 2 — full PASS waits on Stage-3 seal |
| **Stage-4** | **SCAFFOLD ONLY** | `evidence/stage4_prep_20260908/` |

### Phase D proofs (controlled, retained)

| Gate | Evidence |
|---|---|
| Feed/wake CURRENT-resolved | crontab + `POST_PROMOTE_FEED_AND_SELECT.json` |
| Gateway outbound SETTLED (pre-stamp era) | prior pmids in `M2_CANARY_GATEWAY_OUTBOUND_PROOF.json` |
| Gateway stamped SETTLED (post-#926) | pmid **51022** — `M2_CANARY_GATEWAY_REPROOF_POST_926.json` |
| Operator free-text OK | `INBOUND_OK_PROVEN.json` |
| Negative probes | `PHASE_D_E_CLOSEOUT_PROBES.json` |

### Phase E soak (live ~23:05Z)

**Progress:** known-trigger wake @ 23:00Z counts (wakes=1).  

**Still missing organically:** wakes ≥3 consecutive, `research_consumption` non-none, `organic_commitment_or_outcome`. Confirm soak also sees `gateway_canary_delivery` after pmid 51022.

**Do not** hand-fire wakes to pad counts. **Do not** fake research non-none.

---

## 4. Critical fixes (must keep)

1. Keep `tradeai-cio-telegram.service` disabled — steals `getUpdates`.
2. Poller allowlist in wrapper: `COMMS_INBOUND_SENDER_ALLOWLIST=8797974247,6993102664`.
3. Restart poller after every promote (daemon does not follow CURRENT).
4. `settle_delivery` must stamp `delivery_owner` / `gateway_mode` into `provider_coordinates` (PR #926) or soak `gateway_canary_delivery` false-negatives — see proposed AGENTS amendment.
5. Dry worktree still has **uncommitted** poller OK-ack — not shipped.

---

## 5. Ops scripts (campaign)

| Script | Purpose |
|---|---|
| `ops/wake_selection_feed.py` | DB → JSONL feed |
| `ops/install_current_resolving_wake_cron.py` | feed@:55 wake@:00 via CURRENT |
| `ops/canary_gateway_outbound_proof.py` | Controlled SETTLED proof |
| `ops/m2_canary_soak_collector.py` | Stage-3 soak (SELECT-only) |
| `ops/restart_telegram_poller.py` | Restart poller onto CURRENT |

---

## 6. Operator standing orders

1. Keep competing Telegram long-pollers off until soak seal.
2. Let hourly feed@:55 / wake@:00 run; watch soak log under `~/.grok/long-running-background-tasks/`.
3. When soak emits `M2_CANARY_SOAK_READY_*.tar.gz` (or honest AWAITING): run **Phase F final**, then Stage-4.
4. Preserve ORGANIC_ONLY until deadline. Campaign tree is **not** a git repo.

---

## 7. Key evidence paths

```
evidence/OPERATOR_REVIEW_PACKAGE_20260908T2307Z.md
evidence/SESSION_CLOSEOUT_20260908T2300Z.md
evidence/END_STATE_HANDOFF.md
evidence/M2_CANARY_PROMOTED_340aaf831.json
evidence/M2_CANARY_GATEWAY_REPROOF_POST_926.json
evidence/PHASE_E_SOAK_STATUS.json
evidence/phase_f_prep_20260908/DT09_MIGRATION_V2.json
evidence/INBOUND_OK_PROVEN.json
evidence/phase_f_interim_20260908/
evidence/gateway_soak_gap_20260908/
evidence/stage4_prep_20260908/
evidence/proposed/AGENTS_MD_AMENDMENT_DELIVERY_OWNER_STAMP.md
```

---

## 8. Handoff token

```
M2_STAGE2_COMPLETE m2-canary-20260907 pin=340aaf831d0f982afb06e318876b50f05ca069cc release=340aaf831-main-exact-phase2-20260908-185931 pr926=MERGED gateway_reproof=SETTLED_pmid_51022 dt09=PASS stage3=ORGANIC_ONLY wakes=1 f_full=NOT_DONE m2_pass=NOT_YET
```
