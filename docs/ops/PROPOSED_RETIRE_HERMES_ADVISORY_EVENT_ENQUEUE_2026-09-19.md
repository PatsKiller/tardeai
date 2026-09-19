# PROPOSED — operator decision required (AGENTS.md §17 / §9.3)

```
Status: PROPOSED
as_of: 2026-09-19T14:05:00-04:00
Authority: propose-and-stop — installing, editing or removing a scheduler entry is operator-only
Subject: RETIRE scripts/hermes_advisory_event_enqueue.py as a scheduled/automatic producer claim
```

## Finding

`hermes_advisory_event_enqueue` is listed in AGENTS.md research lanes as **KNOWN DARK**
(no cron, no timer, no importer). The script is a **manual CLI** that INSERTs into
`hermes_advisory_events`.

The table is **not** without writers: `hermes_autonomous_librarian_backlog_loop.py`
already INSERTs advisory events automatically. The dark item is the *standalone
enqueue script having no caller*, not the queue itself.

## Proposal (do not apply without operator grant)

1. **RETIRE the expectation** that `hermes_advisory_event_enqueue.py` is a scheduled
   producer. Keep the file as a manual ops tool (or archive with tripwire per §0 rule 6).
2. Document the automatic producer as `hermes_autonomous_librarian_backlog_loop`.
3. If a lane_registry row exists or is added for the manual script, mark
   `state: RETIRED` with `reason_confidence` + `reason_evidence` pointing at this note.
4. Do **not** re-enable a cron that only calls the manual enqueue CLI.

## Why not auto-close

Scheduler / lane retirement is operator-only. This file is the proposal; no crontab
or registry mutation was made in this change.

## Proof already measured

- Script has no production importer (filename grep + AGENTS research table).
- Librarian backlog loop writes `hermes_advisory_events` (CODE).
- Last automatic advisory activity historically aged while the manual CLI sat unused.
