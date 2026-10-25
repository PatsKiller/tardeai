# Approvals UI — boards 19–21, 2026-10-24

Source is built on W5 DeskPage commit
`69c92ae34d860d45e2ff2f0d11178fb77678f848`. W5 retains App/Nav ownership;
W11 changes neither shared file. Default exports take no props:
`src/pages/ApprovalsHub.tsx` handles `/approvals` and `/approvals/:id`;
`src/pages/PolicyHub.tsx` handles `/policy`. Requested rail labels are
“Approvals” and “Rulebook”, in Ops next to Ops Controls.

## Approved board trace

| Board | Implementation | Source |
|---|---|---|
| 19 queue | URL filters, server paging, type/what/proposer/waiting, Read & decide, recent decisions, history, notification gap | `/api/v2/governance/approvals`; null clocks/counts remain unknown |
| 20 reader | Whole route on a phone; Back; changes-only, actual inline whole-document highlights, side by side, changed-section TOC, search | One item’s exact document, diff offsets and SHA from the W11 API |
| 20 reading | Explicit Start reading; full-card IntersectionObserver plus visibility checks; three-second server-attested enter/read sequence | Server review nonce, exact document SHA, per-change markers; changed document resets progress |
| 20 decision | Disabled Approve until all changes read; Request changes / Reject; visible result/error; selected wording comments | Operator-only API; recorded actor/version/time; existing control handoff for grants/activations/trades/conflicts |
| 20 question | Ask the CIO with section text and both source/document hashes | Existing `/api/v2/cio/ask` only on operator action |
| 21 rules | Whole committed rulebook, section paging, tap-accessible explanations, evidence statuses, positions and proposal feedback | `/api/v2/governance/policy`; missing explanations/evidence stay explicit |
| 21 response | Full-screen phone response with Back, focus, Escape/Tab handling and URL state; browser Back closes it | `?rule=...&respond=...`; disagreement becomes a proposal, question uses existing Ask CIO |
| 21 audit | Partial coverage, latest findings, last measured audit and existing job controls | Exact-document/implementation-bound audit evidence, never a claim that a test filename proves enforcement |

All new colors, radii and shadows use the existing tokens. Controls are at least
44px high; queue tables become cards at 820px, primary actions span the card,
and side-by-side text stacks on a phone. No list selection places its detail
below the queue. Exact hashes appear in expandable version details.

## Validation and unresolved proof

The repository frontend build passes after replacing unsupported `replaceAll`
calls with the supported regex form and converting radius/shadow values to
tokens. The first typecheck was reported prematurely while it was still running;
the completed build is the verification authority.

The Playwright fixture mounts the actual components with every HTTP request
intercepted at `http://w11-approvals-fixture.test`. It refuses all other origins
and all unrecognized endpoints; it cannot use the live server. Tests at 412×915,
390×844 and 1440×1100 tap filters/open/back/read/approve/governed handoff/rule
disagreement/question; they assert viewport bounds and capture source hashes.

**Browser proof is blocked, not passed.** Chromium exited before any page loaded
with `sandbox_host_linux.cc: shutdown: Operation not permitted`. No screenshot
or mobile runtime claim is made, and no alternate flags or retry bypass were
used. The coordinator/operator must run the exact offline browser command
prepared in the W11 handoff cache. It writes `impl-19-*`, `impl-20-*`,
`impl-21-*` shots beside the approved mockups and independent viewport JSON.
Publication of this UI tranche must wait for that proof and the W5 dependency.

No live API, approval, grant, activation, model call, push, merge-to-main or
release was performed. Pending data-source/backup/model/event admissions are
separate operator decisions; build authorization pre-decides none of them.
