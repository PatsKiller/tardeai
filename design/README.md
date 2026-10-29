# Readme

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 6296-6341 -->
## Moved from AGENTS.md (25.0.1 lines 6296-6341)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **1 One home per page design, every page versioned.** Every Command Center page is in `design/registry.json` with
  its approved, current and baseline version. `design/pages/<page>/versions/vNNN/` holds `SPEC.md` (what changes, what
  stays, and every removal, hide or move) and `status.json` (state, approval, fingerprints). `v000` is each page and
  tab as built on 2026-10-26, captured logged in and read-only at 1440, 412 and 390. `v001` is the operator's
  2026-10-24 approvals, back-filled. Later changes are `v002` onward. Lifecycle: DRAFT → PROPOSED → APPROVED →
  IMPLEMENTING → VERIFIED → CURRENT, or SUPERSEDED / REJECTED. An approved version is immutable: a change is a new
  version. *Cause (§20): the 10-24 approvals of the 22 desk boards, TradeInView and the Watch row existed only in
  handoff prose. Approvals showed 0 decisions, and nothing recorded a page's approved version.*
- **2 Only the operator approves a design, and only in the ledger.** A version becomes APPROVED or REJECTED only
  through the operator's one-tap decision in Approvals → Designs. The decision is recorded as a signed decision in the
  operator decisions ledger, with the authenticated identity, the time, the version and its fingerprint. Prose in a
  handoff, chat or PR never counts; v001, back-filled from the 10-24 handoffs, is the one exception. Agents may propose
  and read; a decision request from an agent is refused. *Cause (§20): the same 10-24 approvals; a decision recorded
  only in prose cannot be checked.*
- **3 Build only the approved version, and cite it.** A PR that changes UI under `apps/command-center-v3/src` carries
  `Design: <page>/vNNN` (APPROVED or IMPLEMENTING), or `Design: none` if it changes no visible layout. The build
  contains only what that version shows. An agent never adjusts an approved design; if the design proves wrong, the
  agent stops and proposes a new version. VERIFIED and CURRENT are set automatically after release. *Cause (§20): Board
  19's "Decided recently" panel was approved 10-24 and never built, and nothing could tell.*
- **4 No unlisted removal or hide.** If a nav item, route, tab, panel or widget disappears, or moves behind a tap, the
  cited version's SPEC must list it; otherwise the removal guard fails the PR. This makes §28.9 change control
  mechanical. *Cause (§20): TradeInView hid Calendar and Replay on 10-24 without an approved mockup.*
- **5 Phone first, measured; desktop the same.**
  - Phone (≤820 px, built for 412 and 390): one column, and the whole page scrolls. Fixed or sticky chrome together
    takes at most 15% of viewport height. A list opens a full-screen sheet with ← Back. Tap targets are at least
    44 × 44 px. No sideways page scroll. Times are readable ET, never raw ISO timestamps. No empty bullets.
  - Desktop (≥1280 px, built for 1440): the same data and actions, laid out wider.
  - Both use tokens only.
  - These rules are checked on fixtures in every UI PR, by a visual compare against the page's baseline at
    1440/412/390, and on the live site after each release.

  *Cause (§20): the phone metric strip and Ask bar stayed fixed and pages scrolled under them, and no check measured
  it.*
- **6 Logged-in pages are checked too.** The post-release and nightly live drift checks include pages that need
  sign-in. They use the read-only agent reader identity, which can never approve or change anything, and run under
  §28.8: never 04:00–16:15 ET Mon–Fri, one page at a time, with portfolio-server memory checked first. *Cause (§20):
  no agent ever opened Rulebook or Approvals, so "Rulebook unavailable" went unseen.*
- **7 Design assets that show real data never enter the public repo.** `PatsKiller/tardeai` is public.
  - Mockups, live screenshots, handoff specs and evidence images stay in the private store
    (`~/trade-ai-releases/persistent-state/data/design/pages/<page>/`). `status.json` references them by relative path
    and sha256 only.
  - Committed SPEC text carries no portfolio values, holdings, positions, account names or numbers, P/L, or real
    tickers tied to the operator's holdings.
  - Only fixture-data baselines that pass the privacy scan may be committed.

  *Cause (§20): the repository is public (§2A); real financial data is never committed.*
