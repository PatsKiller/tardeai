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
    versions/vNNN/
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
| APPROVED / REJECTED | the operator only — one tap in Approvals → Designs | A decision row in the operator decisions ledger (`data/governance/operator_decisions.jsonl`): authenticated operator identity, time, page, version and its fingerprint. Prose in a handoff never counts again (v001 is the one back-filled exception). Agents are refused. |
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
| Fixture visual compare at 1440 / 412 / 390 (sample data only) | PRs touching UI | report-only for the first week, then merge |
| Phone layout rules: fixed-bar height, tap size, sideways scroll, raw timestamps, empty bullets | every UI PR (fixtures); after release (live, private) | merge (ratchet) / alert |
| Live drift against the private baselines, logged-in pages via the read-only agent reader | after release, nightly (host only) | alert + fix task |
