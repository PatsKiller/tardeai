# Remediation register

IN PROGRESS. Recorded 2026-11-02T19:41:04Z; immutable membership 2026-11-02T18:45:27.608050Z.
These repository tickets are mirrored in OPEN_ITEMS OI-153 through OI-177.
GitHub returned HTTP410: Issues has been disabled in this repository. No setting changed
and no alternate issue-creation route was attempted. No external issue is claimed.

Every frozen UNKNOWN row has an exact per-lane key bound to one of these actual ticket files.
Original immutable inventory still says proposed keys; the later manifest supplies their binding.

| Ticket / register | Priority | Owner | Review by | Frozen members |
|---|---|---|---|---:|
| [CC-DIAG-FAILURE](tickets/CC-DIAG-FAILURE.md) / OI-153 | P0 | platform | 2026-11-03 | 9 |
| [CC-FAIL-JOB](tickets/CC-FAIL-JOB.md) / OI-154 | P0 | platform | 2026-11-03 | 9 |
| [CC-FAIL-MISSED](tickets/CC-FAIL-MISSED.md) / OI-155 | P0 | platform | 2026-11-03 | 6 |
| [CC-GOV-PAUSED](tickets/CC-GOV-PAUSED.md) / OI-156 | P1 | coordinator | 2026-11-05 | 22 |
| [CC-GOV-PROTECTED-INSTRUMENTATION](tickets/CC-GOV-PROTECTED-INSTRUMENTATION.md) / OI-157 | P1 | execution | 2026-11-05 | 50 |
| [CC-OBS-ACTIVE-DISABLED-TIMER](tickets/CC-OBS-ACTIVE-DISABLED-TIMER.md) / OI-158 | P1 | platform | 2026-11-05 | 8 |
| [CC-OBS-CONTINUOUS-SERVICE](tickets/CC-OBS-CONTINUOUS-SERVICE.md) / OI-159 | P1 | platform | 2026-11-05 | 19 |
| [CC-OBS-DB-RECEIPT](tickets/CC-OBS-DB-RECEIPT.md) / OI-160 | P1 | platform | 2026-11-05 | 5 |
| [CC-OBS-EXPECTED-NONLIVE](tickets/CC-OBS-EXPECTED-NONLIVE.md) / OI-161 | P1 | platform | 2026-11-05 | 40 |
| [CC-OBS-INCOMPLETE-RUN-CONTRACT](tickets/CC-OBS-INCOMPLETE-RUN-CONTRACT.md) / OI-162 | P1 | platform | 2026-11-05 | 42 |
| [CC-OBS-MODE-PROVENANCE](tickets/CC-OBS-MODE-PROVENANCE.md) / OI-163 | P1 | platform | 2026-11-05 | 16 |
| [CC-OBS-MTIME-NOT-SUCCESS](tickets/CC-OBS-MTIME-NOT-SUCCESS.md) / OI-164 | P1 | platform | 2026-11-05 | 198 |
| [CC-OBS-NEVER-SCHEDULED-COUNT](tickets/CC-OBS-NEVER-SCHEDULED-COUNT.md) / OI-165 | P0 | platform | 2026-11-03 | 32 |
| [CC-OBS-NO-SIGNAL](tickets/CC-OBS-NO-SIGNAL.md) / OI-166 | P1 | platform | 2026-11-05 | 11 |
| [CC-OBS-ON-DEMAND](tickets/CC-OBS-ON-DEMAND.md) / OI-167 | P1 | platform | 2026-11-05 | 8 |
| [CC-OBS-RECEIPT](tickets/CC-OBS-RECEIPT.md) / OI-168 | P1 | platform | 2026-11-05 | 6 |
| [CC-OBS-RECEIPT-PATH](tickets/CC-OBS-RECEIPT-PATH.md) / OI-169 | P1 | platform | 2026-11-05 | 23 |
| [CC-OBS-SYSTEMD-SCHEDULE](tickets/CC-OBS-SYSTEMD-SCHEDULE.md) / OI-170 | P1 | platform | 2026-11-05 | 75 |
| [CC-OBS-UNREGISTERED-TIMER](tickets/CC-OBS-UNREGISTERED-TIMER.md) / OI-171 | P1 | platform | 2026-11-05 | 5 |
| [CC-ALERT-REPEAT](tickets/CC-ALERT-REPEAT.md) / OI-172 | P0 | comms | 2026-11-03 | 0 |
| [CC-SELFHEAL-READY](tickets/CC-SELFHEAL-READY.md) / OI-173 | P0 | agents | 2026-11-03 | 0 |
| [CC-DASH-FRESHNESS](tickets/CC-DASH-FRESHNESS.md) / OI-174 | P0 | platform | 2026-11-03 | 0 |
| [CC-UX-STATE](tickets/CC-UX-STATE.md) / OI-175 | P0 | platform | 2026-11-03 | 0 |
| [CC-ALERT-CHANNELS](tickets/CC-ALERT-CHANNELS.md) / OI-176 | P1 | comms | 2026-11-05 | 0 |
| [CC-PUSH-ADOPTION](tickets/CC-PUSH-ADOPTION.md) / OI-177 | P0 | coordinator | 2026-11-03 | 0 |

Memberships overlap and must not be summed as jobs. The per-job owner and protected-scope
requirements remain explicit. Existing #2444 and OI-135/148/149/150/152 are not duplicated or closed.

Order: P0 truthful state, failed-run diagnostics, reminder delivery and failed services;
P1 receipt/scheduler/service coverage; P2 reliability/structured policy capability;
P3 broader IA/navigation. Local source completion never closes a runtime recovery ticket.
