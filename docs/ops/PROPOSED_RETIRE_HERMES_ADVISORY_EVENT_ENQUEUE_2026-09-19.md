# APPROVED RETIRE — operator settle (AGENTS.md §17 / §9.3)

```
Status: APPROVED
Effective-Date: 2026-09-20T17:15:00-04:00
as_of: 2026-09-20T17:15:00-04:00
Measured at: AGENTS.md research-lanes table; no lane_registry row for this script
Canonical repo path: docs/ops/PROPOSED_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE_2026-09-19.md
Authority: propose-and-stop — installing, editing or removing a scheduler entry is operator-only
Subject: RETIRE scripts/hermes_advisory_event_enqueue.py as a scheduled/automatic producer claim
See also: ledger DARK-hermes_advisory_event_enqueue; AGENTS.md research lanes (KNOWN DARK — PROPOSED RETIRE)
Supersedes: prior DEFERRED stamp 2026-09-20T14:45 (Grok/email provenance — not a kit-valid Operator-Token)
Operator-Token: APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE
Operator-Token-Surface: cursor_chat|operator|2026-09-20T17:15:00-04:00
Operator-Token-as_of: 2026-09-20T17:15:00-04:00
Operator-Token-Evidence: "i approve or send telegram grant request" (verbatim Cursor chat; mapped to APPROVE_RETIRE per packet recommended settle path; no Telegram PMID invented)
Operator-decision: APPROVE_RETIRE (settle token recorded; follow-on RETIRED lane row / archive+tripwire still pending — no schedule invent this PR)
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
token: APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE
decided_on: 2026-09-20T17:15:00-04:00
surface: cursor_chat|operator (no Telegram PMID invented)
evidence: "i approve or send telegram grant request" (verbatim Cursor chat ~17:15 ET)
effect: settle token recorded; RETIRE expectation for scheduled/automatic producer;
  follow-on still pending — optional lane_registry state:RETIRED row and/or archive+tripwire;
  no live schedule invented this change
supersedes: 2026-09-20T14:45 DEFER stamp (Grok/email — not kit-valid Operator-Token)
```

Prior propose text above is retained for history. Follow-on RETIRED lane / archive is a separate PR.
