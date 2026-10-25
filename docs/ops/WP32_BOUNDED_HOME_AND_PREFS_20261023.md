# WP-32 bounded CIO home reads and session verification

Status: DRAFT — independent home fix tested locally; shared-preference change held by WP-23 claim; deployment and full-session acceptance pending
as_of: 2026-10-24
Measured at: main `8ed8a246486317950df01f2a1846825627f369eb`
Design-Task: DSN-20261023-handoff-v3-P7-T32

PR #2012 is merged and already supplies bounded log tails, a spine index and request coalescing. CIO home still instantiates a full `CIOPlanStore` from its large projection on each composition. That loads historical payloads even though the page needs twelve public plans and a minimal coverage index. The generic shared-symbol preference GET also still hydrates its full value; the earlier bridge fix limits which pages fetch it, rather than the payload size.

## Independent source change

`get_cio_home` now uses `HomePlanView`, a bounded read-only input. It streams one projection record at a time, retains the exact newest twelve public rows and at most the existing 5,000-row coverage window, and applies the bounded event tail using the existing pure event reducer. The full store remains the detail/writer implementation. Home does not invoke its constructor or rebuild/write a projection.

Public fields, order, tie behavior, event updates/supersession, materiality and research references match the existing store. Legacy projections with an absent/out-of-range offset retain their prior read semantics. The view publishes `plan_read` metadata with availability, source byte/count information, limits, catch-up bytes and coverage truncation. Corruption, source replacement/shrink or an exceeded limit produces an explicit unavailable input with no partial-success rows and no full-store fallback.

Limits are 100,000 scanned plan identities, 1,048,576 characters per decoded value, 4 MiB of event catch-up and 24 MiB of estimated retained JSON. These bound the home input; exceeding one requires producer/operator follow-up rather than silently discarding unknown data. The existing home composition cache remains in place.

## Local proof

The new canonical CI gate is `config/ci_gates/cio_home_bounded_reads_20261023.json`. The regression suite exercises:

- Public and coverage equality against `CIOPlanStore`, including status changes, updates, supersession, missing-before-create events and stable ties.
- Unicode/escaped values and chunk boundaries, legacy offsets, malformed/partial tails, truncated/duplicate/oversized sources, coverage caps and source-replacement drift.
- The actual home route with every other domain and write neutralized, proving its public/coverage reads use the bounded view.
- Separate forked children reading a synthetic 66,062,698-byte projection; no production files, live server, DB, provider or credential are used.

One final-source fixture run recorded:

| Reader | Added peak RSS | Python allocation peak | Time |
|---|---:|---:|---:|
| Full store | 132,844 KiB | 133,658,022 bytes | 0.164 s |
| Bounded home view | 7,008 KiB | 3,267,903 bytes | 0.535 s |

Both returned the same twelve plan IDs. Streaming trades additional parsing time for lower allocation. This measures the plan-input component; **full-route production memory is NOT_MEASURED**. Other home domains remain part of the composition and require their own proof.

Receipts are under `/home/johnclaw/.cache/rtc/codex-wp32-20261023/`: `final-bounded-tests.xml`/`.log`, `final-compatible-tests.xml`/`.log`, `memory-proof.json` and `session-evidence.json`. The dedicated suite passes 22 tests, including the two source-replacement cases. The final compatibility group passes 117 tests, including existing home/cache/coverage/notification and CI-registry checks. Helper/test lint, whitespace and generated INDEX checks pass.

## Completed-session observations

The read-only audit covers **2026-10-23 04:00–16:15 America/New_York** (08:00–20:15 UTC):

| Observation | Evidence |
|---|---|
| Watchdog SIGKILL records | Six: 08:34:58, 09:14:58, 09:30:57, 09:56:57, 10:12:57 and 10:24:57 ET |
| Regular-session subset | Four in 09:30–16:15 ET; two occurred before 09:30 |
| Largest watchdog `memory.current` sample | 1,730,846,720 bytes against `memory.high=1,610,612,736` |
| Journal memory peaks | Rounded unit-lifetime peaks up to `1.6G`, recorded on unit exit |
| Post-fix full-session proof | Pending: all six recorded kills preceded #2012's 17:58:55 UTC merge; the fix landed during this session |
| Slowest routes | `NOT_MEASURED`: ordinary retained access rows have no durations, and no slow-request markers were retained in the inspected journal/candidate log |
| Installed user timers | 78 enumerated; timer/lifecycle evidence is retained; a timestamp overlap alone would not establish resource causality |
| Cron correlation | Not collected: `bin/guard show` reported no active grants; no crontab read was attempted |

The watchdog log and 2,298 portfolio-server journal entries supplied the failure observations. A separate read-only timer/lifecycle query examined 7,826 entries; no match to currently enumerated timer service names appeared within ten seconds of the recorded kills. This is a limited correlation, not proof that no scheduled job contributed. Current unit-property lookup returned a user-bus permission denial; it was not retried or bypassed. No live HTTP requests or credential-based database reads were made.

A complete market session after the fixes are deployed is still required for the zero-watchdog-kill acceptance. The absence of later action-log lines cannot prove every expected watchdog fire or business process completed.

## Shared-preference blocker and remaining acceptance

The attempted claim extension for `scripts/api_v2.py` was refused because WP-23 holds it:

- Claim `20261024T023550Z-codex-216b308f`, session `codex-wp23-20261023`.
- Branch `feat/ask-cio-phase8-11-20261023`; scope is the existing Ask-CIO integration.

No preference route or alternate route was changed. The coordinator directed that paging wait until the WP-23 successor merges. The remaining work should project/page the shared-symbol value in SQL before Python hydration, preserve source timestamps and expose total/truncation information, then update its consumers with fixture proof. No producer cache should be silently rewritten to manufacture completeness.

This delivery is the independently reviewable home fix. Exactly one `PUSH_NEEDED` event supplies its operator publication command. Required GitHub checks, merge/release, the shared-preference follow-up, complete scheduler correlation and full-session/full-route acceptance remain outstanding; the coordinator owns merges and releases.
