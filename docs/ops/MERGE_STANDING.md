# Standing merge delegation

**Status: PROPOSED — INERT until two independent things are true.** Nothing here arms itself, and no
agent can arm it.

This is the routine merge path the operator asked for on 2026-11-02 ("Build the standing merge
delegation"): a reviewed, all-green PR inside the merge window may receive the existing
`operator-merge` label without a per-PR tap. It is **not** a merge actor and does not change the
merge itself — Mergify still queues and merges, the window still applies, the deploy poller still
promotes. The delegation moves one keyboard act, the label.

## Arming requires BOTH

1. **A ratified policy capability.** `AGENTS.md` must be `ACTIVE` at **29.6.0 or later**, and that
   version's **history row** must be class **MAJOR** and carry the structured marker
   `APPROVE_MERGE_STANDING: GRANTED`. A MINOR row can never grant it (the grant moves an
   operator/role boundary); a bare mention — a rejected example, a "not adopted", a passing
   reference — never arms anything; a `PROPOSED` header does not count. The text is read from
   `origin/main` in a checkout, and from the tree's own `AGENTS.md` only in the **served release
   tree** (`portfolio-server/CURRENT`), which is by construction the promoted main content. A branch's
   own `AGENTS.md` is never read.
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
| review | **two** `Adversarial-review: MERGE reviewer=… head=… coordinator=…` receipts bound to this exact head, each written by a **different authenticated GitHub author** — the login that posted the comment, not the `reviewer=` string — none by the PR author's account, and each naming a `coordinator=` that holds a live coordinator claim. One comment is one signature |
| window | inside the configured window (default `Mon–Fri 17:30–18:30 America/New_York`, asserted equal to `.mergify.yml` by a test) |
| STOP | the deploy STOP latch must be `ABSENT`; SET or UNREADABLE refuses |
| trust anchors | the PR changes none of the modules this path trusts (`trust_anchors` in the config: the evaluator, the check reader, the STOP reader, the claim board, the receipt parser, this config) |
| rate | at most **one** label per run (`max_labels_per_run: 1`, matching `batch_size: 1`) |
| race | **every** gate is re-asserted immediately before the label — head, draft, base, held labels, an independent `operator-merge`, STOP, the window and the still-valid standing approval. Any violation writes a `standing-merge-prelabel-refused` receipt and labels nothing |

**Receipt provenance is the practical limit.** GitHub identity is the only unforgeable part of a
receipt, so the two signatures must come from two different GitHub accounts. On this host `gh` is
authenticated as the operator, so every agent-written comment shares one login: two distinct
authenticated authors therefore need distinct agent GitHub identities, which do not exist yet.
The gate refuses rather than falling back to the `reviewer=` text. That is deliberate fail-closed
behaviour, not a bug to work around.

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

**Cadence honesty.** The digest timer runs 08:00 / 12:00 / 16:30 ET; the merge window is 17:30–18:30
ET. The wired caller therefore **cannot reach the window**, and `review()` says so in
`cadence.can_fire=false` instead of implying a label will be applied. A cadence that can reach the
window is a **scheduler change and an operator decision** (§17): PROPOSED, nothing installed, no timer
added by this change.

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
3. No timer is added by this change. To make the path actually fire, the operator must decide a
   cadence that overlaps the window (or move the window); until then every run reports
   `cadence.can_fire=false` and labels nothing.
4. Two agent GitHub identities are needed before two receipts can be independently authenticated;
   until then the path refuses on `review:` even with every other gate green.
