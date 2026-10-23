# Agent claim board — who is working on which files

```
Status:      ACTIVE (code); compaction timer NOT INSTALLED; pre-commit gate NOT WIRED (operator steps below)
as_of:       2026-10-23T09:45-04:00
Measured at: origin/main 53aa1b619 (branch feat/claim-board-lifecycle-20261023); not measured live
Changes:     2026-10-23 lifecycle stages + whiteboard (§9), policy-gated pre-commit (§10)
```

Operator-approved design, 2026-10-22. One board that every coding-agent session uses before it edits files:
Claude, Codex and Cursor are **equal peers**. There is no master agent and no coordinator process. Each
session claims the files it will touch; a second session asking for an overlapping path is refused and told
who holds it, on which branch, since when.

The rule text that makes claiming mandatory ships separately as **AGENTS.md 20.0.0** (built as "19.1.0",
renumbered MAJOR). Until 20.0.0 is ACTIVE the pre-commit gate only warns; from then on it blocks (§10).

## 1. What it is

| piece | path |
|---|---|
| library | `scripts/lib/agent_claim_board.py` (`AgentClaim@v1`, `AgentClaimBoard@v1`) |
| lifecycle | `scripts/lib/agent_claim_lifecycle.py` (`AgentClaimLifecycle@v1`; GitHub GET reader, release receipts) |
| CLI | `scripts/agent_claim.py` — `claim`, `heartbeat`, `stage`, `sync`, `release`, `list`, `check`, `precommit`, `compact` |
| pre-commit gate (policy-gated) | `scripts/agent_claim_precommit.sh` — not wired; see §6 and §10 |
| read-only API | `GET /api/v2/coordination/claims` (`?active=1` hides done/abandoned) |
| Command Center | Coordination → **Who's working** (`/v3/coordination?tab=agents`) |
| weekly compaction | `linux_launchers/systemd/tradeai-agent-claim-compact.{service,timer}`; lane `agent-claim-compact` (`NEVER_SCHEDULED`) |
| tests | `tests/test_agent_claim_board_20261022.py` (CI gate `agent_claim_board_20261022`), `tests/test_agent_claim_lifecycle_20261023.py` (CI gate `agent_claim_lifecycle_20261023`), `apps/command-center-v3/src/lib/agentClaimLifecycle.test.ts` (in `npm run build`) |

## 2. The store

Default directory `~/trade-ai-releases/persistent-state/data/coordination/claims/`. Override it with
`--claims-dir` or `TRADEAI_AGENT_CLAIMS_DIR`.

- **One JSON file per claim**, `<claim_id>.json`. Fields: `claim_id`, `vendor`, `session`, `agent`, `task`,
  `paths` (files, directories or globs), `branch`, `pr`, `started_at`, `heartbeat_at`, `status`
  (`active` | `done` | `abandoned`), `note`. Also `host`, `takeover_of`, `ended_at`, `released_by`, and (from
  2026-10-23) `stage` + `stages` {stage: time} for the stages the owner declared (§9).
- `lifecycle/<claim_id>.json` (`AgentClaimLifecycle@v1`) is the **observation cache** for one claim: PR state,
  CI of the head SHA, merge commit, release hit, a time per observed stage. It is not owner data; any CLI run may
  merge-write it (flock on `lifecycle/.lock`, monotonic: a stage time once seen is kept).
- **Created atomically.** The claim is written to a unique temp file opened `O_CREAT|O_EXCL`, fsynced,
  then `os.link`-ed to its final name. `link` fails rather than replace an existing file, so one claim can
  never be overwritten by another.
- **No shared-file writes on the claim path.** `heartbeat` and `release` rewrite only the caller's own file
  (temp + `os.replace`). Scan + create run under an `flock` on `<dir>/.claim.lock`, an empty file that is never
  written. Fallback for a filesystem that ignores flock: each claimant re-scans after writing. If an
  overlapping live claim sorts earlier by `(started_at, claim_id)`, the later claimant marks its own claim
  `abandoned` ("lost race") and reports the conflict.
- `claims_history.jsonl` in the same directory is **append-only**, written by `compact` (archived claims, with
  their lifecycle cache) and by the pre-commit gate (`AgentClaimOverride@v1`, one line per logged bypass, §10).

## 3. Rules

- **Overlap.** Paths are repo-relative; absolute paths and `..` are refused. Exact match, directory
  containment (`docs` claims `docs/x.md`) and globs all count. `*` and `?` match within one segment, `**`
  matches across segments, and `[...]` is supported. Overlap between two globs is decided conservatively: two
  globs that share no real file may still be reported as overlapping, but a real shared file is never missed.
  `apps/**/*.tsx` does not overlap `apps/x/y.ts`.
- **Your own claims never conflict.** A claim is yours if its `session` is yours, or (in `check`) its `branch`
  is your current branch.
- **Stale = no heartbeat for 2 hours** (`--stale-hours`, `TRADEAI_AGENT_CLAIMS_STALE_HOURS`). A stale claim
  stops blocking. A new claim over it records `takeover_of`. The old owner's next `heartbeat` is refused
  ("taken over … stop and coordinate").
- **Release** is owner-only. `--force` releases another session's claim and records `released_by`.
- **Merged frees the files.** A claim at stage `merged` or `released` no longer blocks, even while live (§9).
- **Compaction.** A claim becomes eligible when it is `done` or `abandoned`, or `active` but stale, or `released`, and
  its last activity (the release time, for a released claim) is more than 7 days old. Work with a PR at `pr_open`,
  `ci_green` or `merged` stays on the board until it is released, its PR closes unmerged, or 30 days pass. `compact` appends it to `claims_history.jsonl` (fsynced, then read back
  and matched by sha256) and only then removes the claim file. A file that changed during the archive, or
  whose archive line cannot be read back, is kept. Looking up a compacted claim id answers from the history
  ("compacted into … line N"), so a compacted claim never reads as one that never existed. Live claims are
  never touched.

## 4. Agent workflow (any vendor)

```bash
export AGENT_CLAIM_VENDOR=codex AGENT_CLAIM_SESSION=<your session id> AGENT_CLAIM_AGENT=<name>
python3 scripts/agent_claim.py claim --task "fix X" --paths scripts/lib/x.py 'tests/test_x_*.py' --branch feat/x
#   -> prints the claim_id; exit 1 + holder/branch/since if someone else holds an overlapping path
python3 scripts/agent_claim.py stage <claim_id> building             # started implementing
python3 scripts/agent_claim.py stage <claim_id> pr_open --pr 1990     # PR opened (also found by branch on GitHub)
python3 scripts/agent_claim.py heartbeat <claim_id> [--pr 1965]      # at least every 2 h while working
python3 scripts/agent_claim.py sync --dry-run                        # what GitHub + release receipts would advance
python3 scripts/agent_claim.py check --paths $(git diff --cached --name-only)   # exit 1 on conflict
python3 scripts/agent_claim.py release <claim_id> --status done      # or abandoned
python3 scripts/agent_claim.py list [--all] [--json]
```

Exit codes: `0` ok · `1` conflict or refused claim · `2` usage or ownership error · `precommit`: `10` blocked.

**One session id per agent.** "Mine" means same `session` (or same branch). Worker agents spawned by one
coordinator session must each export their own `AGENT_CLAIM_SESSION` (e.g. `<session>-<worker>`); with a shared id
the board cannot tell them apart and they never conflict with each other.

**Cloud agents** (Codex cloud, Cursor background agents) cannot reach the host's claims directory. Their
signal is an **open draft PR**: `check` also runs `gh pr list --draft --json files` and treats an open draft
PR on another branch that changes an overlapping file as a conflict. If `gh` is missing, offline,
unauthenticated or slow, `check` prints `WARN: … draft PRs were not consulted` and goes on; it does not fail
for that reason. `--no-gh` skips the lookup. Cloud agents should open their PR as a draft early.

## 5. Read-only surfaces

`GET /api/v2/coordination/claims` returns `AgentClaimBoard@v1`: `as_of`, `claims_dir`, `dir_present`,
`stale_after_hours`, `compact_after_days`, `counts` {live, stale, done, abandoned}, `unreadable` (file names
that could not be read; reported, never silently dropped), `truncated` and `claims[]`. Each row carries
`state`, `vendor`, `session`, `agent`, `task`, `paths`, `branch`, `pr`, `started_at`, `heartbeat_at`,
`heartbeat_age_minutes`, `note`, `takeover_of` and `taken_over_by`.

Added 2026-10-23 (additive): top level `stages`, `stage_counts`, `stage_help`, `lifecycle` {observed_at, warning,
refreshing, ttl_s, repo}; per row `stage`, `stages` {stage: time}, `locks_held`, `pr_number`, `pr_url`, `pr_state`,
`pr_draft`, `pr_base`, `head_sha`, `merge_sha`, `ci` {state green|pending|failing|unknown, basis, required, failing,
pending, completed_at, head_sha, checked_at}, `released` {at, sha, basis}, `observed_at`, `observe_warnings`,
`age_minutes`, `stale_warning` and `warnings[]`.

The route is GET only (anything else → 405 `read_only`). It never creates the directory. It sits behind the
default `config/cc_auth.yaml` policy like every other `/api/v2` read, so no new cc_auth entry was needed.

The Command Center tab **Coordination → Who's working** polls this every 30 s. It opens as a **board**: one column
per stage (Claimed, Building, PR open, CI green, Merged, Released (live), Abandoned). Each card shows the task, the
vendor / agent, the files, the branch, a PR link, the CI state, whether the files are held or free, the heartbeat,
the time of each stage reached, the age and a warning line (stale, CI failing, PR closed unmerged, merged but not
live after 3 days). "table view" shows the same rows as one table. Filters: vendor and stage. Finished work
(released, abandoned, released with no PR) is hidden behind "show finished". Every chip, column header and cell
has a tooltip. An unavailable board says so: "not the same as nobody working". A degraded GitHub read shows
"GitHub: degraded" with the reason; the stages then fall back to what agents declared.

## 6. Operator install (not done by this change)

1. **Weekly compaction timer.** Installing a scheduler entry is operator-only (AGENTS.md §9.3). First run the
   dry run and read its output:

   ```bash
   cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
   .venv/bin/python scripts/agent_claim.py compact --dry-run
   cp linux_launchers/systemd/tradeai-agent-claim-compact.{service,timer} ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now tradeai-agent-claim-compact.timer
   systemctl --user start tradeai-agent-claim-compact.service      # forced run (§8.1)
   cat ~/trade-ai-releases/persistent-state/data/runtime/agent-claim-compact_last.json   # ok_at = proof
   ```

   Then flip lane `agent-claim-compact` in `config/lane_registry.json` from `NEVER_SCHEDULED` to `ACTIVE` in a
   reviewed PR.
2. **Pre-commit gate.** `.githooks/` is an operator-only surface (AGENTS.md §23.13 exclusion; guard
   `governed_globs`; `config/ci_risk_tiers.json` `policy_and_guard`), so this change does not edit it. To wire
   the gate, add this line to `.githooks/pre-commit` after the secret scan and before the chain to
   `scripts/githooks/pre-commit` (no `|| true`: the exit code is the gate):

   ```bash
   bash "$ROOT/scripts/agent_claim_precommit.sh" || exit 1
   ```

   Below AGENTS.md 20.0.0 ACTIVE it always exits 0 (warnings only). Behaviour from 20.0.0: §10.
   Set `AGENT_CLAIM_NO_GH=1` to skip GitHub when offline.
3. **AGENTS.md 20.0.0** (separate package; built as "19.1.0") makes claim-before-edit mandatory. The gate reads the
   policy state itself, so ratifying 20.0.0 turns warn into block with no code change.
4. **Optional: keep stages fresh without the UI.** `python3 scripts/agent_claim.py sync --dry-run`, read it, then
   `sync --apply`. `compact --apply` runs the same sync first. No timer is added for it by this change.

## 7. Pre-build check (AGENTS.md §13.5)

Searched for: lease, claim, `agent_file_lease`, coordination, "who is working", `claims_history`.

Found `scripts/lib/agent_file_lease.py` (`AgentFileLease@v2`, SOP 1.2.0). That module keeps flock leases under
the **git common dir** of one clone with a 1-hour TTL. It has no vendor, branch or PR fields, no globs, no
history archive and no draft-PR fallback. It was **not extended**: the operator-approved design needs a
store shared across clones and worktrees in persistent-state, claims that live as long as a PR, and one file
per claim with no shared coordinator lock. Its path canonicalizer (`canonicalize_claim_path`) **is reused**,
so both modules agree on what a valid repo path is. The two do not compete. A lease is a short in-session
lock; a claim is the multi-vendor declaration of intent. Whether to retire leases in favour of claims is
left to 19.1.0.

## 8. Known limits

- The board works only on this host. A cloud agent is visible only through its draft PR.
- Glob-versus-glob overlap is conservative, so it can report a false conflict. Narrow the claim if that
  happens.
- Before AGENTS.md 20.0.0 is ACTIVE an agent can skip claiming, and the hook only warns.
- Stages after `pr_open` need GitHub. With gh missing, offline, unauthenticated or slow, a claim shows its
  declared stage and **keeps its files** (fail safe), and the panel says "GitHub: degraded".
- `released` needs the merge commit locally (`git merge-base --is-ancestor` in the canonical checkout) or, failing
  that, a GitHub compare GET. It is judged against this host's release receipts only.
- A PR merged into a batch branch reads `merged` (its files free) though it is not on `main` yet; it reads
  `released` only once a served release contains it.

## 9. Lifecycle (2026-10-23)

Operator 2026-10-23: a whiteboard showing what each agent is working on, when it is implemented and when it is
finished, so agents do not step on each other.

```
claimed -> building -> pr_open -> ci_green -> merged -> released (live)
   \________________________________________________/
                         -> abandoned
```

| stage | how it is reached | time recorded |
|---|---|---|
| `claimed` | `claim` | `started_at` |
| `building` | owner: `stage <id> building` | when declared |
| `pr_open` | owner: `stage <id> pr_open --pr N` (or `heartbeat --pr N`), **or** observed: an open PR on GitHub for the claim's PR number or its branch | PR `created_at` when observed, else when declared |
| `ci_green` | observed: every required status check of the base branch (`branches/<base>/protection/required_status_checks`; all checks if unreadable) completed successfully on the PR's **head SHA** (`commits/<sha>/check-runs`) | latest `completed_at` of those checks |
| `merged` | observed: PR `merged_at` | `merged_at` |
| `released` | observed: the merge commit is an ancestor of the SHA of a `release_pins/apply-*.json` receipt (earliest after the merge) or of the served SHA (`CURRENT` + `BUILD_SHA`) | that receipt's `at`, else the deploy receipt's `at` |
| `abandoned` | `release --status abandoned`, or lost a claim race | `ended_at` |

- Only `building` and `pr_open` can be declared. `ci_green`, `merged` and `released` need evidence.
- A stage time, once observed, is kept. The **current** stage can move back: a new push that fails CI shows
  `pr_open` with "CI failing" while `ci_green`'s earlier time stays in the timeline.
- **Files are freed at `merged`.** `claim`, `check` and the pre-commit gate refresh a conflicting holder from
  GitHub before refusing; a holder whose PR merged no longer blocks. With GitHub unavailable the holder keeps
  blocking.
- **The card stays until `released`**, then compaction archives it 7 days later with its lifecycle cache
  (`AgentClaimArchive@v1` gains `lifecycle` and `stage_at_archive`).
- `release --status done` before the merge is fine: the claim stops blocking and its card follows its PR to
  `released`.

**GitHub access is read-only and bounded.** Only `gh api --method GET repos/<owner>/<repo>/...` (pulls, pulls by
head branch, required status checks, check runs, compare). Every call has a timeout (8 s,
`--gh-call-timeout`). The first hard failure (gh missing, timeout, auth error) stops further calls for that
refresh. At most 40 claims are observed per refresh. A known merge is never asked again. Repo: `origin` remote,
else `TRADEAI_AGENT_CLAIMS_REPO`, else `PatsKiller/tardeai`.

**Caching.** The CLI writes `lifecycle/<claim_id>.json` (`sync --apply`; `claim`/`check`/`precommit` when they
refresh a conflicting holder; `compact --apply`). The API never writes: it serves the cache files plus an in-memory
observation refreshed in a background thread every 120 s (stale-while-revalidate), so no request waits on GitHub.
`--no-gh` / `AGENT_CLAIM_NO_GH=1` skip GitHub; release receipts are still read.

## 10. Pre-commit gate, policy-gated (2026-10-23)

`scripts/agent_claim_precommit.sh` runs `agent_claim.py precommit` on the staged files.

| AGENTS.md | staged file held by another live session | staged file not covered by a claim of this session/branch |
|---|---|---|
| below 20.0.0, or 20.0.0+ not ACTIVE, or unreadable | `WARN` (holder, branch, since), exit 0 | `WARN`, exit 0 |
| 20.0.0 or later **and** ACTIVE | `BLOCK` (holder, branch, since), exit 1 | `BLOCK`, exit 1 |

- **Policy state** (`agent_claim_board.claim_policy_state`, the `or_later` reading): the control block's
  `Policy-Version` >= 20.0.0, its `Status` ACTIVE, and that version's version-history row beginning ACTIVE. Read on
  every run; no cache and no environment override. `ops_controls_core.policy_state` was not reused because it also
  requires the §27.3 heading, which is specific to Ops Controls.
- **Covered** means a live, not-taken-over claim of this `AGENT_CLAIM_SESSION` or of the current branch whose paths
  (file, directory or glob) include the staged file and which has not merged.
- **Override:** `TRADEAI_CLAIM_OVERRIDE=<reason>` lets the commit through and appends an `AgentClaimOverride@v1`
  line to `claims_history.jsonl` (time, reason, session, vendor, branch, host, policy version, staged paths,
  uncovered paths, conflicting claims). If that line cannot be written, the override is refused.
- **The gate itself fails** (crash, import error): the hook reads the policy with a stdlib-only parser and blocks
  only when 20.0.0+ is ACTIVE; otherwise it warns and the commit continues.
- Open draft PRs (the cloud-agent signal) stay a `check` warning and are not part of the gate.
