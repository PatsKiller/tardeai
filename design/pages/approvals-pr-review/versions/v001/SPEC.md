# Approvals PR review v001 — SPEC (PROPOSED)

Requested by the operator 2026-10-27, verbatim: "we really need to build something that actually has a review that I
can review in the same modal of the command center." Full system spec, covering the reviewer, independence, cost,
storage, ledger and store activation: `docs/ops/PR_REVIEW_MODAL_SPEC.md`. Mockup and renders (synthetic) are
private and bound in `status.json` by sha256.

## List — Approvals → "Merges" tab (added)

- The tab sits after "Waiting on you" and carries a count. MERGE items also appear in "Waiting on you".
- Digest strip: last digest sent and next digest (ET); counts of ready, held, re-reviewing and waiting for credit;
  one line explaining that the review is independent and that the CC and Telegram approvals bind to the same head.
- Rows: PR number, title, plain one-line summary, verdict pill, class · checks · short head · time waited,
  "Review →".
  - Verdict pills: Safe to merge (success) · Merge · N follow-ups (warning) · Held · your own merge (danger) ·
    New push · re-reviewing (neutral) · Review waiting for credit (warning) · Cannot review (danger).
  - Desktop: a table-like grid with column heads. Phone: cards (title + number; summary; meta; verdict + Review →).
- Desktop side panels: "How a merge approval works", "Review spend today" (credit, of the review cap), "Held classes".

## Review sheet (`/approvals/pr:<N>`)

Phone (≤820 px): a full-screen sheet with a 56 px sticky header (← Back, `#N title`, head · files · +/−); one
column; the decision card is last; no other fixed chrome. Desktop (1440): a modal over the list, with a section
index on the left, the review in the centre and a sticky decision card on the right.

1. **Verdict and summary:** verdict, risk level, class pill; 2–5 sentence plain summary; one "why this risk" line.
2. **Who reviewed it:** author (vendor · session), reviewer (model · run · fresh context), "Independent: yes —
   reviewer is not the author", bound head and base, reviewed time ET · duration · cost. Held class: the second
   reviewer's receipt.
3. **Findings:** a count and "read each one before approving". Each finding shows its severity (Blocker / Major /
   Minor / Note), title, `file · line`, detail, "✓ read" state and "Go to the change →".
4. **Checks and test evidence** (from GitHub and the PR, not the model): the four required checks with their state;
   tests, dry run, real-layout proof (shared-infra), size and "fully read by the reviewer".
5. **What changed, by area:** collapsible areas (files · +/−) → file → hunk cards. Each hunk card has an AI one-line
   note and "Show the code (n lines)". The diff scrolls sideways inside its card only.
6. **Ask about this PR:** the Q&A thread (the operator's question, the reviewer's answer with cost), a question box,
   "Ask the reviewer" and "Ask the author to change it" (records Request changes).
7. **Your decision:** findings read n of n; "Approves PR #N at head X only"; **Approve merge** (full width), **Hold**,
   **Ask**; one line on what Approve does: `operator-merge` for this head, Mergify merges in the next ET window,
   never 09:30–16:15 on weekdays, recorded with the operator's tailnet identity.

## States

- Ready.
- Merge with follow-ups.
- **Held:** red verdict, the held path and class named; the button reads "Approve review" (records only; no label;
  merge on GitHub).
- **Stale:** banner with the old and new heads; Approve off; the earlier approval is shown as cancelled; a new
  review is running.
- **Waiting for credit:** the reason and next try; no other paid model.
- **Cannot review:** the reason, e.g. too large → split.
- Store not approved: decision buttons are disabled with "Decision store not yet approved".
- Loading, and load error.

## Additions elsewhere (no removals)

- add: an Approvals tab "Merges" and the route `/approvals/pr:<N>`.
- add: a URL button "Review #N" on each Telegram digest line, opening the sheet (`?head=<sha9>`).

## Removed, hidden or moved

None. The existing reader (`/approvals/:id`) stays for POLICY, DESIGN and other kinds. All existing tabs and side
panels stay.

## Measured on the mockup (synthetic, 2026-10-27)

At 390 and 412: no sideways page scroll, no tap target under 44 px, the only fixed chrome is the 56 px header. At 1440:
the same data and actions in three columns.
