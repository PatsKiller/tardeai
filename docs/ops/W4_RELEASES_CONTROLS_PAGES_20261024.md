# Releases and Ops Controls: shared Jobs body preparation

Date: 2026-10-24. Owner: W4 monitoring. Design-Task: DSN-20261024-w4-monitoring-P1-T1.
Status: preparatory page bodies; W5 frame and complete mobile acceptance remain pending.
Approved reference: w4-ops-pages-redesign.md, desks boards 0 and 16, mobile-first-standard.md.

Releases gains a Jobs URL tab that mounts the same `JobsHealth` component as `/ops/jobs`. It does not fetch the releases/schedules report while that tab is selected. Existing Release train and n8n/schedules sections remain available. The upcoming/recurring timeline now shows schedule intent and stage; its old last-run column is replaced by the shared Jobs execution view, as approved by board 16. Historical errors, skips, busiest lanes, release receipts and queue evidence remain separate recorded history.

Ops Controls mounts the common Jobs component on its Jobs tab and stores the selected tab in the URL, retaining other query parameters. Existing schedule controls remain below the execution view, titled Schedule controls. Release train, kill-switch, passkey, request preview/approval, applier and audit handlers are unchanged. Schedule configuration evidence does not establish successful business execution. No control is invoked by mounting or selecting a tab.

Both page bodies use the scoped ops evidence styles with wrapping tabs and 44px controls. This is preparation for W5's shared frame; it imports no unpublished W5 work.

## Field trace

| Display | Source | Writer / semantics |
| --- | --- | --- |
| Current job execution, failures, missed runs, success receipts | `JobsHealth` → `/api/v2/jobs-health` | Shared W4 execution projection; identical component to `/ops/jobs` |
| Release windows, queue, shipped history, errors | `/api/v2/ops/releases-schedules` | Existing release read model and durable receipts; no release invocation |
| Schedule intent and stage | same `timeline.rows/recurring` | Registry/cron declarations; no execution proof inferred |
| Controls configuration | `/api/v2/ops/controls/state` | Existing guarded server read model; no mutation from a read |
| Controls selected tab | `?tab=jobs|n8n|flags|data|grants|audit` | Browser navigation state only; unrelated query parameters retained |
| Control preview/confirmation/audit | Existing request and passkey handlers | Existing backend authority; no handler or guard change in this checkpoint |

## Remaining acceptance

After W5's frame lands, integrate purpose, URL tabs, canonical writer clocks, in-panel gaps and Decisions through DeskPage. Complete the old n8n-lane current-health column transition to shared Jobs while preserving lane control/configuration evidence. Review old schedule configuration mismatch presentation against the canonical conflict engine; do not add a page-local classifier.

Ops request detail must use the accepted mobile shell and URL Back while preserving its existing guarded handler sequence. Dense controls/release tables still need full phone card acceptance. Final fixture tests must use 1440×1000, 412×915 and 390×844 with actual taps, full-screen in-viewport detail, Back, 44px targets and no horizontal page overflow. Final hidden-driver affected tests, ratchets, registry CHECK, CIO completeness and full build remain PR acceptance. No push, merge, release, schedule edit, policy edit, broker call, live control request or notification is authorized by this preparatory source.
