# Design registry — `docs/designs/<DSN id>.md`

```
Status:  ACTIVE (registry + read-only Work board); ids per AGENTS.md 20.0.0 §28 (PROPOSED until ratified)
as_of:   2026-10-23 (backfill 18:40Z)
Code:    scripts/lib/design_registry.py · GET /api/v2/coordination/designs and /tasks · CC Coordination → Work board
```

There is one store. Each design is one markdown file named by its id, with YAML front matter:

- design `DSN-<YYYYMMDD>-<slug>`
- phase `DSN-…-P<n>`
- task `DSN-…-P<n>-T<m>`

Status values are `PROPOSED | APPROVED | IN_PROGRESS | DONE | LIVE | HELD`. The format and a full example are in
the header of `scripts/lib/design_registry.py`. The registry is reviewed text in git, so a PR changes it. A file
that does not parse is listed on the board as an error; it never hides the others.

**Tasks are what agents claim.** Put a design task on the task board, then take it:

```bash
python3 scripts/agent_claim.py task add --id DSN-20261021-release-train-P5-T1 --title "..." --kind build --areas <globs> --acceptance "..."
python3 scripts/agent_claim.py take DSN-20261021-release-train-P5-T1      # refused if its files overlap a live claim
```

Carry the id through the claim, the worklog, the branch name, the PR title and the commit trailer
`Design-Task: <id>`. A task registered on the board overrides the file's task status: `taken` shows as
IN_PROGRESS and `done` as DONE. Its holder is shown as `vendor:session-prefix`.

Seeded 2026-10-23 (#2004) and backfilled the same day (task T-20261023-730ebe) with every program, phase, operator
approval and grant from 2026-10-21..23. Evidence lines are in each file's body; operator to-dos carry `owner: OPERATOR`
and an `operator/...` pseudo-area on the task board; finished work is a board task marked done with its evidence.

| design | status | file |
|---|---|---|
| DB retention / Iris | IN_PROGRESS | `DSN-20261010-db-retention-iris.md` |
| Releases and integration batches (manual path, 2026-10-21..23) | IN_PROGRESS | `DSN-20261021-release-batches.md` |
| Release Train v2 | IN_PROGRESS | `DSN-20261021-release-train.md` |
| CIO prospect store (one record per security) + no-silos wiring | IN_PROGRESS | `DSN-20261022-cio-prospect-store.md` |
| Data domain approvals (17 proposed domains) | PROPOSED | `DSN-20261022-data-domains.md` |
| Dependency upgrades (approval M) | APPROVED | `DSN-20261022-dependency-upgrades.md` |
| Finviz alerting: false dead-credential and noisy screener pages | DONE | `DSN-20261022-finviz-alerting.md` |
| Shared Momentum / Alerts redesign (Gates 1-4) | IN_PROGRESS | `DSN-20261022-momentum-alerts.md` |
| n8n promotion batch A-F (2026-10-23) | PROPOSED | `DSN-20261022-n8n-promotions.md` |
| Operator approvals and grants (2026-10-21..23) | IN_PROGRESS | `DSN-20261022-operator-approvals.md` |
| Ops -> Controls (passkey, sudo window, dashboards) | IN_PROGRESS | `DSN-20261022-ops-controls.md` |
| Kill switch + read-only Schwab baseline | IN_PROGRESS | `DSN-20261022-schwab-readonly-baseline.md` |
| Command Center site validation (Playwright) + P3 cosmetics | IN_PROGRESS | `DSN-20261022-site-validation.md` |
| Watch redesign (prospect lanes, My Watchlist / System Suggests) | IN_PROGRESS | `DSN-20261022-watch-redesign.md` |
| Account names on every row, alert and notice (never numbers) | IN_PROGRESS | `DSN-20261023-account-labels.md` |
| Agent operations: AGENTS 20.0.0 / 20.1.0 / 21.0.0, claim board, Work board | IN_PROGRESS | `DSN-20261023-agent-ops.md` |
| Ask the CIO (Phases 8-11) | IN_PROGRESS | `DSN-20261023-ask-the-cio.md` |
| Active Trader <-> Trade AI alignment | IN_PROGRESS | `DSN-20261023-at-tradeai-alignment.md` |
| JSONL retention: rotation now, deletion later | IN_PROGRESS | `DSN-20261023-jsonl-retention.md` |
| NVDA phantom STOP HIT (0.133 promo share) | IN_PROGRESS | `DSN-20261023-nvda-false-alert.md` |
| Open PRs with no program owner (triage) | IN_PROGRESS | `DSN-20261023-open-pr-triage.md` |
| Premarket 1-minute cadence + scalp focus list | IN_PROGRESS | `DSN-20261023-premarket-focus.md` |
| Push policy v2 + draft-PR CI skip | PROPOSED | `DSN-20261023-push-policy-v2.md` |
| Portfolio-server memory kills | IN_PROGRESS | `DSN-20261023-server-memory.md` |
| Work pipeline (Coordination default view) + action tiers | IN_PROGRESS | `DSN-20261023-work-pipeline.md` |

Tasks that were already on the board under a `T-…` id are referenced from the design file as `board_task:` rather than
registered twice.
