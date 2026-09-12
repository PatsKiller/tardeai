# Maturity scorecard — 2026-09-12, overnight campaign

Campaign `trade-ai-maturity-overnight-20260912`. Every number below was
measured on this host during the campaign window, not inherited. Status
vocabulary is the campaign's: OBSERVED_CURRENT, OBSERVED_PRIOR_EPOCH,
INTEGRATED, HERMETIC_ONLY, DOCUMENTATION_ONLY, PARTIAL, ABSENT, BLOCKED,
SUPERSEDED.

## Identity at measurement time

| marker | value |
|---|---|
| `origin/main` at campaign start | `eb648174aebc75d0e34eb105b8ff54925efccc7b` |
| served release | `eb648174a-main-exact-phase2-20260911-180637` |
| `SOURCE_COMMIT` / `BUILD_SHA` | both `eb648174a…` |
| API pid 6952 cwd | the served release |
| poller pid 8953 cwd | the served release — **one** poller for the bot token |
| epoch opened | 2026-09-11T22:06Z (the release directory name carries local time) |
| dev tree HEAD | `b8ddeea89…`, **2 commits behind main** |
| cron lines executing dev-tree code | 106 of 456 active; 1 materially affected by the lag |

The API plane is internally consistent. The batch plane is not on the same SHA,
and fast-forwarding the dev tree needs guard scope `maintree`, which this
campaign was not granted. It does not block the maturity spine: the hourly wake,
the research producer, the selection feed and the circulation service all
resolve `CURRENT`, so a promote reaches every lane this campaign touched.

## L1 — provenance and reachability · **PARTIAL**

| clause | measured | status |
|---|---|---|
| wake spine organic and hourly | 6 wakes on the served epoch across 2 contiguous slots | OBSERVED_CURRENT |
| scheduled producers declared and observable | 14 lanes declared this campaign; 4 spine lanes read LIVE, 3 SLOW, 1 LIVE, 6 honest UNVERIFIABLE | OBSERVED_CURRENT |
| durable artifact carries SHA, release, epoch | wake provenance now writes `epoch_id` **and** `release`; previously neither | INTEGRATED |
| producer output reaches the served read plane | **164–172 served files behind their producers** across 5 overlay trees | **ABSENT** |
| state root stable across promote | two inodes; the overlay rule is applied to the release and never to the canonical tree | **ABSENT** |
| no false-success zero-row producer | circulation now reports PARTIAL_DEADLINE / FAILED instead of leaving the last good receipt in place | INTEGRATED |

L1 cannot be accepted while the read plane serves data its producers did not
write. The detector ships; the reconciliation is bidirectional and needs
operator adjudication — see `STATE_ROOT_RECONCILIATION_RUNBOOK.md`.

## L2 — research and memory grounding · **BLOCKED**

| clause | measured | status |
|---|---|---|
| recurring organic research producer | `governed-research-producer` LIVE, 0.36h old, 15 produced on the last run | OBSERVED_CURRENT |
| honest reporting when it produces nothing | already correct: `outcome:"broken"`, `ok:false`, `produced:0` on budget refusal | OBSERVED_CURRENT |
| free-first circulation lane | **0 successful runs since 2026-09-08**; 93 consecutive SIGTERM kills at `TimeoutStartSec=900` | **ABSENT → FIXED, UNDEPLOYED** |
| subject-scoped memory retrieval with decay | 1 fact retained at weight ≈0.40, `cliff_applied=false`, on the served epoch | OBSERVED_CURRENT |
| research consumption with source progression | 5 distinct selection source ids across 6 wakes on this epoch | OBSERVED_CURRENT |
| budget available to the lane | `BUDGET_REFUSED:CALLER_DAILY_CAP` on four consecutive hourly runs | BLOCKED |

## L3 — grounded judgment · **PARTIAL**

| clause | measured | status |
|---|---|---|
| DeepSeek Flash authored a grounded judgment | 5 judgments, 15:00Z–19:00Z 2026-09-11, `model_returned=deepseek-flash`, latency 2306–3786ms | OBSERVED_PRIOR_EPOCH |
| on the served epoch | **0** | ABSENT |
| refuses before spending, while spending is permitted | 4 consecutive slots `offpeak_deferred`, `provider_call_attempts=0`, `live_provider_allowed=true` | OBSERVED_CURRENT |
| no model call without grounding | `l3_skipped_ungrounded`; ungrounded subjects never enter the pipeline | OBSERVED_CURRENT |
| cost provenance persists | was **$0.00 on every paid call** — the author read a field the client does not define | **FIXED, UNDEPLOYED** |
| prompt and input digests persist | `prompt_digest` was never written | **FIXED, UNDEPLOYED** |
| judgment records are individually addressable | **one `judgment_id` for five distinct judgments**; two persisted views an hour apart share it at confidence 0.72 and 0.60 | **FIXED, UNDEPLOYED** |
| release and epoch on the record | `release` was `''` on every judgment | **FIXED, UNDEPLOYED** |
| per-lane budget reservation | absent; `advisory_desk_opinion` took $0.834 over 1019 calls of a $1.50 pool | **FIXED, SHIPS INERT** |
| durable critique record | none exists outside `agent_views.jsonl` | ABSENT |

**L3 cannot be re-proven inside this campaign window.** The DeepSeek off-peak
bulk window reopens at **14:00Z**, measured hour by hour against
`evaluate_offpeak_eligibility`; the campaign deadline is 12:31:44Z. The lane is
refusing correctly in the meantime, which is the desired behaviour, not a fault.

## L4 — outcome learning · **ABSENT**

The contract was never the gap. `GovernedCommitmentOutcome@v1`, the
CONFIRMED/REFUTED/EXPIRED vocabulary, the self-evaluation prohibition and the
append-only ledger all exist. What was missing is *later*:

| measured | value |
|---|---|
| cron entries revisiting due commitments | **0** |
| systemd units revisiting due commitments | **0** |
| callers of `evaluate_outcome` | 1, invoked on the same line that mints the commitment |
| durable records | 224 |
| of those, predictions (`due_at` **and** `horizon`) | 99 |
| of those, observations (neither) | 125 |
| predictions past due | 0 — earliest `due_at` 2026-09-17 |
| **predictions that are falsifiable** | **0 of 99** |

All 99 carry the falsifier "observation contradicts claim within horizon" over
claims asserting only that a review occurred. The sweep now exists and is
scheduled-ready; its input supply contains no falsifiable prediction, so L4
stays ABSENT and this says exactly why.

## L5 — unattended detection and repair · **ABSENT**

The dedicated detector returned `healthy: true` throughout a four-day,
93-failure total outage, while printing the 4.4-day-old timestamp and the
non-served SHA in its own output. `paid == 0` was one of its three conditions,
so a dead service scored as maximally healthy. Fixed so it can go false; the
unattended detect → diagnose → propose → repair → verify → report loop remains
unobserved. **This campaign repairing defects is not L5** and does not count
toward it.

## M2 — same-epoch circulation · **NOT_ACCEPTED**

Measured on the served epoch (`eb648174a`, opened 2026-09-11T22:06Z):

| clause | bar | measured |
|---|---|---|
| contiguous scheduled organic cycles | ≥3 | **3** — 00:00Z, 01:00Z, 02:00Z, **MET** |
| research consumptions with source progression | >0 | 5 distinct source ids |
| gateway-owned provider-ack SETTLED | >0 | **1** SETTLED, 9 UNSETTLED, 1 UNKNOWN_LEGACY |
| durable inbound operator consumption | >0 | **0 inbound events** |
| distinct commitments frozen before outcome windows | >0 | 6 governed, all `frozen_at < due_at` |
| consumption receipts | >0 | 4, all `effect_kind=changed_question` |

The cycle clause was met at 02:00Z, after three unattended cron wakes on the
served SHA — recorded in `M2_CYCLE_CLAUSE_MET_2026-09-12T0200Z.json` before any
promote could reset the count. M2 now fails on exactly one clause.

The inbound clause needs a genuine operator reply. No agent may manufacture one,
and this campaign did not.

## MVL v3.3 — **NOT_ACCEPTED**

Measured on the **producer** plane; the served plane is 16 days behind it, which
is the state-root split above.

| clause | bar | measured | status |
|---|---|---|---|
| reviewed Watch artifacts | 100 | 136 distinct artifacts reviewed — but these are agent advisory artifacts, not Watch artifacts | NOT MET (wrong corpus) |
| known-bad regression fixtures | ≥20 | not located | UNVERIFIED |
| retrieval on eligible Sentinel reviews | ≥95% | **0 of 140 = 0.0%** — no review carries any retrieval or evidence field | **NOT MET** |
| Darwin scoring on eligible artifacts | ≥95% | **136 of 136 = 100%** | MET |
| measured Sentinel false-positive rate | measured | fail rate 4/140 = 2.9%; an FP rate needs those 4 adjudicated and no adjudication exists | **NOT MEASURED** |
| nightly reflection creates candidate lessons | yes | 14 reflection records, 1002 cases seen, 284 scored, `auto_promotions: 0` — newest **2026-08-26**, 17 days stale | PARTIAL |
| no production configuration mutation | yes | `mutates_production: false` on every record | MET |
| no broker call | yes | Darwin `model_calls: 0`, `cost_usd: 0.0` | MET |

## Forbidden terms

READY, 100%, M2_ACCEPTED, MVL_ACCEPTED and L4/L5 acceptance are not claimed
anywhere in this document, and no gate above is reported as met on evidence this
campaign did not measure.
