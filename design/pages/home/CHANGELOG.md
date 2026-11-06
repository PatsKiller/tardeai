# Home — changelog

One line per version: date · version · state · what changed · approval ref.

- 2026-10-24 · v001 · APPROVED · Board 14 Home · operator "I approve the markups. Give it to Codex." (recorded in handoff, back-filled 2026-10-25)
- 2026-10-25 · v000 · BASELINE · as built: read-only live capture, 3 screenshots at 1440, 412, 390 · no approval (a record)

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

- 2026-11-01 PROPOSED v006 (builds on v005; same slot). The operator asked for it ("Yes, version 0.0.6") after this
  feedback on v005: "Does it show what's actionable? I don't see it showing what I should be getting into. To hedge
  against these risks."
  - Adds a **Protect / Hedge / Rotate** block under the verdict:
    - Protect: the top review items, each with a reason built from facts (stop distance, no stop, overnight session,
      account budget breach, same issuer across accounts, wash sale).
    - Hedge: a verdict from the Defense desk's inverse-hedge stoplight (NOT NOW / WATCH / CONSIDER / UNKNOWN) against
      the existing config thresholds, with a link to the Defense desk.
    - Rotate: the top 3 groups beating SPY on both 1 and 5 sessions, with the Defense-desk state and your dollars, and
      links to the Rotation desk and Best opportunities.
  - Adds a three-row digest on the collapsed card.
  - Adds a tap-to-explain (i) on every term, with texts in one config file.
  - Folds stressed or not-measured groups where you hold under $100 into one line.
  - Splits the chip into RESILIENT and HOLDING.
  - Labels a multi-segment issuer without approved weights "segment weights pending approval".
  - Moves "Review now" into Protect.
  - Specifies two engine fixes:
    - Communications and Real estate are UNKNOWN because the daily bars for the sector ETFs are missing.
    - The Defense posture's "waiting for a bounce day" line is a stale alert that contradicts the stoplight.

  No size, order, stop level or "buy" anywhere. Mockup only, awaiting the operator's decision in Approvals → Designs;
  mockups in the private design store.

- 2026-11-01 APPROVED v006. The operator, verbatim: "I approve version 6." Recorded from the message under AGENTS.md §20
  (as for v002, v004 and v005). Build follows in a PR stacked on this one, citing `Design: home/v006`.

- 2026-11-02 APPROVED v007 (builds on v006; same card). The operator, verbatim: "why don't you create the design? I approve the design. And you leave the design and markup for Codex. I like your markups better." Approved mockup (private store, never committed): `v007/mockups/HomeV007MarketRisk.html` sha256 afca9e47…, review link <https://claude.ai/artifact/4dG8NHVfxscDxR36q3L2cQ>. The operator asked for it — "look at everything else on the
  card that could be enhanced. Give the design to Codex to distribute out to agents and sub-agents. Also implement
  tooling tips where appropriate and make sure this is all mobile responsive." — after asking on the same card for
  "the current price points" and "the current catalyst".
  - **Mixed clocks made visible:** each section states its own as-of and source; a section older than its cadence is
    amber with its age, and never shows "now".
  - **Header context:** today's score trend (real points only), the delta and which categories moved, one plain-English
    "what this means for you" line, an Acknowledge tooltip that says exactly what it silences, and the next evaluation
    time.
  - **Every row gets a clock and a price:** current price + day change with its session label, plain-word stop status,
    distance to the stop in % and $, and why the row is listed. The account-% denominator is named (it appears twice on
    Home with different bases today).
  - **Hedge progress** bars toward each trigger, with the missing input named instead of a bar when the denominator is
    absent.
  - **Rotate + sectors:** what you hold in each group, trend arrow, tap-to-see held members, "not a buy list" as a
    tooltip.
  - **Since you were stopped out:** the "now = Friday's close" bug is fixed first and separately; the rows add price +
    session + time, since-exit $/%, distance to invalidation and Stage-2 triggers, guarded headlines, CIO stance with
    age, volume vs 20-day, and a since-exit sparkline marking the exit and the invalidation level.
  - **Stressed groups / budget breaches / multi-segment issuer:** day change and stop distance; a plain-English line
    per breach plus what clears it and an "intentional until <date>" operator record; citations behind the (i).
  - **Score breakdown:** all nine categories with OK / WARN / STRESS / not measured and their as-of, plain-English
    notes for odd-but-correct readings, and "De-escalates if" rewritten as live progress in words.
  - **Phone:** collapsible sections with a one-line collapsed summary, sticky section headers, stacked tables under
    600 px, 44 px targets, no horizontal page scroll at 412 or 390.

  No size, order or stop level anywhere. Build order: the stopped-out "now" bug first, then the data fields, then the UI per the approved mockup, then tests and phone screenshots at 412/390.
