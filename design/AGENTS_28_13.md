<!-- Proposed text for AGENTS.md §28.13, to be inserted by the next AGENTS.md amendment (20.4.0) — this PR does not
     edit AGENTS.md. Operator approval of the workflow: 2026-10-25, "I approve the design workflow. Develop and ship it.
     Also, make sure that it's referenced in the agents.md". -->

## 28.13 Design lifecycle (20.4.0)

**Status: PROPOSED (MINOR) with the 20.4.0 amendment.** Workflow approved by the operator 2026-10-25 ("I approve the
design workflow. Develop and ship it."). It adds the restrictions below and removes none; it does not touch §0, §2,
§17 or role authority. Details: `design/README.md`.

- **One home per page design.** Every Command Center page is in `design/registry.json` with its approved, current and
  baseline version; `design/pages/<page>/versions/vNNN/` holds `SPEC.md` (what changes, what stays, every removal,
  hide or move) and `status.json` (state, approval, fingerprints). Lifecycle: DRAFT → PROPOSED → APPROVED →
  IMPLEMENTING → VERIFIED → CURRENT (REJECTED, SUPERSEDED). An approved version is never edited; a change is a new
  version. *Cause (§20): the 10-24 approvals of the 22 desk boards, TradeInView and Watch row existed only in handoff
  prose; Approvals showed 0 decisions and nothing recorded a page's approved version.*
- **Only the operator approves a design, and only in the ledger.** A version becomes APPROVED or REJECTED only by the
  operator's one-tap decision in Approvals → Designs, recorded in the operator decisions ledger with the authenticated
  identity, the time, the version and its fingerprint. Prose in a handoff, chat or PR never counts (v001, back-filled
  from the 10-24 handoffs, is the one exception). Agents may propose and read; a decision request from an agent is
  refused.
- **Build only the approved version, and cite it.** A PR that changes UI under `apps/command-center-v3/src` carries
  `Design: <page>/vNNN` (APPROVED or IMPLEMENTING) or `Design: none` (no visible layout change). The build contains
  only what that version shows; if the approved design proves wrong, stop and propose a new version. *Cause (§20):
  Board 19's "Decided recently" panel was approved 10-24 and never built, and nothing could tell.*
- **No unlisted removal or hide.** A nav item, route, tab, panel or widget that disappears, or moves behind a tap, must
  be listed in the cited version's SPEC; the removal guard fails the PR otherwise (this makes §28.9 change control
  mechanical). *Cause (§20): TradeInView hid Calendar and Replay on 10-24 without an approved mockup.*
- **Phone first, measured.** At 412 and 390 px: fixed or sticky chrome together ≤ 15% of the viewport height, tap
  targets ≥ 44 × 44 px, no sideways page scroll, no raw ISO timestamps, no empty bullets; list → full-screen sheet with
  ← Back. Checked on fixtures in every UI PR and on the live site after each release. *Cause (§20): the phone metric
  strip and Ask bar stayed fixed and pages scrolled under them; no check measured it.*
- **Logged-in pages are checked too.** Post-release and nightly live checks include pages that need sign-in, through
  the read-only agent reader identity that can never approve or change anything, under §28.8 (never 04:00–16:15 ET
  Mon–Fri; one page at a time; portfolio-server memory checked first). *Cause (§20): Rulebook and Approvals were never
  opened by an agent, so "Rulebook unavailable" went unseen.*
- **Design assets that show real data never enter the public repo.** `PatsKiller/tardeai` is public: mockups, live
  screenshots, handoff specs and evidence images stay in the private store
  (`persistent-state/data/design/pages/<page>/`), referenced from `status.json` by relative path and sha256 only;
  committed SPEC text carries no portfolio values, holdings, positions, account names or numbers, P/L or real tickers
  tied to the operator's holdings. Only fixture-data baselines that pass the privacy scan may be committed. The
  operator views private images through the authenticated Approvals reader.
