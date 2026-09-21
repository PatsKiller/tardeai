Status: ACTIVE
as_of: 2026-09-20T21:00:00-04:00
Measured at: served CURRENT 251d329a2-main-exact-phase2-20260920-174516; api :7777 = 200; lane registry clean (undeclared 0, structural 0)
Canonical repo path: docs/architecture/LLM_COST_GOVERNANCE_AS_IS_2026-09-20-2100.md
Supersedes: docs/architecture/LLM_COST_GOVERNANCE_AS_IS_2026-09-20-1600.md
Authority: dated live reading of the paid-LLM cost-governance surface — not a behaviour spec
Scope: provider-failure alarming, off-peak deferral, and the lanes that carry them. The
  CIO/AEC maturity surface is a SEPARATE series (docs/architecture/CIO_AS_IS_*), which as of
  its 14:45 edition covers none of this; neither supersedes the other.
See also: docs/ops/LLM_OFFPEAK_ROUTING.md, AGENTS.md §12,
  config/lane_registry.json (lanes llm-provider-health, llm-deferred-drain)

# LLM Cost Governance AS-IS — 2026-09-20 21:00 ET

## LEGEND

| glyph | meaning |
|---|---|
| █ LIVE | runs on the served release, durable effect observed |
| ▓ PARTIAL | armed or present, not yet exercised by organic traffic |
| ░ UNWIRED | code present; consumer or schedule missing |
| ✗ ABSENT | no producer, or never executed |
| ⊠ BLOCKED | measured blocked on an operator action |

## Pin / SHA `[VERIFIED]`

| Field | Value |
|---|---|
| Served CURRENT | `251d329a2-main-exact-phase2-20260920-174516` █ |
| Deployed SHA | `251d329a207d17d21f666e604e0a46967a12b052` █ |
| `origin/main` | `d381bae649a5b077e537b81c13837e9a4f537da8` ▓ (live is behind; other sessions merging) |
| API | `:7777 /api/v2/health` = 200 █ |

**The served release was promoted by another session at 14:51**, not by this work. It is a
descendant of merge `348d4fdba`, so it carries PR #1143. Verified three ways: symbols present in
the live tree, the dry-run source-ordering check against live code, and
`git merge-base --is-ancestor`. **`CURRENT` moves under you — re-read
`systemctl --user show portfolio-server.service -p WorkingDirectory` rather than assuming.**

## What this surface covers

### 1. Provider-failure alarming — `llm-provider-health` █

| Field | Value |
|---|---|
| Schedule | `20 * * * *` (crontab, installed 2026-09-20) █ |
| Output signal | `data/runtime/llm_provider_health.json`, written **every** run █ |
| Classes | BILLING / AUTH / TRANSPORT / UNKNOWN |
| Page policy | billing + auth at **any** volume; transport only at ~100% over ≥5 calls |
| Dedupe | one page per lane per cause per 6h |
| Recovery rule | ≥3 successes since last failure → **reported, not paged** █ |

**Standing gap it closes.** DeepSeek ran to −$0.09 on 2026-09-17 and returned HTTP 402 on every
call for three days — 244 failures 09-17, 242 on 09-18, **660+** total; `hermes_external_research`
ate 172. Nothing alarmed, because every health check watched data freshness rather than provider
errors. A 402'd call still settles its cap reservation, so the outage drained the daily *request*
pools while producing no work. **Cap consumption is not evidence of work.**

**First live run caught a true positive:** `chatgpt 7/7` failing — the free Codex OAuth quota,
still exhausted. That lane is ▓ PARTIAL by cause, not by code: the proxy now answers **429 with
Retry-After** instead of a blanket 502, and `/health` reports `serving` + `last_upstream`, because
a 200 only ever meant the process was alive.

### 2. Off-peak deferral — `llm-deferred-drain` █, ARMED ▓

| Field | Value |
|---|---|
| Drain schedule | `10 10,13,16,19 * * *` (crontab, installed 2026-09-20) █ |
| Output signal | `data/runtime/llm_deferred_drain.json`, written **every** run █ |
| Store | `llm_deferred_requests` (uuid default, partial-unique dedupe, `SKIP LOCKED` claims) █ |
| Tiers | `critical` / `standard` (default) / `deferred`, in `llm_caller_priority` █ |
| Operator surface | Command Center → Ops → LLM Spend → **LLM Routing** █ |

**Armed surfaces `[VERIFIED]` 2026-09-20 16:00 ET**

| surface | state | covers (7-day out-of-window volume) |
|---|---|---|
| crontab line 9 `LLM_DEFER_OFFPEAK=1` | █ ARMED | every cron-launched caller |
| `tradeai-cio-reactive.service.d/offpeak-defer.conf` | █ ARMED | `cio_plan_enrichment` (129) |
| `tradeai-hermes-cio-worker.service.d/offpeak-defer.conf` | █ ARMED | `cio_hermes_research` (29) |
| `tradeai-cio-nightly-reflection.service.d/canary-offpeak-defer.conf` | █ ARMED | `reflective_critic_flash` (56) |
| `portfolio-server.service.d/offpeak-defer.conf` | █ ARMED 20:50 | `hermes_external_research` (117) |

**Deferral is now global.** Four drop-in files plus the crontab line. The flag was verified in the
**running process** via `/proc/<pid>/environ`, not merely in the unit definition — a unit showing
`Environment=` proves only what systemd *would* pass, not what the live process holds.

**`portfolio-server` restart, 20:50:55.** MainPID 2994288 → 3183196, health back within 2s, no
observed downtime. **The recorded restart procedure would have taken the API down:** an older note
states `Restart=always`, so `kill -TERM MainPID` would be revived by systemd. This unit is
**`Restart=on-failure`** — a clean TERM would have left the API dead until someone noticed. That
note also names `tradeai-portfolio-server.service`, which is **inactive and vestigial**; the live
unit is `portfolio-server.service` in **user scope**, restartable via `systemctl --user restart`
with no sudo.
**Systemd units do not inherit a crontab variable**, so each unit-driven paid caller needs its own
drop-in. There is no single file: the runtime env is rendered from Bitwarden Secrets Manager, not
from the repo `.env` (a legacy dual-write for cron that sources it), and a non-secret feature flag
does not belong in a secrets store.

**Measured baseline.** 965 of 4,590 successful paid DeepSeek calls over 7 days (**21%**) fell
outside the window. **All 965** are now covered. `cio_operator_reply` is 251/251 manual and
**never** defers; `hermes_usefulness_score` (1,643) is entirely in-window and unaffected.

### 3. Queue state `[VERIFIED]` 16:00 ET

`{'done': 4}` — **all four are canaries, none organic.** Correct at as_of: 21:00 ET is the boundary
and the window predicate still read open, so nothing should have deferred yet. **Organic deferral
remains UNPROVEN** and is the one open question; the first opportunity is tonight once the window
closes.

The distinction matters because the same reading inverts within minutes: before 21:00, zero rows is
the precondition being met; after it, zero rows would mean the flag is not reaching callers despite
all five surfaces reporting armed. The armed callers were confirmed live and spending at 20:46 —
`cio_plan_enrichment` (5 calls, last 20:39:32), `cio_hermes_research` (3, last 20:46:05),
`hermes_external_research` (21, last 20:01:06) — so an empty queue tonight is a finding, not an
absence of work.

**Proven end to end by the REAL scheduled lane.** The 16:10 cron claimed and ran canary 3
unattended: `completed_at 16:10:02`, `attempts 1`, lane log `1 claimed, 1 ok, 0 failed`, heartbeat
`data/runtime/llm_deferred_drain.json` written at 16:10:02. Earlier proofs were hand-invoked or
cron-equivalent (`env -i`, minimal PATH, the verbatim crontab line); this one was the scheduler
itself.

## Known-not-done ⊠

| item | state |
|---|---|
| Critical allowlist | ✗ **EMPTY** — nothing is marked `critical`, so everything automated outside the window defers |
| Organic deferral | ▓ not yet observed; first opportunity is after 21:00 ET tonight |
| Lane gate | █ **CLEAN** again as of 21:00 — undeclared 0, structural errors 0; the other sessions landed their declarations |

## Defects found by running the code, not reading it

- **The alarm re-paged an outage already fixed.** Last 402 at 19:15:06, topped up by 19:46, lane
  healthy at 7/7 — and the 3h window still read CRITICAL. Hence the recovery rule.
- **The alarm swallowed its own delivery failure** to stderr. A dead lane and an undeliverable
  alert are both just silence. Now recorded on the heartbeat, and the dedupe state is **not**
  marked on a failed send, so the next run retries.
- **A disabled feature queried the database on every paid call** — `evaluate()` resolved the tier
  before checking the enable flag.
- **`--dry-run` consumed the work it previewed.** It called `claim_due()`, stranding the row in
  `claimed` permanently — invisible to `pending` counts. **The habit of dry-running first is
  exactly what walked into it.** Fixed in #1143; `reclaim_stale()` now returns stranded claims.

## Failure modes this surface deliberately chooses

- **Queue unreachable → refuse, do not pay.** If we cannot promise the work runs later, quietly
  paying peak prices is the outcome the operator ruled out.
- **The drain refuses to run outside the window** without `--force`; a drainer that ignores the
  window is only a delayed way of paying peak.
- **Heartbeats are written on every run**, healthy or empty, so an idle lane and a dead lane are
  distinguishable.
