# Standing merge delegation

**Status: PROPOSED — INERT until two independent things are true.** Nothing here arms itself, and no
agent can arm it.

This is the routine merge path the operator asked for on 2026-11-02 ("Build the standing merge
delegation"): a reviewed, all-green PR inside the merge window may receive the existing
`operator-merge` label without a per-PR tap. It is **not** a merge actor and does not change the
merge itself — Mergify still queues and merges, the window still applies, the deploy poller still
promotes. The delegation moves one keyboard act, the label.

## Arming requires BOTH

1. **A ratified policy capability.** `AGENTS.md` on `origin/main` must be `ACTIVE` at **29.6.0 or
   later**, and that version's **history row** must name `APPROVE_MERGE_STANDING`. A version that
   merely mentions the token elsewhere does not count; a `PROPOSED` header does not count. This is
   read from `origin/main`, never from the branch being merged.
2. **A genuine operator standing approval.** One operator-authored comment, on the single open issue
   opened by the operator with the title **`Standing merge approvals`**, carrying a line:

   ```
   APPROVE_MERGE_STANDING wt/* until 2026-12-15
   ```

   - A **different token and a different issue** from the standing *push* approval
     (`APPROVE_PUSH_STANDING`). A push approval never authorises a merge.
   - The glob must start with `wt/`, `feat/`, `fix/`, `chore/` or `docs/`, and may never match
     `main`, `master`, `release/*` or `train/*`.
   - `until` is a required UTC date, at most 45 days after the comment.
   - Fenced, indented and HTML-commented lines are **examples, never approvals**.
   - `REVOKE_MERGE_STANDING` in any later operator comment (any case or markup) voids everything
     before it.
   - Closing the issue voids every comment before the close, permanently. An edited operator comment
     refuses the whole path until a new one is posted.

Until both hold, `scripts/lib/merge_standing.py` returns `enabled: false` **before making a single
GitHub call**.

## Every gate, on the exact head

The evaluator re-reads the PR at decision time. All of these must hold:

| gate | rule |
|---|---|
| branch | covered by the operator's glob; never a protected name |
| PR state | not a draft, base `main`, not already labelled `operator-merge` |
| held | no `held`/`broker`/`broker_active_trader` label, no held path (`config/merge_hold_paths.json`) |
| files | every changed path readable; a partial view refuses |
| checks | **every** check on the exact head green (`pr_all_checks_green`), at least one real success; a skip is not a pass; a truncated view refuses |
| review | **two independent** `Adversarial-review: MERGE reviewer=… head=… coordinator=…` receipts, distinct reviewers, none written by the author's agent, session or GitHub login, each bound to this exact head |
| window | inside the configured window (default `Mon–Fri 17:30–18:30 America/New_York`, asserted equal to `.mergify.yml` by a test) |
| STOP | the deploy STOP latch must be `ABSENT`; SET or UNREADABLE refuses |
| rate | at most **one** label per run (`max_labels_per_run: 1`, matching `batch_size: 1`) |
| race | the head is re-read immediately before labelling; if it moved, nothing is labelled |

## Running it

```bash
# default: dry run, describes every candidate and every refusal, labels nothing, writes nothing
python3 -m scripts.lib.merge_standing --dry-run

# host timer only, and only after arming: add one label when every gate holds
python3 -m scripts.lib.merge_standing --apply
```

The evaluator is wired into the **existing digest path** (`pr_merge_digest._run_digest`): every digest
run annotates its ready rows with a standing decision, and a PR the standing path labelled is removed
from the tap list so it is never asked for twice. If the evaluator itself fails, the digest still
sends — the failure is reported in the digest output (`standing.detail`), never raised.

## Evidence

Every label attempt appends a `MergeStandingReceipt@v1` row to
`<persistent-state>/data/runtime/pr_merge_standing/receipts.jsonl`: PR, branch, head, the operator
comment URL that admitted it, the two reviewer ids, how many checks were read, the label result, and
(for a moved head) both SHAs. The receipt has no state-machine consumer yet; it exists so a later
audit can prove what was seen.

## Revoking

Revoke with the operator's comment (`REVOKE_MERGE_STANDING`), close the issue, or set the existing
deploy STOP. Revocation stops **future** labels; it cannot unmerge what already merged. Re-arming
after a close requires reopening that same issue and posting a new dated line.

## What this never does

No merge, no push, no promote, no timer install, no policy edit, no broker path, no secret, no flag,
no held-class waiver, no emergency path, no deploy delegation. It adds one label and writes one
receipt.

## Adoption (operator)

1. Merge the AGENTS.md amendment (29.6.0) that names `APPROVE_MERGE_STANDING` in its history row.
2. Open the issue titled `Standing merge approvals` and post the dated line.
3. No timer is added by this change; the existing digest timer runs the evaluator. If a separate
   cadence is ever wanted, that is a new unit and an operator install — not part of this.
