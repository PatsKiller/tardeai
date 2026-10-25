# LLM Spend and Broker Access page preparation

Date: 2026-10-24. Owner: W4 monitoring. Design-Task: DSN-20261024-w4-monitoring-P1-T1.
Status: preparatory source; W5 frame integration and complete fixture phone acceptance remain pending.
Approved references: w4-ops-pages-redesign.md, board 0 shared frame, mobile-first-standard.md and site-audit FINDINGS.

W9 normally handed these ops-page fixes to W4 at frozen checkpoint `34139b3623f436df226724f4454b186fafb931da`. This source ports the LLM Spend, SpendPanel and Broker Access display fixes only. The shared recorded-evidence formatting module and its test come from W4 Health checkpoint `56800196f70569525f7a2b7a300ec4a47d4ce07a`.

LLM reads use the existing retained-data API hook with 90-second polling. Usage summary, process, lane policy and activity failures display separate unavailable or out-of-date messages. Relative units are explicitly prompt and response characters divided by 1,000; they are volume, not USD. Paid spend remains the provider-derived USD report. Missing spend/token values and missing process totals display unknown rather than zero. Existing operator controls retain their handlers and authority boundaries.

Broker Access uses one recorded open stop-alert count, preserving unknown when the alert store is unavailable. A completed stop check does not close earlier alerts. Date-only success values retain “time not recorded”; no midnight sync time is invented. Account labels use the existing account-label resolver. Receipt exit results display Completed/Failed/Result not recorded. Broker aggregate states remain backend-supplied; this page does not compare timestamps or reclassify conflicts locally. The transferred local sync state comparison is not used.

Both pages gain scoped 44px controls and phone tables that collapse to labelled cards at 820px. Token-based borders, text and dimensions retain desktop tables. Narrow page grids may shrink to the viewport. The styles affect layout only.

## Field trace

| Display | Existing API/field | Writer / semantics |
| --- | --- | --- |
| USD spend, cap ledger, tokens, period | `/api/v2/consumption/spend?period=...` `report.*` | Existing `llm_spend` read model over recorded provider usage and reservation ledger |
| Subscription volume | `/api/v2/consumption/overview` `overview.by_lane.*` | Existing tracked usage; relative units are not dollars |
| Process mode, usage, last call | `/api/v2/consumption/processes` `processes[]` | Existing process registry and usage tracking; no default zero for missing process totals |
| Routing labels | `/api/v2/consumption/lane-registry` | Existing registry; presentation labels only |
| Recent calls | `/api/v2/consumption/logs?limit=40&process_id=...` | Existing call tracking, bounded at 40 |
| Broker state and last success | `/api/v2/system/broker-access` `brokers[]` | Backend read model; page does not call a broker or synthesize aggregate state |
| Open stop alerts | same `stop_health.open_alert_count/alerts_db` | Recorded alert store, one count; missing/unavailable stays unknown |
| Operator sync result | same `operator_sync_log.steps[].rc/signals` | Recorded operator-run evidence, displayed separately from backend aggregate state |
| Account names | same `schwab_tokens.accounts[].account_key` | Existing account-label resolver; no credential values |

## Remaining acceptance

W5's DeskPage must land before frame integration. Each page still needs purpose, URL tabs, canonical writer clocks, gap notices and the Decisions band through that frame. The LLM routing modal needs the accepted mobile detail shell and URL Back behavior under its legitimate file claim; its control handlers must remain unchanged. These are source preparations, not complete redesigned pages.

Fixture browser acceptance must cover healthy/empty/partial/unavailable/retained states at 1440×1000, 412×915 and 390×844, actual taps, in-viewport full-screen detail, Back, 44px targets and no page horizontal overflow. The final PR must include hidden-driver affected tests, all four ratchets, registry CHECK, CIO completeness and full npm build. No live broker, model call, routing change, notification, mode write, deployment or production UI traffic is authorized by this checkpoint.
