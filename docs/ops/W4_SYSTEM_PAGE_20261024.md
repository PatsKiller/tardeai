# System page: shared Jobs and semantic token preparation

Date: 2026-10-24. Owner: W4 monitoring. Design-Task: DSN-20261024-w4-monitoring-P1-T1.
Status: preparatory source; W5 frame and complete mobile acceptance remain pending.
Approved references: w4-ops-pages-redesign.md, desks boards 0 and 16, mobile-first-standard.md, site audit System token debt.

System Jobs and Crons mount the common `JobsHealth` component used by `/ops/jobs`. The old timer-status/current-execution panel is replaced by that shared evidence view under board 16 approval; the independent Overnight queue panel remains. The unused scheduled-jobs request is removed. Cron Compression remains a schedule/configuration diagnostic below the common Jobs view, with missing headline counts shown as unknown. No cron entry, timer or service is edited or invoked.

All 96 original raw hex occurrences in SystemHub are removed or replaced with semantic success, danger, warning and info tokens. The translucent lane fill uses the semantic token through color-mix. Existing sub-10px text is raised to the 10px minimum. Scoped ops styles set 44px native controls and retain existing URL-tab handling. Missing top-level timer, cron, service and LLM-job counts display unknown rather than zero.

## Field trace

| Display | Source | Writer / semantics |
| --- | --- | --- |
| Jobs/Crons current execution | Common `JobsHealth` → `/api/v2/jobs-health` | W4 registry/receipt/wrapper projection; success requires durable execution evidence |
| Independent Overnight queue | Existing `OvernightQueuePanel` | Existing queue read model, retained separately |
| Cron Compression | `/api/v2/system/cron-compression` | Schedule/configuration inventory; not proof that jobs ran |
| System headline counts | Existing quick-count payload `timers_total/cron_count/services_running/llm_jobs` | Existing read model; absent counts stay unknown |
| Platform job execution | Existing `PlatformHealthPanel` → `schedulers.job_execution` | W4 shared execution probe from the first Jobs package |
| Other System tabs and guarded admin controls | Existing tab-enabled API reads and handlers | Unchanged ownership and authority; no broker or admin action called by this change |

## Remaining acceptance

After W5's frame lands, integrate purpose, canonical writer clocks, gap notices and Decisions through DeskPage. Preserve all other tabs/panels. Reuse W9's accepted mobile detail shell for every drill; complete narrow layouts, card tables and keyboard/touch targets for legacy clickable rows. Do not treat these source preparations as complete page acceptance.

Final proof needs fixture-only 1440×1000, 412×915 and 390×844 shots plus actual phone taps, full-screen in-viewport detail, both Back paths, 44px targets and no page horizontal overflow. Final hidden-driver affected tests, four ratchets, registry CHECK, CIO completeness and full build remain PR gates. No push, merge, release, live server traffic, broker call, admin write, schedule edit or notification is authorized by this checkpoint.
