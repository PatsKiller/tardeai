# Phase 1 — disposition and five pilot contracts

Census: 2026-10-07T00:49:34Z. Every row is in `ledgers/lane-ledger.json`. Nothing in this file was activated.

## Disposition

| Disposition | Lanes | Rule |
|---|---|---|
| KEEP_CODE | 145 | Default. Includes paused and never-scheduled rows, which stay declared and are not revived. Includes the exclusion list below. |
| RETIRED | 11 | Registry state RETIRED. Definitions stay. |
| N8N_COORDINATION_PILOT | 5 | The five named candidates. Status DESIGN_ONLY. Cron remains the live owner. |
| N8N_LATER | 11 | Named follow-on families. Not built. |
| CONSOLIDATE_WITH_EXISTING_OWNER | 1 | `holdings-agent-enqueue` stays with the holdings research owner. |

No lane was given to n8n. A green workflow execution is not a disposition.

## Exclusions that stay in their current owner

These stay KEEP_CODE. A later test could reconsider one only with a new contract, a consumer, and a rollback. This pass did not write that test.

| Family | Why it stays | Lanes the matcher caught by id |
|---|---|---|
| Broker stops and live broker reads | Order and stop authority stays in the deterministic path | `alpaca-stop-manager-rth`, `alpaca-stop-manager-oco-repair`, `moomoo-live-read-sync`, `positions-sync`, `positions-shadow-diff`, `positions-proof-daily`, `portfolio-broker-reconciliation` |
| Scalp and market loops | High-frequency signal and recorder paths | scalp lanes, `active-trader-micro-recorder`, `active-trader-micro-recorder-premarket`, `active-trader-signal-calibration` |
| Options math and paper options | Qualification, quote, and strategy math | lanes whose ids contain `options-` or `alpaca` paper reconcile |
| Backup and watchdogs | Must run when n8n is down | backup lanes, `cio-bridge-watchdog`, `postgres-main-watchdog`, `autonomy-watchdog`, `disk-pressure-guard` |
| Canonical memory writes | One memory ledger, in Trade AI | `instrument-belief-writer` |
| Detector and live notifier | Eligibility and send stay in code. The digest is the shadow candidate, not the sender. | `material-change-detector-stage1`, `material-change-notifier-stage2` |
| Fast repricer | Sub-hour market write | `portfolio-repricer` |

2FA, release grants, risk gates, and DOF title or bid decisions have no n8n workflow. They are not a future button.

## Platform choice for the pilot

The incumbent remains systemd, cron, flock, and the existing outboxes. Self-hosted n8n Community 2.43.0 is already installed as a localhost lab and is the coordination candidate. Kestra lost the 2026-10-06 bakeoff, was uninstalled, and is not a candidate. Queue mode is not installed and is not required for five low-frequency shadows. Cloud n8n was not quoted and is a poor fit for a host that already logs about 9,500–10,200 weekday cron command lines a day.

## Pilot contracts

All five are WIRED_UNPROVEN as of `c5de69ee9` (library served, no caller; earlier text said DESIGN_ONLY). Shadow owner: none. No workflow JSON was imported. No send, no model call, no canonical write. Rollback of this phase is to leave the crontab and timers as they were, which is what this pass did.

Shared rules:

- Input is an immutable reference: event id, project, lane id, schema version, origin SHA, subject key, source timestamp, deadline, artifact reference, authority class, correlation id, idempotency key.
- The workflow must be unable to reach Telegram, email, WhatsApp, Slack, Drive writes, provider APIs, broker routes, DOF promote or enrichment-run, and production Postgres even if a node is misconfigured. A dry-run flag is not that boundary.
- Consumer receipt is NOT_MEASURED until a human-visible surface records it. A syslog CMD line is not that receipt.
- Two natural opportunities on a stable served pin are still required before any owner change. That observation has not started.
- Quiet hours, where the incumbent already has them, stay in the incumbent. n8n does not invent a second quiet-hours clock.

### 1. Morning brief receipt — `morning-brief-0730`

- Live owner: comms. Cron `30 7 * * 1-5`, script `send_morning_brief.py`, one host line, `$PROJ`.
- Shadow would compare the expected weekday brief, the artifact, source freshness, and the send disposition already recorded by Trade AI.
- It must not manufacture an empty successful brief and must not send.
- Consumer: operator digest and portal receipt. Both NOT_MEASURED here. The brief log file was 13.33 hours old at the census, which only says the file changed.
- Duplicates: the retired 08:05 and overnight brief senders stay retired.
- Failure: missing artifact is a refusal, not a success. Dead-letter stays in the lab ledger, which does not exist yet.
- Cost: no provider call. Rollback: do not activate the shadow.

### 2. Holdings research handoff — `research-scheduler-holdings`

- Live owner: research. Cron `5 9 * * 1-5`, `research_scheduler.py --mode holdings`, one host line.
- `holdings-agent-enqueue` consolidates here and is not a second pilot.
- Shadow would follow an accepted request through a Hermes run id, dated evidence, and a thesis or a typed refusal, then look for a CIO, watch, or options reader.
- Research production and validation stay in Trade AI and Hermes. n8n does not run the research model.
- The shared trigger ledger file was 0.29 hours old. That file is shared with other research modes, so its mtime is not proof of the holdings mode.
- Consumer acknowledgement: NOT_MEASURED.

### 3. Material-change digest — `material-change-digest`

- Live owner: the digest cron `15 16 * * *` on `notify_material_change.py`. One host line matched the digest tokens.
- The 15-minute notifier and the stage-1 detector stay KEEP_CODE. The matcher also saw the digest script name on the notifier line when the flag was not required. That ambiguity is `MATCHER_MULTIPLE_LINES` on the notifier lane, not permission to move the notifier.
- Shadow would group and record a muted delivery ledger from an already accepted detector event. Significance and eligibility stay in code.
- Output signal is a database column. It was not read. Artifact: NOT_MEASURED.
- Must not mark `notify_outcome` and must not send.

### 4. LLM-spend digest — `llm-spend-report-daily`

- Live owner: comms. Cron `5 7 * * *`, `llm_spend_report.py --period daily`, one host line.
- Weekly and monthly reports are N8N_LATER, same family, not part of the first shadow.
- Shadow would read canonical cost facts and draft a summary. Reservation versus settlement and provider balance were not reconciled in this pass. Label: NOT_MEASURED.
- No new provider charge. The daily artifact file was 13.74 hours old.
- A second cost ledger inside n8n is forbidden.

### 5. Non-trading approval reminder — `approval-package-reminder`

- Live owner: platform. Cron `5 * * * *`, one host line.
- 168 syslog CMD lines in the 7-day slice match an hourly clock. The served CURRENT tree did not have `data/governance/approval_packages.jsonl`. The persistent-state copy was 189.74 hours old. Invocation and artifact freshness disagree. Cause: NOT_MEASURED. This blocks any claim that the reminder is healthy.
- Shadow may only point at an already existing review task. It cannot mint a grant, approve a trade, satisfy 2FA, or advance broker preflight.
- Consumer: NOT_MEASURED.

## Gate

No pilot has an ambiguous business owner. Each has a declared registry owner and one matched crontab line. Each also has an unmeasured consumer and no tested rollback beyond "do not activate." Under the work-order gate, none of them enters an implementation. They stay contracts.
