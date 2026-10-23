# Operating playbook — how any agent or the operator picks up Trade AI work

```
Status:      ACTIVE
as_of:       2026-10-23T17:40-04:00
Measured at: not measured (verbatim copy of HANDOFF_v3_ORDERED_WORK.md Section A and B0, sha256 24c658c6930fc174…)
Source:      ~/trade-ai-releases/persistent-state/data/coordination/handoffs/HANDOFF_v3_ORDERED_WORK.md
```

This is the versioned single source of the rules part of the handoff (operator 2026-10-23: "also add that the above
should be part of the board"). Section A (resume procedure, system map, rules, how a change goes live) and B0 (the
standard agent preamble) are copied here verbatim; the ordered work packages live on the task board
(`scripts/agent_claim.py task list`, Ops → Coordination → Work pipeline). The Work pipeline renders this file on its
**Playbook** tab, every **Copy prompt** prepends the B0 preamble below, and
`scripts/agent_claim.py export-handoff --out <file>` regenerates the full offline handoff (this playbook plus every
work package with its status and proof evidence) from the board. Change the rules here, by PR; the section headings
are pinned by `tests/test_operating_playbook_20261023.py`, because the B0 extractor and the Playbook anchors read them.

Where this text says "this document", it means the handoff that `export-handoff` produces. AGENTS.md wins over this
playbook wherever they differ (AGENTS.md §0 rule 10).

# Section A: how the system works and the rules

## A1. Resume procedure (any agent, every time)

1. **Read `AGENTS.md`** (20.1.0 ACTIVE): all of §0, §25 (release train), §26 (data foundation), §27 (Ops Controls), §28 (agent operations) and §28.3a (picking up work). Then read `CLAUDE.md` and `AI_WORK_POLICY.md`.
2. **Read this document**, then the memory index `~/.claude/projects/-home-johnclaw-trade-ai-v12-rebuild-trade-ai-v12-rebuild/memory/MEMORY.md` and the coordinator worklog `~/trade-ai-releases/persistent-state/data/coordination/worklogs/claude-coordinator-20261022.worklog.md`.
3. **Check the state:**
   - `python3 scripts/agent_claim.py status`
   - `python3 scripts/agent_claim.py task list`
   - `gh pr list --state open`
   - `bin/guard show` (grants)
   - the served SHA, as above
4. **Pick the first WP in Section B** whose dependencies are met and whose owner is AGENT.
   - `take` its task on the board, or `task add` it if it's missing.
   - Claim your files and keep the worklog (`plan`, `done`, `note`, `blocker`, `handoff`).
5. **Present OPERATOR WPs to the operator as exact copy-paste commands**, with real PR numbers and SHAs and **no `<placeholders>`**. Include the dry run first, and say what to paste back.
6. **When you finish a WP:** mark it `[x]` here with evidence, close the board task, and update the coordinator worklog.

## A2. System map

**Checkouts and paths**
- **Canonical checkout** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`.
  - It is the release source: `scripts/cio_phase2_exact_main_deploy.sh` requires it clean and detaches it to the main SHA.
  - `core.hooksPath` points at its `.githooks`.
  - `tradeai-continuous.service` (a system unit) launches the scan loop from it. That is a known regression (WP-27).
  - **Agents never edit it**; they use worktrees under `$HOME`.
- **Served release:** `~/trade-ai-releases/portfolio-server/CURRENT`, a symlink to `<sha>-main-exact-phase2-<stamp>/`. Its identity is at `/v3/build-meta.json`. Cron and n8n executors run from CURRENT.
- **Persistent state:** `~/trade-ai-releases/persistent-state/`.
  - `data/runtime/`: lane receipts `<lane>_last.json`
  - `data/cio/`: CIO stores
  - `data/coordination/`: claims, tasks, worklogs, handoffs
  - `logs/`

**Services**
- **Server:** `portfolio-server.service` (user unit), `127.0.0.1:7777`.
  - The operator browses via the cc-auth unix socket over Tailscale.
  - `MemoryHigh` 1.5 GB, with a `MALLOC_ARENA_MAX=2` drop-in.
  - A cron watchdog SIGKILLs it under memory pressure; its log is `~/logs/portfolio_server_watchdog.log`.
- **Ops applier:** `tradeai-ops-applier.service` executes Ops Controls acts. The web process holds no deploy or GitHub credentials.
- **Release-train claimer:** `tradeai-release-train-claim.{service,timer,path}` (user units). The timer fires every minute; the path unit watches `persistent-state/data/runtime/release_window/train_requests/pending`.

**Database and GitHub**
- **DB:** Postgres `trade_ai`, role `trade_ai`. Credentials load via `scripts.lib.env_bootstrap.load_env`. Never print them.
- **GitHub:** `PatsKiller/tardeai`.
  - Required checks: exactly `cio-hardening`, `agent-governance`, `release-readiness` and `ci-gate` (`strict:false`, `enforce_admins:true`, 0 reviews).
  - `train/*` refs are reserved by the ruleset `release-train-refs` for the train's GitHub App.

**CI and docs**
- **CI gates:** one JSON per gate in `config/ci_gates/`, written only via `scripts.lib.ci_gates.render(make_record(name, files, comment))`, since byte-exactness is tested. **Every new test file must be in a gate**, or the coverage gate and integrity rails fail.
- **Docs index:** `docs/INDEX.md` is generated with `scripts/report_docs_inventory.py --write-index` and checked with `--check-index`. Every new doc needs a row.
- **Docs/AGENTS backlog** (operator rule: a row per change): `~/n8n-maturity-verification/DOCS_AND_AGENTS_UPDATE_BACKLOG.md`.

**Scheduling**
- **Lane registry:** `config/lane_registry.json` lists every scheduled job: cron, n8n or systemd, with `state` and `rollout_stage`.
  - Tools: `scripts/check_lane_registry.py` and `scripts/reconcile_lane_registry.py --write`.
  - Hand-unioned merges break the canonical serialisation, so run reconcile after merging.
- **n8n:**
  - allowlist: `config/n8n_run_allowlist.json`;
  - health contracts: `config/n8n_health_contracts.json`. A DRAFT contract fails CI with `DRAFT_NOT_GRANDFATHERED` until the operator marks it REVIEWED (§23.19);
  - live list: `~/.config/tradeai/n8n-live-lanes.env`.
- **Cron (~400 lines):** under a freeze. No change without an approved row in `~/n8n-maturity-verification/cron-inventory/`. The operator edits the crontab; agents supply preview/apply scripts that match exact lines, back up, and verify from a captured file. Use `grep -q <<<"$var"`, never `cmd | grep -q` (pipefail plus SIGPIPE gives false failures).

**Grants**
- Issued by `bin/guard grant <scope> --for <dur> --uses N --replace --reason "…"`, typed by the operator with APPROVE. Agents never self-grant.
- Scopes include release-write, execution-engineering (A1/A2 broker-adjacent code, named files), execution-ops, broker-read, cron, file-delete, db-write and others (`bin/guard scopes`).
- **Release grant binding** (`scripts/lib/release_grant_binding.py`) matches a PR#, a SHA or a campaign. A SHA wins over a PR. A campaign grant's reason contains the campaign id, and the release run exports `TRADEAI_RELEASE_CAMPAIGN=<id>`.

**Coordination tools**
- **Claim/task board:** `scripts/agent_claim.py` (claims, lifecycle, worklogs, tasks, `next`/`take`, `task done --evidence-only`).
- **Shared-additive paths:** `config/agent_claim_shared_paths.json`.
- **Designs:** `docs/designs/DSN-*.md` (YAML front matter, phases, tasks; see `docs/designs/README.md`).
- **UI:** the Work pipeline (Ops → Coordination).

**Handoff copies of session-only scripts and packages:** `persistent-state/data/coordination/handoffs/scratchpad-20261023/`. It holds:
- `release-agent.sh`, `union_build.py`, `seed-tasks.sh`;
- `cio_prospect_operator_apply.sh`, `workflow.patch`, `hotlist-budget-operator.sh`, `grants-today-operator.sh`, `enforce-claims-operator.sh`;
- the packages `agents-19-1/` (20.0.0, applied), `agents-20-1/` (20.1.0, applied), `agents-21/` and `push-policy-v2/`.

## A3. Rules (never skip)

1. **AGENTS §0, rules 1–11.**
   - MBI_BEHAVIOR=0: no sizing, orders, stops, weights or broker writes.
   - Broker code only under a per-task execution-engineering grant that names the files.
   - Never route around a denial: stop and report.
   - A checkpoint is a commit, not a push.
   - Never auto-fix divergent copies of a store.
   - Never delete: archive with a tripwire. Only the §24.12 disk-hygiene lane and the 20.0.0 /tmp lanes delete.
   - Dry-run before any live run and quote the output.
   - Exit 0 is not evidence; prove it with a durable artifact.
   - Operator-only decisions: propose and stop.
   - A finding that contradicts AGENTS.md wins; report it.
   - Rule 11: claim, log, hand off.
2. **§28.8:** no UI or validation traffic to `127.0.0.1:7777` between 04:00 and 16:15 ET on market days. That covers Playwright, crawlers, vite preview proxying `/api`, and curl. Use fixtures or mocks. After the close: GET only, ≤1 req/s, with `TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1`.
3. **Push policy v1:**
   - 2 pushes per branch, with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1`.
   - A 3rd push uses `TRADEAI_REMOTE_PUSH_OVERRIDE=1`, and **only the operator runs it**. Never put it in an agent script or brief; the classifier blocks it as a "Safety Bypass".
   - Never rename a branch to reset the budget.
   - Force-push is denied. Update a branch by **merging origin/main**.
4. **No pattern kills (`pkill -f`).** Kill only your own PID, after checking that `/proc/PID/cwd` is in your worktree.
5. **Isolation:**
   - Each agent uses its own worktree and its own `AGENT_CLAIM_SESSION=<coordinator>-<name>`; same-session claims never conflict.
   - Use unique scratch names (`~/.cache/rtc/<name>_*`). Never write shared files like `pr_body.md` or `body.md`; collisions posted wrong PR bodies.
6. **Tests pin their clocks.** Two "time bombs" so far: a fixed NOW checked against a real-clock freshness or on-window rule. Integration builds also run clock-shifted (+12h, +3d).
7. **Never convert line endings** in existing files. The CRLF churn guard fails CI.
8. **Operator-only:**
   - merging policy (AGENTS.md, AI_WORK_POLICY.md), `.githooks`, `.cursor/hooks`, `bin/guard`;
   - merging anything the classifier refused for an agent (Active Trader files, e.g. #1997, #1991);
   - grants, crontab, DB migrations, ratification tokens, contract REVIEWED marks;
   - kill-switch clearing, live flags, arming;
   - branch protection;
   - 3rd pushes.
9. **Operator preferences:**
   - Exact commands with real values.
   - Account **names only**, never numbers.
   - No silos: every per-security fact lands in CIO memory keyed by `security_guid`.
   - n8n first and shadow first for new pipelines.
   - Check open PRs before building.
   - A docs-backlog row for every change.
   - Run agents in parallel and keep work moving.
   - All configuration should eventually be editable from Ops Controls modals.

## A4. How a change goes from idea to live

1. **Board task.**
   - `python3 scripts/agent_claim.py --session <s> --agent <a> task add --id DSN-<date>-<slug>-P<n>-T<m> --title … --kind build|fix|design|review --areas <paths> --priority 1-4 [--depends-on …]`, then `take <id>`.
   - Then `plan`, `done` per step, `stage <claim> pr_open --pr N`, and `handoff <claim> --next "…"` when stopping.
   - Close a finished free task with `task done <id> --evidence-only --summary … --evidence <links>`.
2. **Build in your worktree:**
   - hermetic tests with pinned clocks;
   - a CI gate per new test file;
   - a doc plus its INDEX row;
   - a backlog row.
3. **PR:**
   - at most 2 pushes;
   - the PR body ends with the Claude Code footer when an agent wrote it;
   - the 4 required checks green.
4. **Integrate**, either way:
   - **Batch PR:**
     - create `release/batch-N-<date>` from origin/main;
     - `git merge --no-ff` each green PR head;
     - resolve the `package.json` build line with `union_build.py`;
     - regenerate INDEX with `--write-index` and the lane registry with `reconcile_lane_registry.py --write`;
     - union additive registries;
     - run the CC v3 build (`apps/command-center-v3`, `npm run build`), the touched tests, the ci_gates registry and coverage tests, `--check-index`, and the clock-shifted runs.
   - **Direct merge** of small independent green PRs.
5. **Release** (manual until the train is live):
   - Wait for main's 3 workflows green on the exact HEAD: `cio-production-hardening-ci`, `agent-governance`, `release-readiness`.
   - Run `bash release-agent.sh <main-sha> <latest-merged-PR#>`. It:
     - checks main == expected and the 3 workflows green;
     - checks the canonical checkout is clean, then detaches it;
     - requires an active release-write grant (campaign id via `TRADEAI_RELEASE_CAMPAIGN`; **the operator issues a new campaign grant when the old one expires or runs out**);
     - runs `cio_phase2_exact_main_deploy.sh prepare` then `promote`.
   - Verify the served `git_sha` and a 200 on `/v3/` and `/api/health`.
   - **Merge nothing between a merge and its release**: main CI restarts.
6. **Cost:** PR CI ~35–45 min plus main CI ~40 min. WP-11 and WP-12 reduce this.

# Section B0: the standard agent preamble

## B0. Standard agent preamble (every agent prompt below starts with this; paste it first)

> You are a coding agent working on Trade AI at `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` (GitHub `PatsKiller/tardeai`).
>
> **Before anything else:**
> - Read `AGENTS.md` §0 and §28.3a.
> - Read Section A of `~/trade-ai-releases/persistent-state/data/coordination/handoffs/HANDOFF_v3_ORDERED_WORK.md`.
>
> **Rules:**
> - Work only in your own git worktree under `$HOME`, created from `origin/main`. Never edit the canonical checkout.
> - Register your task on the board: `python3 scripts/agent_claim.py --session <unique-session> --agent <name> task add …` (or `take <task-id>` if it exists). Then claim your files, and keep the worklog with `plan`, `done`, `note`, `blocker` and `handoff`.
> - Never send traffic to `127.0.0.1:7777` from 04:00 to 16:15 ET on market days. Use fixtures or mocks.
> - Never `pkill -f`.
> - Use unique scratch files at `~/.cache/rtc/<name>_*`.
> - Never touch broker, order, stop, kill-switch or credential code or files without a named execution-engineering grant.
> - Never read secrets.
> - Never route around a denial: stop and report it.
> - Pin clocks in tests. Register every new test file in a CI gate via `scripts.lib.ci_gates.render`. Add a doc with its `docs/INDEX.md` row (`scripts/report_docs_inventory.py --write-index`) and a row in `~/n8n-maturity-verification/DOCS_AND_AGENTS_UPDATE_BACKLOG.md`.
> - **Pushes:** at most 2 per branch, with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` only. Never use `TRADEAI_REMOTE_PUSH_OVERRIDE`, never force-push, and never rename a branch to reset the budget. To update a branch, merge `origin/main` into it.
> - **Commit trailer** (Claude agents): `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, plus the session line if one is provided.
> - **PR body footer:** `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
> - Get the 4 required checks green: `cio-hardening`, `agent-governance`, `release-readiness`, `ci-gate`. **Do not merge** unless the WP says the agent merges.
>
> **When done:** report the PR, its head SHA, CI state, evidence and anything left, and mark the board task.

**What the operator needs from you:** whenever a WP needs the operator, give them a copy-paste block with real values. Always show the dry run first, then the apply, then tell them what output to paste back.
