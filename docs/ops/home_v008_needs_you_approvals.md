# Home v008 "Needs you" — operator approvals (backend A)

Status: backend only. The card (UI), the HTTP route and the Telegram nudge are separate pieces. Nothing in this module
executes by itself; every action type is fail-closed until its own reviewed adapter is wired.

Spec: `persistent-state/handoffs/SPEC_HOME_V008_NEEDS_YOU_APPROVALS_20261103.md` ·
A/B boundary: `persistent-state/handoffs/DESIGN_HOME_V008_APPROVALS_A_B_BOUNDARY_20261103.md`

## Why it exists

Decisions buried in Telegram are decisions the operator will not see while asleep. A request becomes a card on Home with
one Approve button, and the click is bound to exact facts and leaves a receipt.

## The closed action list

| type | a click does |
|---|---|
| `merge_pr` | merge PR #N at exactly the reviewed head (refuses if the head moved) |
| `rerun_ci` | re-run the failed jobs of run N, once |
| `grant` | issue a guard grant exactly as shown (tier, duration, uses, reason) |
| `stop_job` | end one named stuck process on the stoppable list |
| `install_schedule` | install one reviewed scheduler line already in the lane registry |
| `restore_store` | run a reviewed restore packet (dry-run diff shown, evidence copy, rollback) |
| `policy_approval` | record the APPROVE line for an AGENTS/policy PR at its exact head |

The list is a literal in `scripts/lib/home_approvals.py`, not configuration. A request naming anything else is refused
at creation and never stored — there is no object to render as a button. Broker orders, credentials, live trading flags,
force-push and deletion have no code path here (MBI_BEHAVIOR = 0).

Each type requires its exact bound facts at creation (full 40-hex `head_sha`, numeric `pr`/`run_id`/`pid`, hashes
elsewhere). A card cannot offer a button whose facts are unknown.

## The three rails

1. **Server-only decision.** `decide()` takes an `OperatorContext` that only `server_context()` can mint (a module-private
   seal). `None`, a plain dict, `True`, or a hand-built `OperatorContext` are each refused with
   `server_context_required`. The factory itself accepts only a `tailnet:<login>` operator on the authenticated
   `serve_proxy` listener, and `decide()` requires the recorded actor to *be* that login. The CLI cannot decide at all:
   `approve`/`decline` exit with `server_context_required` because a command line cannot prove a session.
2. **The asker is never the decider.** Refused by identity and by session.
3. **Expiry re-asks.** A request past `expires_at` moves to `expired` with `reask_requested: true`; a click does
   nothing. Nothing is ever auto-approved.

## Facts are revalidated at click time

`revalidate()` asks the executor whether the bound facts still hold. When they moved, the click is refused with a
plain-English reason and the request **stays open** with `blocked_reason` set, so the card disables the button with
"This changed. The lead will re-ask." rather than making the request silently vanish.

## Receipts

Written before the action runs, so a failed action still leaves the decision on record:

- `needs_you/ledger.jsonl` — created / approved / declined / expired / facts_moved / executed / timed_out / failed /
  question
- `coordination/digest_approvals.jsonl` — every decision and timeout

A timeout or partial failure records **what was attempted**: action type, exact facts, the executor steps reached
(`step_reached` and the ordered list), the timeout and the elapsed time. A timed-out action is recorded as
`timed_out_unconfirmed` with `needs_reconciliation: true` — a join timeout does not stop work that is already running, so
the board never claims it did. A per-request execution marker means it cannot be started again.

The execution boundary re-validates everything the approval relied on: the record's schema, its closed-list type, the
hash of its immutable approval binding, and the executor's live-fact check a second time — a record that changed after
approval stays OPEN with `blocked_reason` and nothing runs.

## The event stream the Telegram nudge reads

Every transition appends one `ApprovalRequestEvent@v1` row to `<state root>/approvals/requests.jsonl`, which is the file
`scripts/approvals_notify.py` (piece D) reads:

- `created` — a new request is open;
- `approved` — published **before** the action runs, so a slow, timed-out or failed action is never re-nudged as if it
  were still undecided;
- `declined`, `expired` — closed;
- `updated` — a question or a moved fact; the request stays open.

`requester` is a plain session string for that lane; the richer mapping rides under `requester_detail`. A failed publish
is suppressed — the nudge is an edge, not a gate, and it must never turn a recorded decision into an error. The card is
still the authority on readability: `list_open()` raises on a broken record while the nudge keeps delivering the ones it
can read and reports what it could not.

## Reading the board

`list_open()` returns `[]` only when the store was readable and genuinely empty. A corrupt or unreadable record raises
`store_unreadable`, so the card can show an error state and never a green "Nothing needs you" for a failed read.

## Asking and answering

```
scripts/home_approvals.py --state-root <root> ask --type rerun_ci \
  --title "Re-run CI on #2550" --why "One flaky shard failed twice" \
  --rule "AGENTS §7 checks" --what-happens "Re-runs the failed jobs once" \
  --risk "None material" --undo "Nothing to undo" --requester cc-deepseek-5 \
  --facts '{"run_id": 41683436869, "head_sha": "<40-hex>"}'

scripts/home_approvals.py --state-root <root> list
scripts/home_approvals.py --state-root <root> approve <id> --actor <login> --operator-session --csrf-ok
```

The last two flags are set by the Command Center server from a verified session; an agent invoking the CLI cannot pass
them meaningfully, and the library refuses without a minted context. The CLI requires an explicit state root and never
defaults to `/tmp`.

## Read-only adapters

`scripts/lib/home_approvals_adapters.py` answers "is this still true?" for all seven types without performing anything:
PR head/state, run head, `/proc` start time and command hash, unit absence, packet sha256, grant id. `register_read_only()`
wires the check and leaves execute fail-closed, so a click on an unwired type records "no reviewed wiring yet".

Wiring an execute half (a merge through `pr_merge_delegation`, a CI re-run through the existing lane, and so on) is a
separate reviewed change per type. Do not add a second path to any action that already has one.
