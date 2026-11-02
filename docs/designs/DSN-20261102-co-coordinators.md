# DSN-20261102-co-coordinators — co-coordinators by territory, with checks

**Status:** PROPOSED · **Plan:** `persistent-state/handoffs/PLAN_CO_COORDINATORS_20261102.md` (operator 2026-11-02,
verbatim: "option to with checks. And also let me be able to see in the command center what's going on. Give this to
one of the DeepSeek agents to build right now.") · **Authority:** READ_ONLY_ADVISORY, `MBI_BEHAVIOR = 0`.

## Why

One coordinator per session means coordination state lives in one vendor's chat, and several coordinators at once
would give conflicting orders, double-merge and ask the operator the same question twice. This design makes the
coordination state vendor-neutral and on disk, adds a second-coordinator check for risky actions, and shows it on the
Command Center.

## Tasks

| id | what | PR |
|---|---|---|
| DSN-20261102-co-coordinators-P1-T1 | `scripts/coordinator.py`: registry, notebook, ledger, inbox, checks, handoff, board, whoami; locked atomic writes | A |
| DSN-20261102-co-coordinators-P1-T2 | read-only `GET /api/v2/coordination/coordinators` and `/board` (`scripts/lib/coordination_view.py`) | A |
| DSN-20261102-co-coordinators-P1-T3 | Command Center Ops → Coordination: the Coordinators tab (mobile first; nothing removed) | A |
| DSN-20261102-co-coordinators-P1-T4 | tests + `config/ci_gates/coordinator_20261102.json` | A |
| DSN-20261102-co-coordinators-P2-T1 | AGENTS.md governance amendment (coordinators by territory, one lead, the check rule, handover) | B |

## Store

- `persistent-state/data/coordination/coordinators.json` — `CoordinatorRegistry@v1`: coordinators (id, vendor,
  session, where, territories, role, appointed_by/quote/at, last_heartbeat, status), exactly one lead, `territories`,
  `assignments` (agent id or `pr:<n>` → territory).
- `persistent-state/data/coordination/coordinator/` — `ledger.jsonl` (`CoordinatorEvent@v1`, append-only, write-ahead),
  `BOARD.md` (generated), `LESSONS.md` (operator-seeded after merge), `inbox/<id>/`, `handoffs/`.

The CLI is the only writer; every write takes one flock and is atomic (temp + `os.replace` + fsync). Reads never
create the store; a torn ledger tail is skipped, never repaired. Inbox reads move to `read/`; nothing is deleted.

## Checks

A risky action (held/shared-infra merge, promote, schedule change, policy change, breaker release, anything on the
operator-only list) writes `check_request`; a DIFFERENT active coordinator must write `check_ok`/`check_block` for the
same subject+sha before the action runs. With one active coordinator the fall-back is an independent reviewer's MERGE
receipt (today's practice). The operator's word is still required wherever §17 says so.

## Non-goals

No seeding of `LESSONS.md` or the notebook, no appointments, no scheduling, no writes to a broker, no changes to the
claim board or the merge rails.
