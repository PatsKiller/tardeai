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

## Appendix — proposed lane row for the snapshot timer (NOT applied)

`config/lane_registry.json` was held by another live claim when this PR was built, so the row is proposed here and
must be added by whoever holds the registry (or after it releases): insert it in the **hand-written** section, before
the first row carrying `generated_by`, then run
`python3 scripts/reconcile_lane_registry.py --snapshot-in docs/implementation/n8n-maturity/data/scheduler_snapshot_20261009.json --write`
so the committed registry stays the generator's fixed point.

```json
{
  "lane_id": "coordinator-snapshot",
  "owner": "ops",
  "scheduler": {"kind": "none"},
  "expected_cadence_hours": 0.0167,
  "state": "NEVER_SCHEDULED",
  "state_since": "2026-11-02",
  "state_reason": "PROPOSED by the co-coordinator build (plan PLAN_CO_COORDINATORS_20261102, operator 2026-11-02: coordinators are equal partners, and a sandboxed non-Claude coordinator cannot reach the tmux socket). config/systemd/tradeai-coordinator-snapshot.{service,timer} exist and are NOT installed; the operator installs them after merge. Under the n8n cutover directive the same host capture becomes an n8n-scheduled host lane when it moves.",
  "output_signal": {"kind": "file_mtime", "path": "data/coordination/coordinator/agents"},
  "reason_confidence": "ESTABLISHED",
  "reason_evidence": "No crontab line and no installed timer on the host. scripts/coordinator.py snapshot is the only writer of agents/<session>.txt; tests/test_coordinator_20261102.py covers it."
}
```
