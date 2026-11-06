# Trade AI design workflow

Operator-approved 2026-10-25 ("I approve the design workflow. Develop and ship it."). Binding rule: AGENTS.md §28.13
"Design lifecycle" (text proposed in `design/AGENTS_28_13.md`). This folder is the one home for every page's design:
the approved version, its history, the rules for desktop and phone, and what the automatic checks compare against.

## Privacy rule (public repository)

`PatsKiller/tardeai` is public. Nothing that shows the operator's real financial data is ever committed here:
no portfolio values, holdings, positions, account names or numbers, P/L, or real tickers tied to the operator's holdings.
That covers mockups (they were drawn over real data), live screenshots and handoff prose.

| Lives in the repo (`design/`) | Lives only on the host (private store) |
|---|---|
| This workflow, `system/tokens.json`, `components.md`, `breakpoints.md` | Mockups (`*.dc.html`, `mockup-*.png`) |
| `registry.json`, each page's `PAGE.md`, `CHANGELOG.md` | Original handoff specs and findings |
| `versions/vNNN/status.json` (state, approval, sha256 fingerprints) | Live screenshots (v000 capture, baselines) |
| `versions/vNNN/SPEC.md` — text only, no real numbers | Implementation evidence screenshots |
| Fixture baselines (sample data only, scanned before commit) | |

Private store: `~/trade-ai-releases/persistent-state/data/design/pages/<page-id>/` with `vNNN/` (mockups, spec,
evidence) and `baselines/` (live screenshots). `status.json` names each private file by its path relative to that
folder plus its sha256; `python3 scripts/check_design_registry.py --private-root <store>` proves on the host that every
fingerprint still matches. The operator sees private images through the authenticated Approvals → Designs reader;
agents read them on the host only. Never copy them into the repo, a PR, an issue, a gist or a chat.

## Layout

```
design/
  README.md              this workflow
  AGENTS_28_13.md        the §28.13 text for the next AGENTS.md amendment (AGENTS.md is not edited here)
  registry.json          every page: route, approved / current / baseline version, owner
  system/
    tokens.json          colours, type, spacing, radius, shadows — THE source
    components.md        buttons, chips, sheets, tables, cards, clocks, empty and gap states
    breakpoints.md       desktop / tablet / phone rules
  pages/<page-id>/
    PAGE.md              purpose, route, data sources, owner, versions
    CHANGELOG.md         one line per version: date, version, state, what changed, approval ref
    versions/vNNN/       (vNNN.N marks a revision of an approved version, e.g. prospectus/v001.1)
      status.json        state, approval record, private asset fingerprints, PRs, verified date
      SPEC.md            what changes, what stays, every removal / hide / move (text only)
  proposals/<DSN-id>/    DRAFT work before it becomes a page version
```

`apps/command-center-v3/src/styles/tokens.css` is generated: `python3 scripts/gen_design_tokens.py` renders it from
`system/tokens.json`, and `--check` (run in CI) fails when the two differ. The app imports only the generated CSS.

## Versions

- **v000** — "as built": screenshots of every nav page and tab at 1440, 412 and 390, captured read-only from the live
  site into the private store (`scripts/design_capture.sh`). State `BASELINE`; it is a record, not an approval.
- **v001** — the operator's 10-24 approvals (22 desk boards, TradeInView, Watch row, site fix package), back-filled
  2026-10-25 from the handoff notes: state `APPROVED`, approval kind "recorded in handoff, back-filled 2026-10-25".
  The implementation of most v001 boards is not yet visually verified (`implementation.state = UNVERIFIED`).
- **v002, v003, …** — every later change. An approved version is never edited; a change is a new version.

## Lifecycle

`DRAFT → PROPOSED → APPROVED → IMPLEMENTING → VERIFIED → CURRENT`; side exits `REJECTED` and `SUPERSEDED`.

| State | Who moves it | What must exist |
|---|---|---|
| DRAFT | any agent | `design/proposals/<DSN-id>/SPEC.md` started |
| PROPOSED | the agent, when ready | Mockups at 1440, 412 and 390 built from the real tokens and saved in the private store; `versions/vNNN/status.json` with their fingerprints; SPEC lists every removal, hide or move. It then appears in Approvals → Designs. |
| APPROVED / REJECTED | the operator only — one tap in Approvals → Designs | A decision row in the operator decisions ledger (`data/governance/operator_decisions.jsonl`): authenticated operator identity, time, page, version and its fingerprint. Prose in a handoff never counts again. Two pre-ledger records are accepted as legacy: v001 (back-filled from the 10-24 handoffs) and any version created before 2026-11-05 whose approval names the operator's verbatim words or a relayed artifact approval; every version created on or after adoption must cite its ledger row. Agents are refused. |
| IMPLEMENTING | the building agent | The PR body carries `Design: <page>/vNNN`; agents build only what that version shows. |
| VERIFIED | automatic, after release | Live screenshots at all three widths match the approved mockups within tolerance; differences listed. |
| CURRENT | automatic | Baselines updated; the previous version becomes SUPERSEDED and stays readable. |

If an approved design proves wrong during the build, the agent stops and proposes a new version. It never "adjusts"
an approved design on its own.

## What an agent does for any UI change

1. Read `design/registry.json`, the page's `PAGE.md` and its approved / current version (`SPEC.md`, `status.json`).
2. If the operator will see the change: create `design/proposals/<DSN-id>/`, build mockups at 1440, 412 and 390
   from `system/tokens.json` (save them in the private store, never in the repo), write `SPEC.md` listing every
   removal, hide or move in the form `- <remove|hide|move|rename>: <kind> "<label>" — <why>`, add
   `versions/vNNN/status.json` with state `PROPOSED` and the fingerprints, and stop.
3. After the operator's approval (ledger row): build only that version, put `Design: <page>/vNNN` in the PR body,
   run the checks locally (`npm run build`, `python3 scripts/check_design_registry.py`, the design checks).
4. The train ships it; the post-release check marks it VERIFIED and CURRENT, or files the differences as a fix task.
5. A bug fix with no visible layout change cites `Design: none`; the visual compare confirms nothing moved.

## Rules (desktop and phone)

See `system/breakpoints.md` and `system/components.md`. In short: phone (≤ 820 px, build for 412 and 390) is one
column, the whole page scrolls and fixed bars take at most 15% of the screen height; list → tap → full-screen sheet
with ← Back; tap targets ≥ 44 × 44 px; no sideways page scroll; times in ET and readable; anything hidden behind a tap
counts as a hide and needs approval. Desktop (≥ 1280 px, build for 1440) is nav rail + content with the same data and
actions as phone. Colours, type and spacing only from the tokens; money through the house formatter; a gap shows as a
gap, never as 0.

## Automatic checks

| Check | When | Blocks |
|---|---|---|
| `scripts/gen_design_tokens.py --check` — generated CSS equals `tokens.json` | every PR | merge |
| `scripts/check_design_registry.py` — registry, status files, states, approval records, fingerprints, privacy scan | every PR | merge |
| Design reference: a PR that changes UI files under `apps/command-center-v3/src` cites `Design: <page>/vNNN` (APPROVED or IMPLEMENTING) or `Design: none` | every PR | merge |
| Removal guard: a nav item, route, tab or panel that disappears or is hidden must be listed in the cited version's SPEC | every PR | merge |
| Existing build gates: tokens, UI standards, contrast | every PR | merge |
| Fixture visual compare at 1440 / 412 / 390 (sample data only) | PRs touching UI | report-only until an operator sets the repository variable `VISUAL_BLOCKING=true`, then merge |
| Phone layout rules: fixed-bar height, tap size, sideways scroll, raw timestamps, empty bullets | every UI PR (fixtures); after release (live, private) | merge (ratchet) / alert |
| Live drift against the private baselines, logged-in pages via the read-only agent reader | after release, nightly (host only) | alert + fix task |

---

## Appendix: design rules moved from AGENTS.md (reference)

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
