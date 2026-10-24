---
id: DSN-20261022-operator-approvals
title: Operator approvals and grants (2026-10-21..23)
status: IN_PROGRESS
approval: operator-only (§17); recorded here, never granted here
source: memory project_overnight_approvals_20261022.md; coordinator worklog; bin/guard ledger (ids and reasons only)
summary: Phases P1-P13 are approvals A-M ("yes i approve 'approve all' (A–L)", 2026-10-22 ~22:30 ET; M earlier). P14-P26 later
  approvals and the pending list. P40+ are guard grants.
phases:
- id: DSN-20261022-operator-approvals-P1
  title: A — merge green PRs as combined release batches (all required checks green)
  status: IN_PROGRESS
  evidence: 'used: batch 7 #1982, batch 8 #2002, batch 9 #2018 merged; batch 10 in integration'
- id: DSN-20261022-operator-approvals-P2
  title: B — one release-write grant from Ops Controls; agent runs releases (dry run, auto-rollback, health check, emailed
    report)
  status: DONE
  evidence: grant 7493a870 (10-22 21:54, 'overnight batches 7-9'), then campaign grant 46e85e0d (10-23 09:38); releases 7
    and 8 run
- id: DSN-20261022-operator-approvals-P3
  title: C — build and push the AGENTS 19.1.0 package (numbered 20.0.0)
  status: LIVE
  evidence: 'AGENTS 20.0.0 ratified on #2013 (comment 6367515961), served 80e93c99f'
- id: DSN-20261022-operator-approvals-P4
  title: D — lane-registry rows match the 10-22 resume (14 ACTIVE, 3 N8N-OWNED, 1 RETIRED)
  status: LIVE
  evidence: '#1978 registry truth after the 10-22 resume, batch 8, LIVE 80e93c99f'
- id: DSN-20261022-operator-approvals-P5
  title: 'E — Gate 2: cio_prospect registry row, migration 6bac8924, read-only reader batch for the shadow lane'
  status: IN_PROGRESS
  evidence: 'NOT applied: the store is still shadow; T-20261023-9c7a5c finds why and hands the operator the command'
- id: DSN-20261022-operator-approvals-P6
  title: 'F — mark the #1953 and #1957 n8n contracts REVIEWED'
  status: DONE
  evidence: both contracts status REVIEWED in config/n8n_health_contracts.json on the PR branches; PRs not yet merged
- id: DSN-20261022-operator-approvals-P7
  title: 'G — Home reads positions through reader batch #3'
  status: LIVE
  evidence: '#1978 (Home reader batch #3), LIVE 80e93c99f'
- id: DSN-20261022-operator-approvals-P8
  title: H — Gate 4 execution-engineering grant (operator-issued)
  status: DONE
  evidence: 'grants e88bf21e (10-22 21:54, 8h) and 423dbe39 (10-23 09:00, 8h, + premarket_watch.py); #1971 and #1983 built
    under them'
- id: DSN-20261022-operator-approvals-P9
  title: I — fix the release-train checkout, then run the Phase 5 shadow windows and drills
  status: IN_PROGRESS
  evidence: 'checkout fix #1967 LIVE 80e93c99f; Phase 5 not run (no shadow receipts; arming step E last FAILED 10-22 15:13Z)'
- id: DSN-20261022-operator-approvals-P10
  title: J — arm the 18:00 canary (operator types the arm at the TTY)
  status: PROPOSED
  evidence: waits on Phase 5 (DSN-20261021-release-train-P6-T4)
- id: DSN-20261022-operator-approvals-P11
  title: K — archive (rename, keep) the two big health JSONL logs
  status: IN_PROGRESS
  evidence: 'not done: both files un-rotated 10-23 14:11 ET; PR #2016 + operator packet after 16:15 (DSN-20261023-jsonl-retention)'
- id: DSN-20261022-operator-approvals-P12
  title: 'L — Schwab stays read-only: access mode and trading lock change only by the operator with a passkey'
  status: LIVE
  evidence: AGENTS 20.0.0 §28.6, served 80e93c99f
- id: DSN-20261022-operator-approvals-P13
  title: M — dependency upgrades (Vite 8, esbuild, react-router) last, separate release, rollback plan
  status: APPROVED
  evidence: 'not started: T-20261023-948210 (DSN-20261022-dependency-upgrades)'
- id: DSN-20261022-operator-approvals-P14
  title: 10-21 release-train decisions D1-D6, forced off-window canary, macro calendar, Phase 5-7 kept
  status: DONE
  evidence: D1 standing delegation, D2 GitHub App 5419776, D3 host CLI/Telegram resume, D4 ci-gate required, D5 15.0.0 merged,
    D6 guard hooks in log mode
- id: DSN-20261022-operator-approvals-P15
  title: 10-21 retention rulings "Approve all leans" (D1-D10; D11 held)
  status: IN_PROGRESS
  evidence: DSN-20261010-db-retention-iris
- id: DSN-20261022-operator-approvals-P16
  title: 10-22 Gate 3 mockup, Home, Options, Open Trades, Trading tabs, Releases & Schedules page, Watch mockup
  status: LIVE
  evidence: 'batch 5 ee38621b1 (#1924 #1945 #1948 #1949 #1938)'
- id: DSN-20261022-operator-approvals-P17
  title: 10-22 ~15:35 "start executing immediately with multiple agents for everything not built and not live; ignore the
    stops for now"
  status: DONE
  evidence: 'agents launched 10-22 (memory: project_momentum_catalyst_gates.md)'
- id: DSN-20261022-operator-approvals-P18
  title: 10-22 passkey ("yes on passkey") + "approve sudo window"
  status: IN_PROGRESS
  evidence: 'passkey LIVE 10-22 21:26; sudo window #1970 open (DSN-20261022-ops-controls P5)'
- id: DSN-20261022-operator-approvals-P19
  title: 10-22 enrichment-coverage scope + in_directive_watch at source
  status: IN_PROGRESS
  evidence: '#1958 / #1960 green (DSN-20261022-cio-prospect-store P7)'
- id: DSN-20261022-operator-approvals-P20
  title: 10-23 Ask the CIO phases 8-11 + option B advisory sizing (AGENTS 21.0.0)
  status: IN_PROGRESS
  evidence: DSN-20261023-ask-the-cio; 21.0.0 PROPOSED
- id: DSN-20261022-operator-approvals-P21
  title: 10-23 10:00 hot-list budget 100->170 s, timeout 110->180
  status: LIVE
  evidence: operator ran hotlist-budget-operator.sh; crontab APPLIED and verified (T-20261023-73f31d done); registry row T-20261023-838c62
    open
- id: DSN-20261022-operator-approvals-P22
  title: 10-23 ~11:05 AGENTS 20.1.0 live-server rule "approved"
  status: DONE
  evidence: '#2019 ratified (comment 6370144385), merged d42fa803d'
- id: DSN-20261022-operator-approvals-P23
  title: 10-23 11:10 log deletion authority ("You have my authority to delete them.")
  status: HELD
  evidence: 'blocked by §24.12, the persistent-state never-touch list and §23.14: needs a MAJOR amendment (DSN-20261023-jsonl-retention
    P2)'
- id: DSN-20261022-operator-approvals-P24
  title: 10-23 P3 UI fixes approved
  status: IN_PROGRESS
  evidence: '#2017 green, conflicting (DSN-20261022-site-validation P2)'
- id: DSN-20261022-operator-approvals-P25
  title: 10-23 13:35 Work pipeline mockup + BOTH action tiers
  status: IN_PROGRESS
  evidence: '#2021 (Tier 1); Tier 2 stacked (DSN-20261023-work-pipeline)'
- id: DSN-20261022-operator-approvals-P26
  title: Pending operator approval list (umbrella board task T-20261023-240510)
  status: PROPOSED
  evidence: see the table below
  tasks:
  - id: DSN-20261022-operator-approvals-P26-T1
    title: 'OPERATOR: rotate the Trade AI DB password and the Cursor credential — board task T-20261023-dca62d'
    status: PROPOSED
    areas:
    - secrets
    board_task: T-20261023-dca62d
  - id: DSN-20261022-operator-approvals-P26-T2
    title: 'OPERATOR: approval list — board task T-20261023-240510'
    status: PROPOSED
    areas:
    - docs/ops
    board_task: T-20261023-240510
- id: DSN-20261022-operator-approvals-P40
  title: 'Grant 69fb2866 [execution-engineering] 10-21 14:47 ET -> 10-21 17:47 ET, 20 uses left, expired: Schwab reauth step-up
    gate investigation/fix, hermetic tests only'
  status: DONE
- id: DSN-20261022-operator-approvals-P41
  title: 'Grant e171bffe [cron] 10-21 15:50 ET -> 10-21 17:50 ET, 2 uses left, expired: hermes-watchlist-scorer n8n cutover:
    comment out crontab L451'
  status: DONE
- id: DSN-20261022-operator-approvals-P42
  title: 'Grant fce00834 [release-write] 10-22 08:41 ET -> 10-22 10:41 ET, 0 uses left, replaced: Release 3: #1913 c81eb463c'
  status: DONE
- id: DSN-20261022-operator-approvals-P43
  title: 'Grant fb5100bf [release-write] 10-22 08:55 ET -> 10-22 16:55 ET, 0 uses left, replaced: Release 4: #1915 Finviz
    (+17.0.0 #1914)'
  status: DONE
- id: DSN-20261022-operator-approvals-P44
  title: 'Grant 8505d9ee [broker-read] 10-22 11:04 ET -> 10-22 12:04 ET, 0 uses left, exhausted: Confirm SPCX stop coverage
    and holdings after stops filled/replaced'
  status: DONE
- id: DSN-20261022-operator-approvals-P45
  title: 'Grant 71b31bf2 [broker-read] 10-22 11:08 ET -> 10-22 12:08 ET, 0 uses left, exhausted: Apply broker_read_sync: resync
    holdings.json after clean dry run'
  status: DONE
- id: DSN-20261022-operator-approvals-P46
  title: 'Grant 7726e77a [config-write] 10-22 11:13 ET -> 10-22 11:43 ET, 2 uses left, expired: Release-train step E: 4 release-train-request
    lanes + pr-hygiene-audit to the live list'
  status: DONE
- id: DSN-20261022-operator-approvals-P47
  title: 'Grant 4af07346 [release-write] 10-22 12:19 ET -> 10-22 16:19 ET, 3 uses left, expired: Release 5: #1922-#1926'
  status: DONE
- id: DSN-20261022-operator-approvals-P48
  title: 'Grant 4710a3a8 [release-write] 10-22 18:57 ET -> 10-22 22:57 ET, 0 uses left, replaced: Batch 5 #1959 + batch 6
    #1961 + 19.0.0 #1962'
  status: DONE
- id: DSN-20261022-operator-approvals-P49
  title: 'Grant cfb10259 [release-write] 10-22 20:31 ET -> 10-22 22:31 ET, 0 uses left, exhausted: Release for #1962 (f7c1e96cb)'
  status: DONE
- id: DSN-20261022-operator-approvals-P50
  title: 'Grant 7493a870 [release-write] 10-22 21:54 ET -> 10-23 09:54 ET, 0 uses left, replaced: Overnight release batches
    7-9 (approve-all A-M)'
  status: DONE
- id: DSN-20261022-operator-approvals-P51
  title: 'Grant e88bf21e [execution-engineering] 10-22 21:54 ET -> 10-23 07:54 ET, 20 uses left, expired: approve-all H: kill_switches.py,
    momentum_alerts.py, microstructure_signals.py, momentum_alerts_api.py, read_api.py, signal_calibration.py; A1/A2 only'
  status: DONE
- id: DSN-20261022-operator-approvals-P52
  title: 'Grant 72504f52 [release-write] 10-23 08:52 ET -> 10-23 14:52 ET, 0 uses left, replaced: Release 7: #1963 0f5bf2453
    + batch 7 #1982'
  status: DONE
- id: DSN-20261022-operator-approvals-P53
  title: 'Grant 423dbe39 [execution-engineering] 10-23 09:00 ET -> 10-23 17:00 ET, 20 uses left, active: approve-all H + premarket
    speed-up: premarket_watch.py + the H files + kill_switches.py; A1/A2 only'
  status: IN_PROGRESS
- id: DSN-20261022-operator-approvals-P54
  title: 'Grant c16464e2 [release-write] 10-23 09:38 ET -> 10-23 21:38 ET, 0 uses left, replaced: campaign release-batches-20261023
    (duplicate issue)'
  status: DONE
- id: DSN-20261022-operator-approvals-P55
  title: 'Grant 46e85e0d [release-write] 10-23 09:38 ET -> 10-23 21:38 ET, 16 uses left, active: campaign release-batches-20261023:
    all batch releases today (batch 7 #1982 onward), approve-all A/B'
  status: IN_PROGRESS
---

Backfill 2026-10-23 (task T-20261023-730ebe). Approvals are the operator's (§17, §28.4); an agent records them
and never grants them. Grant ids and reasons come from the guard ledger; no secret is recorded.

Operator, verbatim, 2026-10-22 ~22:30 ET: "yes i approve 'approve all' (A–L)". M, earlier: "if we get through
everything else, you can do all of the upgrades. And have a rollback plan just in case something breaks."
Never covered: clearing kill switches (operator at the terminal or Ops Controls with a passkey), positions
without stops ("I'll manage that."), any broker order, stop or 2FA action, self-issued grants.

Counting: done = P2 B, P3 C, P4 D, P6 F, P7 G, P8 H, P12 L (DONE/LIVE); pending = P1 A (standing, in use),
P5 E, P9 I, P10 J, P11 K, P13 M.

## Pending operator items (every OPERATOR task on the board)

| task | item | status |
|---|---|---|
| `DSN-20261021-release-train-P4-T2` | OPERATOR: re-run arming step E (relay contract check) — failed 2026-10-22T15:13Z; probe fixed by #1923, NOOP receipt by #1967 (LIVE 80e93c99f) | PROPOSED |
| `DSN-20261021-release-train-P6-T3` | OPERATOR: merge draft flips #1937 / #1939 / #1942 after Phase 5 proof | PROPOSED |
| `DSN-20261021-release-train-P6-T4` | OPERATOR: arm the 18:00 canary at the TTY (approval J) | PROPOSED |
| `T-20261023-711566` | OPERATOR: 06:00 window decision (12 critical jobs) — board task T-20261023-711566 | PROPOSED |
| `DSN-20261022-momentum-alerts-P2-T2` | OPERATOR: run the catalyst consolidation packet (docs/ops/packets/catalyst-consolidation-20261022) — #1978 is LIVE | PROPOSED |
| `DSN-20261022-momentum-alerts-P4-T1` | Operator decision on the AT live replacement (shadow today) | PROPOSED |
| `DSN-20261023-ask-the-cio-P8-T2` | OPERATOR: third push for #2011 (push budget) | PROPOSED |
| `DSN-20261023-ask-the-cio-P9-T1` | OPERATOR: third push for #2006 (local commit 9d4fd4d04, env_names sort fix) | PROPOSED |
| `DSN-20261023-ask-the-cio-P9-T2` | OPERATOR: review the cio-ask-research lane contract (DRAFT -> REVIEWED) on #2006 | PROPOSED |
| `DSN-20261023-ask-the-cio-P9-T3` | OPERATOR: decide the cio_ask_deep_research spend cap ($5/day proposed vs $2/day global cap) | PROPOSED |
| `DSN-20261023-ask-the-cio-P10-T1` | OPERATOR: approve the questions/answers store row (§26), the positions_store reader cio_ask and the memory apply flag | PROPOSED |
| `DSN-20261022-cio-prospect-store-P3-T4` | OPERATOR: approve positions reader batch #4 (curator held flag) — phrase 'approve positions reader batch #4 (curator held flag)' | PROPOSED |
| `DSN-20261022-cio-prospect-store-P5-T3` | OPERATOR: decide suppress_add_hold and HELD->EXIT | PROPOSED |
| `DSN-20261022-cio-prospect-store-P5-T4` | OPERATOR: decide the SAIQ GUID split | PROPOSED |
| `DSN-20261022-data-domains-P2-T1` | OPERATOR: sign off batch B domains | PROPOSED |
| `DSN-20261022-data-domains-P3-T1` | OPERATOR: sign off batch C domains (writers consolidate first) | PROPOSED |
| `DSN-20261023-agent-ops-P1-T6` | OPERATOR: AGENTS 21.0.0 advisory sizing apply/ratify | PROPOSED |
| `DSN-20261023-agent-ops-P1-T7` | OPERATOR: push policy v2 apply/ratify; then draft-PR CI skip workflow PR | PROPOSED |
| `DSN-20261023-jsonl-retention-P1-T1` | OPERATOR: review the JSONL rotation lane contract on #2016 (red until REVIEWED) | PROPOSED |
| `DSN-20261023-jsonl-retention-P1-T3` | OPERATOR: run the rotation packet after 16:15 ET (archives the two big health JSONL logs — approval K) | PROPOSED |
| `DSN-20261023-jsonl-retention-P2-T1` | OPERATOR: log deletion decision — deletion needs a MAJOR AGENTS amendment (§24.12 / never-touch list / §23.14) | PROPOSED |
| `DSN-20261022-ops-controls-P2-T1` | OPERATOR: rename the passkey named "804607" (add a new passkey, revoke the old one) | PROPOSED |
| `DSN-20261022-ops-controls-P5-T2` | OPERATOR: set ops_controls.sudo_window_enabled after #1970 is LIVE | PROPOSED |
| `DSN-20261022-n8n-promotions-P1-T1` | OPERATOR: approve or decline promotion letter A | PROPOSED |
| `DSN-20261022-n8n-promotions-P2-T1` | OPERATOR: approve or decline promotion letter B | PROPOSED |
| `DSN-20261022-n8n-promotions-P3-T1` | OPERATOR: approve or decline promotion letter C | PROPOSED |
| `DSN-20261022-n8n-promotions-P4-T1` | OPERATOR: approve or decline promotion letter D | PROPOSED |
| `DSN-20261022-n8n-promotions-P5-T1` | OPERATOR: approve or decline promotion letter E | PROPOSED |
| `DSN-20261022-n8n-promotions-P6-T1` | OPERATOR: approve or decline promotion letter F | PROPOSED |
| `DSN-20261023-premarket-focus-P2-T1` | OPERATOR: run docs/ops/packets/premarket-1min-20261023/install.sh outside 05:55-09:35 ET, add the inventory row | PROPOSED |
| `DSN-20261023-premarket-focus-P3-T1` | OPERATOR: flip premarket cadence_mode to live after a clean shadow session | PROPOSED |
| `DSN-20261023-at-tradeai-alignment-P3-T1` | OPERATOR: merge #1991 (green; classifier denied the agent merge) | PROPOSED |
| `DSN-20261023-at-tradeai-alignment-P4-T1` | OPERATOR: SAIQ prior-close reference (moomoo 5.56 vs Finviz ~5.28) — which prior close both surfaces show | PROPOSED |
| `DSN-20261022-site-validation-P4-T1` | OPERATOR: portfolio valuation-clock decision (holdings reprice vs overview snapshot, report #17) | PROPOSED |
| `DSN-20261010-db-retention-iris-P5-T1` | OPERATOR: install the archive off-box sync packet (docs/ops/packets/archive-offbox-20261021) | PROPOSED |
| `T-20261023-847c24` | OPERATOR: clear global kill switch after #1983 live — board task T-20261023-847c24 | PROPOSED |
| `DSN-20261022-schwab-readonly-baseline-P5-T1` | OPERATOR: Grok stop review (held from the SPCX resume) | HELD |
| `T-20261023-dca62d` | OPERATOR: rotate the Trade AI DB password and the Cursor credential — board task T-20261023-dca62d | PROPOSED |
| `T-20261023-240510` | OPERATOR: approval list — board task T-20261023-240510 | PROPOSED |

## Grants (bin/guard ledger, 2026-10-21 12:00 ET onward)

| issued (ET) | tier | id | uses left | status | expires (ET) | reason |
|---|---|---|---|---|---|---|
| 10-21 14:47 | execution-engineering | 69fb2866 | 20 | expired | 10-21 17:47 | Schwab reauth step-up gate investigation/fix, hermetic tests only |
| 10-21 15:50 | cron | e171bffe | 2 | expired | 10-21 17:50 | hermes-watchlist-scorer n8n cutover: comment out crontab L451 |
| 10-22 08:41 | release-write | fce00834 | 0 | replaced | 10-22 10:41 | Release 3: #1913 c81eb463c |
| 10-22 08:55 | release-write | fb5100bf | 0 | replaced | 10-22 16:55 | Release 4: #1915 Finviz (+17.0.0 #1914) |
| 10-22 11:04 | broker-read | 8505d9ee | 0 | exhausted | 10-22 12:04 | Confirm SPCX stop coverage and holdings after stops filled/replaced |
| 10-22 11:08 | broker-read | 71b31bf2 | 0 | exhausted | 10-22 12:08 | Apply broker_read_sync: resync holdings.json after clean dry run |
| 10-22 11:13 | config-write | 7726e77a | 2 | expired | 10-22 11:43 | Release-train step E: 4 release-train-request lanes + pr-hygiene-audit to the live list |
| 10-22 12:19 | release-write | 4af07346 | 3 | expired | 10-22 16:19 | Release 5: #1922-#1926 |
| 10-22 18:57 | release-write | 4710a3a8 | 0 | replaced | 10-22 22:57 | Batch 5 #1959 + batch 6 #1961 + 19.0.0 #1962 |
| 10-22 20:31 | release-write | cfb10259 | 0 | exhausted | 10-22 22:31 | Release for #1962 (f7c1e96cb) |
| 10-22 21:54 | release-write | 7493a870 | 0 | replaced | 10-23 09:54 | Overnight release batches 7-9 (approve-all A-M) |
| 10-22 21:54 | execution-engineering | e88bf21e | 20 | expired | 10-23 07:54 | approve-all H: kill_switches.py, momentum_alerts.py, microstructure_signals.py, momentum_alerts_api.py, read_api.py, signal_calibration.py; A1/A2 only |
| 10-23 08:52 | release-write | 72504f52 | 0 | replaced | 10-23 14:52 | Release 7: #1963 0f5bf2453 + batch 7 #1982 |
| 10-23 09:00 | execution-engineering | 423dbe39 | 20 | active | 10-23 17:00 | approve-all H + premarket speed-up: premarket_watch.py + the H files + kill_switches.py; A1/A2 only |
| 10-23 09:38 | release-write | c16464e2 | 0 | replaced | 10-23 21:38 | campaign release-batches-20261023 (duplicate issue) |
| 10-23 09:38 | release-write | 46e85e0d | 16 | active | 10-23 21:38 | campaign release-batches-20261023: all batch releases today (batch 7 #1982 onward), approve-all A/B |
