# Communications Gateway — Go-Live Runbook (single consolidated operator prompt)

```
Status: ACTIVE
as_of: 2026-09-07T11:33:00-04:00
Measured at: served build 3cb740e4c69380fe9355da6b4857a94cf21e6c27 (PR #874 Wave E + docs, merged from d18d81208)
```

This is the **one** operator-facing go-live document for the Communications Gateway. It
collapses the multi-step merge → deploy → restart sequence into a single governed plan
approval and the exact ordered commands. Everything below is operator-executed through
`bin/guard`; an agent never self-authorises these scopes (AGENTS.md §8, §17).

---

## 0. The single operator prompt

From the primary worktree root, run **one** command. It displays the plan file
(`docs/deployment/wave-cde-go-live-plan.md`), then grants exactly the scopes that plan
declares, each for the declared window/uses:

```bash
cd /home/johnclaw/trade-ai-worktrees/cc-header-truth-v2-claude
bin/guard plan docs/deployment/wave-cde-go-live-plan.md \
  --scopes "git-push release-write db-write cron service"
```

- `bin/guard plan <file>` **displays the plan file first**, then asks for the scope list
  (`[CODE] bin/guard`, `cmd_plan`). With `--scopes "…"` supplied, it skips the interactive
  scope prompt and shows the auto-accept list.
- The operator types **`APPROVE PLAN`** (exactly) at the confirmation prompt. An agent
  never types, pipes, or simulates this.
- `secret` and `gate` are **never** auto-accepted by `plan` (`[CODE] bin/guard`:
  `"Not included, and never auto-accepted: secret, gate."`).
- After approval, verify with `bin/guard show`; revoke unused grants with
  `bin/guard revoke <tier>` or `bin/guard revoke --all`.

| Scope | Why it is needed |
|---|---|
| `git-push` | push the validated local merge commit (one push) |
| `release-write` | `prepare`/`promote` the release to `CURRENT` |
| `db-write` | apply the communications migrations to prod Postgres |
| `cron` | confirm the poller wrapper cron is intact (read/replace) |
| `service` | restart the poller daemon and verify the served process |

---

## 1. Correctness facts (read before executing — two of them are traps)

### 1.1 The poller runs under **cron**, not under tmux `[VERIFIED]`

The Telegram callback poller is a `--daemon` process launched by a host-local cron
wrapper. The crontab entry is:

```
*/2 * * * * bash ~/.config/tradeai/bin/run_telegram_callback_poller_current.sh
```

That wrapper (`[CODE] ~/.config/tradeai/bin/run_telegram_callback_poller_current.sh`):

- resolves `CURRENT` to a concrete release dir and `cd`s into it,
- sources host env files, then
- `exec`s `scripts/run_telegram_callback_poller.py --daemon` under
  `flock -n /tmp/tradeai_telegram_poller.lock`, writing a PID to
  `/tmp/tradeai_telegram_poller.pid`.

`flock -n` means the every-2-minute cron tick is a **watchdog**: if the daemon is already
alive the tick exits immediately; if the daemon died, the next tick (≤2 min) relaunches it.
`[VERIFIED]` the live daemon runs from the served release:

```
2163523 …/.venv/bin/python -u …/f88853e89-main-exact-phase2-20260905-135414/scripts/run_telegram_callback_poller.py --daemon
```

### 1.2 The `telegram` tmux session is **Grok's agent window**, not the poller `[VERIFIED]`

`tmux ls` shows a `telegram` session, but that session belongs to Grok's agent window —
it is **not** how the callback poller runs. Do **not** kill, attach, or restart the
`telegram` tmux session to change the poller. The poller's lifecycle is cron + flock
(§1.1). Restarting the wrong thing here (or killing Grok's window) is a live-outage risk
with no effect on the poller.

---

## 2. Ordered go-live sequence

Execute strictly in order. Each step names its rollback.

### Step 1 — Merge

```
# from the primary worktree, on the validated branch
git log origin/main..HEAD        # confirm the exact SHA to merge
# merge (or gh pr merge) — the exact SHA is recorded in the plan file
```

**Rollback:** the merge commit is revertible with a revert PR; nothing is deployed yet,
so `CURRENT` is untouched.

### Step 2 — Deploy (`prepare` then `promote`)

Run from the **deploy worktree** (`~/r20-r24-exact-main-deploy`), not from a feature
worktree. `cio_phase2_exact_main_deploy.sh` reads its own worktree HEAD.

```bash
cd ~/r20-r24-exact-main-deploy
# detach onto the exact merged SHA first (the script reads its own HEAD)
git checkout <merged-sha>
scripts/cio_phase2_exact_main_deploy.sh prepare
scripts/cio_phase2_exact_main_deploy.sh promote
```

`prepare` clones `CURRENT`, overlays `origin/main`, rebuilds the frontend, stamps the SHA.
`promote` re-points `CURRENT` + systemd at the prepared release, restarts the service, and
health-checks — and **auto-rolls back to the previous release if the health check fails**
(`[CODE] scripts/cio_phase2_exact_main_deploy.sh`, `cmd_promote`). Do not claim `PROMOTE OK`
from a health-failed promote.

**Rollback:** `scripts/cio_phase2_exact_main_deploy.sh rollback` re-points `CURRENT` at the
previous release (or run `promote`'s own auto-rollback path). Verify the live dir
independently afterwards — `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`.

### Step 3 — Restart the poller (cron relaunch, **not** tmux)

After promote, the served release moves, but the long-lived poller daemon is still the old
process from the old release dir. Restart it by killing the daemon and letting the next
cron tick relaunch it from the **new** `CURRENT`:

```bash
# kill the old daemon; flock releases; cron relaunches it within ≤2 min from the new CURRENT
pkill -f run_telegram_callback_poller.py
# verify the relaunch picked up the new SHA (wait ≤2 min):
pgrep -af run_telegram_callback_poller.py
```

Do **not** `tmux kill-session -t telegram` and do **not** attach to the `telegram` tmux
session to "restart" anything — see §1.2.

**Rollback:** if the relaunched poller is unhealthy, `pkill -f run_telegram_callback_poller.py`
again and roll back the release (§2); the next cron tick relaunches from the rolled-back
`CURRENT`.

### Step 4 — Verify mode + served identity

```bash
curl -s http://127.0.0.1:7777/v3/build-meta.json | python3 -m json.tool   # git_sha == merged SHA
curl -s http://127.0.0.1:7777/api/v2/communications/health | python3 -m json.tool  # mode + owned_classes
```

---

## 3. Mode posture — CANARY soak, then ACTIVE

- **Now:** `COMMS_GATEWAY_MODE=CANARY`, `CANARY_CLASSES=ops`,
  `CANARY_CHATS=6993102664,8797974247` (`[VERIFIED]` via `/api/v2/communications/health`
  and the systemd drop-in `32-comms-gateway-mode.conf`).
- **Soak:** hold CANARY for an operator-determined window with the two sample-send
  outcomes confirmed (`operator_alert`→SENT, `report`→`LEGACY_DELIVERED` fail-closed — see
  `docs/deployment/canary-results.md`).
- **Then ACTIVE:** only after soak, switch the drop-in to
  `COMMS_GATEWAY_MODE=ACTIVE` + `COMMS_GATEWAY_ACTIVE_CLASSES=ops` and re-check the gates in
  `docs/deployment/production-activation.md` against the then-current SHA. The prior
  ACTIVE-for-`ops` attempt was reverted as premature — do not repeat it without a new soak.
- **Rollback at any point:** set `COMMS_GATEWAY_MODE=OFF` and restart consumers; the ledger
  rows stay (`docs/deployment/rollback-plan.md`).

---

## 4. Closeout

After the sequence: quote the dry-run/receipt output, record the merge SHA, the deployed
`CURRENT` pin, the poller restart receipt, and the final `/api/v2/communications/health`
snapshot. Revoke unused grants:

```bash
bin/guard revoke --all
bin/guard show
```
