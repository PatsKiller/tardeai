# Wealth site — FUNCTIONALITY MAP (reference v02 → real capability)

Reference: `docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v02.html`, sha256 `23f96d84199c5a7cabb3837a7bd94fab87d68eed15d3d5bbfb5d07e6f8dde7aa`.
Its anchors are the hash routes `#group/tab` built from its `groups` table: **56 views** in 9 groups, 6 drawers and the shell.
Machine-readable twin: `docs/wealth/functionality-register.json`. Keep both in step; the JSON is what checks read.
Preview (fictional data, banner): `https://ms01-openclaw.tail163d14.ts.net/wealth/design-reference/index.html`.

## Rules (operator 2026-11-14)
- v02 is the implementation SPECIFICATION. Port its structure, tokens, type, spacing, charts, responsive layout, nav, drawers and valuation cues. Replace ONLY its fictional data with canonical read-model data.
- One row per page, tab, drawer and action. The owner edits the new code AND this row. The reviewer is never the author.
- Status is one of **VERIFIED_WORKING / EXISTS_UNVERIFIED / PARTIAL / MISSING / NOT_APPLICABLE**.
  - `UNMAPPED` means the owner has not done the first pass yet. It is not a status anyone may ship on.
- Existing code is not proof. VERIFIED_WORKING needs evidence from the **served** route: a request plus its response fields, or a screenshot path, taken at a stated ET time.
- No fake buttons. No silent empty success. No generic "NEEDS BACKEND".
  - A gap names the exact adapter or backend change and who owns it.
  - Unknown renders as unknown, with its age.
- Every row states the contract: canonical account id, security id, session label, metric meaning, source clock, and coverage behaviour.
- Actions:
  - Wire only existing supported actions.
  - Financial approvals and auth are preserved.
  - No order, provider or approval action is ever exercised to "test" a row.
- Source annotations go at component and adapter boundaries only: metric semantics, provenance, clock and coverage behaviour, action constraints.
- A slice is "implemented" only after:
  - reference-vs-build screenshots at 1440 and 390 px;
  - real tab and drawer interaction checks;
  - a release on /wealth/;
  - +15/+30/+60 checks.

## Columns
anchor · owner/reviewer · status · existing route · endpoint/reader/producer · contract (account/security/session/metric/clock) · observed working · evidence · gaps → adapter/backend · next step

`candidate readers` were seeded by the lead from the scaffold registry. They are hints only, not evidence.


## Home

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#home/today` | Investment desk | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/overview, /api/v2/home/do-now, /api/v2/home/priorities-live, /api/v2/home/cio-card |  |  |  |
| `#home/outlook` | Market outlook | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/market-risk/latest, /api/v2/morning-brief (no directional-outlook reader: LQ-946) |  |  |  |
| `#home/needs` | Needs your review | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/needs-action, /api/v2/home/do-now |  |  |  |

## Portfolio

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#portfolio/holdings` | Holdings | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/portfolio/holdings, /api/v2/portfolio/book-map, /api/v2/tax-lots |  |  |  |
| `#portfolio/performance` | Performance | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/portfolio/performance |  |  |  |
| `#portfolio/income` | Income | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/income-dashboard, /api/v2/dividends |  |  |  |
| `#portfolio/allocation` | Allocation | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/portfolio/book-map |  |  |  |
| `#portfolio/retirement` | Retirement | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/retirement |  |  |  |
| `#portfolio/fundamentals` | Fundamentals | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/symbol-cards |  |  |  |
| `#portfolio/levels` | Levels & valuation | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | valuation-assessment@1 (no backend yet, -8), /api/v2/symbol-cards |  |  |  |

## Risk & defense

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#protection/exposure` | Risk exposure | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/risk, /api/v2/market-risk/latest |  |  |  |
| `#protection/coverage` | Stop coverage | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/risk/protection-truth |  |  |  |
| `#protection/defense` | Defense plan | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/defense/posture |  |  |  |
| `#protection/hedges` | Hedge alternatives | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/defense/posture |  |  |  |
| `#protection/scenarios` | Stress scenarios | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/risk |  |  |  |
| `#protection/review-log` | Review history | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |

## Watch

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#watch/overview` | Overview | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED | /api/v3/watch/ |  |  |  |
| `#watch/my-list` | My List | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED | /api/v3/watch/ |  |  |  |
| `#watch/suggestions` | Suggestions | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED | /api/v3/opportunities |  |  |  |
| `#watch/prospects` | Prospects | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED | /api/v3/opportunities |  |  |  |
| `#watch/setups` | Setups | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED |  |  |  |  |
| `#watch/sectors` | Sectors | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED |  |  |  |  |
| `#watch/discover` | Discover | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED |  |  |  |  |
| `#watch/alerts` | Alerts | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED | /api/v2/watch/alerts/list |  |  |  |
| `#watch/pullbacks` | Pullbacks | cc-deepseek-5 → cc-deepseek-7 | UNMAPPED |  |  |  |  |

## Reposition

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#reposition/rotation` | Defensive rotation | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/rotation/summary |  |  |  |
| `#reposition/reentry` | Re-entry | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/recovery, /api/v2/reentry/decision-desk |  |  |  |
| `#reposition/exits` | Exit reviews | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/recovery |  |  |  |
| `#reposition/capital` | Capital book | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |
| `#reposition/comparison` | Plan comparison | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |
| `#reposition/plan-lab` | Plan lab | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |
| `#reposition/event` | Market events | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |

## Trade

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#trade/desk` | Trade desk | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/strategy-desk |  |  |  |
| `#trade/active` | Active positions | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `#trade/options` | Options | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `#trade/strategies` | Strategies | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `#trade/journal` | Journal | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/journal |  |  |  |

## CIO & research

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#intel/desk` | CIO desk | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED | /api/v3/cio |  |  |  |
| `#intel/questions` | My questions | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/research` | Research | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/company-files` | Company files | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/reports` | Reports | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED | /api/v2/reports/list |  |  |  |
| `#intel/communications` | Investment alerts | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/history` | Decision history | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED | /api/v3/watch/cio/history |  |  |  |

## Operations

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#ops/health` | Readiness | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED | /api/v2/system/platform-health |  |  |  |
| `#ops/jobs` | Jobs & schedules | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/data` | Data quality | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/incidents` | Incidents | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED | /api/v2/home/incidents |  |  |  |
| `#ops/releases` | Releases | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/agents` | Agents & resources | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/memory` | Memory integrity | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/delivery` | Delivery audit | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |

## Design review

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#review/guide` | Review guide | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |
| `#review/site-map` | Whole-site plan | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |
| `#review/backend` | Backend contract | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |
| `#review/coverage` | Approval register | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |

## Drawers

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `openDrawer('memory')` | memory | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `openDrawer('question')` | question | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `openDrawer('alert')` | alert | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `openDrawer('phone')` | phone | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review tool |  |  |
| `openDrawer('guide')` | guide | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review tool |  |  |
| `openDrawer('feedback')` | feedback | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review tool |  |  |

## Shell (cc-opus-3)

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `main nav (9 groups, tabs)` | main nav (9 groups, tabs) | cc-opus-3 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `account scope selector (all / per account)` | account scope selector (all / per account) | cc-opus-3 → cc-deepseek-3 | UNMAPPED | /api/v2/overview |  |  |  |
| `header account value` | header account value | cc-opus-3 → cc-deepseek-3 | UNMAPPED | /api/v2/overview |  |  |  |
| `header regular-session move` | header regular-session move | cc-opus-3 → cc-deepseek-3 | UNMAPPED | /api/v2/overview |  |  |  |
| `mobile menu + phone layout` | mobile menu + phone layout | cc-opus-3 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `drawer/overlay system` | drawer/overlay system | cc-opus-3 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `security detail drawer` | security detail drawer | cc-opus-3 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `valuation cues (colour+bold/italic+text+icon+tooltip)` | valuation cues (colour+bold/italic+text+icon+tooltip) | cc-opus-3 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
