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
