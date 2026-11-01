# PR review in the Command Center — independent review, read and decided in one sheet

- **Design:** `approvals-pr-review/v001` (PROPOSED, AGENTS.md §28.13). Nothing here is built.
- **Requested by:** the operator, 2026-10-27, verbatim: "we really need to build something that actually has a review
  that I can review in the same modal of the command center."
- **Status:** design and spec only. Building needs the operator's design approval (Approvals → Designs) and the
  decisions in §12.
- **Data:** every PR number, title, SHA, session and file in this spec and the mockup is invented.

## 1 Problem

1. The operator approves merges by tapping the Telegram digest (PR #2235, `scripts/lib/pr_merge_digest.py`). The
   digest shows a number, a title, a class and a CI state. It does not show what the PR does, what could go wrong, or
   whether anyone other than the author has read it.
2. The operator works from a phone and cannot review diffs on GitHub there.
3. An automated permission check refuses agent-driven merges as "merge without review". It is right to refuse:
   today no independent reviewer reads a PR before it merges. A tap on a one-line summary is the operator's approval,
   but nobody has reviewed the code.
4. AGENTS.md 25.0.0 §28.15 item 10 says a review counts only when the reviewer is not the author's agent and session.
   No review of that kind runs today.

## 2 Goal

For every READY PR:

- A reviewer agent that is not the author reads the exact head. It writes a structured review bound to that head SHA.
- The operator reads the review in a full-screen sheet in the Command Center, opened from Approvals or from the
  digest link.
- The operator decides per PR: **Approve**, **Hold** or **Ask**.
- The decision goes into the operator decisions ledger, bound to the head SHA. An Approve takes the same
  `operator-merge` label path the digest uses.
- A new push makes the review stale and cancels any approval of the old head.

## 3 What already exists (reused, not rebuilt)

| Piece | Where | Reused for |
|---|---|---|
| Decision ledger: hash-chained, flock-serialized, `READ_STARTED` → `READ_MARKER` → `DECIDED`, refuses `DOCUMENT_CHANGED`, `CHANGES_UNREAD`, `ALREADY_DECIDED` | `scripts/lib/operator_approvals.py` (`DecisionLedger`) | Recording the operator's decision for each PR and head |
| Approval queue projection (sources → items; a failed source is a gap, never a zero) | `operator_approvals.queue_projection` | A new source, `pr_reviews`, gives the queue one `MERGE` item per PR |
| Approvals page with kind tabs; `/approvals/:id` reader with per-change read markers, "Ask the CIO", Approve / Reject / Request changes | `ApprovalsHub.tsx`, `AmendmentReader.tsx` | The list row and the sheet's read-before-approve rule |
| Phone full-screen sheet with ← Back; desktop side panel | `MobileDetailSheet.tsx`, `OpsIncidents.tsx` (#2238) | The sheet itself |
| Digest: READY = not draft, the four required checks green on the head, not held | `pr_merge_digest.classify_pr` | Deciding when a review is queued |
| Approve → `PrMergeDigestApproval@v1` → `operator-merge` label → `PrMergeHeadBinding@v1` | `settle_approve_all` | The same label call, with `source: "cc_review"` |
| Head moved → label removed, PR goes back into the next digest | `reconcile_head_binding` (every 3 min) | Making a review stale (no new mechanism) |
| Held classes: `broker_order`, `secrets`, `agents_policy`, `hooks_guard`, `merge_deploy_control` | `config/merge_hold_paths.json`, `scripts/lib/merge_hold_paths.py` | The held banner; no `operator-merge` |
| Anthropic credit (tiers, per-call caps, daily cap, journal); per-process caps | `config/anthropic_credit_policy.json`, `config/llm_process_registry.json` | The reviewer's budget (§7) |

## 4 Flow

```
PR READY (non-draft, 4 checks green on head H)
  → host review runner queues review(PR, H)       [debounce 10 min after the last push]
  → independence check (author ≠ reviewer)         [refuse → no review, gap shown]
  → data-quality gate (§29): full file list, diff hash, H still the head
  → reviewer model call (Anthropic credit)         [caps: §7]
  → PrReview@v1 written to the review store        [bound to H, base B, diff sha256]
  → Approvals "Merges" tab + digest line link to /approvals/pr:<N>
  → operator opens the sheet, reads the findings (read markers), decides
       Approve → ledger DECIDED(APPROVE, item pr:<N>, head H)
                → host applier adds operator-merge for H, writes PrMergeHeadBinding@v1 (source cc_review)
                → Mergify merges in its ET window → deploy_on_main promotes
       Hold    → ledger DECIDED(HOLD); PR is left out of later digests until it gets a new head or the operator releases the hold
       Ask     → ledger QUESTION; reviewer answers in the sheet (one capped call); not terminal
  → new push to the PR (head H′):
       review(H) marked STALE; Approve off; reconcile removes operator-merge if H was approved; review(H′) queued
```

## 5 The review — `PrReview@v1`

The deterministic harness fills one record per (PR, head SHA). The model writes only the fields marked *model*.
Every other field comes from GitHub or the repo.

| Field | Source | Notes |
|---|---|---|
| `pr`, `title`, `url`, `base_ref`, `base_sha`, `head_sha` | GitHub | `head_sha` is the binding |
| `diff_sha256`, `files[]` (path, area, +/−, status) | harness | the full file list is required; a partial list → `CANNOT_REVIEW` |
| `author` {vendor, agent, session, model} | commit trailers (`Claude-Session:`, `Co-Authored-By:`), claim board, PR body | used for the independence check |
| `reviewer` {process_id, provider, model, run_id, started_at, finished_at, cost_usd} | harness | |
| `independent` {ok, rule: "§28.15 item 10", compared: [author ids]} | harness | `ok=false` → no review is published |
| `summary` | *model* | plain language, 2–5 sentences: what it does for the operator, what it does not touch |
| `risk` {level LOW/MEDIUM/HIGH, why} | *model*, then the harness raises the floor | the harness floor: `shared-infra` → at least MEDIUM; any held class → HIGH |
| `classes` {held: [...], shared_infra: bool, labels: [...]} | `merge_hold_paths.held_classes`, labels | the model never decides whether a PR is held |
| `areas[]` → `hunks[]` {file, header, start_line, note} | harness splits the diff into hunks; *model* writes one `note` per hunk | a hunk with no note is shown as "not explained"; a review with more than 10% of hunks unexplained → `CANNOT_REVIEW` |
| `evidence` {checks: {name: state}, tests_changed, tests_added, dry_run_quoted, real_layout_proof, adversarial_receipts} | GitHub + PR body parse | never the model's word |
| `findings[]` {id, severity BLOCKER/MAJOR/MINOR/NOTE, title, file, line, detail, suggestion} | *model* | `file:line` must fall inside a changed hunk; otherwise the harness drops the finding and counts it |
| `verdict` MERGE / MERGE_WITH_NOTES / HOLD / CANNOT_REVIEW | *model*, then the harness rules | any BLOCKER → HOLD; any held class → shown as "Held · your own merge" whatever the verdict; failed gate → CANNOT_REVIEW |
| `stale` | derived at read time | `head_sha` ≠ the PR's current head |
| `document_sha` | `operator_approvals.digest(review minus runtime fields)` | what the ledger binds |

The reviewer prompt gets the diff, the file list, the PR body and the AGENTS.md sections the touched paths fall
under (§0, §25.10, §28.15 items 2, 3 and 10, plus §28.13 for UI). It also gets one instruction: report what the diff
does, not what the PR body claims, and raise a finding wherever the two disagree. Output is strict JSON
(`build_*_json_schema` pattern, the same as `cloud_review`). One retry is allowed on a schema failure.

## 6 Independence — how this satisfies an "independent review" for the merge actor

- **The reviewer is never the author.** The review runner is a host process (`pr_independent_review`) with a fresh
  context. It has no access to the author's session transcript or worktree. Its id is
  `host:pr_independent_review:<run_id>`. That id is never the same as an author agent and session, so it meets
  §28.15 item 10 ("another agent identity").
- **Different model where it matters.** By default the reviewer is Claude Opus 5.5. If the author's trailers name
  the same model family, and the PR is `shared-infra` or held, a second read is added from a different provider:
  the free OAuth ChatGPT or Grok lane through the existing `cloud_review` path, which costs $0. A held-class PR
  needs two reviewer identities (§28.15 item 3). The sheet shows both. (Decision D2.)
- **Two independent reviews before any merge.** For a non-held PR, Mergify merges only after (a) a review by an
  identity other than the author and (b) the operator's own decision, recorded under the operator's authenticated
  tailnet identity, bound to the same head the reviewer read. No agent merges, labels or approves on GitHub
  (§25.10). The host applies the label, and only as the effect of the operator's ledger decision. This is the same
  authority model as the digest tap.
- **What GitHub sees.** `gh` is logged in as the operator (shared identity). Agents therefore post no GitHub review
  or comment that could be read as the operator's. The review lives in the host store. GitHub sees it only through
  an optional commit status `tradeai/independent-review` on the head. That status should be set by a GitHub App
  identity, never the operator's token. (Decision D4: requiring that status in `.mergify.yml` is itself a held
  change and needs the operator's own merge.)
- **What it does not do.** An AI review never approves anything. A `MERGE` verdict does not add a label. Only the
  operator's Approve, in the CC or in the digest, does that.

## 7 Who runs the reviewer, and what it may spend (§29)

- **Runner:** `scripts/pr_independent_review.py`, run by a host timer `tradeai-pr-review` every 5 minutes. It
  reviews only PRs that are READY by the `classify_pr` rules. Held PRs are reviewed too, so the operator can read
  them. A draft or red PR gets no review.
  - It never merges, labels, pushes, comments on GitHub, or reads a secret beyond the credit key the existing
    Anthropic router already uses.
  - Advisory only; `MBI_BEHAVIOR = 0`.
- **Process registry row** (new, in `config/llm_process_registry.json`):
  - `id: pr_independent_review`, `anthropic_first: true`, listed in `anthropic_only_processes`
  - credit tier `long_form` (Opus 5.5, per-call cap $2.00)
  - `max_input_tokens: 60000`, `max_output_tokens: 6000`
  - `daily_soft_cap: 20`, `daily_cost_cap_usd: 6.00`
  - `tools_allowed: false`, `fallback_allowed: false`, `circuit_breaker: true`, `dedupe_policy: request_id_only`
    (request id = `pr:<N>:<head_sha>`)
  - Q&A uses a second row, `pr_review_question`: tier `mid` (Sonnet 5.5), per-call cap $0.10, 10 per day, $0.50 per day.
- **Bounds:**
  - one review per (PR, head);
  - at most 3 reviews per PR per UTC day;
  - a 10-minute settle after the last push before a review starts.
  - A diff over the input budget is reviewed by area, in at most 3 calls. If it still does not fit, the verdict is
    `CANNOT_REVIEW` with the finding "too large to review in one pass — split the PR".
- **Preflight before each run** (§29), quoted into the run receipt:
  - the credit journal: total and daily remaining;
  - the process cap;
  - the global daily provider cap (§12).
  - The run is sized under the lowest of them; if nothing fits, it does not start.
- **When the credit is unusable** (paused, exhausted, or expired after 2026-11-16) the review **queues**. There is no
  DeepSeek and no paid fallback. The sheet says "Review waiting for credit" and gives the time of the next try.
- **Expected spend:** not measured yet. Estimate: 5–15 reviews a day at $0.10–$0.50 each, about $1.50–$6.00 a
  day on the credit. The first live review records the real per-call cost. The daily process cap is the hard stop. (Decision D3 sets the number.)

## 8 Where reviews and decisions are stored

- **Reviews:** `data/coordination/pr_reviews/<pr>/<head_sha>.json` (`PrReview@v1`), plus an append-only
  `index.jsonl` (pr, head, verdict, document_sha, at), on the host under persistent-state, never in git.
  - Reviews are archived, never deleted (§0 rule 6).
  - New store → a new row in `config/data_source_authority.json`: domain `pr_reviews`, single writer
    `scripts/pr_independent_review.py`, status `proposed`. New stores are operator-only (§26.6). (Decision D5.)
- **Decisions:** the existing `data/governance/operator_decisions.jsonl` (`DecisionLedger`) with:
  - a new kind `MERGE` in `KINDS`;
  - item id `pr:<N>`;
  - `document_sha` = the review's `document_sha` (so it changes when the head changes);
  - `source_sha` = `head_sha`;
  - new decisions `HOLD` (terminal for that head) and `QUESTION` (not terminal), next to `APPROVE` and
    `REQUEST_CHANGES` ("Ask the author to change it");
  - read markers on each finding and on the summary. The operator must read every finding before Approve; hunks can
    be browsed but are not gated.
- **Label effect:** a host applier (`pr_review_apply`, inside the reconcile timer) reads new `DECIDED APPROVE`
  rows of kind `MERGE` and checks:
  - the PR's current head equals `source_sha`;
  - the PR is not held;
  - the four checks are still green.

  It then calls the same label function `settle_approve_all` uses and writes `PrMergeHeadBinding@v1` with
  `source: "cc_review"` and the ledger row hash. If a check fails, it writes an outcome row and the sheet shows the
  reason, for example "head moved".

## 9 The Command Center surface (mockup: `design/pages/approvals-pr-review/versions/v001`)

- **Approvals → new tab "Merges"**, added after "Waiting on you". MERGE items also appear in "Waiting on you".
  - Each row shows: PR number, title, plain summary, a verdict pill (Safe to merge · Merge with N follow-ups ·
    Held · your own merge · New push, re-reviewing · Review waiting for credit · Cannot review), class, checks,
    short head SHA and time waited.
  - A strip shows the last and next digest times and the review spend today.
- **Row → full-screen sheet** (phone ≤820 px, ← Back) / a modal over the list (desktop 1440). The sheet shows, in
  order:
  1. verdict and plain summary, with the risk level and why;
  2. who reviewed it: author, reviewer, "independent: yes", the bound head and base, time, duration and cost;
  3. findings by severity, each with `file · line`, a "✓ read" state and "Go to the change";
  4. checks and test evidence, read from GitHub and the PR, not the model;
  5. what changed, by area: files, then hunks, each with a one-line AI note and "Show the code" (the code scrolls
     sideways inside its own card, never the page);
  6. Ask: the operator's question, answered by the reviewer, with the cost; plus "Ask the author to change it";
  7. Your decision: findings read (n of n), "Approves PR #N at head X only", **Approve merge** (full width) /
     **Hold** / **Ask**, and one line on what Approve does.
- On desktop a section index sits on the left and the decision card is sticky on the right. On a phone the decision
  card is the last card. The only fixed chrome is the 56 px sheet header, about 7% of an 844 px viewport, inside
  §28.13 item 5's 15%.
- **Held PR:** red verdict "Held · needs your own merge", the held class and path named, and both reviewer receipts.
  The button is **Approve review**: it records the operator's reading in the ledger and adds no label. The merge
  stays the operator's own, on GitHub (§25.10).
- **Stale review:** a banner names the old and new heads. Approve is off. Any earlier approval is shown as cancelled.
  The new review's progress is shown.
- **Waiting for credit / cannot review:** the reason, the next try, and the options (raise the cap with `/caps`, or
  merge it yourself).
- **From the digest:** each digest line gets a URL button "Review #N" →
  `https://<cc-tailnet-host>/v3/approvals/pr:<N>?head=<sha9>`. If `head` no longer matches, the sheet opens in the
  stale state.
  - "Approve all" stays as it is. Proposed: it leaves out any PR whose review says HOLD, has a BLOCKER, or is
    missing, and lists those as "open the review". (Decision D1.)
- **Removals, hides, moves:** none. The tab is added; the existing reader (`/approvals/:id`) stays for POLICY and
  DESIGN items.

## 10 Making the operator decisions store writable

The ledger refuses every write with `STORE_APPROVAL_PENDING` until `operator_approvals.writes_approved()` finds the
`operator_decisions` row in `config/data_source_authority.json` with:

- `store.file == "governance/operator_decisions.jsonl"`;
- `writer == "scripts/lib/operator_approvals.py"`;
- an `approval` block whose `approved_by == "operator"` and which has `approved_on` and `reference` set.

Today that row is `status: proposed` with `approval: null`. Activation needs:

1. **The operator's own words**, in his own session (§28.4), approving `operator_decisions` as the single store of
   Approvals decisions. A relayed approval does not count. The ledger cannot record its own activation, so this is
   the one decision that has to happen outside it.
2. **One PR** that sets the row to `status: approved` and fills `approval` {approved_by: operator, approved_on,
   reference: the verbatim words + where they were given}. This is a §26.6 new-store sign-off. It goes through the
   digest like any other PR. (`config/data_source_authority.json` is not on the held list, but the PR must say it is
   a §17/§26.6 store approval.)
3. **A deploy** (the poller promotes it). Then one dry write against a temporary copy, and one real
   `READ_STARTED` row from the operator's first sheet open, as the proof (§8.1).

Until that happens the sheet can show reviews, but every decision button is disabled with "Decision store not yet
approved". The Telegram digest stays the only working merge approval.

## 11 Build plan (after approval; each a normal PR)

1. `PrReview@v1` contract, harness and hunk splitter, independence check, store row (proposed), process registry
   rows. Tests: synthetic fixtures only; the token manager and credit are stubbed (§24.6).
2. `pr_independent_review.py` with a dry run (prints the would-review set and the preflight; makes no call), the timer,
   and one live review of a docs-only PR as the proof.
3. Ledger: the MERGE kind, HOLD/QUESTION, finding read markers, the `pr_review_apply` applier. It touches the
   digest and label code, which is on the held list (`merge_deploy_control`). The new applier module is added to
   that class in the same PR. The operator merges it himself.
4. CC: the Merges tab and the review sheet, built to the approved `approvals-pr-review/v001`, with fixture e2e at
   1440/412/390.
5. Digest: the "Review #N" button and the HOLD/BLOCKER exclusion (held-class file → the operator's own merge).

## 12 Open decisions for the operator

- **D1 "Approve all" and the review.** Should "Approve all" leave out PRs whose review says HOLD, has a BLOCKER, or
  is missing? Proposed: yes.
- **D2 Reviewer model.** Opus 5.5 for every review, plus a free OAuth second read for shared-infra and held PRs?
  Or Fable 5.1 for held PRs (per-call cap $4)? Proposed: Opus plus the OAuth second read.
- **D3 Review budget.** $6/day and 20 reviews/day on the credit, Q&A $0.50/day. After the credit expires on
  2026-11-16, should reviews queue or move to a paid lane? Proposed: they queue until the operator decides.
- **D4 Visible on GitHub.** Should a GitHub App post a `tradeai/independent-review` commit status, and should
  Mergify require it? Requiring it edits `.mergify.yml`, which is held, so it would be the operator's own merge.
  Proposed: post the status now, require it later.
- **D5 Activate the stores.** `operator_decisions`: the operator's own words (§10). `pr_reviews`: the new-store
  sign-off (§26.6).
- **D6 Held PRs from the phone.** Held PRs stay "Approve review" plus a GitHub merge. A passkey-gated held merge
  from the CC would need an AGENTS.md amendment, because §25.10 says no host script merges. Proposed: no change.
- **D7 Design.** Approve or reject `approvals-pr-review/v001` in Approvals → Designs (or by the operator's own words
  while the ledger is not yet active).
