# Nudger → n8n migration — reviewed proposal (2026-11-03)

**Status:** PROPOSED. Nothing here is armed. No live file, timer, n8n workflow or allowlist entry is changed
by this document. Operator decision required at §7.
**Owner:** cc-deepseek-6 (board item 16). **Reviewer:** lead (codex) → operator.
**Rule it obeys:** "n8n first" for scheduled pipelines (operator, 2026-10-09 dispatch-class ruling), shadow
first, and never route around a native denial.

## 1. What exists today (the honest description)

`~/trade-ai-releases/persistent-state/data/coordination/coordinator/agent_nudger.py` — **outside the repo**,
owned by the coordinator directory, run by a host timer every 5 minutes. It:

- lists tmux sessions matching `^(cc-deepseek|cc-anthropic|cx-|cu-|codex$)`, minus one excluded session;
- captures the last 12 non-empty screen lines, hashes them, and decides **BUSY / IDLE** from screen text only
  (spinner markers), plus `STALL` (vendor 5xx / "overloaded" / "rate limit") and `UNSENT` (text in the input
  box that was never submitted);
- under `--apply` only: types one of three fixed prompts and presses Enter, rate-limited per session
  (`min_gap_minutes` 10, `stall_gap_minutes` 3), and appends one line to `coordinator/ledger.jsonl`;
- default is **DRY RUN**; state is `coordinator/agent_nudger_state.json` (atomic replace).

Properties worth keeping: fixed prompt text; no Ctrl-C/Ctrl-U; screen-only detection; per-session cooldown;
one ledger line per nudge. Properties that argue for the migration: it lives outside the repo (no claim, no
review, no CI, no receipts beyond its own ledger), its schedule is a host timer rather than the scheduler of
record, and a typo or an edited copy is invisible to every rail we have.

## 2. Target shape

```
n8n schedule (every 5 min)
  └─ gateway records a run request (coordination `runs` row, mode=dry_run|live)
       └─ scripts/n8n_run_executor.py  (existing: locks, stage clamp, RunReceipt, run_outcomes, breaker)
            └─ lane `agent_nudge` → scripts/agent_nudger.py  (repo-owned, deterministic, no network)
                 └─ tmux capture/send-keys on this host ONLY; state + ledger under persistent-state
```

n8n never gets a shell, a tmux socket, or a variable that names a command: it writes a ledger row naming a
lane, and the executor owns everything after that. That is the same contract every other lane uses; no new
privilege is introduced by the scheduler.

## 3. Phases and tasks (design ids = `DSN-20261103-nudger-n8n-P<n>-T<m>`)

| id | task | acceptance |
|---|---|---|
| `DSN-20261103-nudger-n8n-P1-T1` | Move the script into the repo verbatim in behaviour: `scripts/agent_nudger.py`, config in `config/agent_nudger.json` (`NudgerConfig@v1`), state default `<state>/data/coordination/agent_nudger/state.json`, ledger lines to the same state dir; add a `--dry-run` default and `--apply`. | byte-identical decisions for a fixed set of captured panes (fixtures); `--apply` refuses unless `--apply`; unit tests for BUSY/IDLE/STALL/UNSENT/cooldown |
| `P1-T2` | Parity harness: replay N captured panes from a read-only copy of the live state and compare the repo copy's decisions with the live nudger's last 50 ledger lines. | a table of agree/disagree; **no disagreements before P2** |
| `P1-T3` | Refusals: a session whose name matches `broker|order|execution|mbi` is never captured into a prompt and never typed at; the config cannot re-enable it (built-in list, unioned like `incident_requeue.refused_regex`). | a test that a config with an empty refusal list still refuses |
| `P2-T1` | Add lane `agent_nudge` to `config/n8n_run_allowlist.json`: command pinned to the repo script, `stage: shadow`, `mode_arg` = `--dry-run`, lock `agent_nudge`, timeout 120 s, `output_signal` = the state file. | the executor runs it in `dry_run` even if a `live` fire is requested (stage clamp); receipt shows `stage_clamp` |
| `P2-T2` | n8n workflow (scheduled, every 5 min) that records the run request and stores the executor's outcome; alert on `RUN_REFUSED`/`RUN_TIMEOUT` through the existing incident path. | one week of shadow receipts; zero refused rows caused by the lane |
| `P2-T3` | Shadow parity report: what the shadow would have typed vs. what the live nudger did, per session, per run. | disagreements are explained or the phase does not advance |
| `P3-T1` | Cutover window chosen on evidence (operator approval): stop the host timer (archived, not deleted), flip the registry `stage` to `live` for the lane, operator-quoted dry run first. | first live receipt with a `nudge` line; the old timer is archived with a tripwire |
| `P3-T2` | Rollback: one command flips the stage back to `shadow` and re-enables the archived timer; state file format is shared so both can run (the lane lock prevents double typing). | a quoted rollback drill |
| `P4-T1` | Decommission the coordinator copy: archive under `archive/` with a read-tripwire; update `WORKERS.md`/`BOARD.md` to point at the lane. | nothing in the coordinator dir is live; tripwire tested |

## 4. Guard boundaries this migration keeps

1. **Native denial is never bypassed.** If the executor refuses (lane not allowlisted, stage unknown, lock
   held, effect-claim refused), the run is a refusal and a report; nothing falls back to a direct `tmux`
   call from n8n or from a shell node.
2. **Dry-run is the default at three layers:** the script's own default, the lane's `mode_arg`, and the
   stage clamp. `--apply` requires a live stage and an operator-approved registry change.
3. **The prompt text is code.** It is not configurable from n8n, not parameterised by a ledger row, and
   covered by a test; a change is a reviewed PR.
4. **No new authority:** the lane only calls `tmux ls|capture-pane|send-keys` and writes its own state and
   ledger. It never reads a credential, never touches broker paths, never presses Ctrl-C/Ctrl-U.
5. **Broker-adjacent sessions are refused** by the built-in list (`P1-T3`), regardless of config.
6. **Every nudge leaves a receipt:** the executor's RunReceipt plus one ledger line in the existing
   `ledger.jsonl` shape (`by: agent-nudger`).

## 5. Risks and mitigations

| risk | mitigation |
|---|---|
| A keystroke scheduler is powerful; a bad edit types into every agent session | fixed text in repo code; tests; shadow week; cooldown; per-run receipt; stage flip is the off switch |
| n8n down → no nudges (agents idle) | keep the host timer through P2/P3; the lane lock makes double-running harmless |
| Screen parsing is brittle across vendor UIs | fixtures from real panes; disagreements counted in the parity report; unknown screens default to `wait`, never `NUDGE` |
| State file divergence (host dir vs persistant-state) | one owner after P1 (`<state>/data/coordination/agent_nudger`); the live file is copied once, then read-only |
| n8n container cannot see the host tmux server | the lane runs in the executor on this host; n8n only records the request. If the executor is moved into a container later, the lane is refused, not silently broken |

## 6. What this proposal does NOT do

- It does not edit, stop or move the live nudger or its timer.
- It does not add the allowlist entry, the workflow or the registry row.
- It does not change the prompt text.
- It does not make n8n able to run arbitrary commands (nothing in n8n names a command; the allowlist is data
  read by the executor).

## 7. Operator decisions requested

1. **Approve the target shape** (n8n schedule → executor lane → repo script) or prefer a different scheduler.
2. **Approve P1 only** first (repo copy + tests + parity, live nudger untouched), and decide P2/P3 on the
   parity evidence.
3. **Name the cutover window** for P3 (markets closed is not required — this touches no broker path — but
   the operator's presence is).
4. Confirm the **ledger shape** stays `coordinator/ledger.jsonl` (one line per nudge, `by: agent-nudger`) or
   moves to the incidents/ops ledger.

## 8. Open questions for the lead

- Should the lane live in `config/n8n_run_allowlist.json` under the existing `agents` territory, or a new
  `coordination` class? (Affects caps and the breaker group.)
- Does the parity week count as sufficient evidence for P3, or does the lead want a second week?
- Should the refusal list include any session that has ever been used for broker/execution work (by name
  history), not just the current name?
