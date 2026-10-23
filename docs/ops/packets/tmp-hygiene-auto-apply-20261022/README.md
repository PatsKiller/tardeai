# /tmp hygiene that deletes — auto-apply on host timers (2026-10-22)

```
Status:        PROPOSED (PR fix/tmp-hygiene-auto-apply-20261022); inert until the operator installs the timers
Owner:         platform
Authority:     operator 2026-10-22, verbatim: "It needs to be able to delete it. Just looking at it won't do anything."
Supersedes:    the plan-only posture of lane tmp-hygiene (docs/ops/packets/disk-hygiene-n8n-20261018, 2026-10-19)
Evidence:      01_auto_dry_run_20261022.txt (read-only run against the real /tmp)
Tests:         tests/test_tmp_hygiene_auto_apply_20261022.py (CI gate tmp_hygiene_auto_apply_20261022)
```

## Why

`/tmp` is a tmpfs with 1,048,576 inodes. It reached 97% inodes on 2026-10-19 and 99% on 2026-10-22. Since 2026-10-19
the n8n lane `tmp-hygiene` has run daily in `--plan` mode only: on the morning of 2026-10-22 it found 22 candidates
and 59,088 reclaimable files and removed nothing, because deletion needed `--apply` with `TRADEAI_DISK_HYGIENE_GRANT`
and the n8n executor may not apply. Its rules covered only Claude session scratch and `pytest-of-<user>`. Neither
rule could select the largest offenders:

| entry | inodes (2026-10-22) | creator | rule now |
|---|---|---|---|
| `/tmp/cbd/<pid>/` (24 dirs) | 136,419 | ad-hoc `pytest --basetemp=/tmp/cbd/<pid>` | **B** |
| `tradeai_hermetic_env_*` (3,700 → 5,200 dirs) | 23k → 32k | `scripts/lib/hermetic_test_guard.py` (atexit; killed workers leak) | **E** `hermetic_env` |
| `pipeline_step_{worker,receipt,par}_<hex>_*.lock` (~3,000 files) | ~3k | `_manifest_runner.sh` step lock hard-coded to /tmp | **E** + creator fixed |
| `pipeline_*_results.XXXXXX` (141 files) | 141 | `_manifest_runner.sh` mktemp, leaked on early returns | **E** + creator fixed |
| `pipeline_par_<hex>-s.lock` (139 files) | 139 | stage lock before tests set `PIPELINE_LOCK_DIR` | **E** |
| `n8nmat-unit-*`, `ga1-*`, `cio_acc_v4_*`, `opctl_apply_*`, `goal_due_repair_dry_*` | ~10k | named tests / dry-run script | **E** |
| `pytest-of-johnclaw/pytest-*` | 48k | pytest | P (now selected: future mtimes ignored) |
| `ready-*`, `candidate-*`, `pr<N>-*`, `pipeline-*`, ... review checkouts | 13–24k each | agent `git worktree add /tmp/...` | **G** (idle > 2 days) |
| `tradeai-reassess-*` (82k), `momentum-*`, `n8n-campaign-*` | — | — | never-touch globs (unchanged) |

Future-dated mtimes were the hidden blocker: `/tmp/cbd` and `pytest-of-johnclaw` carried mtimes 29 and 84 days in the
future (test fixtures), so the newest mtime of each tree was always "recent" and nothing was ever idle.

## What changed

1. **Rules** (`config/disk_hygiene_rules.json` `tmp`):
   * `pytest_basetemp` (B): `/tmp/<name>/<pid>/` only when every child of `<name>` is a pid dir and every child of
     `<pid>` is a pytest numbered dir (`<prefix><n>`) or a `<prefix>current` symlink; the pid is not a live
     pytest/python process.
   * `named.rules` (E): a full regex per creator, entry type pinned, `max_size_bytes` 0 for lock files, and
     `require` / `allow_only` child names where the creator's layout is fixed.
   * `git_trees` (G): a registered linked worktree that is clean, unlocked and has no commit only its HEAD holds is
     removed with `git worktree remove` (never `--force`; its branch stays in the main repo); a clone needs a clean
     tree, every branch pushed, no stash and no linked worktree left; an unregistered worktree is kept.
   * `future_mtime_skew_s` 300: mtimes later than now + 300 s are counted (`future_mtime_entries`) and never count as
     activity; a tree with only future mtimes is never a candidate (`no_real_mtime`).
   * Every rule keeps the shared checks: owned by the uid, bounded scan complete, idle ≥ 1 day (G: 2 days), no
     `/proc/*/cwd` and no `/proc/*/fd` inside, `never_touch_globs` (systemd-private-*, .X11-unix, .ICE-unix, tmux-*,
     ssh-*, snap-private-tmp, n8n-campaign-*, momentum-*, tradeai-*) and the home never-touch list; nothing outside
     `/tmp` (re-checked per item at apply time).
   * `tradeai_hermetic_env_*`: the never-touch glob `tradeai-*` uses a hyphen and does not match this underscore
     name. Decision: it is selectable under rule E only with its fixture layout (`env` present; only `CURRENT`, `env`,
     `home`, `state_root`, `xdg_runtime`, `dev_root_absent`, `live_root`), because it is a test fixture of known
     content, not a record. `tradeai-*` itself stays never-touch (it covers `tradeai-reassess-*` scratch with
     `ARCHIVED_TRIPWIRE.json` files).
   * `apply.max_items_per_run` 200 → 5000 (the lock-file backlog alone is ~3,000 items).
   * `auto_apply`: the kill switch, the **standing operator approval** (id `operator-20261022-tmp-hygiene-delete`,
     the verbatim quote, date, context) that replaces `TRADEAI_DISK_HYGIENE_GRANT` on the auto path only, the
     pressure trigger (85%), alert levels (P2 90%, P1 97%) and the output names.
2. **`scripts/tmp_hygiene_auto.py`** (new, host only): kill switch → approval → refuses under the n8n executor and
   for any root but `/tmp` → (pressure mode: act only at ≥ 85% inode use, at most every 15 min) → lock in the state
   root → fresh plan → `tmp_hygiene.apply` on it in the same run (re-validation of every item, caps) → deletions
   ledger `tmp_hygiene_deletions_<yyyymm>.jsonl` (path, bytes, files, age_days, rule, how), run report
   `tmp_hygiene_auto_apply_latest.json`, manifest `tmp_hygiene_manifest_auto_latest.json`, `LaneRunReceipt@v2`
   (`tmp-hygiene-apply`; `tmp-hygiene-pressure` for the 5-min check) → inode alert through
   `telegram_alert.send_telegram` (P2 ≥ 90%, P1 ≥ 97%, recovery once; deduped by `lib/alert_condition_state`,
   condition `system_health:tmp_inodes`, re-alert every 6 h).
3. **Units** `linux_launchers/systemd/tradeai-tmp-hygiene-{apply,pressure}.{service,timer}`: hourly at :20 and every
   5 minutes. **Registry** rows `tmp-hygiene-apply` and `tmp-hygiene-pressure` (systemd, `NEVER_SCHEDULED` until
   installed); the n8n row `tmp-hygiene` notes the new rules and still deletes nothing.
4. **Creator fix** `scripts/pipelines/_manifest_runner.sh`: the per-step flock uses `${PIPELINE_LOCK_DIR:-/tmp}`
   (production unchanged: cron sets nothing, so `/tmp`; tests already pass their own dir), and the `RESULTS` mktemp
   file is removed by a `RETURN` trap (plus `EXIT` for a `set -e` abort) on every path, not only the happy one.

## Why the host timer and not n8n

AGENTS.md §0 rule 6 carries one exception (15.0.0, §24.12): "the n8n lane `disk-hygiene` may remove the
reclaimable items its reviewed rules select (scripts/disk_hygiene.py, config/disk_hygiene_rules.json), and nothing
else". §24.12 names one script and one lane, says "No other deletion code is covered by analogy", and lists what is
reclaimable as git clones/worktrees and release directories only. The n8n allowlist `never` list keeps "destructive
retention stages" off the executor (§23.14), and `tmp_hygiene.apply` already refuses under `TRADEAI_RUN_ID`. Read
together, the text does not admit an n8n-executed deletion by a second lane, so:

* **n8n** keeps scheduling evidence and alerting: the daily `tmp-hygiene --plan` lane (now evaluating the wider
  rules) and `disk-usage-monitor` (inode bands, P2 intents), and its heartbeat watcher can read the two new host
  lanes' receipts.
* **The host** runs the deletion, on operator-installed systemd timers, like `tradeai-disk-hygiene-enforcer.timer`
  and `tradeai-disk-pressure-guard.timer` already do for releases.

§24.12 also says deleting anything outside clones, worktrees and release dirs "stays under 'Never delete' and is an
operator-only decision (§17)". The operator's 2026-10-22 ruling is that decision for the reviewed `/tmp` rules, and it
is recorded verbatim in `tmp.auto_apply.standing_approval`; no agent deletes by hand, and no agent installs the
timers. **AGENTS.md finding (§0 rule 10):** §24.12 does not name `/tmp` hygiene. A follow-up amendment should
extend §24.12 to "`scripts/tmp_hygiene.py` / `scripts/tmp_hygiene_auto.py` under `config/disk_hygiene_rules.json`
`tmp`, run by the host lanes `tmp-hygiene-apply` and `tmp-hygiene-pressure`" so the policy text matches the
operator's ruling. If the operator prefers the amendment ratified first, leave the timers uninstalled until then —
nothing in this PR deletes on its own.

## Activation (operator)

1. Merge the PR (the reviewed rules change; §17 "changing the disk-hygiene rules" — a `config-write` grant naming
   `config/disk_hygiene_rules.json` and the PR).
2. Review a fresh dry run (writes nothing): `cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python
   scripts/tmp_hygiene_auto.py --dry-run | less`.
3. Install and start the timers (user units, as `tradeai-disk-pressure-guard`):
   `cp linux_launchers/systemd/tradeai-tmp-hygiene-{apply,pressure}.{service,timer} ~/.config/systemd/user/ &&
   systemctl --user daemon-reload && systemctl --user enable --now tradeai-tmp-hygiene-apply.timer
   tradeai-tmp-hygiene-pressure.timer`.
4. Optional first run now: `systemctl --user start tradeai-tmp-hygiene-apply.service`, then read
   `~/trade-ai-releases/persistent-state/data/runtime/disk_hygiene/tmp_hygiene_auto_apply_latest.json` and
   `df -i /tmp`.
5. Flip the two registry rows to `ACTIVE` in a follow-up PR once the first receipt exists.

**Kill switch:** `tmp.auto_apply.enabled: false` (the script then exits without deleting) or
`systemctl --user disable --now tradeai-tmp-hygiene-apply.timer tradeai-tmp-hygiene-pressure.timer`.
**Rollback:** stop the timers; nothing else depends on them.
