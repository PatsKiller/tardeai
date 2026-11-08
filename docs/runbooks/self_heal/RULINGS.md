# Rulings behind the workbook

Hand-written. Every **disputed cell** in the catalog — an `action`, a `tier`, an id, a category — that a reviewer
could reasonably have decided the other way, with the evidence and the reasoning behind the decision that shipped.
A page in this directory is generated; this file is the record of *why* it says what it says, so one decision can be
re-opened without re-reading the catalog.

The decisions below were made by **cc-deepseek** under LQ-20261107-1259 (the operator's P0 runbook-catalog row),
against the 14-day replay of 2026-11-08T22:45Z. They are proposals for the lead's review, not operator rulings.

## The evidence every ruling was made against

`scripts/ops/self_heal_runbook_replay.py --as-of 2026-11-08T22:45Z --window-days 14`, catalog v2026-11-08.2:

| | |
| --- | --- |
| receipts scanned | 41 586 |
| failures | **1 028** (748 receipt failures + 280 dead letters) |
| signatures | **24** |
| entries hit | **17 of 50** |
| catch-all | **0** |

The per-signature table is [COVERAGE.md](COVERAGE.md). A ruling below cites a hit count from it; the count is the
whole argument for a tier in most cases.

LQ-20261107-1256 (cc-deepseek-8) reported 12 unclassified signatures and 6 action/tier disagreements. §1–§2 are what
changed to close them; §3 is each disagreement, ruled.

## 1. Two matcher words, no new entry

| signature (replay) | hits / 14 d | corpus wanted | before | after |
| --- | --- | --- | --- | --- |
| `RUN_SKIPPED_LOCK: flock_held` | 565 | A01 wait / `auto` | A01 wait / `auto_notify` | **A01 wait / `auto`** |
| `RUN_TIMEOUT: timeout_exit_<N>` | 53 | E01 timeout | K05 catch-all | **E01 wait / `auto_notify`** |

`lock_held` was added to A01's `failure_class`; the replay's classifier already derives that class from
`RUN_SKIPPED_LOCK`, so a held lock now reaches the entry that describes it rather than a neighbour.
`wall_timeout` was added to E01's for the same reason.

## 2. Nine entries for the nine gaps

Each was added at its priority position (the file is not re-sorted: a reorder would bury the change in churn), with
the corpus's action and tier unless a ruling below changed it.

| entry | class | hits / 14 d | action | tier | why it is not the catch-all |
| --- | --- | --- | --- | --- | --- |
| `A06-effect-already-claimed` | `effect_claimed` | 3 | `noop_wait_recheck` | `auto` | a concurrency skip is normal; escalating it would alert on correct behaviour |
| `C06-output-unverifiable` | `output_unverifiable` | 38 | `escalate_finding` | `auto_notify` | the run finished but its output cannot be proven — an evidence gap a human must close |
| `C07-upstream-verification-failed` | `upstream_verification` | 0 | `escalate_finding` | `auto_notify` | the defect is upstream of this lane; a re-run cannot verify what the source did not publish |
| `F06-effect-no-owner` | `effect_no_owner` | 42 | `escalate_finding` | `auto_notify` | a missing owner is dispatch-plane config, not a lane fault |
| `H04-db-error-while-updating` | `db_error` | 0 | `escalate_finding` | `auto_notify` | a write error is never retried blindly: a retry can duplicate the write |
| `H05-db-connection-closed` | `db_connection_closed` | 2 (+1 SSL) | `noop_wait_recheck` | `auto` | a closed connection during rollback is benign; the next slot is the retry |
| `I05-env-names-missing` | `config_env` | 6 | `escalate_finding` | `human_only` | the fix is an allowlist edit only an operator makes |
| `I06-log-path-not-a-directory` | `config_path` | 0 in-window (659 / 30 d) | `escalate_finding` | `auto_notify` | the lane cannot take its lock or write its log until a config edit lands |
| `J03-data-defect-in-input` | `data_defect` | 3 | `escalate_finding` | `auto_notify` | the input is missing or too old; a runbook must never repair a producer's rows |

`C07`, `H04` and `I06` have **zero hits in this 14-day window** and are required by the corpus and by the mining
taxonomy (I06 is the highest-count config defect of the 30-day window: 659 failures on 10 lanes). An entry at 0 hits
is unexercised, not dead; it is kept because the 30-day evidence is the wider source.

## 3. The six group-D disagreements, ruled

LQ-1256 §4 listed six cells where the corpus expectation and the catalog disagreed. Each is ruled here. The ruling
changed **the catalog** in four cases and left it in two; the corpus `expect` block was then aligned to the ruling,
never to the engine's unexamined answer.

### R1 — `flock-held-skip`: A01 tier `auto` (was `auto_notify`)

565 skips in 14 days across 12 lanes. A held lock is the lock doing its job: the next slot will run when the holder
finishes. A message per skip is 565 messages that carry no action. The budget still bounds the silence: after
`max_attempts` (3) the engine escalates `max_attempts_reached`. **Amend if** a real contention incident is traced to
a skip that no message named.

### R2 — `executor-lost`: F01 tier `auto` (was `auto_notify`)

106 losses in 14 days. An executor lost to a restart is recovered by the scheduler's next slot; the loss is already
visible in F01's own receipt. Notifying per loss would page on every deploy. **Amend if** losses cluster inside one
hour for one lane — that is a restart-storm signal the tier cannot express, and it belongs in the monitor, not here.

### R3 — `empty-output`: C02 action `rerun_once_via_gateway` / `auto` (was `escalate_finding` / `auto_notify`)

27 occurrences, 26 of them dead letters. An empty output is usually a producer hiccup that one gateway re-run clears.
Escalating on the first empty produced findings nobody acted on. The entry now spends its one attempt on a re-run,
under the gateway's effect key, and escalates only if that fails. `delay_s = 120` gives the upstream a moment.

### R4 — `bridge-route-refused`: F02 keeps `escalate_finding` / `auto_notify` (corpus wanted a gateway re-run)

9 occurrences. `BRIDGE_ROUTE_REFUSED` is a **policy answer** — the governed bridge refused the route. A gateway
re-run asks the same policy the same question and gets the same answer; the escalation is the correct signal, and it
is rare (9 / 14 d). This is the one group-D cell where the corpus, not the catalog, was wrong.

### R5 — `json-decode-error`: I04 keeps `escalate_finding` / `human_only`, and the corpus category moves J -> I

6 occurrences (5 as their own signature, 1 folded into `RUN_FAILED: exit_<N>`). Invalid config JSON is a config
defect a human fixes; the plan's category **I** (config/registry drift) describes it, and the LLM fixer's **J** does
not. The corpus fixture's `category` and `expect.category` were both moved to `I` with the entry id, so the schema
check and the expectation agree.

### R6 — E01 `wall_timeout`: keep `noop_wait_recheck` / `auto_notify`

53 occurrences. The executor killed the run at the wall; no runbook action shortens the next slot, so waiting is
honest. The notification is kept because a run that hits 124 is a **duration signal**: the lane's own budget is the
thing to change, and a silent wait would hide it. (The corpus asked for `escalate_finding`; escalating a timeout that
will simply be retried on schedule adds a finding without an action.)

## 4. The catch-all: `GATE_REASONS` is empty, and stays a gate

The replay exits 3 when any signature reaches `K05-unclassified-catch-all` without a written reason. After §1–§2
**no signature in the window reaches it (0 hits)**, so `GATE_REASONS` is empty — not "every gap is tolerated", but
"there is no gap". A new unclassified signature fails the gate until someone adds an entry or writes a reason with
its evidence. Widening the catch-all is never the fix.

## 5. One signature, several plans — documented, not a defect

`RUN_FAILED: exit_<N>` (155 hits) plans to four different entries: `J01-code-defect` (144), `A03-sqlite-database-locked`
(9), `D02-provider-5xx` (1, refused by its retry-budget precondition) and `I04-invalid-config-json` (1). The signature
is short because a dead letter records only `exit_1`; the **class** is derived from the rest of the receipt, and the
class is the real signal. The workbook prints every plan variant rather than a last-sample action, so this stays
visible instead of becoming a wrong claim.

## 6. Small corrections made with the rulings

- The catalog's `_ordering` note called the catch-all "K04"; it is **K05**. Fixed in the same revision.
- The nine new entries were written with one or two test labels; each now declares the plan's triple
  (`-match`, `-refuse`, `-repeat`, plus the corpus-derived labels where they exist). The LQ-1231 module asserts
  `>= 3` per entry and one synthetic sample per entry; its `MATCH_SAMPLE` gained the nine rows.

## 7. How to re-open a ruling

1. Add the evidence to this file: the signature, its count, the lane(s), and what the alternative would have done.
2. Change the catalog (one entry's `action`/`tier`, or one matcher word) and the corpus `expect` in the same commit.
3. Regenerate: replay -> `COVERAGE.json` -> `gen_self_heal_runbook_docs.py --write`.
4. The self-heal freeze applies: **no fixer `--apply` and no model-backed fix attempt** until the operator approves
   this catalog. A ruling that needs run evidence from a live cycle waits for that approval.

— cc-deepseek, 2026-11-08T22:56Z (LQ-20261107-1259)
