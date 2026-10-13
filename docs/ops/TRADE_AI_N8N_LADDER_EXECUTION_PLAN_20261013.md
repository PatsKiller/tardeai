# Trade AI → n8n ladder — execution plan

as_of: 2026-10-13  
Depends on: diligence branch `wt/trade-ai-page-diligence-20261013` merged + released  
Grant packet: `n8n-maturity-verification/.../TRADE_AI_PAGE_DILIGENCE_AND_N8N_LADDER_GRANT_PACKET_20261013.md`

## Preconditions (hard)

1. Diligence code **live** on portfolio-server CURRENT (five-facts stamping, AT attach, YouTube Ops UI, STALE dedupe, MONITOR_ONLY completeness).
2. Operator pastes YouTube cookies via Ops UI if still RED (human-only).
3. Spot-check: shared candidates CURRENT_SESSION TradeAI rows show `passed_count > 0` when catalyst/price/float/RVOL/gap exist in cache.
4. `momentum-cache-reconcile` remains dry_run until (3) is OBSERVED, not hermetic-only.

## Step 1 — `momentum-cache-reconcile` canary → cutover

**Intent:** live write of SharedMomentumCandidates projection; preserve CONFLICT; no winner.

| Phase | Action | Evidence |
|---|---|---|
| 1a dry_run | Existing shadow lane continues; compare projection hash vs host | `*_last.json` + SIEM |
| 1b canary | Admit live_arg for projection write only; single RTH window | Receipt RUN_DONE live; UI hash matches |
| 1c cutover | Registry stage→cutover for this lane only | Natural fires; CONFLICT rows unchanged |

**Refuse if:** five-facts still 0/5 on CURRENT_SESSION with source fields present; or write would clear CONFLICT.

## Step 2 — `momentum-lifecycle-monitor` canary

**Intent:** MONITOR_ONLY notify on underfill / count_integrity≠RECONCILED / PARTIAL / zero five-facts / CONFLICT spike.

| Phase | Action |
|---|---|
| 2a | Confirm completeness findings present in monitor report (workspace already emits) |
| 2b | Canary: live notify path (Telegram/SIEM) without recovery_intents |
| 2c | Do **not** reactivate `tradeai-momentum-lifecycle-candidate` until relay first-fire fix is released |

## Step 3 — `trade-ai-scalp-live` canary → n8n scheduler

**Intent:** n8n Schedule Trigger becomes scheduler of record for 5-min RTH tick; host cron twin kept until lock proof.

| Phase | Action |
|---|---|
| 3a | Inventory exact crontab line + registry `scheduler.kind` |
| 3b | Publish/activate n8n schedule twin; leave host cron uncommented |
| 3c | Observe natural fires + overlap/flock receipts |
| 3d | Separate cron grant: comment (never delete) host twin after acceptance |

## Step 4 — Ordered fan-out tick

Only after step 3 cutover evidence. One governed workflow: Finviz pull → Trade-AI scalp → AT signal. No second producers.

## Step 5 — AT → TradeAI one-symbol rescore bridge

On APPROACHING/TRIGGERED: governed one-symbol attach (verdict + setup_evidence). Replaces “no scan today” when same-day scan missing for that symbol only.

## Step 6 — Projection-age watchdog

Alert if shared snapshot age > N minutes during RTH (default propose N=15 until measured).

## Step 7 — YouTube cookie sender fold

Host check unchanged; n8n/incident-router delivers RED; Ops UI stays host. Never write cookies from n8n.

## Rollback

Each step: unpublish/deactivate only the named workflow; leave host cron authoritative; restore registry stage to shadow/dry_run for that lane only.
