# Work board structure — every task carries problem, definition of done, prompt, commands and proof

```
Status:      ACTIVE (code, on branch feat/wp-board-structure-20261023); board data imported 2026-10-23T21:34Z
as_of:       2026-10-23T18:00-04:00
Measured at: worktree ~/wt-wpboard from origin/main 4e1a440fd; importer run against the real coordination store
Design-Task: DSN-20261023-work-pipeline-P3-T1 (= WP-41 of the v3 handoff)
```

Operator, 2026-10-23, verbatim: "this is what should be done inside of the board also. structure: problem,
definition of done, agent prompt, operator commands, and proof of completion." Then: "also add that the above should
be part of the board."

## 1. The task schema (additive, backward compatible)

`scripts/lib/agent_task_board.py` (`AgentTask@v1`, unchanged schema id) gains optional fields. A task without any of
them reads, lists, is taken and is finished exactly as before.

| field | meaning |
|---|---|
| `problem` | markdown: what is wrong now |
| `definition_of_done` | markdown: the target state |
| `agent_prompt` | markdown, ready to paste. Stored **without** the B0 preamble; it is prepended on copy |
| `operator_commands` | markdown with code blocks: what the operator runs (dry run first) |
| `proof` | how completion is proven (the durable artifact, AGENTS.md §0 rule 8) |
| `proof_evidence` | filled at done: links, SHAs, receipt paths |
| `notes` | traps, rollback and other labelled blocks from the plan |
| `wp_id`, `stage`, `owner_kind`, `owner_label` | `WP-07`, `Stage 2`, `AGENT` / `OPERATOR` / `BOTH`, the owner text |
| `wp_status`, `wp_status_note`, `related_tasks`, `source_ref` | the plan's status box and note, linked board tasks, provenance |

Each section is capped at 20,000 characters. Rules:

- **Done needs evidence.** A task with a `proof` cannot be marked done without `proof_evidence`. This applies to
  `task done` (`--proof-evidence` or `--proof-evidence-file`, or evidence already set with `task edit`),
  `task done --evidence-only` (its summary and links become the proof evidence) and the operator's "Mark done" in the
  Work pipeline (its text becomes the proof evidence).
- **Operator packages are never handed to an agent.** `next` skips tasks with `owner_kind` OPERATOR, and `take`
  refuses them: an agent prepares the exact commands and stops (AGENTS.md §0 rule 9). `BOTH` packages can be taken.
- The board read model (`board()`) lists which sections a task has (`sections`), never their text, so the 30 s
  Work pipeline view stays small. The text is served per task.

## 2. CLI (`scripts/agent_claim.py`)

```bash
python3 scripts/agent_claim.py task add --title "…" --kind build --areas … \
  --problem-file p.md --dod-file d.md --prompt-file a.md --operator-file o.md --proof-file v.md \
  --wp-id WP-42 --stage "Stage 7" --owner-kind AGENT
python3 scripts/agent_claim.py task edit <id> --dod-file d.md --clear notes      # '-' reads stdin
python3 scripts/agent_claim.py task show <id> [--full-prompt]                   # every section; B0 + prompt
python3 scripts/agent_claim.py task list --wp                                   # work packages only
python3 scripts/agent_claim.py task done <id> --proof-evidence "PR #2045 merged; served 1a2b3c4"
python3 scripts/agent_claim.py export-handoff --out ~/handoff.md                # the offline document
```

## 3. Importer: `scripts/import_handoff_workpackages.py --file <handoff> --dry-run|--apply`

Each `### WP-NN <title>` becomes one task. The header line gives `owner_kind` (from the upper-case words AGENT and
OPERATOR), `owner_label`, `depends_on` (every `WP-NN` named, except inside an "optional" parenthesis) and the status.
"Current issue" / "Current state" / "What happened" become `problem`; "Target state" and "Remaining…" become
`definition_of_done`; any "Agent … prompt" becomes `agent_prompt`, with its `(B0.)` marker removed, plus inline
`> (B0.)` prompts inside numbered items; "Operator commands" and other "Operator …" blocks become `operator_commands`;
"Verify" becomes `proof`; everything else labelled (Traps, Rollback, Limits) becomes `notes`. The narrative above
each stage's first WP becomes that stage's description (`<claims_dir>/tasks/wp_stages.json`).

- New tasks get the id `DSN-20261023-handoff-v3-P<stage>-T<wp>` (the board's id format) with the pseudo-area
  `handoff/WP-NN`; an agent extends its claim with `claim --add` before it touches files. Priority follows the stage:
  stages 1–2 P1, 3–4 P2, 5–6 P3, 7 P4. OPERATOR packages are kind `review`, others `build`.
- An existing task with the same `wp_id` is updated in place. If the importer did not create it, it keeps its title,
  status and dependencies, and only sections the plan states are set.
- Existing tasks that name the WP, share a PR number with it or have a near-identical title are linked as
  `related_tasks` and listed in the dry run. They are never closed or duplicated.
- A WP whose status is entirely `[x]` closes its free task, with the status text as evidence.
- Re-running is idempotent: the second dry run reports every package as unchanged.
- `export-handoff` writes the same format back. Import, export and import again is a fixed point; a test covers it.

### First run against the real board, 2026-10-23

Dry run (abridged; the full output is in the PR description):

```
Stage 1: Get merged work live, and lock in the agent workflow — 3 WPs, no intro
Stage 2: Release train (…) — 8 WPs, intro 1034 chars
…
CREATE    WP-01 -> DSN-20261023-handoff-v3-P1-T01  [AGENT, Stage 1, in_progress] Release whatever is merged on main but not served
…
UPDATE    WP-41 -> DSN-20261023-work-pipeline-P3-T1  [AGENT, Stage 7, in_progress] The board carries the whole plan (…)
          … adopts existing task (taken): sections only …
plan: 41 work packages · create 40 · update 1 · unchanged 0 · close 0 · with related tasks 9 · stages 7
dry run: nothing written
```

Apply: `applied: created 40 · updated 1 · closed 0 · stages 7`. A second dry run then reported
`create 0 · update 0 · unchanged 41`.

## 4. The playbook: `docs/ops/OPERATING_PLAYBOOK.md`

The playbook holds Section A of the v3 handoff (resume procedure, system map, rules, how a change goes live) and B0
(the standard agent preamble), copied verbatim. It is reviewed by PR. `scripts/lib/handoff_playbook.py` parses it
into anchored sections and caches the result by file mtime and size; files over 512 KB are refused. The B0 preamble
is the first blockquote under `## B0.`, and `tests/test_operating_playbook_20261023.py` pins the headings.

## 5. Work pipeline (Ops → Coordination)

- **Rows** show the WP id, stage and owner kind. The **Details** button, also on Queued and Next up cards, opens a
  drawer with five sections: Problem, Definition of done, Agent prompt, Operator commands and Proof of completion.
  - **Copy prompt** copies the B0 preamble, then `---`, then the task's prompt.
  - **Copy commands** copies the bodies of the fenced code blocks.
  - **Proof of completion** shows the evidence once the task is done.
  - For an operator task with a proof, **Mark done** needs evidence text before it posts.
- **Stage/WP filter** (`?wp=Stage 2` or `?wp=WP-07`, kept in the URL). Choosing a stage shows its introduction.
- **Next up** preset (`?preset=next-up`) lists, for each owner kind (Agents, Operator, Operator + agent), the first
  work package in plan order whose dependencies are met, plus the next two.
- **Playbook** tab renders the playbook read-only, with a section index and anchors. The client polls it every
  10 minutes.
- **Export handoff** (pipeline header and Playbook tab) downloads the full handoff, regenerated from the board.

The served routes are all GET only:

| route | what it returns | bound |
|---|---|---|
| `GET /api/v2/coordination/task?id=<task_id>` | one task's sections and `full_prompt` | one file read; id validated and capped at 120 characters |
| `GET /api/v2/coordination/playbook` | the parsed playbook | parsed once per mtime |
| `GET /api/v2/coordination/handoff-export` | `{markdown, filename, bytes, work_packages}` | single-flight, rebuilt at most once per 30 s, capped at 2 MB |

The pipeline view itself keeps its 30 s single-flight cache and its caps. Each item gains a small `wp` block (labels
and section names only), and the payload gains `wp_stages` (each description capped at 4,000 characters).

## 6. Tests

| suite | file |
|---|---|
| backend (CI gate `work_board_structure_20261023`) | `tests/test_work_board_structure_20261023.py` |
| playbook (CI gate `operating_playbook_20261023`) | `tests/test_operating_playbook_20261023.py` |
| UI model (in the CC v3 build) | `apps/command-center-v3/src/lib/workPipeline.test.ts` |
| Playwright, at 1440 and 412 px | `apps/command-center-v3/e2e/work-pipeline.spec.ts` (`work-package structure` block) |

The Playwright fixture is `src/fixtures/workBoardStructure.fixture.ts`. It was captured from the real board after the
import, with no traffic to the live server.

## 7. Proposed AGENTS.md sentence (for the 20.2.0 package, WP-15; not applied here)

§28.3b, new bullet: "**Every task carries its structure.** Every task carries problem, definition of done, agent
prompt, operator commands and proof of completion; done requires evidence." *Cause (§20): operator 2026-10-23,
verbatim: "this is what should be done inside of the board also. structure: problem, definition of done, agent
prompt, operator commands, and proof of completion."*

## 8. Known limits

- The importer reads one handoff format. A plan in a different shape needs `task add`/`task edit`, or a new parser.
- A blocked work package reads red ("blocked") in the pipeline, as every blocked task already did. Importing the
  plan's dependencies therefore adds red rows; the Next up view shows what can start.
- Agents running older code (the served release before this PR) do not skip OPERATOR packages in `next`. This is the
  same behaviour as today's `OPERATOR:` to-dos, and it is fixed once this PR is released.
