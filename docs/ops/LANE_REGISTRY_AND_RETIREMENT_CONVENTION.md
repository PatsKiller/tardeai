# Lane registry and the retirement convention

**Status:** ACTIVE from 2026-08-30.
**Authority:** READ_ONLY_ADVISORY. Nothing here installs, removes or edits a
scheduler. Changing a production scheduler entry is operator-only.

## The failure this exists to fix

A production lane was disabled on 2026-06-01 by "Phase 102," which commented out
four overnight cron entries and tagged them `PHASE102-RETIRED`. Nothing reported
its absence for three months.

The liveness monitor was not broken. It ran every 15 minutes throughout, and it
has a good record — it caught DuckDuckGo returning `[]` for weeks while the job
exited 0. It simply had no way to know that lane was supposed to exist. It
learns its lanes from hardcoded tuples in `scripts/lib/research_lane_health.py`
(`EXTERNAL_AUTO_LANES`, `EXTERNAL_MANUAL_LANES`) plus a few bespoke collectors.

**It can see a lane producing poorly. It cannot see a lane producing nothing
because nobody told it the lane was there.**

## The design principle

Detection generalises; prevention does not. A guard against commented-out crons
would not have caught a renamed script, a masked systemd unit, or a queue that
quietly stopped being read. What catches all of those is a declaration of what
*should* be producing, compared against what *is*.

This is the same shape as the dark-contract gate: declare intent, seed a
baseline of inherited debt, let a gate catch drift.

## The registry

`config/lane_registry.json`. One row per lane that is supposed to produce
something.

| field | why |
|---|---|
| `lane_id` | stable name |
| `owner` | who to ask |
| `scheduler` | `{kind: cron\|systemd\|none, expression}` |
| `expected_cadence_hours` | how often output should appear |
| `output_signal` | **the durable artifact that proves it ran** |
| `state` | `ACTIVE` · `RETIRED` · `PAUSED` · `NEVER_SCHEDULED` |
| `state_reason` | required when not `ACTIVE` |
| `state_since` | required when not `ACTIVE` |
| `review_by` | required when `PAUSED` |
| `active_days` | optional; `0`=Mon … `6`=Sun. Weekend cadences are **declared, not inferred** |

### `output_signal` is the field that matters

A lane is **not** verified by its exit code, its cron entry, or its log file
existing. It is verified by a durable artifact that would not exist if it had
not run. Exit code 0 has been wrong about this system three times.

Kinds: `file_mtime` (a path), `json_key` (a JSON file plus a dotted key holding
a timestamp), `db_max` (table plus timestamp column, optional `where`).

### `RETIRED` and `PAUSED` are declared states, not absences

A retired lane keeps its row. Its silence is expected and is reported as
expected — `EXPECTED_SILENT`, no alert. That is the entire point: the failure
being fixed is that **"off" was indistinguishable from "gone."**

`PAUSED` requires `review_by` so the operator gets asked again. A paused lane
nobody is ever asked about is a retired lane with better manners.

### Never invent a reason

Where a retirement's cause cannot be established from the commit, the PR, the
crontab comment or a decision document, the correct entry is `UNKNOWN`. An
honest `UNKNOWN` is itself a finding. The seeded registry carries 26 of them.

## Verdicts

| verdict | meaning | finding? |
|---|---|---|
| `LIVE` | producing within cadence | no |
| `SLOW` | 1–2× past cadence | no |
| `SILENT` | past cadence, no output, state is `ACTIVE` | **yes** |
| `EXPECTED_SILENT` | no output, state is `RETIRED`/`PAUSED`/`NEVER_SCHEDULED` | no |
| `UNDECLARED` | scheduled job producing output with no registry row | **yes** |
| `ORPHANED` | registry row whose scheduler no longer exists | **yes** |
| `UNVERIFIABLE` | `output_signal.kind == none` — cannot be proven either way | no |

`ORPHANED` is the verdict that would have caught the June retirement within one
cadence period.

## Monitoring

`scripts/lib/lane_registry.collect_lane_registry_report()` is appended to
`research_lane_health.collect_report()` as one more lane row, in the same shape
as every other collector. **This extends the monitor that already works. It is
not a second monitor.** Disable with `RESEARCH_LANE_HEALTH_REGISTRY=0`.

Suppression rules that keep it usable rather than noisy:

- `changed_findings()` escalates on **state change**, not on continued state. A
  lane silent for many cycles produces one alert, not one per cycle.
- Weekend and market-closed cadences are declared via `active_days`. A
  weekday-only lane does not alarm on a Sunday.
- A quiet system reports `QUIET`, not a page.

A monitor that alerts every cycle gets muted, and a muted monitor is worse than
none because it still looks like coverage.

## The CI gate

`scripts/check_lane_registry.py --fail-on-new`.

- A new scheduled job with no registry row → **exit 1**
- A registry row with no `output_signal` → **exit 1**
- A non-`ACTIVE` row with no `state_reason`/`state_since` → **exit 1**
- Registry unreadable or discovery unavailable → **exit 2**

Exit 2 is distinct on purpose: a gate returning 2 because a file is absent reads
identically to a pass unless the caller checks for the specific value, and that
has happened here. Mutation-tested in `tests/test_lane_registry.py`.

`undeclared_baseline` holds the inherited debt (563 entries at seeding) so the
gate is green on day one and **can only shrink**.

## The retirement convention

A commented cron line carrying only a phase tag is what produced the
unanswerable question. From now on, a retired entry carries its own answer:

```
# RETIRED 2026-06-01 lane=deep_overnight_llm reason=<why> owner=<who> review_by=<date>
```

Then add or update the lane's row in `config/lane_registry.json`.

This is a convention, not a control — it depends on the next agent following it.
Its value is that when the next question like this one arises, the answer is in
the file rather than in a forensic dig through three months of commits.

Proposed annotations for the existing commented entries are in
`docs/ops/lane_retirement_annotations.proposed.txt`. They are a **proposal**:
applying them edits the live crontab, which is operator-only.

## What this must not become

- **Not a second monitor.** Extend the one that already works.
- **Not a permission system.** Blocking people from disabling things produces
  workarounds and eventually gets switched off itself. Make disabling *visible*,
  not hard.
- **Not a noise generator.** If the first week produces alerts nobody reads it
  will be muted.
