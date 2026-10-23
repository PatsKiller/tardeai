# Agent claim board — who is working on which files

```
Status:      ACTIVE (code); compaction timer NOT INSTALLED; pre-commit check NOT WIRED (operator steps below)
as_of:       2026-10-22T22:30-04:00
Measured at: origin/main 0f5bf2453 (branch feat/agent-claim-board-20261022); not measured live
```

Operator-approved design, 2026-10-22. One board that every coding-agent session uses before it edits files:
Claude, Codex and Cursor are **equal peers**. There is no master agent and no coordinator process. Each
session claims the files it will touch; a second session asking for an overlapping path is refused and told
who holds it, on which branch, since when.

The rule text that makes claiming mandatory ships separately as **AGENTS.md 19.1.0**. Until then the
pre-commit check only warns.

## 1. What it is

| piece | path |
|---|---|
| library | `scripts/lib/agent_claim_board.py` (`AgentClaim@v1`, `AgentClaimBoard@v1`) |
| CLI | `scripts/agent_claim.py` — `claim`, `heartbeat`, `release`, `list`, `check`, `compact` |
| pre-commit check (warn-only) | `scripts/agent_claim_precommit.sh` — not wired; see §6 |
| read-only API | `GET /api/v2/coordination/claims` (`?active=1` hides done/abandoned) |
| Command Center | Coordination → **Who's working** (`/v3/coordination?tab=agents`) |
| weekly compaction | `linux_launchers/systemd/tradeai-agent-claim-compact.{service,timer}`; lane `agent-claim-compact` (`NEVER_SCHEDULED`) |
| tests | `tests/test_agent_claim_board_20261022.py` (CI gate `agent_claim_board_20261022`) |

## 2. The store

Default directory `~/trade-ai-releases/persistent-state/data/coordination/claims/`. Override it with
`--claims-dir` or `TRADEAI_AGENT_CLAIMS_DIR`.

- **One JSON file per claim**, `<claim_id>.json`. Fields: `claim_id`, `vendor`, `session`, `agent`, `task`,
  `paths` (files, directories or globs), `branch`, `pr`, `started_at`, `heartbeat_at`, `status`
  (`active` | `done` | `abandoned`), `note`. Also `host`, `takeover_of`, `ended_at`, `released_by`.
- **Created atomically.** The claim is written to a unique temp file opened `O_CREAT|O_EXCL`, fsynced,
  then `os.link`-ed to its final name. `link` fails rather than replace an existing file, so one claim can
  never be overwritten by another.
- **No shared-file writes on the claim path.** `heartbeat` and `release` rewrite only the caller's own file
  (temp + `os.replace`). Scan + create run under an `flock` on `<dir>/.claim.lock`, an empty file that is never
  written. Fallback for a filesystem that ignores flock: each claimant re-scans after writing. If an
  overlapping live claim sorts earlier by `(started_at, claim_id)`, the later claimant marks its own claim
  `abandoned` ("lost race") and reports the conflict.
- `claims_history.jsonl` in the same directory is **append-only** and written only by `compact`.

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
- **Compaction.** A claim becomes eligible when it is `done` or `abandoned`, or `active` but stale, and its last
  activity is more than 7 days old. `compact` appends it to `claims_history.jsonl` (fsynced, then read back
  and matched by sha256) and only then removes the claim file. A file that changed during the archive, or
  whose archive line cannot be read back, is kept. Looking up a compacted claim id answers from the history
  ("compacted into … line N"), so a compacted claim never reads as one that never existed. Live claims are
  never touched.

## 4. Agent workflow (any vendor)

```bash
export AGENT_CLAIM_VENDOR=codex AGENT_CLAIM_SESSION=<your session id> AGENT_CLAIM_AGENT=<name>
python3 scripts/agent_claim.py claim --task "fix X" --paths scripts/lib/x.py 'tests/test_x_*.py' --branch feat/x
#   -> prints the claim_id; exit 1 + holder/branch/since if someone else holds an overlapping path
python3 scripts/agent_claim.py heartbeat <claim_id> [--pr 1965]      # at least every 2 h while working
python3 scripts/agent_claim.py check --paths $(git diff --cached --name-only)   # exit 1 on conflict
python3 scripts/agent_claim.py release <claim_id> --status done      # or abandoned
python3 scripts/agent_claim.py list [--all] [--json]
```

Exit codes: `0` ok · `1` conflict or refused claim · `2` usage or ownership error.

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

The route is GET only (anything else → 405 `read_only`). It never creates the directory. It sits behind the
default `config/cc_auth.yaml` policy like every other `/api/v2` read, so no new cc_auth entry was needed.

The Command Center tab **Coordination → Who's working** polls this every 30 s. Every chip, column header and
cell has a tooltip. Finished claims are hidden behind "show finished". An unavailable board says so: "not the
same as nobody working".

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
2. **Pre-commit warning.** `.githooks/` is an operator-only surface (AGENTS.md §23.13 exclusion; guard
   `governed_globs`; `config/ci_risk_tiers.json` `policy_and_guard`), so this change does not edit it. To wire
   the warn-only check, add this line to `.githooks/pre-commit` after the secret scan and before the chain to
   `scripts/githooks/pre-commit`:

   ```bash
   bash "$ROOT/scripts/agent_claim_precommit.sh" || true
   ```

   The script always exits 0. Set `AGENT_CLAIM_NO_GH=1` to skip the draft-PR lookup when offline.
3. **AGENTS.md 19.1.0** (separate package) makes claim-before-edit mandatory and turns the hook from warn to
   block. Until then the board is advisory.

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
- Before 19.1.0 an agent can skip claiming, and the hook only warns.
