# Automatic agent dispatch lane (`scripts/agent_dispatch.py`)

**Status:** BUILT, not enabled. This lane starts nothing by itself — the operator enables it (an n8n lane every 5
minutes or a host timer), and nothing in this PR touches cron, timers or `config/lane_registry.json` (§17).

**Why it exists.** Operator, 2026-11-04 ~13:10 ET: *"Once again, why are agents idle? … with all of this being idle,
I'm not for sure."* Ten of thirteen sessions sat idle for three hours after the no-idle mandate, because
idle-avoidance depended on the coordinator choosing to sweep. This makes the sweep mechanical.

## What one cycle does

```
tmux ls → every fleet session (broker/order/exec sessions are in the refusal list and never touched)
  └─ capture-pane → state: busy | input_pending | idle | blind
       └─ for each IDLE session, one assignment, in this fixed order:
            (a) its own queue rows with status queued or assigned only
            (b) a review: a CLEAN, non-draft PR it did not author, with no MERGE verdict at that exact head
            (c) merge-prep: CLEAN + exact-head MERGE verdict, but the author's claim carries a different head
            (d) the oldest unowned queue row
            (e) a chore: a claim past heartbeat + 2 h
       └─ send ONE instruction; paste-buffer, pause, Enter; confirm busy within 30 s; one retry
       └─ ledger line per dispatch; MERGE_READY.md every apply; DISPATCH_IDLE_ALERT.md when work runs out
```

`blind` is a state of its own: a pane that cannot be captured is never treated as idle, and never as busy. A session
that is busy or has unsent input in its box is left alone — unsent input means the operator or the vendor CLI is
already mid-action.

## What it will never do

- **Never merge or push.** `pr_merge_delegation` is not imported and `gh pr merge` / `git push` appear nowhere; the
  lead's helper remains the only merger. `MERGE_READY.md` is a report.
- **Never author a review or write a review artifact.** It *assigns* a review by naming the PR; the reviewer writes the
  verdict. A PR's author session (the active claim on its head branch) is never offered its own PR, and every
  instruction repeats "you did not author it".
- **Never change a queue row's status**, never write a claim, never touch a worktree. Rows are read-only input; the
  only statuses that count as work are `queued` and `assigned` — every other status is silence, per the queue's own
  `status_rules` (2026-11-04).
- **Never schedules itself.** No cron, no timer, no lane registry entry.
- **Never calls a model.** Deterministic code only: screen classification, file reads, `gh` reads, tmux keystrokes.

## The rails are tested, not asserted

`tests/test_agent_dispatch_20261104.py` (57 checks) covers: busy beats everything; unsent input is not idle; a failed
capture is blind; only `queued`/`assigned` are work; `takeable_at` and another session's live claim hold a row; the
selection order (a)…(e) including "never your own PR" and "a MERGE at head needs no second reviewer"; the merge pump
separating ready from one-step and refusing an author's own MERGE; the submit path pasting (never `send-keys -l`),
retrying once, and logging `dispatch_failed`; the idle alert threshold; the two-reviewer cap and the newest-PR-first order; and that **a dry run creates no files** while
an apply writes only the ledger and its two report files.

Four of those are written as invariants rather than as behaviour, because each was a real defect found by review at a
later head:

- **Identity, not spelling.** Every output path is checked twice — by resolved path *and* by inode — so a hardlink
  (`ln MERGE_READY.md AUDIT_FIX_QUEUE.json`) is refused instead of truncating the queue. All three output identities
  are settled *before the first keystroke*, so a misconfigured `--ledger` costs zero sends, not a fleet-wide paste
  followed by a refusal.
- **New evidence only.** A busy marker must be absent from the pre-paste tail (or more frequent in the new one) and
  the tail must have changed; a capture that returns after the confirm deadline is discarded, not believed.
- **`submitted` means an Enter was delivered** after a paste that succeeded — never "an attempt was made".
- **The reviewer cap is per head.** History is keyed by `(pr, head sha)`: verdicts and dispatches recorded against an
  older head neither spend the new head's budget nor bar that reviewer from reviewing the new revision.

## How to read the ledger

One JSON line per dispatch, appended to `coordination/coordinator/dispatch_ledger.jsonl`:

```json
{"schema":"AgentDispatch@v1#Dispatch","ts":"…Z","cycle_id":"cyc-…","session":"cc-deepseek-4",
 "kind":"review","target":"2620","sent_sha256":"…","submitted":true,"busy_after_30s":true,
 "attempts":1,"detail":"busy confirmed after 3s","outcome":"dispatched"}
```

- `outcome: dispatched` — the pane went busy inside the confirm window. That is the only success signal.
- `outcome: dispatch_failed` — submitted but never went busy after two attempts. **The first thing to read when the
  fleet looks quiet:** a run of `dispatch_failed` means keystrokes are not landing (dead pane, vendor dialog, wrong
  session), not that the fleet has no work.
- `kind` says what was handed out (`queue`, `review`, `merge_prep`, `unowned_queue`, `chore`); `target` names the row id
  or PR number, so a cycle can be reconstructed without asking any agent what it was told.
- `sent_sha256` is the hash of the exact text sent — comparable against what a session says it received.

`MERGE_READY.md` lists every CLEAN PR that is ready (exact-head MERGE verdict + current author claim) and every PR one
step away with the step named. `DISPATCH_IDLE_ALERT.md` exists only when a cycle found no work while sessions were
idle: it asks the lead for a decision (add work, or close sessions) and names them.

## Prior art

Built on the **repo** nudger, `scripts/agent_nudger.py` — the copy with tests, a refusal list, isolated
`--state`/`--ledger`, and BLIND handling for a failed capture. The **live** coordinator copy
(`coordination/coordinator/agent_nudger.py`) has diverged from it and is what the host cron runs today; see
`docs/ops/NUDGER_N8N_MIGRATION_PROPOSAL_20261103.md` §1a for why the two differ and which is canonical for what. The
detection semantics here are the repo port's, deliberately, and the multi-line submit trap that the live copy hits
(`send-keys -l` of a multi-line prompt does not submit) is avoided by pasting through a tmux buffer.

## Running it by hand

```
python3 scripts/agent_dispatch.py                 # dry run (default): whole plan, no writes, no keystrokes
python3 scripts/agent_dispatch.py --json          # the same plan as machine-readable JSON
python3 scripts/agent_dispatch.py --apply         # send, then write ledger + MERGE_READY.md (+ alert when work runs out)
python3 scripts/agent_dispatch.py --limit 2       # cap dispatches in one cycle while watching behaviour
```
