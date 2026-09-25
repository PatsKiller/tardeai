# Trade AI Engineering Standard

Status:      PROPOSED (v1.0.0; becomes ACTIVE with the AGENTS.md amendment that links it)
Owner:       platform
as_of:       2026-09-25T09:30:00-04:00
Measured at: base 1c60ecb42 / served 1c60ecb42

This standard describes the conventions this repository **actually enforces**, and names each
enforcer. A rule marked **UNENFORCED** is still expected, but nothing checks it. Don't cite it
as a control. AGENTS.md and AI_WORK_POLICY.md outrank this document. When they disagree,
they win, and the disagreement is a defect in this file.

Legend for "Enforced by":
- **CI:** job name in `.github/workflows/`
- **ACC:** `scripts/ai_local_acceptance.sh`
- **HOOK:** `.githooks/`
- **BUILD:** `apps/command-center-v3` `npm run build`

## 1. Python

| Rule | Enforced by | Covers | Legacy exceptions |
|---|---|---|---|
| Ruff lint, `F` rules, line length 120, target py310, pin `ruff==0.16.2` | **UNENFORCED on PR diffs.** `scripts/agent_changed_file_quality.py` exists, but CI runs it only on its own governance files (`agent-governance.yml:92`), and `ai_local_acceptance.sh` never runs Ruff. Run it yourself: `.venv/bin/ruff check <changed .py>` | changed Python files (by convention) | `pyproject.toml` ignores `F401/F811/F841` globally, plus per-file for `tests/**` and `scripts/api_v2.py` |
| `ruff format --check` | **UNENFORCED** (same reason). `agent_changed_file_quality.py` would fail on legacy unformatted files you touch | changed Python files | **Ratchet, stated honestly:** there's no baseline file. A file you edit is formatted only if it already was; don't mass-reformat a legacy file in a behaviour PR (it hides the change). Reformatting belongs in its own PR |
| Every script compiles | CI `aif-financial-senses-integration` → `tests/test_every_script_compiles.py` | `scripts/**/*.py` | — |
| Type checking (mypy/pyright) | **UNENFORCED** | — | — |
| Imports must not hard-require undeclared deps. CI installs only `pytest pyyaml` (+`requests` in cio-hardening) | CI `cio-hardening` (fails at import) | code reached by CI tests | Reproduce locally by shadowing the module with one raising `ModuleNotFoundError(name=…)` (a plain `ImportError` gives a false failure) |
| CRLF files stay CRLF; no line-ending churn | CI `cio-hardening` + ACC → `scripts/check_line_endings.py` | changed files | — |

## 2. Tests

| Rule | Enforced by | Covers | Legacy exceptions |
|---|---|---|---|
| A new `tests/test_*.py` must be registered in a CI route (usually a themed suite in `scripts/run_cio_hardening_ci.py`) | CI `cio-hardening` + ACC → `scripts/check_test_coverage.py --fail-on-new` | all test files | `UNLISTED_BASELINE` (958 files) in that script; it may only shrink |
| Registering a test edits a governed control surface. Regenerate evidence **last** | CI `agent-governance` → `scripts/validate_sop_evidence_integrity.py`; `docs/implementation/maturity-program/sop-1.2.0-*/` digests | `config/sop_120_control_surface.manifest.json` paths | — |
| Behaviour + refusal + preservation-on-failure tests for stateful producers | **UNENFORCED** (review expectation) | — | — |
| Tests never write live stores or the live M2 shadow | `tests/conftest.py` routing + `scripts/lib/m2_live_shadow_guard.py` (refuses the live shadow under pytest) | memory/bitemporal tests | — |
| Tests that exercise production DB grants run as a role with those exact grants | **UNENFORCED** except `tests/test_memory_agent_least_privilege_20260924.py` | memory writer | — |
| Alarm paths must fire, not be swallowed | `tests/test_alarm_fires*.py`, `tests/test_no_swallowed_alarms.py` | alarm modules | `config/alarm_firing_baseline.txt` (163), `config/alarm_swallow_baseline.txt` (96) |

## 3. TypeScript / React (Command Center v3)

| Rule | Enforced by | Covers | Legacy exceptions |
|---|---|---|---|
| `tsc` type check | BUILD (`npm run build` runs `tsc`); CI `cc-header-truth-ci` (`npx tsc`, path-filtered) | `apps/command-center-v3/src` | — |
| Design tokens only (no ad-hoc colours etc.) | BUILD → `scripts/check_design_tokens.sh` | v3 sources | `config/design_token_baseline.json` |
| Unit tests for surface libs (freshness, envelope, authority, projection …) | BUILD (node test files listed in `package.json` `build`) | `src/lib/*.test.ts` | — |
| Route-level UI truth (Playwright) | CI `cio-truth-gates-ui-validation`, `cc-surface-agreement-ci`, `active-trader-live-motion-ui-validation` (path-filtered) | specific routes | Most routes have no e2e spec |
| ESLint / Prettier | **UNENFORCED** (none configured) | — | — |
| No hardcoded runtime facts (model name, maturity counts, balances) rendered as live | **UNENFORCED**. Known violation: `src/pages/AgentsHub.tsx:26` | — | Tracked in `docs/architecture/AGENT_SERVICE_MAP_2026-09-25.md` §4 |

## 4. SQL and migrations

| Rule | Enforced by | Covers | Legacy exceptions |
|---|---|---|---|
| Migrations are additive and idempotent (`IF NOT EXISTS`), with a `.down.sql` where reversible | **UNENFORCED** (122 files in `migrations/`, 15 with `.down.sql`) | `migrations/` | Pre-2026-09 files |
| No migration runner: applied with `psql -v ON_ERROR_STOP=1 -1`, `lock_timeout` set, tables backed up first | **UNENFORCED** (runbook practice; see `docs/ops/COGNITIVE_MEMORY_PRODUCTION_RUNBOOK.md`) | production DB | — |
| Production schema changes need a `db-write` guard grant whose reason names the change | **ADVISORY.** `bin/guard` hooks are wired only through `.cursor/hooks.json` (Cursor, pointing at another worktree). Claude Code and others have no repo hook, and the grant reason is never checked against the change | shell commands under Cursor | — |
| Destructive reset never on production or the live shadow | SQL guards in `sql/r10_*.sql` + `m2_live_shadow_guard.destructive_reset_permitted` | memory schemas | — |

## 5. Contracts, schemas and versions

| Rule | Enforced by | Covers | Legacy exceptions |
|---|---|---|---|
| Versioned contract names `Name@vN` must have a consumer, or declare `NO_CONSUMER_REASON` | CI `cio-hardening` + ACC → `scripts/check_dark_contracts.py --fail-on-new` | `scripts/**` | `KNOWN_DARK` census (36 entries, 2026-08-27) |
| Data domains declare writer, store, freshness | ACC → `scripts/check_data_source_authority.py` | `config/data_source_authority.json` | `config/data_source_authority_baseline.json` |
| Scheduled jobs are declared (owner, cadence, state, reason) | ACC → `scripts/check_lane_registry.py --fail-on-new` | crontab + user systemd timers | 518-entry inherited-debt baseline in the registry |
| Expected-ON units and flags | `scripts/check_expected_services.py` (read-only report) | `config/expected_services.json` (58 units + 2 flags) | Drift: `portfolio-server`, `cio-governed-bridge` undeclared |
| Payloads carry `as_of`, freshness and explicit UNAVAILABLE semantics | **UNENFORCED** generally; partial via v3 `surfaceFreshness` / `observationEnvelope` tests | — | — |

## 6. Logging, errors, egress

| Rule | Enforced by | Covers |
|---|---|---|
| All Telegram sends go through `telegram_alert.send_telegram` / the gateway chokepoint | `scripts/check_telegram_chokepoint.py` (baseline `config/telegram_chokepoint_baseline.json`) | `scripts/**` |
| LLM/provider egress only through approved routers | `scripts/check_provider_chokepoint.py` (baseline `config/provider_chokepoint_baseline.json`) | `scripts/**` |
| Fail-soft must be recorded (receipt/log), never silent | **UNENFORCED** except the alarm-swallow test above |
| Structured logging format | **UNENFORCED** |

## 7. Security and secrets

| Rule | Enforced by | Covers |
|---|---|---|
| No secret values or hardcoded chat IDs / broker names in tracked files | HOOK `pre-commit` (staged) + `pre-push` (whole tree) → `scripts/check_no_secrets.py`; values come from `.env` rendered from Bitwarden SM | all tracked files; opt-out `# hardcode-ok` only for routing fixtures |
| Secrets live in Bitwarden Secrets Manager; logical names in `config/secret_registry.yaml` | `bin/guard` marks `secret` never grantable (**advisory** outside Cursor) | — |
| Credentials never in argv (e.g. systemd `ExecStart` needs `$$VAR`) | **UNENFORCED** |

## 8. Comments and documentation

| Rule | Enforced by | Covers | Legacy exceptions |
|---|---|---|---|
| New docs carry a header (`Status:`, `Owner:`, `as_of:`, `Measured at:`) | `scripts/report_docs_inventory.py` counts `MISSING HEADER` (74 today); not a gate | `docs/**/*.md` | the 74 |
| `docs/INDEX.md` fingerprint matches the tree | CI `agent-governance` + ACC → `report_docs_inventory.py --check-index` (`merge=regenerate` in `.gitattributes`) | `docs/` | — |
| Comments explain *why* and cite an incident, issue or contract; runtime claims are labelled OBSERVED / CODE-ONLY / DOC-CLAIM / UNKNOWN with a SHA | **UNENFORCED** | — | — |

## 9. Remote, review and deploy

| Rule | Enforced by |
|---|---|
| Push only with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` + explicit operator intent (`AI_WORK_POLICY.md`); budget 1 (max 2) pushes per tranche | HOOK `.githooks/pre-push`. **Gap:** `.githooks/pre-push:19-35` + `scripts/lib/guard_push_auth.py:30-48` treat **any** active `git-push` guard grant as authorization **and** a budget override, without checking that its reason names this branch. While any git-push grant is active, the budget and branch scope are **not enforced** |
| Relationship between `bin/guard` and `AI_WORK_POLICY.md` | `AI_WORK_POLICY.md` never mentions `bin/guard`. The policy's authority is `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` + operator intent; the hook additionally accepts a guard grant as a substitute (gap above) |
| Force-push, history rewrite | user-level `~/.claude/settings.json` (Claude Code only) + GitHub `allow_force_pushes: false`. **Not** `bin/guard` |
| `cio-hardening` must pass before merge | GitHub branch protection (the **only** required check today) |
| `agent-governance` must pass before merge | **UNENFORCED** (the job runs on every PR but isn't required) |
| Only the operator merges; independent review of sensitive paths | **UNENFORCED**: 0 required reviews, `enforce_admins: false`, no CODEOWNERS, and `gh pr merge` isn't classified by any hook |
| Deploy = `prepare` then `promote`; verify live SHA and process `cwd` independently | `scripts/cio_phase2_exact_main_deploy.sh` (refuses a hybrid SHA; auto-rollback on failed health). `release-write` grant is **advisory** (the promote command isn't classified by the Cursor hook) |

## 9a. Hidden mutations in the standard tools (know before you run them)

- `scripts/regenerate_generated_files.sh` runs `git add -A` (lines 18, 34, 36). That contradicts
  `scripts/new-worktree.sh`'s "never add-all" advice. Run it only on a clean worktree, as the last
  step, then check `git status` / `git diff --cached --stat` for anything unrelated before committing.
- `scripts/ai_local_acceptance.sh` runs `git checkout -- "$stamp"` on build-stamp files (:162), and may
  run `npm ci` in `apps/command-center-v3` (:207-210). That's a dependency install, which no guard
  classifies.
- `scripts/agent_session_start.py --verifier` is **not** read-only: it writes a receipt
  (`scripts/lib/agent_session_receipt.py:213-218`). Nothing checks that receipts exist before a push
  or merge.

## 9b. What `ai_local_acceptance.sh` does not cover

- It never runs Ruff.
- It runs the CIO gate set only when changed paths match its `cio_*` / tests / listed patterns.
- `docs/architecture/**` is not in its policy-only list, so a docs-only change there takes the full path.

## 10. Agent workflow (session to handoff)

1. **Start.** Run `scripts/new-worktree.sh <name>` (never work in the primary tree). It does **not**
   create a `.venv` or `node_modules`: `ln -s ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv .venv`
   (gitignored) and put `.venv/bin` first on `PATH`. For the GUI, either let `ai_local_acceptance.sh` run
   `npm ci` in the worktree (a deps install) or build from the primary tree's `node_modules`. Then
   `scripts/agent_session_start.py --agent <registered id> --mode mutating --claim <paths> --store <stores>
   --doc-read AGENTS.md --doc-read AI_WORK_POLICY.md --expected-worktree $PWD --expected-head $(git rev-parse HEAD)`.
   Record the base SHA and the served SHA (`readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`).
2. **Design.** Find the owning registry ([`ARCHITECTURE_INDEX.md`](../architecture/ARCHITECTURE_INDEX.md)) and the
   existing producer/contract before adding one. Name the authority class, and the grant you'll need.
3. **Implement.** Make the smallest coherent change. No hardcoded values. Never `git stash` (the stash
   list is shared across worktrees).
4. **Negative tests.** Cover refusal and failure paths, plus a CI-parity run with missing deps shadowed.
   Register new tests in a CI route.
5. **Local gates.** Run `bash scripts/ai_local_acceptance.sh` with `.venv/bin` first on PATH, and grep for
   `FAILED|STOP|GATES FAILED` (the exit code lies). Run `regenerate_generated_files.sh` **last**, then
   `check_no_secrets.py --tree`.
6. **PR.** One push with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` and explicit operator intent. If you use a guard grant, confirm its reason names this branch; the hook doesn't check (§9). The PR body states base/head
   SHA, files and stores, authority class, contracts, migrations, negative tests, proof, and rollback.
   Don't claim your own PR was independently reviewed.
7. **Merge.** Only the operator merges. Stacked PRs: merge the top one. Update a behind branch with a
   merge commit, never a force-push.
8. **Deploy verification** (operator-merged SHA only).
   - Dry run first (AGENTS.md §0 rule 7): state what will restart and what the next run will do.
   - Commands, cwd `~/tradeai-exact-main-20260827` (`prepare` refuses unless HEAD == origin/main and the
     tree is clean; `git checkout -- apps/command-center-v3/build-meta.json` first):
     `git fetch origin && git checkout --detach origin/main && bash scripts/cio_phase2_exact_main_deploy.sh prepare && bash scripts/cio_phase2_exact_main_deploy.sh promote`.
   - `promote` **always restarts `portfolio-server`** (so a `service` grant is always implied) plus
     `TRADEAI_CURRENT_BOUND_UNITS`, and fast-forwards the dev tree.
   - Cron producers run from the **dev tree**, not CURRENT, so they pick up changes on their next
     natural run, which may be hours or days away (weekday-only or market-hours lines).
   - Verify: `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`, `readlink /proc/<MainPID>/cwd`
     for each unit you rely on, and `git -C ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild rev-parse HEAD`.
     Restart units promote doesn't bind (the CIO desk bot).
9. **Handoff.** Report what's live versus merged versus local, open operator decisions, and the evidence
   paths.

## 11. Worked example: producer → API → GUI

Goal: change what `/v3/agents` shows for Alex's gate progress, safely.

| Layer | Where | Command / check |
|---|---|---|
| Producer (static) | `config/agent_maturity_catalog.json` (`agents.alex`) | edited by `scripts/cio_gate_measurement_bridge.py --write` (:598, :633); never hand-edit counts |
| Producer (observed) | `scripts/agent_runtime/maturity_observability.py` `build_observations` (:697), `maturity_payload` (:875) | `pytest tests/test_agent_maturity_observability.py` |
| API | `scripts/portfolio_server.py:833/866` → `scripts/agent_runtime_read_boot.py:89` → `scripts/agent_runtime/read_http.py:126` `_dispatch_maturity` → `GET /api/v3/agent-maturity` | `curl -s 127.0.0.1:7777/api/v3/agent-maturity` (read-only); check `generated_at` and `freshness` |
| GUI | `apps/command-center-v3/src/lib/agentMaturityObservability.ts:104` → `src/pages/AgentRuntimeHub.tsx` → route `/v3/agents` (`src/App.tsx:201`) | `npm run build` (tsc + lib tests) |
| No contract? | If the value has no `Name@vN` contract (e.g. an untyped dict like `api_v2.py:8194` with a hand-written TS type), don't invent one silently. Either add a versioned schema name **with a consumer** (`check_dark_contracts.py` fails a new contract nobody consumes), or record the gap. Never widen an untyped payload without a test pinning its shape | `python3 scripts/check_dark_contracts.py --fail-on-new` |
| Render `as_of` | Reuse `apps/command-center-v3/src/lib/surfaceFreshness.ts` (`parseTimestamp` :41, `tradeAiSurfaceFreshness` :87). Flag `last_updated` strings with no timezone as ambiguous instead of guessing | `npm run build` |
| Trace a displayed value | Pick the Alex row on `/v3/agents` → find its field in the API JSON → find which `maturity_observability` function set it → confirm the catalog/bridge input and its `as_of` | if a step can't be followed, file it as a gap |
| Grants | Code: none beyond git-push for the PR. Deploy: `release-write` (+ `service` if a restart is needed) | `bin/guard show` right before acting (another session can replace a grant of the same scope) |

A safe change here: add or propagate `as_of` / `NOT_YET_MEASURED` from the bridge output through
the observation to the page. Test it at each layer, with a refusal test for a missing measurement,
which must render UNAVAILABLE rather than a count.
