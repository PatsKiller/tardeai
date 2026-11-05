# Automations v001 — SPEC (APPROVED): what the n8n lanes are doing, and what still runs on cron

Operator request, 2026-11-04: "I need a page like this in command center for n8n" — a screenshot of n8n's own Overview
(KPI strip, tabs, workflow list with steps, folder and status). Mockup v001 was built from real data at 2026-11-04 19:15 ET
and approved by the operator without a tap; the approval and the mockup's sha256 are recorded in
`coordinator/ledger.jsonl` (entry 3480, 2026-11-05T00:19:58Z).

This page is **new** and removes nothing. The existing **N8nToday** tab stays and links to this page.

## The page's one job

Answer, in one screen: are my automations running, what is failing and why, and how much of the old scheduler is left to
retire. It is a dashboard — summary before detail, state encoded in form (pills, stripes, counts) as well as in numbers.

## Sections (desktop 1440; phone 390/412 one column, same order)

1. **Alert banner** — shown only when the 7-day failure rate exceeds 10%. Names the single largest cause and the queue row
   that fixes it. Quiet otherwise; never a standing banner.
2. **KPI strip (7 days)** — scheduled runs · failed runs · failure rate · average run time · cron jobs left (and how many
   already have an n8n draft). Each figure carries its change against the prior 7 days from the daily snapshot table.
3. **Workflows tab** — every non-archived workflow. Row: name · last run (ET) · updated · created · area (n8n folder) ·
   step count · ok/total runs with fail % · state pill (Live / Shadow / Off). A failing row carries its last error reason
   on one line and a red left stripe. Search, and filters All / Failing / Live / Off.
4. **Row sheet** (full screen on phones, ← Back) — state; why it fails plus a link to its fix row; runs per 6 h over 7 days
   (green/red); what it replaces (cron line or timer, and whether that is off); repo file and backup file with drift
   status; lifecycle stage with 72 h progress.
5. **Cutovers tab** — lifecycle counts per stage (Draft · Dry run · Shadow · Cutover · 72 h check · Sunset), plus a table of
   lanes inside the 72 h check: cutover time, cron line off, runs passed/due, time to sunset.
6. **Cron left tab** — active crontab lines and system timers, split "has n8n draft" / "no draft yet". The count is the
   number this programme exists to drive to zero.
7. **Library & backup tab** — last export to `~/Claude/N8N`, counts per folder, and sha256 drift per workflow.

## Data (read-only; logic in the broker, the page only renders — AGENTS §13)

One read-only data-broker endpoint assembling: n8n Postgres (`workflow_entity`, `execution_entity`, and the error message
from `execution_data` only), `config/lane_registry.json`, `crontab -l` and system timers, the cutover ledger, and
`~/Claude/N8N/MANIFEST.json`. No secrets in the payload.

n8n keeps roughly 7 days of executions, so a daily **snapshot** (n8n lane, 23:59 ET) of per-workflow runs / fails / average
time lands in a table; trends and week-over-week deltas read from it, never from a live scan of the execution table.

**"Failure" means a real failure.** A lock skip — the previous run still going, inside its SLA — is counted separately as
**skipped** (FQ-129). Conflating the two is what made the current fleet look 97% broken.

## Acceptance

- Live at 1440, 412 and 390; every row opens its sheet; the sheet closes with ← Back on a phone.
- The numbers match the n8n DB at check time, and the check is shown (query + timestamp in the payload/receipt).
- A Playwright site-audit row is added for this page.

## Limits stated up front

- The page cannot be more honest than its sources: `execution_data` is read for the error message only, and a workflow
  whose errors are not recorded will show "no error recorded", not an invented cause.
- Trend figures are blank, not zero, until the snapshot table has history.
