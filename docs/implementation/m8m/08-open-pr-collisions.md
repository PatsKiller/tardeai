# 08 — Open PR collisions

Observed 2026-10-06 with `gh pr list` and `gh pr view 1417`. This branch does not cherry-pick any of them. #1460 is already the freeze pin (`65fbeecf`), category **SERVED**. It is not an open PR.

| PR | State | Head | Why it collides with later M8M work |
|---|---|---|---|
| #1417 | draft | `535aa3fb339b23f368471e353ef05651bbe75d63` | Touches `config/lane_registry.json`, `tests/test_cron_lanes_20261003.py`, `scripts/run_cio_hardening_ci.py`, `docs/INDEX.md`, `config/cio_known_dark_classification.json`, `docs/cio/CIO_KNOWN_DARK_CLASSIFICATION.md`. Lane disposition work must rebase onto this if it merges. This evidence pack does not edit those files. |
| #1378 | open | `16e4b061e279` | Telegram message contract. Do not add a sender beside it. |
| #1373 | open | `33612cc8d886` | CIO overview and Playwright. |
| #1352 | open | `69c0d14468cb` | Options arm revoke decision and a backup blocker note. Do not change the arm. |
| #1351 | open | `a9fc1d042b47` | Audit follow-up and release pin check. |
| #1350 | open | `ff911a4c350d` | Memory and whole-system audit. |
| #1330 | open | `883b2b0f4eea` | Adjudicator and re-measurement lanes. |
| #257 | draft | `130d961be8f5` | Schwab live-stop truth. Broker-adjacent. Left untouched. |
| #133 | open | `a3038bcdfb9c` | Health log autofix. |

#1456–#1459 were not in the open list. Preparation-time "open #1460" is stale.

`docs/INDEX.md` was not regenerated because the generator's write path is a tree-wide add and because #1417 already edits that file.

DOF: `gh` was not asked for a DOF pull-request list in this pass. Local DOF `master` matches `origin/master` at `5d3c39e` plus the dirty tree described in the baseline. No DOF PR was opened.
