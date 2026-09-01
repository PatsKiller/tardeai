# Operator UX — the private investment office home (`/v3/cio`)

Status:      ACTIVE
as_of:       2026-08-13T19:58:47-04:00
Measured at: efcc51365 / not measured

This is the contract Alex (CIO) upholds when the operator opens the office. It
is written from the operator's point of view, not the engineer's.

## The one rule that matters

The operator should see **the decision, then the evidence** — never the other way
around. A $5M-a-year advisor does not make the client read a data dictionary to
find out what to do today.

## Landing

`/v3/cio` opens on **CIO NOW**. Above the fold there are at most five cards. Each
card is one thing the operator may need to act on, stated in dollars first:

> **SCHD · Trim** — Act now
> Dollar change **$0** · Position value **$212K** · Weight **16.5%**
> **Why now:** Advisory TRIM — SCHD (concentration > cap)
> `Why? · evidence` · `ACK` `DEFER` `DONE` `REJECT` `RATE`

Nothing above the fold mentions a model, a prompt, or an internal run ID.

## The six sections

| Section | What the operator sees |
| --- | --- |
| CIO NOW | decisions with dollars, why-now, urgency, next review, evidence, and operator actions |
| CAPITAL PLAN | total / reserved / investable cash, target band, recommended deploy/raise, sources & uses, resulting cash |
| PORTFOLIO POSTURE | thesis, concentration, risk heat, sector tilts, performance vs benchmark, income, tax issues, constraints |
| OPPORTUNITIES | watch candidates, re-entry, rotation ideas, research gaps, each with readiness |
| REPORT | the latest institutional report (embedded) and Generate Now |
| EVIDENCE / AUDIT | source refs, timestamps, provenance, validator states, run IDs, internal codes |

## Labeling rules

- Plain English. `above policy band`, not `ABOVE_BAND`. `Trim`, not `S3`.
- Dollars before percentages whenever a dollar amount is the actionable figure.
- No snake_case in a primary view. Internal codes live only in EVIDENCE / AUDIT.

## Confidence and evidence state

- **Stale / missing** evidence is muted grey/amber and labeled "unavailable" or
  "not generated yet". It is visually distinct from **negative** judgment.
- **Red** means a negative investment judgment (a loss, a trim, a breach) — never
  "we do not have this number".
- The report iframe and its "generated at" stamp appear only after a real fetch.
  The UI never implies a model ran when it did not.

## Operator actions

`ACK / DEFER / DONE / REJECT / RATE` are durable and advisory-only. They record
the operator's disposition (and optional 1–5 usefulness rating) so later
decisions honor them. They never place an order, move a stop, or touch 2FA.

## Responsive and accessible

One design serves desktop, tablet, and phone. Every control is a real button or
tab reachable by keyboard. Tooltips explain unfamiliar financial metrics
(hover/title). No horizontal scrolling at any width.

## Where the deep-dive lives

Specialist workspaces (Advisory Desk, Hermes, Rotation, Watch, Reports) remain
available and are linked from EVIDENCE / AUDIT and REPORT. They are not the front
door — the front door is the decision.
