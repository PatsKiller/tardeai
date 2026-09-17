Status: ACTIVE
as_of: 2026-09-17T10:13Z
Measured at: Google Drive folder listing + Gmail thread `1a0ac4140b169fa6` + `gh pr view` `[VERIFIED]`
Canonical repo path: docs/architecture/maturity_reconciliation_20260917/REVISION_LEDGER_2026-09-17-rev8.md
Authority: supersession record and operator-action proposal. READ_ONLY_ADVISORY, `MBI_BEHAVIOR=0`. Nothing here was deleted, uploaded or emailed.
Revision: 8
See also: docs/architecture/maturity_reconciliation_20260917/CIO_AS_IS_2026-09-17-rev8.md
 docs/architecture/maturity_reconciliation_20260917/HONEST_MATURITY_ASSESSMENT_2026-09-17-rev8.md

# Revision ledger — which revision is canonical, and what is still published

## 1 · Why this is Revision 8

The number 8 was chosen because **6 and 7 are both already taken, in different
ways**:

- **Revision 6** exists *twice* on Google Drive — two folders with the identical
  title, one of them empty (§3).
- **Revision 7** was **declared canonical by email while unmerged**. The email
  went out `2026-09-16T22:05:52Z` with the subject *"Trade AI Maturity Gap
  Closure — Revision 7 (Telegram four-channel curation) — supersedes Rev 6 +
  thinner priors"* and the body *"This package supersedes Revision 6"*. Its
  source **PR #1055 is OPEN and CONFLICTING** as of `2026-09-17T10:13Z`, last
  updated `2026-09-16T22:11:07Z`, branch `docs/telegram-maturity-rev7-20260916`.
  The four documents it adds under
  `docs/architecture/maturity_gap_closure_20260916/` **do not exist on `main`**.

Reusing 6 would collide; reusing 7 would overwrite a package that was already
distributed to a reader. **8 collides with nothing.**

## 2 · Supersession map

| Revision | Where it lives | Status after this document |
|---|---|---|
| Rev 4 | Drive `Word_Docs_2026-09-16_0930EDT_rev4` (`18QuO7uWfki3_cQwf-VvyUZrVPtyhgRXp`, created `2026-09-16T13:22:38Z`) | **superseded — still published** |
| Rev 5 | Drive `Word_Docs_2026-09-16_1332ET_rev5` (`1AbkMARNZEGm6kgZqtXAFsji6Ax9V63a-`, created `2026-09-16T17:32:54Z`) | **superseded — still published** |
| Rev 6 (copy A) | Drive `Word_Docs_2026-09-16_1719ET_rev6` (`1st1m_v96JXpFexVgtfAT6vmpv1yreh6R`) — 14 `.docx` + `PDF_copies/` (14 PDFs) | **superseded — still published** |
| Rev 6 (copy B) | Drive `Word_Docs_2026-09-16_1719ET_rev6` (`1y5lMI_GsGFkIukq7B1iUAcjdyUdxVILj`) — **empty** | **superseded — still published, and removable (§3)** |
| Rev 7 | Drive: 4 `.md` loose in `architecture/`; repo: PR #1055 branch only; email thread `1a0ac4140b169fa6` | **superseded in its figures — still published, still unmerged** |
| **Rev 8** | this directory, `docs/architecture/maturity_reconciliation_20260917/` | **canonical for the figures it carries** |

**What Revision 8 supersedes:** the release, gate, goal-loop, intake and script-census
figures in Revisions 4–7.

**What it does NOT supersede:** Revision 7's *Telegram four-channel* subject
matter — the corpus measurements (DM 1,456 texts / 22.7 % → 2.4 %, CIO Desk 194 /
0 %, Proposal Decisions 181 / 72 %, OpenClaw 24 / 0 %) were measured against a
chat export this document did not re-parse. Those stand until re-exported. Rev 8
replaces only the figures it re-measured.

**Superseded but still published — nothing was removed.** Every artifact above
remains exactly where it is. Per AGENTS.md §0 rule 6 ("Never delete") and §17
("deleting anything" is operator-only), this document proposes and stops.

### Revision 7's stale figures, corrected

| Rev 7 claimed | Measured 2026-09-17 |
|---|---|
| served pin `61d67f635` | **`ede0698a5`** |
| `origin/main` `03b8ce9e7` | **`ede0698a5`** |
| "origin/main is one merge ahead of the served pin" | **they are equal** |
| guardian goal `wake_count = 0` | **1** |
| "`GOAL_STATUS_CHANGED` 0 over 37 days / 34,718 wakes" | still **0**, now over **34,912** wakes |

Revision 7 was not careless about this — its own closing section says
*"`GOAL_STATUS_CHANGED` — re-read before quoting; it was 0 at stamp"* and
*"'Merged' ≠ 'served'"*. It was overtaken by nine hours of merges and two
promotions. **That is the argument for not declaring a revision canonical until
its PR is merged.**

## 3 · ⚠ Two Google Drive folders share one name

Both live in Drive folder `architecture`
(`14XqtuJbfR0sO6Fc4aki4SZQm6-0JFc1H`), owned by john@jwwhiting.com:

| Folder id | Title | Created | Contents |
|---|---|---|---|
| `1y5lMI_GsGFkIukq7B1iUAcjdyUdxVILj` | `Word_Docs_2026-09-16_1719ET_rev6` | `2026-09-16T21:21:41.940Z` | **ZERO files** |
| `1st1m_v96JXpFexVgtfAT6vmpv1yreh6R` | `Word_Docs_2026-09-16_1719ET_rev6` | `2026-09-16T21:22:35.194Z` | **14 `.docx`** + `PDF_copies/` (14 PDFs) |

They were created **53 seconds apart** — the signature of a sync run that
created the destination folder, failed or was retried, and created it again.

**A reader cannot tell which "rev 6" is authoritative from the name alone.** One
opens to fourteen documents; the other opens to nothing, which reads as "the rev 6
package is empty" rather than "you opened the wrong identical folder".

**Proposed operator action (§17 — NOT performed):** trash the **empty** folder
`1y5lMI_GsGFkIukq7B1iUAcjdyUdxVILj`, keeping `1st1m_v96JXpFexVgtfAT6vmpv1yreh6R`
which holds the files. Deleting anything is operator-only; an agent must not do
this, and this agent did not. The empty folder holds no content, so removing it
destroys nothing — but the decision is still the operator's.

## 4 · Operator-only actions this reconciliation surfaced (§17 — propose and stop)

| # | Action | Why it is operator-only | Evidence |
|---|---|---|---|
| 1 | Trash empty Drive folder `1y5lMI_…` | "deleting anything" (§17); §0 rule 6 | §3 above |
| 2 | Add `--update-catalog` to the `:35` cron line | "any new production cron or systemd entry" — a crontab line edit is also a lane-registry edit | `config/agent_maturity_catalog.json` has **0** gate ids |
| 3 | Add `--write-measurements` to the `:35` cron line | same | lane `goal-gate-bridge` is **SILENT**; its `output_signal` file has never been written |
| 4 | Give lane `dormant-lane-consumers` a real `output_signal`, or correct its declared one | scheduler/registry change | the script never writes `data/cio/dormant_lane_consumers.jsonl` |
| 5 | Correct the stale `ACTIVE_RELEASE` marker | release-state file feeding a convergence check | reads `890e3aef feature/advisory-desk-v1 20260811-094957`; `CURRENT` = `ede0698a5` |
| 6 | Resolve PR #1055 and decide rev 7's disposition | merge/publication decision | OPEN · CONFLICTING (**another agent is resolving this; not touched here**) |
| 7 | Merge PR #1059, then `set_goal_predicate.py --apply` on a live goal | `--apply` on a live goal is operator-gated | `GOAL_PREDICATE_SET` = 0 against 34,912 wakes |
| 8 | Decide whether Revision 8 is published (DOCX / PDF / Drive / email) | publication decision | **this package is markdown-only, committed locally, not pushed** |
| 9 | Address the intake backlog | operational | 322 queued, oldest `2026-09-09`; 2,277 failed; 4,277 refused_stale |

## 5 · What this agent did and did not do

**Did:** measured the live system; wrote three markdown documents; committed
them locally to an isolated worktree.

**Did not:** render DOCX or PDF · upload anything to Drive · send any email ·
push any branch · delete anything · touch the `#1055` branch · change any cron,
systemd unit or config · run anything with `--apply`.

`MBI_BEHAVIOR=0`, advisory only. No broker, sizing, order or stop path was
touched or read for decision purposes.
