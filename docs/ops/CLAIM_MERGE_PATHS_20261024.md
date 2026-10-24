# WP-02 follow-up: merge-aware claim precommit scope

Design-Task: DSN-20261024-claim-merge-paths-P1-T1

When merging fetched main history, `agent_claim.py precommit` derives its own path scope from
`git diff --cached --name-only -z MERGE_HEAD` itself. Inherited main files no
longer count as worker-authored changes when the incoming parent is in fetched
main history, and passing a filtered `--paths` list
cannot hide a worker change. Normal commits keep their existing explicit-path
behavior. No hook, policy, override or protected-file rule changes.

## Reproduction and correction

The previous hook supplies an index-versus-HEAD list. In a merge of main into a
worker branch, that list contains main's newly staged files and omits the branch
work already present in HEAD. WP-23 consequently needed the coordinator's manual
`MERGE_HEAD` path list.

The regression uses a real isolated Git repository: the worker edits/adds/deletes
three claimed files; main edits/adds two files held by another session. Before
the correction the actual CLI returns 10 and identifies both inherited main files
as conflicting and uncovered. Afterward it checks only the three worker files
and passes. The result JSON records `path_basis` and `evaluated_paths`.

| Situation | Gate behavior |
|---|---|
| Merge has claimed worker changes and inherited main files | Derives worker paths against incoming parent; inherited files excluded. |
| Caller omits an unclaimed worker file | Full derived scope still refuses the missing claim. |
| Worker changes a main file while resolving the merge | Resolution differs from incoming parent and requires a claim. |
| Incoming parent and resolved index are identical | Explicitly evaluates an empty worker delta. |
| Linked worktree | Resolves its own marker through `git rev-parse --git-path MERGE_HEAD`; no assumption that `.git` is a directory. |
| Invalid merge parent, failed Git read or timeout | Returns gate-error 3 before claim evaluation; existing active-policy hook refuses the commit. |
| Unaccepted feature merge or missing main ref | Checks the union of index-versus-MERGE_HEAD and index-versus-HEAD; incoming unclaimed files remain blocked. |
| Ordinary commit | Preserves existing claim enforcement for caller paths. |

NUL-separated names preserve spaces. Git reads have finite timeouts and no
interactive prompts. The change neither skips claim ownership/worklog checks nor
introduces a new override.

## Verification

**144 tests pass normally and 144 pass with psycopg2 hidden**, including 12 new
real-Git fixtures and the four existing claim-board/lifecycle/worklog/shared-path
suites. All clocks and repositories are fixture-owned. No live board, database,
network, credentials or application server is used by tests.

```bash
PYTHONPATH="$HOME/.cache/rtc/nopg" python -m pytest -q \
  tests/test_agent_claim_merge_paths_20261024.py \
  tests/test_agent_claim_lifecycle_20261023.py \
  tests/test_agent_claim_board_20261022.py \
  tests/test_agent_claim_worklog_20261023.py \
  tests/test_agent_claim_shared_paths_20261023.py
```

The hidden-driver module raises `ModuleNotFoundError` with `name="psycopg2"`, as
required by the coordinator's October 24 standing rule. The new file is registered
using canonical `ci_gates.make_record`/`render`. Logs:
`/home/johnclaw/.cache/rtc/claim-merge-paths-20261024/final-regression.log` and
`/home/johnclaw/.cache/rtc/claim-merge-paths-20261024/nopg-regression.log`.

This is a local source correction. Publication, exact-head remote checks, merge
and release remain with the coordinator/operator. Existing hook files and
`AGENTS.md` are unchanged.
