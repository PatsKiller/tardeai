# Execution Ops Grant

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 5442-5505 -->
## Moved from AGENTS.md (25.0.1 lines 5442-5505)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **Permitted actions — these and nothing else, on the named unit only.** *Cause (§20): the operator's request of
  2026-10-10 ~21:50 ET ("only re-point the code root (drop-in to portfolio-server/CURRENT), daemon-reload, and
  restart"), widened at ~21:52 ET to reading the unit's status and journal ("today's incident needed it") and to its
  enable flag when that flag is user-writable.*
  1. **Inspect, at any hour:** `systemctl --user status <unit>`, `systemctl --user show <unit>` for named properties
     other than `Environment`, `journalctl --user -u <unit>`, `readlink /proc/<MainPID>/cwd`, and the unit's drop-in
     directory and drop-in files. Never `Environment`, an `EnvironmentFile` target or `/proc/<pid>/environ` (§24.7);
     the one environment value that may be printed is the `PYTHONPATH` entry, filtered on its own, to prove the code
     root.
  2. **Re-point the code root:** write `~/.config/systemd/user/<unit>.d/95-code-root-current.conf`, setting
     `WorkingDirectory` (and, where the base unit carries a dev-tree code path in `ExecStart` or `PYTHONPATH`, the
     matching reset-and-set) to `~/trade-ai-releases/portfolio-server/CURRENT`, the release §10 serves. A
     drop-in it supersedes is archived by rename to `<name>.archived-<YYYYMMDD>` (§0 rule 6), never deleted.
  3. **Reload and restart:** `systemctl --user daemon-reload` chained with that unit's restart in the same command,
     and `systemctl --user restart <unit>`, which also starts an inactive unit.
  4. **The unit's own enable flag** (its `ConditionPathExists=` path): create it, or archive it by rename, only when
     the path is under the operator's home. A flag under `/etc` needs root and stays operator-only; measured
     2026-10-10, the motion unit's flag is `/etc/tardeai/enable-active-trader-motion`.

  Not under this grant: `start` of anything other than through `restart`, `stop`, `kill`, `enable`, `disable`,
  `mask`, `unmask`, `edit`, `revert`, `set-property`, editing the base unit file, a drop-in with other content, and
  `sudo`. A `service` grant is never authority over a broker-execution unit.
- **Markets closed, from the market calendar, failing closed.** Every action in items 2–4 runs only while
  `scripts/lib/cio_market_session.market_session()["state"]` is `"CLOSED"`: weekends, NYSE holidays, and 20:00–04:00
  ET on trading days. Pre-market and post-market count as open. A calendar error refuses the action, unlike
  `scripts/market_day_gate.sh`, which fails open because it gates read-only syncs. Item 1 is allowed at any hour.
  *Cause (§20): operator request 2026-10-10 ~21:50 ET ("only when markets are closed (market calendar)"); a
  restart during a session can drop an open position's exit watch.*
- **Preflight before the first mutation, quoted in the incident record.** (a) The grant is active, and its reason
  names this unit and these actions. (b) The market state is `CLOSED`. (c) The unit's tests pass at CURRENT, run from
  `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` with `TRADE_AI_CI=1` and the interpreter the unit uses:
  for the motion unit, `tests/test_active_trader_motion_runtime.py` and
  `tests/test_active_trader_motion_host_proof.py`. Any failure stops the procedure. (d) No store moves: the
  unit-code-roots checks (`packets/unit-code-roots/repoint.py`) find no `data/`, `docs/` or `logs/` path and no
  registry `output_signal` that resolves differently under the unit's present root and CURRENT. A `STORE_RISK` or
  `SIGNAL_MOVES` verdict stops the procedure and goes to the operator (§0 rule 5). (e) `systemd-analyze --user verify`
  of a merged copy exits 0. (f) A dry run prints the exact drop-in text, every archive rename and every command
  (§0 rule 7). *Cause (§20): operator request 2026-10-10 ~21:50 ET ("with a preflight that the unit's code at CURRENT
  passes its tests"); the store check is the unit-code-roots finding of 2026-10-10 19:55 ET that 15 top-level
  `data/` entries resolve differently in the dev tree and in CURRENT.*
- **Proof, and rollback by restoring the archived drop-in.** After the restart: `ActiveState=active`; `readlink
  /proc/<MainPID>/cwd` resolves to the CURRENT release directory; the `PYTHONPATH` entry does not name the dev tree;
  the journal shows the runtime's own start line. A receipt with the before and after values is written to the
  incident packet (§0 rule 8). If any check fails, the agent archives the new drop-in by rename, restores the archived
  one by rename, runs daemon-reload and restart, verifies the old cwd, then stops and reports. *Cause (§20): operator
  request 2026-10-10 ~21:50 ET ("rollback by restoring the archived drop-in"); §0 rule 8.*
- **Never, under any grant.** Never read, copy or print a credential or env file (§24.7). Never set, flip or rewrite a
  live/paper flag or mode, and never restart a unit whose last journal start line shows a live mode, because that is
  live activation (A4, §17). Never touch an order, stop, session-grant or 2FA path. Never edit a file under
  `scripts/active_trader/**`, `scripts/brokers/**` or `scripts/moomoo/**`, and never call a broker. Restarting starts
  the unit with the configuration it already has. *Cause (§20): §0 rules 1–2, §2A, §17, §22; the operator request of
  2026-10-10 ~21:50 ET ("never reading credentials, changing live/paper flags, touching order/stop paths, or editing
  that code").*
- **Mechanics, and what still does not enforce.** The operator installs the scope once with
  `~/n8n-maturity-verification/packets/agents-4-7-0/install_execution_ops_scope.py`. It adds `execution-ops` to
  `bin/guard` `ALL_TIERS` with the 6 h cap, and to `.cursor/hooks/guard-lib.sh`. There, `restart`, `try-restart` and
  `daemon-reload` on a unit matching `tradeai-active-trader-`, and writes or renames under its drop-in directory,
  classify as `execution-ops` instead of `service`. The script also adds the rule
  `broker.execution_ops` to `config/agents_guard_hook_rules.json`. Three gaps stay open. The guard binds the scope and
  not the unit. Other `systemctl` verbs on a broker-execution unit still classify as `service`, so this rule, not the
  classifier, forbids them. The Claude Code PreToolUse hook is not installed on the host (`docs/ops/AGENTS_GUARD_HOOK.md`).
  The remote `/approve` path grants through the `bin/guard` of the release that runs the callback poller, so a
  remote grant works only once that release carries the scope. *Cause (§20): measured 2026-10-10 — a `service` grant
  matched `tradeai-active-trader-*` through `prod_unit_regex`, and no scope existed for this work.*
