# Momentum Scalp — 2026-06-29 Health DEGRADED Incident

Status:      HISTORICAL
as_of:       2026-06-29T08:03:38-04:00
Measured at: efcc51365 / not measured

_First trading morning (Monday) after the every-5-min Finviz lane + SEC context + multi-source health
went in. Health Agent fired **DEGRADED 69/100** at 07:46 ET. Investigation + fixes below. No live trades,
no broker writes; source/scheduler/monitoring only._

## What the alert said

`execution:0 · pipeline:45`; `/api/v2/trade-ai did not respond (server busy)`; new findings firing:
`sec_form4_context_stale` (missing), `momentum_scalp_proposal_gen_stale` (3504m), `momentum_scalp_social_scan_stale`
(750m); plus pre-existing `47 agent jobs queued >2h`, `25 proposals >48h no submit`.

## Root cause #1 — server overload from the 5-min lane (REAL regression I introduced)

Each 5-min lane run took **~210s**: `finviz_scan` 90s (full 29-screener `finviz_screener_runner --run`)
+ `signal_sync` 86s + `proposal_gen` 33s + validation 0.5s. The cron fired `*/5` but runs exceeded 5
min, causing **4 flock-skips** (06:00→06:10, 06:25→06:35, 06:35→06:45, 07:15→07:25). On the
single-threaded server with a global DB connection (see `reference_dashboard_performance`), this
saturated the box ~3.5 min of every 5 → `/api/v2/trade-ai` timeouts, load avg ~7.

The pipeline itself was **working correctly** — `scan_counts: 19 rows, 2 GO, 14 WAIT, 3 SCOUT`; the GO
candidate (UPC) was correctly **skipped on a stale weekend quote** (`SKIPPED_STALE_QUOTE quote_stale_3781min`)
— fail-closed behavior intact. The problem was purely cadence/load.

### Fix (cron, applied immediately)

Split the lane so the heavy 90s Finviz refresh runs **every 15 min**, and the fast downstream
conversion chain stays at **every 5 min**, both `flock`-serialized on one lock and hard-bounded by
`timeout`:

```cron
*/5  6-11 * * 1-5 … timeout 200 run_finviz_momentum_scalp_scan.py --window early --apply \
                     --skip-finviz-refresh --sync-signals --generate-proposals \
                     --run-validation-fast-path --submit-validation     # downstream only (~120s)
*/15 6-11 * * 1-5 … timeout 150 run_finviz_momentum_scalp_scan.py --window early --apply  # finviz refresh only
```

This removes the 90s Finviz `--run` from 11 of every 12 runs. Discovery stays fresh (15-min refresh +
the existing 07/08/10/12 finviz crons + the 09:00 orchestrator + 30-min social scan). No gate weakened;
no broker write; operator/2FA untouched. Crontab backed up.

## Root cause #2 — health-check bugs (false floods + a wrong column)

| Finding | Verdict | Cause | Fix |
|---------|---------|-------|-----|
| `momentum_scalp_signal_sync_stale` | **broken check** | queried `strategy_signals.created_at` which doesn't exist (cols are `fired_at`/`expires_at`) → silently errored | use `MAX(fired_at)` |
| `momentum_scalp_proposal_gen_stale` (3504m) | **false flood** | fired pre-market because no proposals were created — but that was correct (only GO candidate had a stale weekend quote) | **condition-aware**: fire only when a fresh GO signal (≤120m) exists but isn't converting, and only in the active session (09:30–12:00) |
| `momentum_scalp_social_scan_stale` (750m) | **transient false alarm** | `scalp_scan_results` was actually fresh (07:47); fired on a pre-open carryover gap | scope to the active session (09:30–16:00); threshold 180m |
| `sec_form4_context_stale` (missing) | **false "missing"** | the SEC log exists (cron ran 05:45); a health run before 05:45 saw no log | SEC window starts **06:00** (after the 05:45 cron) |

**Principle:** an OUTPUT-staleness check is a poor proxy for "stage broken" during legitimately quiet
pre-market periods (weekend-stale quotes are correctly skipped; the orchestrator runs at 09:00). The
checks now fire only in the active session and only on a real conversion gap — the Finviz-lane log
health check (`collect_momentum_scalp_source_health`) remains the primary "is the lane running" signal.

## Not mine (pre-existing, surfaced by the same alert)

`execution:0` — 47 decision-feeding agent jobs queued >2h; 25 broker-route proposals >48h without a
submit tag; `health_agent_cron.log` errors; 1 P0/P1 SIEM issue. These predate this work and are tracked
by their own (existing) collectors/remediations; not changed here.

## Safety

No live trades, no broker writes (24/24 schwab-write guards green; no-broker-write-bypass 11/11). No
freshness/TTL/route/liquidity/risk/account/kill-switch gate weakened — the fail-closed stale-quote skip
that *prevented* the pre-market proposals is exactly correct and untouched. Social Scouts remain
non-tradeable; social-only WATCH/WAIT/SCOUT; large-float manual-review. Operator confirmation / 2FA
untouched. Validation sample unchanged at 2/30; no strategy maturity claim.
