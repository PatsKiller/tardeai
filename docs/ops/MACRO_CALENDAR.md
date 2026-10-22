# Macro calendar — may the release train use the 08:00 ET window?

```
Status:      PROPOSED (branch feat/macro-calendar-20261021; lane macro-calendar-refresh at SHADOW, contract DRAFT)
as_of:       2026-10-21T21:30:00-04:00
Measured at: base d55da84d0 (origin/main); FRED live dry run NOT measured — FRED in maintenance (§8)
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Runbook-Id:  macro-calendar-refresh
Tests:       tests/test_macro_calendar_20261021.py (gate macro_calendar_20261021, ANCHOR MACRO_CALENDAR_20261021)
```

**Why.** The release train's controller (`scripts/lib/release_train_controller.py`, branch
`feat/release-train-controller-20261021`) must not activate a release at 08:00 ET on a day with an 08:30 ET macro
release, and it fails closed: with no calendar it skips 08:00 every day. The repository had no macro-events provider.
`scripts/economic_calendar.py` declared the gap after FMP was retired on 2026-09-13. The operator ruled on
2026-10-21: **FRED is the primary source, plus a yearly file for FOMC and overrides. n8n manages the refresh, the
host controller decides, and the calendar fails closed.**

## 1. Pieces

| Piece | Path | What it does |
|---|---|---|
| Refresh | `scripts/macro_calendar_refresh.py` | Verifies the release ids (`GET /fred/releases`). Fetches the scheduled dates (`GET /fred/releases/dates`, `realtime_start` = today ET, `realtime_end` = today + 120 days, `include_release_dates_with_no_data=true`, paged). Maps them to 08:30 events, merges the overrides and writes the calendar atomically. `--dry-run` fetches and prints, and writes nothing. |
| Overrides | `config/macro_calendar_overrides.json` (`MacroCalendarOverrides@v1`) | FOMC decision dates for 2026–2027, plus operator `add` / `remove` rows. Each row needs a reason. |
| Calendar | `<state root>/data/runtime/macro_calendar.json` (`MacroCalendar@v1`) | Per-date events, the 08:30 flag, the 08:00 skip flag, source receipts, `fetched_at` and `valid_through`. |
| Reader | `scripts/lib/macro_calendar.py` | `skip_0800(day) -> (skip, reason)`, `verdict(day, now)` and `ReleaseTrainCalendar`. Pure stdlib, no network, never writes. |
| Lane | `macro-calendar-refresh` (n8n dispatcher, ingest class, daily `5 5 * * *` ET, SHADOW) | Registry row, allowlist entry (`--dry-run`, `live_arg` null, env enforce), DRAFT health contract and cron-inventory row. No crontab line. |
| Inbox | `GET /api/v2/needs-action` source `macro_calendar` | "08:00 release window skipped: calendar stale" or "…: calendar missing": P2 when 08:00 is enabled and the train armed, else P3 (info). |

## 2. The FRED release ids

FRED gives release **dates**, not times. The 08:30 flag therefore comes from this mapping: each release's published
time, from the issuing agency's schedule. Every run checks each id against `GET /fred/releases`, and the name must
match. A missing or renamed id fails the run, and nothing is written. A silently wrong id would make an 08:30 day look
clear.

| FRED id | Event key | FRED release name (expected) | ET | Agency | Why this id |
|---|---|---|---|---|---|
| 50 | `employment_situation` | Employment Situation | 08:30 | BLS | The jobs report (PAYEMS, UNRATE) |
| 10 | `cpi` | Consumer Price Index | 08:30 | BLS | CPIAUCSL |
| 46 | `ppi` | Producer Price Index | 08:30 | BLS | PPIFIS |
| 9 | `retail_sales` | Advance Monthly Sales for Retail and Food Services | 08:30 | Census | The advance retail sales report (RSAFS) |
| 53 | `gdp` | Gross Domestic Product | 08:30 | BEA | Advance, second and third estimates |
| 180 | `jobless_claims` | Unemployment Insurance Weekly Claims Report | 08:30 | DOL | ICSA. Thursdays; on a Thursday-holiday week it moves to Wednesday, and FRED carries the actual date |
| 54 | `pce` | Personal Income and Outlays | 08:30 | BEA | PCE and the PCE price index |
| 95 | `durable_goods` | Manufacturers' Shipments, Inventories, and Orders | 08:30 | Census | DGORDER. The advance durable-goods report is at 08:30 and the full M3 report at 10:00. If FRED dates both, the lane skips 08:00 on both, so it can over-skip (the safe direction) but never under-skip |
| 27 | `housing_starts` | New Residential Construction | 08:30 | Census | HOUST |

**Verification status `[UNVERIFIED]` at this commit.** The ids are the agent's knowledge of FRED's release
catalogue. They could not be confirmed live on 2026-10-21, because every FRED endpoint answered HTTP 200 with its "Site
Maintenance" HTML page (§8). The refresh verifies them by name on every run, so a wrong id is caught at the first
run against a live FRED, not used. The operator's go-live step 1 (§9) is the first live `--dry-run`, which prints
the verification table.

**Coverage.** `valid_through` is the earliest "last scheduled date" across the nine releases, capped at the horizon.
Past that date at least one release's schedule is unknown, so the reader returns STALE there. If a mapped release has
no scheduled date in the window at all, the run fails: coverage is unknown.

## 3. Overrides (`config/macro_calendar_overrides.json`)

- `fomc.decision_dates` holds 16 dates. They are the last day of each 2026 and 2027 meeting, taken from
  <https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm> on 2026-10-21 `[VERIFIED]`. Each date is
  recorded at 14:00 ET with `skips_0800: false`, as the operator ruled, so FOMC days do not skip 08:00 unless the
  operator sets `fomc.skips_0800` to `true`. Review the file once a year, when the Fed publishes the next schedule.
- `add` takes `{date, event, name, time_et, skips_0800 (default true when time_et is 08:30), reason, added_by, added_on}`.
- `remove` takes `{date, event (an event key, or "*" for every event that day), reason, removed_by, removed_on}`.
- An invalid file fails the run, and nothing is written. That covers a row with no reason, a bad date, a bad event key
  or a bad time. Half an override file is never used.

## 4. `MacroCalendar@v1`

```json
{
  "schema": "MacroCalendar@v1", "lane_id": "macro-calendar-refresh", "timezone": "America/New_York",
  "fetched_at": "<UTC ISO>", "covers_from": "YYYY-MM-DD", "valid_through": "YYYY-MM-DD",
  "valid_through_bounded_by": ["housing_starts"], "horizon_end": "YYYY-MM-DD", "rule_0800": "...",
  "release_days_0830": ["YYYY-MM-DD", "..."], "skip_days_0800": ["YYYY-MM-DD", "..."],
  "dates": {"2026-11-10": {"weekday": "Tue", "has_0830": true, "skip_0800": true,
            "events": [{"event": "cpi", "name": "Consumer Price Index", "time_et": "08:30", "skips_0800": true,
                        "source": "fred", "release_id": 10, "agency": "BLS"}]}},
  "release_map": [...], "verification": [...], "fomc_decisions": [...], "overrides_applied": {"added": [], "removed": []},
  "source_receipts": [{"source": "fred", "endpoint": "/fred/releases", ...},
                      {"source": "fred", "endpoint": "/fred/releases/dates", "params": {...}, "rows": 0, "rows_sha256": "..."},
                      {"source": "overrides", "path": "config/macro_calendar_overrides.json", "sha256": "..."}]
}
```

`dates` lists only days that have an event, between `covers_from` and `valid_through`. The calendar is written with
`atomic_json_store.atomic_write_json` (a temp file, fsync, then `os.replace`), and only after it is built. A failed run
leaves the previous file untouched, and that file then ages into STALE.

## 5. The interface the controller calls

```python
from lib.macro_calendar import ReleaseTrainCalendar, skip_0800, verdict

verdict(day, now)    # -> ("CLEAR" | "MACRO_DAY" | "STALE" | "UNAVAILABLE", reason); never raises
skip_0800(day, now)  # -> (skip: bool, "<VERDICT>: reason"); skip is True for everything but CLEAR
TrainController(..., calendar=ReleaseTrainCalendar())   # drop-in for release_train_controller.MacroCalendar
```

`ReleaseTrainCalendar.verdict(day, now)` has the same signature and the same four words as the controller's
`MacroCalendar.verdict`. So `_rules()` keeps raising `Halt(NO_OP, f"WINDOW_SKIPPED_MACRO_{verdict}", why)` unchanged.
**Wired (release 3, branch `fix/release-train-arming-blockers-20261021`).** `TrainController.__init__` now builds
`calendar or MC.ReleaseTrainCalendar()`. The controller's own `MacroCalendar` class, its
`~/.config/tradeai/release_train/macro_calendar.json` path (`MacroReleaseCalendar@v1`) and its 168 h limit are
removed, so there is a single source: this file at `<state root>/data/runtime/macro_calendar.json`, stale after 72 h
(the operator's ruling).

`day` is the ET date of the window. An aware `datetime` is converted to America/New_York, and a naive one is taken as
ET wall time. Age is measured between absolute instants, so a DST change inside the 72 h window neither adds nor
removes an hour. The calendar file resolves under `TRADEAI_STATE_ROOT`, or else the persistent-state resolver, the
same root the lane receipts use.

## 6. Fail closed — every way to an answer

| Condition | Verdict | 08:00 |
|---|---|---|
| The day has an event with `skips_0800` (any mapped 08:30 FRED release, an operator `add` at 08:30, FOMC only if the operator set it) | MACRO_DAY | skipped |
| The day is covered and has no such event | CLEAR | allowed |
| The file is missing | UNAVAILABLE | skipped |
| The file is corrupt: bad JSON, wrong schema, `fetched_at` with no offset, a malformed date entry, `valid_through` before `covers_from` | UNAVAILABLE | skipped |
| `fetched_at` is more than 72 h old | STALE | skipped |
| `fetched_at` is more than 1 h in the future | STALE | skipped |
| The day is outside `covers_from..valid_through` | STALE | skipped |
| A bad `day`, or a `now` with no offset | UNAVAILABLE | skipped |

Needs-action evaluates the next 08:00 window: today if it is before 08:00 ET, otherwise the next weekday. STALE gives
"08:00 release window skipped: calendar stale", and UNAVAILABLE gives "…: calendar missing". A MACRO_DAY is an expected
skip and raises no item. **Severity (release 3):** the item is P2 only when the 08:00 window is live-able, meaning
its slot is enabled in an ACTIVE delegation and the train is armed (`needs_action.release_train_0800_scope`). Otherwise
it is P3, information only. While the lane is at SHADOW it writes no calendar, so the item shows every day. It stays P3
until 08:00 is enabled and the train is armed, and from then on a missing calendar is a P2 to act on.

## 7. The lane and the key

- Run argv `$PY scripts/macro_calendar_refresh.py`. The dry run adds `--dry-run`, and `live_arg` is null at shadow.
  Lock `/tmp/tradeai_macro_calendar_refresh.lock` (flock). Timeout 300 s.
- Env enforce: `FRED_API_KEY` and `TRADEAI_PERSISTENT_STATE_ROOT`. The other names it reads are executor base names.
  The import closure is 5 modules (`macro_calendar_refresh`, `lib/macro_calendar`, `lib/lane_last_receipt`,
  `lib/persistent_state_root`, `lib/atomic_json_store`). It contains no env-file loader, no DB, no sender and no
  broker. `lib/env_bootstrap` was deliberately not used: its whole-file read path fails the enforce-mode closure
  check. Under n8n the executor hands the lane `FRED_API_KEY` from its own environment. A manual run takes the key
  from the caller's environment.
- The key is never printed, logged, stored or put in an error. Errors carry an HTTP status only, never the URL, and
  any echo of the key in a FRED error body is replaced with `***`. A run prints only `FRED_API_KEY configured: yes|no`.
- A receipt failure is typed with the closed skip-reason enum. FRED down, non-JSON or a short read is
  `dependency_unavailable`. A failed id check or an invalid overrides file is `unconfigured`. No key is
  `no_credentials`. The fine-grained kind is in `summary.failure_kind`.
- Data-source authority: the call site is under the existing approved provider `fred`
  (`config/data_source_authority.json`), and `check_data_source_authority.py` reports 0 findings. No new domain row
  was added. A `macro_release_calendar` domain (store `data/runtime/macro_calendar.json`, writer this lane,
  `no_coverage` fail closed) would also need AGENTS.md §7A re-rendered (`scripts/render_source_of_truth.py`), and this
  change does not edit AGENTS.md. Proposed for the operator (§9).
- §24.9 (Postgres for a new authoritative store): the calendar is a derived, regenerable artifact. It is rebuilt
  from FRED and a committed config file every day, the controller ruling specified a file, and an n8n Cloud move
  keeps the same shape. It is not a store of record.

## 8. Live dry run — evidence

Run on 2026-10-21 at about 21:20 ET, read-only, from a neutral cwd, with the key from the agent's inherited
environment. The agent did not read an env file.

```
$ cd /tmp && python3 <worktree>/scripts/macro_calendar_refresh.py --dry-run
[macro-calendar] FAILED (dependency_unavailable): FRED /releases answered non-JSON (maintenance page): '<!doctype html> <html lang="en"> <head>     <title>Site Maintenance | St. Louis ' — no calendar written; the 08:00 window stays skipped once the previous calendar goes stale
[macro-calendar] FRED_API_KEY configured: yes
exit=1
```

The public site (`fred.stlouisfed.org/release?rid=50`) returned the same maintenance page. **The mapping is not yet
proven against live FRED.** The run did prove the fail-closed path live: HTTP 200 with HTML was refused, nothing was
written and no key was printed. This section is updated when a live dry run succeeds.

## 9. Operator items

1. **Contract review.** `config/n8n_health_contracts.json` id `macro-calendar-refresh` is a DRAFT. Mark it REVIEWED
   (owner platform) or amend it. Until then `check_n8n_health_contracts.py` reports `DRAFT_NOT_GRANDFATHERED`
   (AGENTS.md §23.19). An agent may not review its own contract.
2. **First live FRED dry run** (read-only, after FRED's maintenance ends):
   `python3 scripts/macro_calendar_refresh.py --dry-run`. Confirm that all nine ids print `OK`, that coverage is at
   least 60 days, and that the upcoming `SKIP 08:00` days match the agencies' published schedules.
3. **Going live** is the operator's word. It sets the registry row's `scheduler.stage` and `dispatch.mode`, and sets
   the allowlist `live_arg` (for example `[]`) under the §23 stage rules. It also needs `FRED_API_KEY` present in the
   n8n run-executor's environment, a host change. The agent did not read or check the rendered env file.
4. **Controller wiring.** Make the one-line change in §5 on the release-train controller branch.
5. **Proposed:** a `macro_release_calendar` domain row in `config/data_source_authority.json`, plus the AGENTS.md
   §7A re-render (§7).
6. **Not done:** `scripts/economic_calendar.fetch_economic_events` still returns `[]` (the declared gap). Wiring it to
   this calendar would change the CIO market-context input, which is a separate change.
