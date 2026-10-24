# Work pipeline: the default Coordination view, keyed by work item (2026-10-23)

```
Status:      ACTIVE in code (branch feat/work-pipeline-20261023, stacked on release/batch-9-20261023); not deployed by this PR
as_of:       2026-10-23T14:00:00-04:00
Measured at: release/batch-9-20261023 d5912c3ee; read-only reads of the claim board, task board, PR census and release receipts
             (no traffic to the live server 127.0.0.1:7777: AGENTS.md 20.1.0 window until 16:15 ET)
```

Operator, 2026-10-23 13:15 ET, on Ops → Coordination → "Who's working" (verbatim): "This doesn't make logical sense
to me. This should be telling who, what, when, where, and how, and should be an incubator workflow that I can see at
each stage, whether it's green, amber, red, what are next steps? What's happening here?" and "There are no filters. We
have a whole bunch of stuff that says stale, where are the items that are queued up?"

Then, on the mockup: "the HTML looks great. But nothing is actionable on there", and approved both action tiers
("both"). Tier 1 is in this PR; Tier 2 is a follow-up PR stacked on it.

## Why the old view looked wrong

"Who's working" (batch 7) is one row per **file claim**, and "stale" meant only "no heartbeat for 2 h". A PR that is
finished, CI green and waiting for a release batch has no reason to heartbeat, so the most finished work looked
dead, and work that nobody had started (the task board) was not on the page at all.

## What the page shows now

Ops → Coordination opens on **Work pipeline** (`/v3/coordination`). The per-file claim table is still there as
**Files held** (`?tab=agents`); Automation moved to `?tab=operations`.

One row per **work item**: a task-board task, a PR, a claim with no task, or a design or packet awaiting approval.
Grouping: a task owns its claim and that claim's PR; several claims on one PR are one item; an open PR nobody claimed
is still an item; merged PRs from the last census are items until verified live.

Each row has a strip of eleven stage cells:

`Proposed → Approved → Queued → Claimed → Building → PR open → CI → In batch → Merged → Released → Verified live`

| Colour | Meaning |
|---|---|
| green | done |
| amber | where the item is now: in progress or waiting |
| red | blocked, failed or stale |
| grey | not reached |

Hovering a cell gives its time and evidence (claim id, PR, check names, release receipt, deploy health).

| The item sits in | When | RAG | Next step (owner) |
|---|---|---|---|
| Proposed | a PROPOSED design or packet, or a draft PR held for the operator | amber | Operator: approve or reject |
| Queued | a free task on the task board | amber; red when a dependency is not done | Agent: `agent_claim.py take <id>`; an `OPERATOR:` task is the operator's to-do |
| Claimed / Building | a claim, no PR | amber; **red "stale" when no heartbeat for 2 h** | Agent: start / build / take over |
| PR open | PR open, no CI seen, a draft, or closed unmerged (red) | amber | Agent |
| CI | checks running (amber) or failing (red; **"stale" only when nothing happened for 2 h**) | | Agent: fix the named checks |
| In batch | CI green: **"waiting for batch"** (amber, never stale), "next batch #n" (operator-queued), "#2018" (in an open batch PR), "operator merge" (a standing exclusion in an open or recent batch PR, e.g. "the operator merges those"; an exclusion for pending or failing checks only means it waits for the next batch), "stacked" (base is not main) | amber | Coordinator: add to batch / Agent: fix the batch / Operator: merge |
| Merged | merged, not in a release yet | amber | Agent: ship it |
| Released | in a release receipt, not verified | amber; red when deploy health failed | Agent: verify live |
| Verified live | the served release contains the merge and `deploy_receipt.json` says health ok | green, finished | — |

A claim worklog's Handoff "Next step:" replaces the derived next step while the agent owns the work (claimed to CI).

Each row also shows **Who** (agent, vendor and session, `OPERATOR`, or the PR author), **What** (title, task id, DSN
id, PR), **When** (started, last activity, age in the current stage), **Where** (branch, worktree, file count with
the files expandable), **How** (plan progress such as 3/7 and the latest worklog line), the **Blocker**, and **NEXT**
with its owner.

Top strip: one count per stage (unfinished items), Red, Amber and **Needs me** (operator-owned next steps).

Filters, all kept in the URL: stage, RAG, next-step owner (me / agents), vendor, design (DSN), PR/batch ("green, not in
a batch" or one batch PR) and text search (title, ids, branch, files, next step). Presets: **Needs me**, **Queued: not
started**, **Waiting for batch**, **Blocked/red**, **Live today**. Finished items are hidden behind "show finished".

The **Queued** section lists the free task-board tasks by priority, the green PRs not yet in a batch (operator-queued
ones first, in order) and the operator to-dos (`OPERATOR: …` tasks).

## Actions (Tier 1, this PR)

Every card carries **Open PR**, **CI log** (`/checks`), **Diff** (`/files`) and **Worklog** (opens the claim's worklog
from `GET /api/v2/coordination/claims?worklog=<id>`). An operator-owned next step has **Copy command**: the exact
command with the real PR number and head SHA, copied client-side, no server write (e.g.
`gh pr merge 1997 --merge --match-head-commit d23a244…`; an `OPERATOR:` task naming a script copies
`bash scripts/…/x.sh && python3 scripts/agent_claim.py task done <id> --summary "…"`).

Writes go to one governed endpoint, `POST /api/v2/coordination/commands`
(`scripts/lib/work_pipeline_commands.py`), body `{command, params, idempotency_key}`:

| Command | Params | Effect (coordination store only) |
|---|---|---|
| `note` | `item`, `text` | the claim worklog (Decisions, `operator (<login>): …`); else the task history; else the PR's note list in the batch queue |
| `set_priority` | `task_id`, `priority` 1–4 | task board; old value in the task history |
| `hold` / `unhold` | `item` (task or PR), `reason?` | task: `held` field; `agent_claim.py next` and `take` skip a held task. PR: `held_prs` in the batch queue; the batch builder skips it |
| `batch_add` / `batch_remove` | `pr` | the ordered `next_batch` list in the batch queue; `batch_add` refuses a held PR and, from the last census, a PR that is not open, not green or already in an open batch |
| `task_add` | `title`, `kind`, `areas`, `priority?`, `acceptance?` | a new task, `source: operator` |
| `task_split` | `task_id`, `parts` | children on the board; the parent reads `split` |
| `release_stale_claim` | `claim_id` | only a RED-stale claim (no heartbeat for 2 h and pre-PR, or CI failing): released `abandoned` with `released_by=tailnet:<login>`, files freed, worklog kept with a final summary and an "operator takeover" status line, its task back on the board |

Checks, in order: POST only → the operator principal (`tailnet:<login>` on the serve_proxy listener, login on the
cc_auth allowlist; the service token, i.e. agents, n8n and cron, is refused `AGENT_CALLER_REFUSED`) → CSRF
(`cc_auth.command_csrf_check`, enforced whatever report_only says; the route is also a `csrf.hard_routes` entry in
`config/cc_auth.yaml`) → never-on-board commands (`NEVER_ON_BOARD`) → Tier 2 commands (`STEP_UP_REQUIRED`) → the
idempotency key (8–100 `[A-Za-z0-9_.:-]`; a repeat replays the recorded result and writes nothing; the same key for a
different command is `IDEMPOTENCY_KEY_REUSED`) → the command's own validation. The actor is always the authenticated
principal; a body field named `actor` is ignored. Every outcome, refusals included, is one fsynced line in
`<claims_dir>/pipeline/commands_audit.jsonl` (`WorkPipelineCommandAudit@v1`, append-only).

Never on the board: broker orders, stops, kill-switch clearing, issuing grants. AGENTS.md §27.2 applies: agents never
call this endpoint either.

### The batch queue (for whoever builds the next release batch)

`<claims_dir>/tasks/batch_queue.json` (`BatchQueue@v1`, written under the task board's lock):

```
next_batch: [{pr, by, at}, …]     # operator order: build the next batch from these, in this order
held_prs:   {"<pr>": {by, at, reason}}   # never put these in a batch while held
pr_notes:   {"<pr>": [{by, at, text}]}   # operator notes on PRs that have no claim
```

`python3 scripts/batch_queue.py show` prints it; `python3 scripts/batch_queue.py next` prints the PR numbers to
include, held ones dropped. A batch builder runs it before choosing PRs, and still checks each PR is green at its head.

## Data sources and bounds (memory safety)

`GET /api/v2/coordination/pipeline` (`scripts/lib/work_pipeline.py`) joins:

- the claim board and lifecycle (`agent_claim_board.board_view`, its own background GitHub observer) and the task
  board;
- designs and packets awaiting approval (`design_registry.work_board().designs()`, its own 30 s cache);
- a PR census: `gh pr list --state open --limit 100` (with `headRefOid` and `statusCheckRollup`), `gh pr list
  --state merged --limit 40`, `gh pr view <n> --json body` for at most 3 open `release/batch-*` PRs (their
  `## Included` table and `## Excluded` list), and the required checks of `main` (hourly);
- release receipts: `release_pins/apply-*.json` and the served SHA (`agent_claim_lifecycle.ReleaseReader`, local
  `git merge-base --is-ancestor`) and `deploy_receipt.json` health;
- the batch queue.

Bounds: the view is rebuilt at most once per 30 s, single-flight (a concurrent request gets the last value). The census
runs only in a background thread, at most once per 60 s and never two at once; a request never waits on GitHub and
never triggers more than one refresh. Every gh call is read-only (`pr list`, `pr view`, `api --method GET`; anything
else is refused), has a 25 s timeout and a 6 MB output cap; a failed refresh keeps the last good census and says so.
Lists are capped (100 open, 40 merged, 3 batches, 400 items, 60 files per item) and worklogs are read through a 24 KB
tail. The pr-hygiene receipt was not used: it does not exist on this host.

## Files

- `scripts/lib/work_pipeline.py`, `scripts/lib/work_pipeline_commands.py`, `scripts/batch_queue.py`
- `scripts/lib/agent_task_board.py`: `set_priority`, `set_hold`, `note`; `next`/`take` skip held tasks
- `scripts/api_v2.py`: `GET /api/v2/coordination/pipeline`, `POST /api/v2/coordination/commands`
- `config/cc_auth.yaml`: hard CSRF route `work_pipeline_command`
- `apps/command-center-v3/src/pages/WorkPipelinePanel.tsx`, `src/lib/workPipeline.ts`, `src/lib/workPipelineActions.ts`,
  `src/fixtures/workPipeline.fixture.ts` (captured from the real stores 2026-10-23), `CoordinationPage.tsx` (default tab)
- Tests: `tests/test_work_pipeline_20261023.py`, `tests/test_work_pipeline_commands_20261023.py` (CI gate
  `config/ci_gates/work_pipeline_20261023.json`), `src/lib/workPipeline.test.ts` (in `npm run build`),
  `e2e/work-pipeline.spec.ts` (fixtures, 1440 and 412 px; in `cc-surface-agreement-ci`)

## Not in this PR

Tier 2 (passkey assertion + typed phrase through the host applier): approve a design or phase, mark a DRAFT health
contract reviewed, merge a PR, release now, approve an approval-list item. Follow-up PR, stacked on this one.
