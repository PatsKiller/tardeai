<!-- AGENTS.md §28.12 (26.0.0). The title is a plain-English sentence: the operator's Telegram digest shows only the title.
     Fill every line of "In plain English" before "Technical detail". scripts/check_pr_plain_english.py checks it. -->
## In plain English
**What changes:** <2–3 sentences a non-engineer can follow>
**Why:** <the problem, and how we know: measurement, alert or review finding, with its date>
**Who / what it affects:** <which part of the system; whether the operator will notice anything, and where>
**When it takes effect:** <after merge the deploy poller promotes it within minutes; any timer, schedule or market-hours detail>
**Approval:** <Digest tap (eligible for "Approve all") — or — Held, operator's own merge (touches a class in config/merge_hold_paths.json)>
**Risk and fallback:** <what could go wrong, how we would notice, and how to undo it: revert PR, switch or flag, or "docs only">

## Technical detail
- Base SHA: `` · Head SHA: ``
- Claim id and worktree:
- Files and named stores changed:
- Contracts changed (name@version):
- Migrations:
- Tests run (command and result), including negative / refusal tests:
- Dry run (anything that writes durable state, sends to an operator surface, spends money or touches a schedule):
- Proof after release (what will be checked on CURRENT, and how):

## Evidence (Engineering Constitution v1.1, docs/governance/ENGINEERING_CONSTITUTION.md)
<!-- Activation is not validation. Exit 0 is not evidence. Unmeasured = UNVERIFIED, never a guess. -->
- Acceptance criteria (written before the work; numeric where possible):
- BEFORE (the failure observed in production: query / receipt / screenshot, with timestamp):
- AFTER (the same observation on the live release, with timestamp; fill after activation):
- Receipt + artifact + measurable output + verification for every new or changed run:
- Provenance of every new displayed number (value, source, timestamp, confidence, freshness):
- Silent-failure check (what can now fail without notifying the operator?):
- Observation window (6 h / 24 h / 7 days for critical) and its end time:
- Independent verifier (never the author):
- Verdict: FIXED · FIXED BUT UNPROVEN OVER TIME · PARTIALLY FIXED · UNVERIFIED · FAILED · REGRESSED

## If this PR changes AGENTS.md
- [ ] `Policy-Version`, `Last-Reviewed` and the version-history row are bumped (`scripts/check_agents_policy_state.py`)
- [ ] After merge: update the claude.ai Project copy of AGENTS.md (agents outside the repo read that copy)
