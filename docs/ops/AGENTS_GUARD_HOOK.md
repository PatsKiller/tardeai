# AGENTS.md guard hook for Claude Code (PreToolUse)

```
Status:      ACTIVE (log-only week from install; deny after operator review)
as_of:       2026-10-09T17:00:00Z
Measured at: origin/main 377e9b536 (hook not yet installed on ms01)
```

Operator decision, 2026-10-09: "design and implement". Run it **log-only for the first week**, then switch it to deny.

## Why

`bin/guard` is wired only through `.cursor/hooks.json`, so for Claude Code the guard scopes are an honor system
(AGENTS.md §22, "Guard is not a universal boundary"; independent review 2026-09-25). This hook gives Claude Code
sessions the same AGENTS.md hard rails at the tool boundary. It reads the guard grant ledger, but it **never grants,
consumes or writes** a grant.

The hook is still not an enforcement boundary. It parses shell text, so a determined caller can get around it, for
example by writing a script and then running it. Enforcement still belongs at the resource that changes:
branch protection, the release script, and the session-grant verifier (§22). The hook stops honest mistakes and
records what happened.

## Pieces

| Piece | Path |
|---|---|
| Hook (system `python3`, stdlib only, fails open) | `scripts/hooks/agents_guard_pretooluse.py` |
| Rules: patterns, paths, units, hosts and tiers, each rule citing its AGENTS.md section | `config/agents_guard_hook_rules.json` (`AgentsGuardHookRules@v1`) |
| Decision log: one `AgentsGuardDecision@v1` line per matched rule | `$TRADEAI_STATE_ROOT/data/runtime/agents_guard_hook.jsonl` |
| Weekly review | `scripts/report_agents_guard_hook.py` |
| Tests (CI gate `AGENTS_GUARD_HOOK`) | `tests/test_agents_guard_hook_20261009.py` |

## Behaviour

- **No rule matches:** exit 0 with no output, and nothing is logged. Normal permission flow applies.
- **`log` mode** (default): the hook never denies. It appends one line per matched rule with `ts`, `session_id`,
  `tool`, `rule_id`, `section`, `would_deny`, `denied`, `reason`, `detail`, `grant_tier`/`grant_state`,
  `command_sha256` and `command_preview`. The preview is redacted and at most 200 characters. **The raw command is
  never stored.**
- **`deny` mode:** prints
  `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`
  and exits 0. The reason names the rule, its AGENTS.md section and, for grant-gated rules, the `bin/guard request`
  to send.
- **Rules with `action: "log"` never deny, even in deny mode.** These are `remote.pr_merge` (whether agents may merge
  is still the operator's call) and `secrets.env_dump`.
- **Fail open.** If the hook hits any internal error (bad JSON, missing rules, a parser bug, or its own 2 s alarm),
  it logs `rule_id: "hook.error"` and allows the call. A bug in the hook must never brick a session. The report
  counts these errors.
- **Mode precedence:** `TRADEAI_AGENTS_GUARD_MODE` (`log` or `deny`), then `mode` in the rules file (ships as
  `log`), then `log`. Any other value means `log`.
- **Cost:** the measured median is about 5–10 ms to evaluate and about 40 ms wall clock with interpreter start-up.
  The test bound is 200 ms.

Claude Code facts were checked against https://code.claude.com/docs/en/hooks on 2026-10-09. They match the brief:
- The stdin JSON carries `session_id`, `cwd`, `tool_name`, `tool_input`, `hook_event_name` and `transcript_path`.
  It also carries `tool_use_id` and `permission_mode`, which the hook logs or ignores.
- JSON `permissionDecision: "deny"` with exit 0 is the preferred way to deny. Exit 2 with stderr also blocks.
- Exit 0 with no output means no decision.

Differences from the brief:
1. The default PreToolUse timeout is **30 s**, not 600 s. This snippet sets 10 s.
2. Any exit code other than 0 or 2 is a *non-blocking* error. That suits fail-open, but the hook still always
   exits 0.
3. A matcher containing characters other than letters, digits, `_` and `|` is treated as a regex, so
   `Bash|Edit|...|mcp__.*` is a valid unanchored regex.
4. The docs list `Read`, but the brief's matcher left it out. This snippet adds `Read|Grep` so the secrets rule also
   covers file reads.

## Rules (rules file version 1.0.0)

| id | family | action | grant | AGENTS.md |
|---|---|---|---|---|
| `broker.live_host_call` | broker | deny | none (always) | §0.2, §22 A4/A5 |
| `broker.order_invoke` | broker | deny | none (always) | §0.2, §22 A5 |
| `broker.live_flag` | broker | deny | none (always) | §0.2, §17 |
| `broker.live_credential` | broker | deny | none (always) | §0.2, §2A, §17 |
| `broker.execution_code_edit` | broker | deny | `execution-engineering` | §0.2, §22 A1/A2 |
| `delete.recursive_rm` | delete | deny | none; temp allowlist | §0.6, §17 |
| `delete.find_delete` | delete | deny | none; temp allowlist | §0.6 |
| `delete.git_clean` | delete | deny | none (`-n` allowed) | §0.6 |
| `delete.shred_truncate` | delete | deny | none; temp allowlist | §0.6, §9.4 |
| `delete.sql_destructive` | delete | deny | none | §0.6, §9.4, §17 |
| `delete.docker_volume` | delete | deny | none | §0.6, §17 |
| `remote.hook_bypass` | remote | deny | none | §0.3 |
| `remote.non_origin_push` | remote | deny | none | §0.3 |
| `remote.push_to_main` | remote | deny | none | §0.3, §0.4 |
| `remote.gh_api_ref_write` | remote | deny | none | §0.3 |
| `remote.branch_rename` | remote | deny | none | §0.3 |
| `remote.pr_merge` | remote | **log** | — | §22, operator rail |
| `secrets.read` | secrets | deny | none | §2A |
| `secrets.write` | secrets | deny | none | §2A |
| `secrets.env_dump` | secrets | **log** | — | §2A |
| `liveops.service` | liveops | deny | `service` | §9.3, §10, §17 |
| `liveops.cron` | liveops | deny | `cron` | §9.3, §17 |
| `liveops.deploy` | liveops | deny | `release-write` | §10, §22 A3 |
| `liveops.self_grant` | liveops | deny | none (never grantable) | §0.3, §17 |
| `governed.served_edit` | governed | deny | none | §7A, §10, §20 |
| `governed.hook_config` | governed | deny | none | §0.3 |

Notes on individual rules:
- **broker.\***: the live hosts are `api.schwabapi.com`, `api.alpaca.markets`, `api.snaptrade.com`,
  `openapi.moomoo.com` and OpenD on `:11111`. `paper-api.alpaca.markets` is not a live host. An order call is
  `place_order(`, `submit_order(`, `replace_order(` or `cancel_order(` in inline Python, Node or heredoc code, or
  running a declared broker entry point.
- **Execution code edits are an interpretation.** The brief said "DENY always". AGENTS.md §22 (ratified 1.3.0) allows
  A1/A2 edits to the declared execution file set under an active `execution-engineering` grant, so
  `broker.execution_code_edit` honours that grant. To make it deny always, remove `grant_tier` from the rule.
- **delete.\*:** the temp allowlist is `/tmp/claude-*` (which includes the session scratchpad), `/tmp/pytest-of-*`,
  and worktree build directories (`~/tradeai-wt-*/{build,dist,node_modules,__pycache__,.pytest_cache,...}`).
  Unresolvable targets such as `$DIR` or xargs input count as not allowlisted. Shell variables set earlier in the same
  command are followed: `S=/tmp/claude-1000/...; rm -rf "$S/x"` is allowed. `$(mktemp ...)` counts as a fresh temp
  path. A `find` that only matches bytecode or cache names (`__pycache__`, `*.pyc`, `.pytest_cache`, ...) is allowed.
- **Archive-expiry exception:** `archive_expiry_exception.enabled` is **false** while the operator decision is
  pending ratification. Turning it on is an AGENTS.md amendment (§20), not a config tweak.
- **broker.order_invoke (inline code):** the code must both call an order function and import a broker module. A
  Python heredoc that only edits source text containing `place_order(` does not count.
- **Push rules scope:** the push rules apply when the cwd, or the `git -C` directory, is inside a Trade AI checkout
  (`~/trade-ai-v12-rebuild`, `~/tradeai-wt-*`, `~/trade-ai-worktrees`, `~/trade-ai-releases`, `/tmp/claude-*`) or
  is unknown. Pushes from the agent memory repo or the DOF project are out of scope.
- **secrets.read:** reading names only is allowed, for example `grep -o '^[A-Z_]*='`, `grep -c/-l/-q`,
  `cut -d= -f1` and `awk -F= '{print $1}'`. Sourcing an env file to run a program is allowed. `.env.example` is
  allowed.
- **liveops.service:** read-only verbs such as `status`, `show` and `cat` are always allowed. Units and containers
  outside `prod_unit_regex` and `docker_prod_container_regex` are allowed. A grant is "active" when
  `expires > now` and `uses != 0` in `~/.cursor/approvals/grants.json` (or `$GUARD_APPROVALS_DIR`). The rule does
  not check whether the grant's **reason** names this PR or SHA; that stays the agent's own duty and the release
  script's binding.
- **governed.served_edit:** governed paths are `AGENTS.md`, `AI_WORK_POLICY.md`, `CLAUDE.md`,
  `config/data_source_authority*.json`, `.githooks/**`, `.github/workflows/**`, `config/guard*`, this hook and its
  rules, `.cursor/hooks/**` and `bin/guard`. Editing them in a worktree or branch is allowed because those changes go
  through a PR. Editing them under the served release, `CURRENT`, `persistent-state` or `~/trade-ai-deployments` is
  denied.

### Shell parsing

- **Splitting:** commands are split on `;`, newlines, `&&`, `||`, `|` and `&`, ignoring anything inside quotes.
- **Nested commands:** the hook also checks code inside `$( )`, backticks, `<( )`, `bash -c` (and the other shells),
  `su -c`, `eval`, `ssh host '...'`, `flock -c` and heredoc bodies fed to a shell.
- **Prefixes it sees through:** environment assignments, plus `sudo`, `env`, `nohup`, `nice`, `timeout`, `stdbuf`,
  `xargs`, `systemd-run` and similar wrappers.
- **Directories:** `cd` and `pushd` are followed inside one command.

**Known gaps (accepted):**
- `grep -r` over a directory that contains a `.env` file.
- A program that opens a secret file itself.
- A script written and then executed.
- Variables the hook cannot resolve, other than for deletes, where they count against the command.

## Pre-install replay `[MEASURED]` 2026-10-09

Before shipping, the hook's `evaluate()` was replayed over the Bash, Edit, Write, MultiEdit and Read calls in the 30
smallest of the 40 most recent Claude Code transcripts under `~/.claude/projects/-home-johnclaw/`: **31,643 calls**.
It ran with the live grant ledger at replay time, and no command text left the box.

**First pass, which this PR fixes:**

| Problem | Cause | Fix |
|---|---|---|
| One call took 1.5 s | The names-only grep regex backtracked catastrophically | Linear-time pattern, plus a regression test |
| Writing a doc that mentioned `DROP SCHEMA` counted as destructive SQL | SQL was matched against heredocs written to files | SQL is now matched only for DB clients and for inline code that executes SQL |
| Pushes to `main` in the agent memory repo and the DOF repo were flagged | The push rules applied to every repo | Push rules now apply only inside Trade AI checkouts |
| `S=…/scratchpad; rm -rf "$S/x"` was flagged | Shell variables were not followed | Variables set earlier in the command are now resolved |
| The grep *pattern* `…\.env` was read as a path | The pattern argument was treated as a file | Pattern arguments of grep and scripts of sed/awk are skipped |
| `git -c core.hooksPath=.githooks` was flagged | Pointing at the repo's own hooks was treated as a bypass | That setting is allowed |
| `bin/guard grant --help` was flagged | Asking for help looked like issuing a grant | `--help` is allowed |
| `__pycache__` cleanup and `ln -s .env` were flagged | Too broad | Both are allowed |
| `~/.config/tradeai/bin/*.sh` was treated as a secret | The secrets glob covered the whole directory | It now covers `*.env` files only |

**Second pass, after the fixes:** no call over 50 ms. Would-deny counts:

| Rule | Would-deny |
|---|---|
| `secrets.read` | 345 |
| `liveops.cron` | 81 |
| `delete.recursive_rm` | 67 |
| `secrets.write` | 21 |
| `remote.gh_api_ref_write` | 13 (all branch-protection PATCH/POST, operator-only under §17) |
| `broker.execution_code_edit` | 13 (Active Trader P1 files, no execution-engineering grant active now) |
| `remote.hook_bypass` | 12 (`--no-verify`, `core.hooksPath=.git/hooks`) |
| `delete.git_clean` | 6 |
| everything else | 1–3 each |

Log-only matches: `remote.pr_merge` 548 and `secrets.env_dump` 7.

What the reviewed samples show:
- **secrets.read** is mostly real value prints: `grep FLAG /run/user/1000/tradeai/env`, `sed … ~/.pgpass`, `cat` of
  `.env` files.
- **liveops.cron** is crontab installs.
- **delete.recursive_rm** is mostly `rm -rf evidence/...` and similar inside worktrees.

These are the expected subjects of the log-week review, not parser noise.

## Install (operator)

The agent does **not** install this. Add the following to the user-level `~/.claude/settings.json` and merge it with
any existing `hooks.PreToolUse` entries. It points at the served `CURRENT` release, so each promote updates the hook
and its rules:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit|Read|Grep|mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "TRADEAI_AGENTS_GUARD_MODE=log /usr/bin/python3 \"$HOME/trade-ai-releases/portfolio-server/CURRENT/scripts/hooks/agents_guard_pretooluse.py\" || true",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**Why `|| true` matters:** if the file is missing, `python3` exits **2**, for example before the promote that ships
this PR or after a rollback to an older release. Claude Code treats exit 2 as a **blocking** denial, so without the
fallback every tool call would be refused. With `|| true` a missing file fails open, like every other hook error. A
deny still works, because it travels as stdout JSON. Install after the release that contains this PR is promoted. To
check it once installed:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git push origin HEAD:main"},"cwd":"/tmp","session_id":"check"}' \
  | TRADEAI_AGENTS_GUARD_MODE=deny /usr/bin/python3 ~/trade-ai-releases/portfolio-server/CURRENT/scripts/hooks/agents_guard_pretooluse.py
# expect: {"hookSpecificOutput": {... "permissionDecision": "deny" ...}}
tail -1 ~/trade-ai-releases/persistent-state/data/runtime/agents_guard_hook.jsonl
```

## The log week, then deny

1. Run `python3 scripts/report_agents_guard_hook.py --days 7` each day, or at least once at the end of the week.
2. For every **false-positive candidate**, which is the same command blocked in three or more sessions, a read-only
   looking command, or a command repeated six or more times, decide one of:
   - **Rule too wide:** narrow it in `config/agents_guard_hook_rules.json` (bump `version`), add a test case to
     `tests/test_agents_guard_hook_20261009.py`, and ship by PR.
   - **Agent was wrong:** leave the rule as it is.
3. `hook.error` must be 0, or explained, and `elapsed_ms.p95` must be under 100.
4. To flip to deny, change `TRADEAI_AGENTS_GUARD_MODE=log` to `=deny` in `~/.claude/settings.json`. That is an
   operator edit, and the hook itself denies agents editing that file. The new mode applies to new tool calls at
   once.

## Rollback

- **Fastest:** set `TRADEAI_AGENTS_GUARD_MODE=log` in the settings command. Nothing is denied and the log continues.
- **Full:** delete the `PreToolUse` entry from `~/.claude/settings.json`.
- **Bad rules in a release:** roll back the release (`cio_phase2_exact_main_deploy.sh rollback`, operator grant) or
  set `TRADEAI_AGENTS_GUARD_RULES` to a reviewed copy.
- The hook fails open on its own errors, so a broken hook degrades to "allow and log `hook.error`", never to a
  lockout.
