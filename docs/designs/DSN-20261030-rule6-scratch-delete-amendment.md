---
id: DSN-20261030-rule6-scratch-delete-amendment
title: 'Rule 6 amendment — agents delete their own scratch, plus a scheduled scratch purge'
status: PROPOSED
approval: OPERATOR (MAJOR — §0 rule 6 + §17; token `APPROVE_AGENTS_POLICY_27_0_0 <pr> <head_sha>`; held-class operator merge §25.10)
source: operator 2026-10-30 — "We may need to readdress the rules so you can delete, and something can delete on schedule. All of this scratch pad stuff should've been deleted when the agent didn't need it anymore."
summary: >
  §0 rule 6 gains a THIRD, narrow exception: an agent may delete only scratch it created, in a declared
  scratch namespace, after proving the branch/PR is merged or abandoned and no running process or claim
  references the path. A daily scheduled purge (host timer, not n8n) reclaims ~/.cache/agent-tmp, ~/.cache/rtc
  and stale worktrees via the existing disk-hygiene standing path, extended with one new rule T. NOT RATIFIED.
---

# Rule 6 amendment — agents delete their own scratch, plus a scheduled purge

> **Revised as 27.0.1 (2026-10-30, branch `wt/scratch-purge-fix-20261030`).** Review of #2303 found: the
> agent worktree hand-delete overlapped rule W and contradicted §24.12 unamended; rule T did not read its config
> (`idle_days`, `entry_regex` hard-coded or ignored) and has no PR-merged check; every `--standing` plan failed on
> `claim_unreadable` because `coordination/claims/policy_broadcast_state.json` is not a claim; the schedule text
> (daily host timer, "never n8n") contradicted the lane registry and the pending allowlist change. 27.0.1 keeps
> agent self-delete for `~/.cache/agent-tmp/<task-id>` only, makes rule T config-driven and validated, and states
> what the code checks. The first standing plan (2026-10-30, read-only) found rule T candidates worth 48 MB of the
> 43 GB under `agent-tmp`: the rest is younger than two days or holds git worktrees. Sections below are the 27.0.0
> text, kept for the record.

**This is a PROPOSAL, not a ratification.** It changes §0 rule 6 and §17 (both
`Approval-Class: OPERATOR_REQUIRED`, §20, §25.10) and comes back to the operator for explicit approval.

## Forensics (quoted)

- `~/.cache/agent-tmp` = **43 GB across 119 per-task agent scratch dirs** (2026-10-25 → 10-30).
- `~/.cache/rtc` = **23 GB / 646 dirs**.
- `~/tradeai-wt-*` + `~/wt-*` + `~/worktrees` ≈ **91 GB**.

All agent-created scratch that nothing ever reclaimed, because §0 rule 6 forbids agents deleting anything —
it piled up until ENOSPC truncated `holdings.json`.

## Operator intent (verbatim)

> "We may need to readdress the rules so you can delete, and something can delete on schedule. All of this
> scratch pad stuff should've been deleted when the agent didn't need it anymore."

## Classification: MAJOR

Adding a delete authority to agents weakens §0, so this takes the highest class. MAJOR requires explicit
operator approval (§20).

---

# 1 · The amendment draft

## 1.1 §0 rule 6 — replacement (verbatim)

```
6. **Never delete.** Archive with a tripwire that fires if anything reads the archived path.
   Three exceptions, and nothing else: (a) the n8n lane `disk-hygiene` may remove the reclaimable
   items its reviewed rules select (scripts/disk_hygiene.py, config/disk_hygiene_rules.json);
   (b) the host /tmp hygiene lanes may remove the /tmp items their reviewed tmp.* rules select
   (scripts/tmp_hygiene_auto.py); and (c) an agent may delete only scratch it created, in a
   declared scratch namespace, after proving its branch/PR merged or abandoned and that no running
   process or claim references it — never a live store, DB, holdings, identity, lineage, the
   InstrumentRecord store, or another agent's active work (AGENTS.md §24.12, §24.13).
```

## 1.2 §17 addition (operator-only list)

```
- **Installing the scheduled agent-scratch purge lane, and approving its scratch namespace list and idle
  threshold** (§24.13 — the lane deletes, so namespace list, age threshold and schedule install are operator-only;
  the agent-facing self-delete is bounded to the §24.13 declared namespaces, nothing wider).
```

## 1.3 §24.13 (new section)

```
## 24.13 Agent scratch: self-deletion and the scheduled purge

- **An agent may delete only its own scratch, and only in a declared namespace.** Scratch = a path the agent's own
  task/run created, under a declared root: `~/.cache/agent-tmp/<task-id>` and a worktree off a branch it owns
  (`scripts/new-worktree.sh`). The namespace list is `config/disk_hygiene_rules.json` (`standing_apply.agent_scratch`).
- **Prove before you delete.** Before removing a scratch dir an agent records, in the worklog: (a) the branch/PR is
  merged (`origin/main` ancestor) or explicitly abandoned with a recorded handoff; (b) no running process has its cwd
  or an open fd inside the path; (c) no live claim or active worklog references it (`scripts/agent_claim.py status`).
  A check the agent cannot prove makes the dir ineligible — it is left in place and reported.
- **Never agent-deletable, under any grant:** a live store, the DB, holdings, identity, lineage, the InstrumentRecord
  store, a served release, `persistent-state`, credentials, or another agent's active/claimed work. Those stay
  archive-with-tripwire and operator-only (§0 rule 6, §17).
- **The scheduled purge lane** (proposed, not installed) is the `disk-hygiene` lane's standing path: a daily host
  timer (05:00 ET, after the close, off-peak) runs `scripts/disk_hygiene.py --standing --apply` against the reviewed
  `standing_apply` rules (A/S/T/W). It re-validates every item at apply time, reads the claim board, worklogs, open
  PRs and process cwds, refuses on any opaque process, and stops at the caps. It never runs under the n8n executor;
  installing it is operator-only (§17).
```

---

# 2 · The mechanism — a scheduled purge lane (proposal, not installed)

The existing `scripts/disk_hygiene.py` standing path already collects fresh read-only evidence
(`collect_standing_evidence`) — crontab, systemd units, `/proc` cwds/fds, the coordination tree (claims + worklogs),
open GitHub PRs, release pointers — and refuses to apply while any evidence is incomplete, stale, or opaque. We extend
it with one new rule **T**.

## 2.1 Code (separate reviewed PR, after approval)

`scripts/lib/disk_hygiene_retention.py` — one line:

```python
RULE_KINDS = {"A": "archived_dump", "S": "rtc_scratch", "T": "agent_scratch", "W": "git_worktree"}
```

`scripts/disk_hygiene.py` — add a `T`/`agent_scratch` arm alongside the existing `S`/`rtc_scratch` arm in
`standing_results`, and add `"agent_scratch"` to the `rmtree` kind tuple in `remove_item`. No new deletion primitive.

## 2.2 Config — proposed `config/disk_hygiene_rules.json` entries

`standing_apply.rules` `["A","S","W"]` → `["A","S","T","W"]`, plus:

```json
"agent_scratch": {
  "_why": "Rule T (2026-10-30): ~/.cache/agent-tmp grew to 43 GB across 119 per-task agent scratch dirs (2026-10-25..10-30) because §0 rule 6 forbade agents deleting even their own scratch. <root>/<task-id>/ is a candidate only when idle > idle_days (bounded newest-mtime scan), no /proc/*/cwd or /proc/*/fd inside, no live claim or worklog reference (coordination evidence), and the owning branch/PR is merged or abandoned. Removed by rmtree, symlinks never followed.",
  "path": "~/.cache/agent-tmp",
  "idle_days": 2,
  "entry_regex": "^[A-Za-z0-9][A-Za-z0-9_.-]*$",
  "require_claim_absent": true,
  "require_process_absent": true,
  "never": "symlink, or an entry equal to / inside / containing a never-touch or protected path"
}
```

## 2.3 Schedule — proposed host systemd timer (NOT installed)

`linux_launchers/systemd/tradeai-agent-scratch-purge.timer` — `OnCalendar=*-*-* 05:00:00 America/New_York`, a
oneshot `.service` that runs `scripts/disk_hygiene.py --standing --apply`. Kill switch: `standing_apply.enabled=false`
or stop the timer. Installation is operator-only (§17).

---

# 3 · Version-bump bookkeeping

- `Policy-Version: 27.0.0`, `Status: PROPOSED`, `Effective-Date: PENDING`, `Last-Reviewed: 2026-10-30T11:30:00-04:00`,
  `Supersedes: 26.2.2`.
- History row: `| 27.0.0 | 2026-10-30 | PROPOSED | MAJOR | … | PENDING — APPROVE_AGENTS_POLICY_27_0_0 <pr> <head_sha>; held-class operator merge (§25.10). |`
- §0 rule 6 propagated to the four adapters (CLAUDE.md, .cursor/rules/00-tradeai-work-policy.mdc,
  .github/copilot-instructions.md, .goosehints).

---

# 4 · Operator-approval checklist

1. The §0 rule 6 change (adding exception c) — MAJOR.
2. The §17 entry (namespace list + threshold are operator-only).
3. The §24.13 section.
4. The namespace list — `~/.cache/agent-tmp/<task-id>` (T), `~/.cache/rtc` (S), own worktrees (W).
5. The age threshold — `idle_days: 2` (48h) for agent-tmp and rtc; worktree `untouched_hours: 48`.
6. The 05:00 ET schedule install (separate from the policy merge).

**Approval token:** `APPROVE_AGENTS_POLICY_27_0_0 <pr> <head_sha>` in the operator's own session.
