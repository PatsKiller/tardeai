# Job catalog vs n8n audit: one audit header, two pages (LQ-20261107-506)

```
Status:      ACTIVE (code on branch wt/livefix-cc-sonnet-3-lq506; not deployed by this change)
as_of:       2026-11-07T20:45:00-05:00
Measured at: live read-only GETs /api/v2/jobs-catalog and /api/v2/ops/n8n-catalog, 2026-11-07 ~20:30 ET
```

Operator, 2026-11-07 20:34 ET (relayed by claude-lead): "I need the desktop to have all of that same information.
That the phone has." No page and no tab is removed. The separate mockup gate was waived by the operator.

## What changed

| Where | Change |
|---|---|
| Ops > Job catalog (`/v3/ops/jobs-catalog`) | Shows the same n8n audit header and six stat tiles as the audit tab, from the same GET (`/api/v2/ops/n8n-catalog`), with no copied numbers. A header line links to the audit tab. Each job row carries a verdict badge (PASS, FAIL, UNVERIFIABLE, plus the LQ when there is one). |
| Jobs & n8n, `tab=catalog` | The tab label reads "n8n audit" (was "n8n catalog"). The route is unchanged. |
| Sidebar, Ops > Is it running | New entry "n8n audit" linking `/v3/ops/jobs-n8n?tab=catalog`. Additive. |

One function, `auditHeaderHtml(wire)` in `src/lib/n8nCatalogApproved.ts`, builds the header and tiles for both pages.
`overviewHtml` is that function plus the verdict section, so the audit tab is byte-identical to before.

Unknown is not zero. While the audit is unloaded a job row shows no badge. Once it is loaded, a job with no verdict
shows "n8n audit: not audited".

## Why the counts differ

Both pages count the same registry, but they count different things.

| Number | Page | What it counts |
|---|---|---|
| 721 | Job catalog | Every registry job: 512 ACTIVE, 152 RETIRED, 34 NEVER_SCHEDULED, 23 PAUSED. |
| 695 | Job catalog header text | The older description count, not the 721 total. |
| 81 | n8n audit | Jobs whose n8n mode is `live` (n8n alone runs them). |
| 31 | n8n audit | Mode `both`: n8n and a cron twin. |
| 23 | n8n audit | Mode `dry`: n8n shadow only. |
| 436 | n8n audit | Mode `none`: active jobs not on n8n. |
| 150 | n8n audit | Retired, not counted. |
| 116 | n8n audit | Lanes with an audit verdict (see below). |

Check: 81 + 31 + 23 + 436 + 150 = 721.

The 116 audited lanes are 81 live + 31 both + 1 dry + 3 lanes not in the registry (`market-event-outcomes`,
`market-reference-bars`, `oauth_lane_keepalive`). The verdicts are 43 PASS (31 PASS and 12 PASS_IDLE), 9 FAIL and
64 UNVERIFIABLE. The other 22 dry lanes have no verdict. In all, 586 registry jobs have none: 436 active non-n8n
jobs plus 150 retired.

The mismatch the operator saw has three causes: the two pages count different sets (all jobs against n8n-handled
lanes), 721 includes 150 retired jobs, and 116 includes lanes outside the registry.

## Wording trap, not fixed here

The approved audit header says "Each of the 116 n8n-only lanes was checked". That is wrong. 116 includes 31 cron
twins and 3 lanes outside the registry, so about 82 are n8n alone. The header text belongs to the approved view,
so this change leaves it alone and reports it.

## Proof

Playwright at 412 and 1440 against the vite dev server proxied to the live API. The header paragraph, the sub line
and the six tiles (43 / 116, 9, 64, 31, 23, 436) read from the shadow root are identical on both pages and both
widths, with no horizontal scroll. Screenshots are in `inbox/claude-lead/LQ-506-evidence/`.

Tests: `src/lib/jobCatalogAudit.test.ts` (badge states) and `src/lib/navConfig.test.ts` (the new entry and its
locate). `navConfig.test.ts` also has one failure, "route /* is reachable from the menu unlocated", which fails on
the base release as well.
