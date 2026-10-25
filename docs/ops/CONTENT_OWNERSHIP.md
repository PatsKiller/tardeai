# Content ownership

**Status:** REVIEW CANDIDATE · fixture verification, not release evidence
**Updated:** 2026-10-25

Approved board 13, desks redesign of 2026-10-24. Each subject has one full
view. Other pages show a short summary and a link to that view.

| Content | Single home | Other surfaces | Implementation owner |
|---|---|---|---|
| Fund look-through: sectors, industries, themes, underlying stocks | [Portfolio → Look-through](/v3/portfolio?tab=Look-through) | Allocation keeps the sector bar and a link; Re-Entry links | W7 / W5 |
| Sector momentum and leaders | [Watch → Sectors](/v3/watch?tab=sectors) | Home summary; Defense link | W3 / W5 / W7 |
| Buy-ready and entry-near packets | [Re-Entry → Ready now](/v3/portfolio/re-entry) | Watch stage; alerts link | W5 |
| Rotation ideas and candidates | [Rotation](/v3/rotation) | Holdings flag and link; Re-Entry link | W6 / W5 |
| Questions and replies | Ask the CIO bar; [My questions](/v3/cio/questions) | Rotation links to the same bar | Ask workers / W6 |
| Trade AI scan | [Trading → Trade AI](/v3/trading?tab=Trade+AI) | Intelligence counts and link; header counts | W6 / W9 |
| Research topics | [Research Intel](/v3/research-intel) | Intelligence link | W6 / W9 |
| Discovery inbox | [Research Intel](/v3/research-intel) | Hermes link | W6 / W9 |
| Hermes identity and soul settings | [System → Hermes](/v3/system?tab=Hermes) | Hermes desk link | W6 |
| Backtests and paper readiness | [Strategy](/v3/strategy) | TradeInView classic link; Home/Trading readiness chip | W5 / TradeInView B |
| Agent memory, learning and calibration | [Agents](/v3/agents) | CIO and Health summary only | W5 / W7 / W9 |
| Research lineage and challenge queue | [Research lineage](/v3/closed-loop) | Intelligence link | W6 |
| Hermes outcome evaluations | [Hermes → Outcome loop](/v3/hermes?tab=outcome-loop) | No second Closed Loop desk | W6 |
| Per-security hold/add/trim/exit opinions | [Advisory Desk](/v3/advisory) | CIO Desk link | W6 / W7 |
| Idea-source performance | [Rec Intelligence](/v3/rec-intel) | TradeInView origin reads the same attribution | W6 / TradeInView A/B |
| Briefs, digests and analyst reports | [Reports](/v3/reports) | Home and Risk link | W6 / W7 |
| Hedges, inverse funds and protection ideas | [Defense](/v3/defense) | Trading Options link for lifecycle | W5 / W9 |
| Portfolio totals, stops, approvals, market regime and CIO status | `scripts.lib.cio_truth.resolve` | All pages format the same resolved values | W1 |
| Scheduled-job execution | [Jobs & health](/v3/ops/jobs) | Other operations pages embed the same projection | W4 |

W7's regression test checks the removal of its old Home metric tiles,
competing CIO status panels, duplicate capital source tables and the full
Allocation look-through panel. The browser fixture checks rendered ownership,
including the link from Allocation to Look-through. Changes in other owners'
files are verified with their handoffs; this table does not grant permission to
edit their claimed paths.

## Removals completed by desks A (boards 1–4), 2026-10-25

Each removal below is assigned to another home by board 13 and is listed in the PR notes. Detail and proof are in
`docs/ops/DESKS_A_REDESIGN_20261025.md`. `tests/test_desks_a_20261025.py::test_board13_duplicates_replaced_by_links`
checks that each copy is gone and the link is present.

- **TradeInView classic Backtesting tab:** now a link to Strategy › Backtests. The backtest panels render there.
- **Rotation "Ask the Rotation Advisor" box:** now a link to My questions (asked through the Ask the CIO bar).
- **New Re-Entry desk:** look-through and the rotation workspace are links only.
- **New Defense desk:** sector momentum and leaders are a link to Watch › Sectors.

The classic Re-Entry and Defense pages keep their copies until the operator accepts the new desks. Still open, because the
home pages lack the content:
- Intelligence Trade AI rows (board 5);
- research topics (boards 5/9);
- Hermes Discovery inbox (boards 7/9).
