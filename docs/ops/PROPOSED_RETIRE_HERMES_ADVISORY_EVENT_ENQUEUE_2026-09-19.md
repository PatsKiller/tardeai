# DEFERRED — operator continue-park (AGENTS.md §17 / §9.3)

```
Status: DEFERRED
Effective-Date: 2026-09-20
as_of: 2026-09-20T14:45:00-04:00
Measured at: AGENTS.md research-lanes table; no lane_registry row for this script
Canonical repo path: docs/ops/PROPOSED_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE_2026-09-19.md
Authority: propose-and-stop — installing, editing or removing a scheduler entry is operator-only
Subject: RETIRE scripts/hermes_advisory_event_enqueue.py as a scheduled/automatic producer claim
See also: ledger DARK-hermes_advisory_event_enqueue; AGENTS.md research lanes (KNOWN DARK — PROPOSED RETIRE)
Operator-decision: DEFER (continue-park; no RETIRE archive / no schedule invent)
decided_on: 2026-09-20T14:45:00-04:00
decision_reference: Grok session plan approve — triple-DEFER maturity gap closeout
```

## Finding

`hermes_advisory_event_enqueue` is listed in AGENTS.md research lanes as **KNOWN DARK — PROPOSED RETIRE**
(no caller — no schedule, no timer, no importer). The script is a **manual CLI** that INSERTs into
`hermes_advisory_events`.

The table is **not** without writers: `hermes_autonomous_librarian_backlog_loop.py`
already INSERTs advisory events automatically. The dark item is the *standalone
enqueue script having no caller*, not the queue itself.

`config/lane_registry.json` has **no** row for `hermes_advisory_event_enqueue`
(only a related timer name `hermes-advisory-cache-worker.timer`). Retirement therefore
means documenting RETIRE in AGENTS / ledger and optionally adding a RETIRED lane row
**only after** operator grant — not inventing a live schedule.

## Exact operator decision ask

Reply with one of:

1. **APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE** — treat the standalone enqueue CLI
   as RETIRED as a scheduled/automatic producer; keep file as manual ops tool **or**
   archive with tripwire (§0 rule 6); document automatic producer as
   `hermes_autonomous_librarian_backlog_loop`; if a lane_registry row is added, it must
   be `state: RETIRED` with `reason_confidence` + `reason_evidence` pointing here.
2. **WIRE** — operator grants a schedule/timer that calls the enqueue CLI (separate §9.3
   grant; declare lane_registry `output_signal` first).
3. **DEFER** — leave KNOWN DARK / PROPOSED RETIRE as parked.

**Do not** enable a schedule that only calls the manual enqueue CLI without choosing (2).

## Proposal (do not apply without operator grant)

1. **RETIRE the expectation** that `hermes_advisory_event_enqueue.py` is a scheduled
   producer. Keep the file as a manual ops tool (or archive with tripwire per §0 rule 6).
2. Document the automatic producer as `hermes_autonomous_librarian_backlog_loop`.
3. If a lane_registry row exists or is added for the manual script, mark
   `state: RETIRED` with `reason_confidence` + `reason_evidence` pointing at this note.
4. Do **not** enable a schedule that only calls the manual enqueue CLI.

## Why not auto-close

Scheduler / lane retirement is operator-only. This file is the proposal; no scheduler
or registry mutation was made in this change.

## Proof already measured

- Script has no production importer (filename grep + AGENTS research table).
- Librarian backlog loop writes `hermes_advisory_events` (`[CODE]`).
- Last automatic advisory activity historically aged while the manual CLI sat unused.

---

## Operator decision (recorded)

```
token: DEFER
decided_on: 2026-09-20T14:45:00-04:00
reference: Grok Build session — plan approve (triple-DEFER maturity gap closeout)
effect: continue-park for goal accounting; no production mutation; no build started
```

Prior propose text above is retained for history. A later `APPROVE_*` may reopen this park.
