<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Install the standing rules into the repo

**Status:** recovered verbatim
**Source:** session transcript, operator message 038

---

Claude Code Execution Prompt — Install the standing rules into the repo
Purpose: stop the operator having to carry the same rules into every session by hand. This
package puts the standing rules where you read them automatically, and moves wave briefs into
the repository so a wave starts with a path rather than a paste.
This is a documentation and configuration package. No production code, no store writes, no
cron changes, no deploy required.
Ordering
Publishing is currently blocked at gh pr create, with two finished branches already stranded.
Do not create a third stranded branch. Prepare this package locally, then open it as the
third PR in the same batch once the operator grants the rule — after the compile guard and
after the sweep. If publishing is still denied when you reach that point, stop and report.
1. CLAUDE.md at the project root
The operator is supplying the content. Write it verbatim to /CLAUDE.md at the repository
root. Do not paraphrase, condense, or reorder it — every rule in it was written after a
specific failure and the wording carries the reason.
Two mechanical requirements:
Use safe_text_edit or a byte-level write. Match the repository's prevailing line-ending
style and assert it did not change.
Run the line-ending gate and the compile-adjacent checks before committing. A file introduced
by the rules package that trips the rules package would be its own finding.
If a CLAUDE.md already exists, do not overwrite blindly. Diff it, report what the existing
file contains, and stop for the operator's call on merging the two.
2. docs/briefs/
Create the directory and move the wave briefs into it so a session can start from a path.
docs/briefs/README.md — one paragraph on what a brief is, the naming convention, and the
rule that a brief states questions and thresholds, never current measured values.
One file per wave already run, named WAVE_<n>_<slug>.md, seeded from whatever brief text
exists in /tmp, in prior audit documents, or in the operator's supplied files. If a wave's
brief text cannot be recovered, create a stub naming the wave and saying the brief was not
preserved — an honest gap, not a reconstruction.
docs/briefs/TEMPLATE.md — the shape a future brief takes: objective, packages, acceptance
as an observable runtime event, standing constraints by reference to CLAUDE.md rather than
restated, and the operator-only list.
Do not reconstruct briefs from memory or from what the work appears to have been. A
fabricated brief would be exactly the manufactured-evidence pattern the rules forbid.
3. Skill reconciliation
A trade-ai-v12 skill already exists and describes this system. Read it and report any place
where it and CLAUDE.md disagree — particularly on authority rails, maturity claims, or which
components are live.
Do not edit the skill in this package. Report the conflicts and let the operator decide
which source wins. Two documents silently disagreeing about what the system does is the exact
condition that produced the two-surface problem.
4. Permissions
Add to .claude/settings.json under permissions.allow, if the file is repository-tracked:
Code
Both, not one. gh pr merge has been blocked by the classifier on at least four separate
occasions in this programme, and granting only create reproduces the stall one step later.
If .claude/settings.json is not tracked, or is machine-local, say so and leave it to the
operator rather than writing outside the repository.
This does not change the rule against routing around denials. It removes a denial that
should not have been firing on routine publishing; it does not license working around one that
does fire.
5. Verify the install
CLAUDE.md exists at the root, is tracked by git, and its byte content matches what was
supplied. Diff it and quote the result.
docs/briefs/ exists with a README, a template, and one file per recoverable wave.
Report which waves have real briefs and which are stubs.
Confirm line endings match the repository's prevailing style on every file touched.
Report the conflicts found in step 3, if any.
What this package must not do
No production code changes.
No store writes, no cron entries, no systemd units.
No edits to the existing skill.
No reconstruction of brief text that cannot be sourced.
No deploy — this changes nothing the server executes.
After it lands
The next wave brief can be a path plus a few lines of objective, because the standing rules,
the evidence vocabulary, the multi-agent protocol, the deploy protocol, the maturity proofs
and the operator-only list all live in CLAUDE.md and load automatically.
Report back with: the three PR numbers in merge order, the live pin once the first two are
deployed, and whether the rules file is in place on main.
