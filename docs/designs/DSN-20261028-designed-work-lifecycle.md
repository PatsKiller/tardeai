---
id: DSN-20261028-designed-work-lifecycle
title: Designed work never gets lost — task-id rule, stale-work monitor, design→task closure check
status: PROPOSED
approval: awaiting operator (the AGENTS.md 26.1.0 amendment is a held-class operator merge, §25.10)
source: docs/governance/LESSONS_LEARNED.md L28-29 · docs/governance/OPEN_ITEMS.md OI-131
phases:
  - id: DSN-20261028-designed-work-lifecycle-P1
    title: AGENTS.md 26.1.0 — "designed" means a task id on the board
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261028-designed-work-lifecycle-P1-T1
        title: Draft the 26.1.0 amendment (header/banner/§28.3b/version row) + LESSONS L28-29 + OPEN_ITEMS OI-131
        status: IN_PROGRESS
        areas: [AGENTS.md, docs/governance/LESSONS_LEARNED.md, docs/governance/OPEN_ITEMS.md]
      - id: DSN-20261028-designed-work-lifecycle-P1-T2
        title: "OPERATOR: ratify and merge 26.1.0 (held-class)"
        status: PROPOSED
        owner: OPERATOR
        areas: [operator/agents-policy/26-1-0]
  - id: DSN-20261028-designed-work-lifecycle-P2
    title: Enforcement — stale-work monitor and design→task closure check
    status: PROPOSED
    tasks:
      - id: DSN-20261028-designed-work-lifecycle-P2-T1
        title: "Stale-work monitor: flag PROPOSED designs with no owner, IN_PROGRESS phases with unclaimed tasks, and lanes a design names 'to admit' still NEVER_SCHEDULED/PAUSED"
        status: PROPOSED
        areas: [scripts/lib/agent_claim_board.py, scripts/lib/agent_task_board.py]
      - id: DSN-20261028-designed-work-lifecycle-P2-T2
        title: "Design→task closure check (CI, mirroring check_open_items.py): a DSN's buildable prose item must have a registered task; a design naming a lane must match a registry row"
        status: PROPOSED
        areas: [scripts/check_design_task_closure.py, config/ci_gates]
---

# Designed work never gets lost

## 0 · The failure this closes

**This DSN now carries 26.1.0, which folds TWO operator-directed changes under one token:** (a) the designed-work
task-id rule (§28.3b), and (b) the push-grant removal (§0 rule 4 + §28.15 item 8 — an operator-approved scope is the
push authorization; the guard hook must not demand a `git-push` grant for an approved-scope fast-forward push of the
agent's own branch; the per-branch budget and never-`main`/`release/*` ban still bind). See LESSONS L28-29 (task id) and
L28-30 (push grant); enforcement gaps OI-131 (stale-work monitor/closure check) and OI-133 (hook still demands
`git-push`).

On 2026-10-24 the W8 workstream spec'd its `conflict-resolver` lane as a paragraph in `docs/ops/W8_WRITERS_20261024.md`
("the separate W8 Conflict Engine PR will declare `conflict-resolver`…") with no task id. Four days later the lane had
no registry row, allowlist entry, health contract or PR, and every Watch card rendered "conflict ledger not yet
produced". A design expressed only as prose is invisible to `agent_claim.py status` / `next` and the Work board, so no
other agent could see or take it. The same audit found six `PROPOSED` designs and four spec'd-but-unadmitted lanes
sitting unwired.

## 1 · The rule (AGENTS.md 26.1.0, PROPOSED)

**"Designed" means each buildable unit is a task id on the board.** A design's prose may name future work, but any item
it promises ("a separate PR will declare X", "W8 will schedule Y", "a later amendment will …") is also a `-P<n>-T<m>`
task row in the design's own front matter, registered on the task board. Prose without a task id is not claimable and
must not be called "designed".

## 2 · The enforcement (P2, not yet built)

- **Stale-work monitor** — flags a `PROPOSED` design with no owner, an `IN_PROGRESS` phase whose tasks are unclaimed,
  or a lane a design names "to admit" that is still `NEVER_SCHEDULED`/`PAUSED` past its review date, surfacing on the
  Work board (P2, not P0/P1).
- **Design→task closure check (CI)** — mirrors `scripts/check_open_items.py`: a DSN's buildable prose item must have a
  registered task, and a design naming a lane must match a `config/lane_registry.json` row.

## 3 · Gates

The P1 amendment is a held-class operator merge (§25.10): §17's "any MAJOR change to this file" does not apply (MINOR),
but "policy: AGENTS.md" is a held path in `config/merge_hold_paths.json`, so only the operator's own merge lands it.
P2 is ordinary engineering PRs, each claimed and reviewed normally.

## 4 · What does not change

No authority rail, operator-only boundary, role, broker, secret, egress or financial path. §0, §2, §2A, §7A, §17,
§23.14 and the broker/order/stop/sizing rails are byte-identical.
