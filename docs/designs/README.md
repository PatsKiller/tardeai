# Design registry — `docs/designs/<DSN id>.md`

```
Status:  ACTIVE (registry + read-only Work board); ids per AGENTS.md 20.0.0 §28 (PROPOSED until ratified)
as_of:   2026-10-23
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

Seeded 2026-10-23, with evidence lines in each file's body:

| design | file |
|---|---|
| Release Train v2 (P0–P7) | `DSN-20261021-release-train.md` |
| Momentum / Alerts redesign, Gates 1–4 (P1–P4) | `DSN-20261022-momentum-alerts.md` |
| Ask the CIO (P8–P11) | `DSN-20261023-ask-the-cio.md` |
| CIO prospect store (P0–P4) | `DSN-20261022-cio-prospect-store.md` |
| Data domain approvals (batches A–D, operator_settings held) | `DSN-20261022-data-domains.md` |

Not seeded: the AGENTS.md 20.0.0 and 21.0.0 packages and push-policy v2. On 2026-10-23 they were not committed
anywhere a file link could point to. Add them once they are in git.
