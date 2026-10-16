# Self-heal Claude Code fixer — code defects fixed in iterations, shipped as a tested PR

```
Status:      PROPOSED (code + PAUSED registry row; DISARMED; push/PR blocked until AGENTS.md 24.11 is ACTIVE)
as_of:       2026-10-16
Base:        n8n/self-heal-tranche-20261016 (PR #1828, OPEN) at f752e3e38 — stacked on it; retarget to main when #1828 merges
```

Operator, 2026-10-16: "with the self-fixing in some of these procedures, I just don't want the regular LLM routing.
I want it to connect into Claude Code to fix it in iterations. This is supposed to be smart."

## 1. What it does

The self-heal tranche (`scripts/n8n_failure_diagnosis.py`, `scripts/lib/n8n_self_heal.py`) classifies an n8n lane
failure as `transient`, `code_error`, `auth` or `unknown`. Transient failures stay with the self-heal tier (rerun,
reap). A `code_error` is never rerun: the diagnoser **publishes an `N8nCodeDefect@v1` record** (`code_defect_hook`,
consumer `claude_code_iterative_fix`, `consumer_status: pending_consumer`). **This lane is that consumer** — not a
second queue — and, instead of the governed bridge (grok → chatgpt →
DeepSeek), runs headless **Claude Code** in an isolated worktree, in iterations, until a regression test that fails on
`origin/main` passes with the fix and the PR-profile CI is green. It then opens one PR labelled `self-heal-fix`, which
goes through the normal review → merge → release-window path. It never merges.

| Piece | Path |
|---|---|
| CLI / side effects (worktrees, claude, pytest, git, gh) | `scripts/self_heal_fixer.py` |
| Decisions (pure: lifecycle, contract intake, prompt, backends, diff guard, gates, repair memory, shadow router) | `scripts/lib/self_heal_fixer.py` |
| Independent evaluator (acceptance; never reads backend claims) | `scripts/lib/self_heal_fix_evaluator.py` |
| Config (caps, allowlists, refuse patterns, policy marker) | `config/self_heal_fixer.json` |
| Registry row (PAUSED, KEEP_ON_CRON, host cron) | `config/lane_registry.json` `self-heal-fixer` |
| n8n: never runnable | `config/n8n_run_allowlist.json` `blocked_reasons.self-heal-fixer` |
| Tests (mocked claude CLI, tmp git repos) | `tests/test_self_heal_fixer_20261016.py` |
| Today's incident fixture | `tests/fixtures/self_heal_fixer/daily_incubator_refresh_20261016.json` |

## 2. What already existed (reused, not duplicated)

- **`scripts/claude_escalation_handler.py`** (`claude-escalation-handler`, cron + systemd source in
  `communication_events`): health-agent escalation queue, Tier 1 allowlisted `retry_cmd`, Tier 2/3 local LLM, Tier 3c
  `claude -p … --output-format text` for **diagnosis text only** (no tools, no edits, no tests).
- **`scripts/coder_dispatch.py`** + `config/coder_backends.json`: multi-coder router (claude_code first). Worktree →
  compile/test → advisory diff or PR. One shot, no iteration, no red-first proof, `--permission-mode acceptEdits` with
  no tool allowlist, inherits the full env. **Operator HOLD 2026-10-16** (`config/lane_cutover_policy.json` holds:
  `coder-dispatch: operator_hold_20261016: disposition RETIRE; cron already commented`). Why it was stopped:
  AGENTS.md §24.5 — in PR mode it would push and run `gh pr create` from cron (L556, `JOB_REDUCTION_DEEP_PASS.md`
  §11); #1672 made push need `--allow-push` + `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` and never from `--from-queue`.
- Reused here: the claude binary and backend registry entry (`config/coder_backends.json` `claude_code`), the
  worktree-isolation pattern, the guard ledger peek (`scripts/lib/guard_push_auth.py`), the push budget and pre-push
  hook unchanged, the diagnoser's escalation shape and heal states (`recovery_requested` … `incident_resolved`).
- Not reused: coder_dispatch's single-shot flow and its env/permission model. **`coder-dispatch` stays retired**
  (hold untouched; this PR edits neither `coder_dispatch.py`, its cron line, nor its registry row).
- **The producer contract** (#1828): `scripts/n8n_failure_diagnosis.py` `code_defect_hook` writes `N8nCodeDefect@v1`
  into each diagnosis record's `code_defect` (`data/runtime/n8n_diagnoses/diagnoses.jsonl`) and the escalation's
  `fix_path`: `defect_id = cd-<lane>-<signature>-ep<N>`, `lane`, `signature`, `episode`, `failure_kind`,
  `failure_class`, `evidence {siem_id, incident_key, event_type, failed_run_id, coordination_ledger,
  diagnoses_store, receipt, evidence_pack}`. The producer never edits code or opens a PR; the consumer never writes
  the producer's store (it records consumption in its own state and repair memory). The tests build records with
  the producer's own function, so a contract drift breaks the consumer's tests.

## 3. Lifecycle

```
fix_requested ─▶ fix_attempting (k=1..N) ─▶ fix_pr_opened ─(operator merge + release)─▶ fix_deployed
      │                 │      │                  ▲                                        │
      │                 │      └▶ fix_ready_local ┘ (push blocked: 24.5; operator may push)   ▼
      │                 ├▶ fix_failed  (budget / no progress)  ─▶ P1 once           output_recovered
      └▶ fix_refused ◀──┴─ (diff guard hard refusal, refused lane) ─▶ P1 once            │
                                                                                       ▼
                    fix_pr_opened ─(PR closed unmerged)─▶ fix_closed            incident_resolved
```

- **A fix PR is not a heal** (`F.HEALED = {output_recovered, incident_resolved}`). `fix_deployed` needs the merge
  commit to be an ancestor of the release `CURRENT/GIT_SHA`; `output_recovered` needs the lane's registry output
  signal to advance after `deployed_at`; `incident_resolved` needs the diagnoser's escalation for the incident to be
  gone or healed.
- Illegal transitions raise (`TransitionError`), e.g. `fix_pr_opened → incident_resolved`.

## 4. Trigger and dedupe (consumer of N8nCodeDefect@v1)

- Source: `N8nCodeDefect@v1` records addressed to `claude_code_iterative_fix` — the last 5,000 lines of the
  diagnoses store plus the diagnoser state's escalations (`fix_path`); anything else (other schema version, other
  consumer) is ignored. `--incident FILE` takes one record (`{"code_defect": …, "receipt": …, "registry_row": …}`).
  The live diagnoser state on main predates the contract, so automatic intake starts when #1828 is merged and live.
- Evidence: the run named by `evidence.failed_run_id` from the coordination ledger (sqlite opened `mode=ro`; falls
  back to the lane's newest `RUN_FAILED`): argv, `stderr_tail`, `code_sha`; the registry row; the final exception; a
  repro note (the failing command is recorded but **never run** — reproduce in a hermetic pytest). Credential-shaped
  text is redacted.
- **One job per `defect_id`, ever** (a new episode is a new defect id); one active job per `(lane, signature)`;
  after `fix_failed` / `fix_refused` / `fix_closed`, a 72 h cooldown for that signature.
- Refused at intake (and escalated P1): lanes or scripts matching broker/order/stop/execution patterns, scripts on
  protected paths, and lanes in `lane_cutover_policy.json` `holds`.

## 5. The fixer and its iterations

- Two worktrees per job under `/tmp/tradeai_self_heal_worktrees/`: the fix worktree on a new branch
  `self-heal-fix/<lane>-<sig8>-<ts>` off `origin/main`, and a detached base worktree at the same SHA.
- Claude runs as `claude -p --output-format json --permission-mode dontAsk --tools Read,Edit,Write,Glob,Grep,Bash
  --allowedTools <list> --disallowedTools <list> --max-budget-usd <x> --setting-sources project --strict-mcp-config
  --no-session-persistence`, prompt on stdin, cwd = fix worktree. `dontAsk` denies every tool call not pre-approved:
  Bash is allowed only for the harness's pytest wrapper and read-only git; push/commit/gh/crontab/systemctl/psql/
  curl/bash/sh/python/rm/web are denied. `--setting-sources project` matters: `~/.claude/settings.json` pre-approves
  `gh pr merge:*` and `cio_phase2_exact_main_deploy.sh` for interactive sessions (measured 2026-10-16); those rules
  are not loaded (and deny rules win anyway). The child env is `HOME PATH USER LOGNAME LANG LC_ALL TERM TMPDIR` +
  `TRADE_AI_CI=1` + a scratch `TRADEAI_STATE_ROOT`: no DB, broker or provider credential reaches the model or its
  shell.
- **Sandbox (bubblewrap).** pytest executes model-written code, so a prompt rule is not enough. Every test run — the
  model's (through the wrapper `<worktree_root>/<job>-bin/pytest`, which is outside every writable path), red-first,
  targeted and the PR-profile CI — runs under `bwrap --unshare-net --ro-bind / / --tmpfs /run --tmpfs /tmp …`: no
  network at all (no localhost Postgres — the host's 5432 is reachable outside, refused inside, pinned by a test), the
  filesystem read-only except the two worktrees, their git admin dirs and the scratch state; release trees,
  persistent state, `~/.cursor`, `~/.claude`, `~/.config/gh`, `~/.ssh`, `.pgpass`, `~/.n8n`, the repo's `.env`,
  `data/`, `logs/` hidden. `sandbox.enabled` with bwrap missing fails the job (`sandbox_unavailable`).
- The prompt quotes **AGENTS.md §0 verbatim from the base commit** (no rails → no prompt), the hard limits, the
  procedure (failing test first → fix → targeted tests → register the test), and the evidence pack.
- Per iteration the **harness** (not the model) decides:
  1. diff guard (§6) — a hard refusal ends the job as `fix_refused`;
  2. **red-first**: the changed tests are copied onto the base worktree and must FAIL there;
  3. targeted tests (the changed test files) must pass in the fix worktree;
  4. `run_cio_hardening_ci.py --profile pr --base <base_sha> --include-worktree --no-tail` must pass.
- Iteration k+1 gets iteration k's failing set, guard refusals, red-first verdict and test output tail.
- Stops: pass; `max_iterations` (4); `max_minutes` (90); `max_cost_usd` ($12; each call capped at
  `min($4, remaining)`); **no progress** = the same non-empty failing set twice in a row.
- Per-iteration evidence in the job and in `data/runtime/self_heal_fixer/<job_id>/`: diff stat, tests run, red-first,
  targeted/CI exit codes, failing set, cost, seconds, prompt, claude result, test log; `fix.patch` and `pr_body.md`
  on success.
- On success the harness commits (trailers from config). It pushes **once** with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1`
  and `TRADEAI_REMOTE_PUSH_OVERRIDE` removed from the env (the pre-push hook and 2-push budget bind; a new branch
  needs one push), then `gh pr create --label self-heal-fix` (falls back to no label if the label is missing).
- On failure: `fix_failed` and **one P1 escalation** (`SelfHealFixEscalation@v1`, with what each iteration tried)
  appended to `data/runtime/self_heal_fixer_escalations.jsonl`. The fixer sends nothing itself; wiring that outbox
  into the fan-in/comms gateway is a follow-up.

## 5a. Backends, the static selector, and qualifying Codex later

- Contract `SelfHealFixBackend@v1`: cwd = the fix worktree, prompt on stdin, the credential-free env, tests only via
  the sandboxed pytest wrapper; the only output that counts is the files it changed. Kinds: `claude_cli` (the argv
  above) and `cli_stdin` (generic `argv_template`).
- `config/self_heal_fixer.json` `selector`: **static**, `backend: claude_code`. A backend is selectable only when
  `enabled` AND `qualified`. `codex_cli` is wired (`cli_stdin`, `codex exec --sandbox workspace-write
  --skip-git-repo-check -`) but `enabled: false, qualified: false`.
- Qualifying Codex = verify the argv against the installed CLI; it passes the same acceptance scenarios (the test
  `test_a_second_backend_kind_passes_the_same_acceptance_scenario` already runs the full loop through a second backend
  kind and the same evaluator); one live seeded-defect job judged by the evaluator; then an operator config PR flips
  `qualified`. No code change.

## 5b. Independent acceptance (`scripts/lib/self_heal_fix_evaluator.py`)

- **Local** (`SelfHealLocalAcceptance@v1`) reads only harness facts: a regression test exists, it **failed on the
  base commit**, it passes with the fix, `run_cio_hardening_ci.py --profile pr` passed in the worktree, the diff guard
  refused nothing. The backend's result (`ok`, `summary`, cost) is stored for the operator under `backend_result` and
  is never read by the evaluator — a test pins that a backend claiming success with a failing test is rejected.
- **PR head** (`SelfHealPrHeadAcceptance@v1`): `gh pr view --json headRefOid,statusCheckRollup`; `pass` only when every
  reported check passed, at least one ran, and the head is the SHA the harness pushed (`head_moved` otherwise).
- **Final** (`SelfHealAcceptance@v1`) = local accepted AND PR-head CI `pass`. Recorded on the job at every advance.
  The operator still merges; acceptance is evidence for that review, not a merge trigger.

## 5c. Repair memory and the shadow router

- `data/runtime/self_heal_fixer/repair_memory.jsonl` (`SelfHealRepairMemory@v1`), append-only, one row per
  `consumed`, per `iteration` (backend, selector, diff stat, diff sha256 + saved patch path, tests run, red-first,
  targeted/CI exit codes, failing set, local acceptance, cost, seconds), per `attempt_outcome`, and per lifecycle
  advance (`lifecycle:fix_pr_opened|fix_deployed|output_recovered|incident_resolved` with acceptance, merge and
  release SHAs). Keyed by `signature`, `defect_id`, `lane`, `failure_kind`.
- `shadow_route` scores each backend on that memory (Laplace-smoothed local acceptance, same `failure_kind` first)
  and records `{mode: shadow, used: false, chosen_static, recommended, agrees, scores}` on the job and in the
  outcome row. It never selects; adaptive routing is a later, separate decision.

## 6. Authority: the diff guard (code, not the model)

Hard refusal (job ends `fix_refused`, P1) when the diff touches any `diff_guard.refuse_paths` pattern: AGENTS.md /
CLAUDE.md / AI_WORK_POLICY.md, `.cursor/ .claude/ .githooks/ .github/ bin/`, the fixer's own code/config/tests,
`scripts/check_*.py` gates, guard/push-budget/test-impact modules, any `*allowlist*`, `*baseline*`, `*chokepoint*`,
`*ratchet*`, `*permission*`, `*approval*` file, the lane registry / cutover policy / `config/n8n_*`, crontab and
systemd files, `.env`/credential/secret/cookie files, broker/order/execution/2FA paths, the behaviour rail
(`cio_instrument_record.py`), SQL/migrations, and pytest configuration; or when a test is deleted, a test function
removed, an assert removed (net), or a skip/xfail/deselect/importorskip added. `scripts/run_cio_hardening_ci.py` is
**append-only inside `GATES`**: only string/bracket/comment lines, no removals. Soft refusals (empty diff, no
regression test, > 8 files or > 600 lines) go back to the model as feedback.

The fixer never merges, releases, edits crontab or systemd, restarts anything, touches broker code or credentials, or
writes the production DB (tests run with `TRADE_AI_CI=1` and a scratch state root; the ledger is opened read-only).
The AGENTS guard hook is **not installed for Claude Code** (`docs/ops/AGENTS_GUARD_HOOK.md`, measured 2026-10-14/15),
so these controls are enforced by the harness and by `dontAsk`, not by the hook.

## 7. Gating (DISARMED by default)

`--apply` attempts a job only when **all** hold:

1. an ACTIVE guard grant of tier `git-push` whose reason contains `self-heal-fixer` (peeked, never consumed);
2. fewer than `daily_job_cap` (3) jobs started today (ET); one job per cycle.

The push/PR step additionally needs `AGENTS.md` **at the job's base commit** to contain the heading
`## 24.11 Self-heal fix PRs from the self-heal-fixer lane` with `ACTIVE` on that line. Without it the job ends at
`fix_ready_local`: committed on a local branch, `pr_body.md` and `fix.patch` written; an operator may push it by hand
(the next cycle then moves it to `fix_pr_opened` when `gh pr list --head <branch>` finds the PR).

Arming (operator, after the PR merges, is released, and the cron line is installed under a `cron` grant):

```
bin/guard grant git-push --for 8h --uses 4 --reason "self-heal-fixer arm 2026-10-17 daily cap 3"
```

Note: the pre-push hook enforces grant scope by branch/SHA, so this grant does **not** authorize pushes by itself
(it is unscoped for any branch and is neither honoured nor consumed by the hook); the fixer's push is authorized by
`TRADEAI_REMOTE_PUSH_AUTHORIZED=1` within the budget, exactly like an agent push.

Install line (registry `scheduler.install_line`, a §17 operator decision under a `cron` grant):

```
40 9-18 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/tradeai_self_heal_fixer.lock timeout 10800 $PY scripts/self_heal_fixer.py --cycle --apply >> logs/self_heal_fixer.log 2>&1  # TRADEAI_LANE self-heal-fixer
```

Weekdays 09:40–18:40 ET is inside the operator's scheduled-paid-LLM window (§9.3 / §12).

## 8. Dry run (2026-10-16, today's `daily-incubator-refresh` incident, backend stubbed)

```
TRADEAI_STATE_ROOT=<scratch> .venv/bin/python scripts/self_heal_fixer.py --cycle \
  --incident tests/fixtures/self_heal_fixer/daily_incubator_refresh_20261016.json --out <scratch>/shf_dry
```

The fixture is the real ledger receipt for `d:daily-incubator-refresh:live:20261016T0815` (RUN_FAILED exit 1,
`conn.rollback()` in the except handler raised `psycopg2.InterfaceError: connection already closed`, masking the
original error) plus the `N8nCodeDefect@v1` record the producer's own `code_defect_hook` emits for it
(`defect_id cd-daily-incubator-refresh-ad840af40ea8e971-ep1`, `failure_kind code_error:InterfaceError`). Output: one
job `shf-5cd9c023a9-1` (`fix_requested`), backend `claude_code` (static), arming `false` ("active git-push grant does
not name self-heal-fixer"), policy `push_allowed: false` (24.5), outcome `dry_run_planned`, prompt 8,243 chars with
§0 verbatim and the stderr tail, planned branch `self-heal-fix/daily-incubator-refresh-ad840af4-<ts>`, shadow route
recorded (`used: false`), no worktree, no model call, no state written. Files:
`job.json`, `evidence.json`, `prompt_iter1.md`, `plan.json` (backend argv, bwrap sandbox prefix, env names),
`receipt.json`.

## 9. Policy amendment needed (operator token)

AGENTS.md 12.0.0 §24.5 says a cron line, timer, n8n-fired lane or daemon **never pushes, opens a PR or writes to a
remote**. The fixer pushes one branch and opens one PR from a scheduled lane, so it needs a named exception. The
amendment widens what a scheduled job may do, so by the version policy it is **MAJOR → 13.0.0**. Proposed text,
inserted after §24.10:

```markdown
## 24.11 Self-heal fix PRs from the self-heal-fixer lane (13.0.0, ACTIVE; amends 24.5 for one lane)

- **One named exception to 24.5.** The registered host lane `self-heal-fixer` (`scripts/self_heal_fixer.py`,
  `config/self_heal_fixer.json`) may push ONE new branch named `self-heal-fix/…` and open ONE pull request labelled
  `self-heal-fix` per fix job, with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1`, within the push budget and never with an
  override. Nothing else in 24.5 changes: no other scheduled job pushes, and this lane never merges, releases,
  pushes to `main`, or force-pushes.
- **Only for a code defect, only with proof.** The job starts from a self-heal diagnosis of class `code_error`; the
  PR is opened only after a regression test that fails on the base commit passes with the fix and
  `run_cio_hardening_ci.py --profile pr` is green in the job's worktree.
- **Code-enforced limits.** The diff guard refuses any change to policy, guard, CI-gate, allowlist, baseline,
  permission, registry, crontab, systemd, credential, broker/order/execution or migration paths, and any test
  deletion, skip or assert removal; the model runs with `dontAsk`, a tool allowlist and a credential-free env.
- **Armed by the operator.** DISARMED unless an active guard `git-push` grant names `self-heal-fixer`; at most
  `daily_job_cap` jobs a day. A fix PR is not a heal: the incident closes only at `incident_resolved` (deployed code
  plus recovered output).
```

Ratification token (bind PR number and head SHA when the amendment PR exists):

```
APPROVE_AGENTS_POLICY_13_0_0 <PR> <sha>
```

Until then the lane is useful but conservative: it produces a tested local branch + PR body for the operator to push.

## 10. What is proven, and what is not

| Step | Proven | How |
|---|---|---|
| defect record → job (consumer of N8nCodeDefect@v1) | yes, offline | producer's `code_defect_hook` output → `code_defects` → `admit` (tests; dry run on the real incident) |
| failing test first (red on base) | yes, offline | tmp git repo + mocked backend; harness copies the test onto the base worktree and requires failure |
| patch + targeted tests + PR-profile CI | yes, offline | same loop; CI is a stub `run_cio_hardening_ci.py` in the tmp repo; the real PR profile ran in the bwrap sandbox on this host (selection only, §11) |
| commit → push → PR (labelled) | yes, offline | real `git push` to a tmp bare remote, fake `gh` records `pr create --label self-heal-fix` (only behind the 24.11 gate) |
| PR-head CI acceptance | yes, offline | fake `gh pr view` statusCheckRollup → evaluator |
| merge → fix_deployed → output_recovered → incident_resolved | state machine yes, offline | fake `gh` MERGED + release SHA ancestry in a tmp repo + output signal file + diagnoser escalation cleared |
| a real Claude Code run on a real defect | **no** | needs arming (grant) — the first live job is the live proof |
| a real PR on GitHub, real CI on its head | **no** | needs the 24.11 amendment ACTIVE (or an operator push of a `fix_ready_local` branch) |
| a real merge, release, output recovery | **no** | operator merge + release window, then the lane's next run |

## 11. Sandbox smoke (2026-10-16, host)

The fixer's bwrap prefix around `run_cio_hardening_ci.py --profile pr --base origin/main --include-worktree
--print-selection` in a real detached worktree of this repo: selection ran, exit 0 (git works with only the worktree
admin dir writable). In the same sandbox `~/trade-ai-releases` lists 0 entries, the repo `.env` reads
`Permission denied`, and a write to the repo root fails `Read-only file system`. The test
`test_sandboxed_loop_runs_tests_without_network` runs the whole loop sandboxed and asserts `127.0.0.1:5432` is refused
inside (it accepts outside on this host); it skips on a runner without usable bubblewrap.

## 12. Open items

- The tranche (`n8n/self-heal-tranche-20261016`, #1828) must merge first: this PR is stacked on it (retarget to
  `main` after). Once both merge, `docs/ops/n8n_self_healing.md` can name this lane as the consumer (left untouched
  here to keep #1828's files conflict-free). `consumer_status` stays the producer's field; consumption is recorded
  in this lane's state and repair memory.
- Wire `data/runtime/self_heal_fixer_escalations.jsonl` into the fan-in (P1 once) — today it is a written outbox.
- Create the `self-heal-fix` label once (`gh label create self-heal-fix`); the fixer falls back to no label.
- First live run is the first real check of the `claude` argv against CLI 2.1.299 (tests use a mocked CLI only).
