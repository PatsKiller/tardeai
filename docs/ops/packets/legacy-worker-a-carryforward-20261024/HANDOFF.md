# Worker A source handoff to W8

Status: FROZEN SOURCE CANDIDATE; combined acceptance belongs to W8
Owner: codex-legacy-worker-a-carry-20261024
as_of: 2026-10-24
Measured at: accepted base d635873e1063efb8a9ff8e8ce542654ed2ef7654
Design-Task: DSN-20261024-stale-n8n-set-P1-T1

The source commit containing this handoff is the non-config Worker A package. Its parent
`9a478b9969b3be9067596d3acafed1f4cf86408c` contains only the 19-line advisory policy-reader
import decoupling. Include both commits in W8's one combined package. The existing Ask quality
head `87a6d1d0f` has disjoint nullable-cost/operator-request hunks; retain both during normal integration.

W8 config checkpoint: `5e63dbce307b6936c0c9848b54b08b5e980a04d6`.
Source branch: `work/DSN-20261024-legacy-worker-a-carry-P1-T1`.
Source worktree: `/home/johnclaw/wt-codex-legacy-worker-a-carry-20261024`.
Normal claim continuation: `20261025T001613Z-codex-91c0b1d7`; its predecessor
`20261025T001029Z-codex-83d5b9e8` released the Ask contract path after the minimal commit.
The source claim is released normally after source freeze, so W8 may ordinary-claim its listed paths.
No override or forced takeover is needed.

Scope: verified non-config hunks from `8ba33bd6c4612770a71a814874632eaba3b19f6e`, plus ONLY
`jsonl_retention` and its purge-path inventory entry. All accepted C1 KEEP_FOREVER rows and
other disk settings survive. The three W8 operational config files are untouched. Six lane ids only;
no seventh Schwab contract. Five runnable lanes remain SHADOW/dry_run; quote refresh stays inert.
Archive contract review cites the operator's 2026-10-24 legacy carryforward directive; activation
remains separate. No runtime retention apply, broker, sender, scheduling, release or remote write occurred.

Source validation before this candidate: 43 hidden-PG helper/contract/policy tests passed, Ruff passed,
coverage and host-path ratchets passed, dark-contract and retention-policy ratchets passed. Original
archive tests cover actual temporary JSONL files, byte accounting/manifests/tripwires, concurrent writers,
recreated live files, recovery, long-held fds, market-window/apply refusals, and read-only previews.
Configuration-dependent acceptance requires combining this source with W8's frozen config.

Run the 12-file affected profile from the previous 848-case run, plus the contract/research tests and
W8's safety suite, with `TRADE_AI_CI=1` and psycopg2 hidden. List and runner are in
`~/.cache/rtc/legacy-worker-a-carryforward-20261024/{affected-files.json,run_hidden.py}`.
Run ratchets, lane/health/relay/DSA checks, CIO completeness, docs index regeneration and the frontend
build on the exact combined source. Record failures truthfully; do not mark publication ready from
this source-only helper result. W8 owns the sole combined reviewed publication; no source PUSH_NEEDED.
