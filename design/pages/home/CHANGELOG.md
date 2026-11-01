# Home — changelog

- 2026-10-27 OPERATOR-DIRECTED REMOVAL (no mockup required; the operator directed it): "Remove everything about the
  old train from the AGENTS.md, and from the Command Center and from the code." Changes on Home (`/v3/`, Do-now layout
  `HomeDoNow.tsx`; classic view `HomeHub.tsx`):
  - Removed: the release-train summary source (`/api/v2/coordination/release-train`), the "Deploy on main" drawer
    (`home-drawer-release`) and its "Deploy hold…" shortcut, the `DeployHoldStrip` / `ReleaseTrainCard` components.
  - Renamed / replaced: the System pulse tile "Deploy hold" is now **Deploys** — one status line from
    `GET /api/v2/ops/deploys` (latest `DeployOnMainReceipt@v1` outcome + main SHA, and the deploy STOP latch).
  - Kept (renamed): the STOP control. The drawer is now **Deploys** (`home-drawer-deploys`) with the shortcut
    **STOP deploys…** (`home-deploys-stop-shortcut`); the drawer body is `DeploysPanel` (latest + last five receipts,
    the set-only **STOP DEPLOYS** control, links to Ops → Controls, Releases & schedules and the Mergify dashboard).
  - Phone (412 / 390): the drawer still opens a full-screen sheet with ← Back; checked in
    `apps/command-center-v3/e2e/deploys-train-removal.spec.ts` and `e2e/home-do-now.spec.ts` at 1440 / 412 / 390.

- 2026-10-31 PROPOSED v002 (design DSN-20261031-market-risk-ui; engine DSN-20261031-market-risk-engine P3-T2): header fact
  "Market" → "MARKET RISK" (tier, score, top contributor); Orange/Red banner with Acknowledge above the header; "Market in
  one look" gains the five contributors and takes the old regime/VIX/sectors text; classic hero tile "REGIME" → "MARKET
  RISK". Awaiting the operator's tap in Approvals → Designs. Mockups (synthetic) in the private design store.

- 2026-11-01 PROPOSED v004 (builds on v002; v003 is PR #2394): a YELLOW market-risk summary card in the v002 banner slot.
  Calm warning tone (card surface with a warning left rule, soft pill, no tone fill), collapsed by default on phone and
  expanded on desktop; shows the contributor lines, "Your book", "De-escalates if", the SHADOW label in shadow mode, and
  Open Risk / Review stops as links. No Acknowledge (YELLOW never pages). ORANGE/RED keep the v002 banner; not-evaluated
  and GREEN/BLUE unchanged; stale shows the stale line instead of numbers. Nothing removed. Mockup only, awaiting the
  operator's decision in Approvals → Designs; mockups in the private design store.

- 2026-11-01 APPROVED v004. The operator, verbatim: "I approve the markups implement". Recorded from the message under
  AGENTS.md §20 (as for v002). Build follows in a PR stacked on this one, citing `Design: home/v004`.

- 2026-11-01 PROPOSED v005 (builds on v004; same slot): an actionable market-risk card for YELLOW, and the same
  sections extending the ORANGE/RED banner. Adds a plain verdict line with the shock type and "your exposure" in dollars;
  a sector table (1d/5d vs SPY, your dollars and share of book, look-through, UNKNOWN groups you hold flagged); your
  positions in stressed groups ranked by dollars exposed (account, value, % of account, stressed share, stop distance,
  stance); budget breaches with account labels and dollars; a "Review now" list of 1–5 prompts ranked by dollars at risk
  linking to the existing Review / stop review; "Since you were stopped out" with Stage 1 (early setup) / Stage 2
  (confirmed) re-entry status, invalidation level, wash-sale end date and earnings warning; a segment split for
  multi-segment issuers from a new operator-owned `config/issuer_segments.json`. Moves the contributor lines to "Why the
  score is N". Collapsed on phone to the verdict, exposure and the top review item. No size, order or stop level anywhere.
  Mockup only, awaiting the operator's decision in Approvals → Designs; mockups in the private design store.

- 2026-11-01 APPROVED v005. The operator, verbatim: "Are you approved? Homepage version 005." Recorded from the message
  under AGENTS.md §20 (as for v002 and v004). With his correction from the broker screenshot: a symbol re-bought in the
  same account after a stop-out is a holding there, not an exit, and shows "wash sale occurred, loss deferred" instead of
  a forward warning. Build follows in a PR stacked on this one, citing `Design: home/v005`.
