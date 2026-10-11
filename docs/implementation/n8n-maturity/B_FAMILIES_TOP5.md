# B families top 5 — one parameterised job per same-script cron family

**Status:** CURRENT — code + registry merged by this PR; crontab NOT changed (cron freeze; operator cron grant per packet)

**Date:** 2026-10-11

**Owner:** n8n maturity program, Agent BF5 (designs: Agent LL, `b-family-designs/RANKING.md`)

## What changed

Fourteen crontab lines ran five scripts in different modes on different schedules. Each family is now one
registry lane and one entry:

    cd $PROJ && $PY scripts/run_family_slot.py --family <lane_id> >> logs/run_family_slot.log 2>&1

`scripts/lib/family_slot_jobs.py` holds the slot table: cron expression → mode(s). Each mode's command is the
retired crontab line's command verbatim (`{root}` = the served path the line named). The entry derives the mode(s)
from the fire minute (10-minute attribution window; a fire outside every slot exits 2, it never guesses), runs each
as `/bin/bash -c <command>` in the project root with the cron environment untouched and stdout+stderr appended to the
mode's own log, keeps going after a failing mode, returns the first non-zero exit, and writes `LaneRunReceipt@v1`
`data/runtime/<lane>_last.json`. `--dry-run` prints the plan and writes nothing; `--mode X` runs one mode by hand;
`--print-crontab` prints the family's lines; `--audit-week <monday>` prints fires/week old vs new.

The gate wrappers (`non_trading_hours_gate.sh`, `llm_priority_guard.sh`, `run_with_deepseek_offpeak.sh --official`)
stay inside each mode's command as safety nets; the slot table only schedules the minutes they allow, so the
scheduler stops firing into a refusal. `gate_allows()` models them for tests and for the receipt's
`gate_prediction`.

| Design | Lane | Retired lines (live 2026-10-11) | New crontab lines | Fires/wk old → new | Saved |
|---|---|---|---|---:|---:|
| B3 | `topic-research-synthesizer` | L732 `20 * * * *`, L736 `50 21 * * *` | `20 0-3,16-23 * * 1-5`, `20 * * * 0,6` (reground rides the Fri/Sat 21:20 slot) | 175 → 108 | **67** |
| B7 | `research-scheduler` | L581, L582 `0 10-16`, L583, L585 | `5 9 * * 1-5`, `0 12-16 * * 1-5`, `30 20 * * 1-5`, `0 19 * * 0` | 46 → 36 | **10** |
| B8 | `catalyst-momentum-engine` | L379 `*/30 4-9`, L380 `30 9-15` | `0 4-9 * * 1-5`, `30 4-15 * * 1-5` | 95 → 90 | **5** |
| B2 | `topic-ingestion` | L734 `45 20 * * 1-5`, L735 `45 2 * * *` | `45 20 * * 1-5`, `45 2 * * 0,6` | 12 → 7 | **5** |
| B1 | `cio-event-detector` | L847, L848, L849 | same three schedules | 6.2 → 6.2 | 0 |
| | | **13 lines** | **13 lines** | **334 → 247** | **87** |

Registry lanes: 12 rows (11 retired + `topic-ingestion`) → 5 lanes. Distinct crontab commands: 13 → 5.
**Crontab entries: 13 → 13.** A crontab line carries one minute/hour/day-of-week set; these families' slot sets
differ in minute or weekday, so one line per family would fire at the union (B3: 168/wk, more than today). One
scheduler entry per family needs a multi-slot vehicle: a systemd timer with several `OnCalendar=` (new unit, §17) or a
dispatcher row with `dispatch.cron` slots (B3/B2 class llm/ingest, shadow first; B7/B1 host-only per §23.3). The entry
and slot table are already the code that either vehicle would call.

## Equivalence

`tests/test_family_slot_jobs_20261011.py` (hermetic) proves:

1. **text** — each mode renders the retired line's command verbatim (lines copied from the live crontab sha256
   `7eb97ad6…` with the root replaced), same log, same lock; the packet's `verify_equivalence.py` repeats this
   against the LIVE crontab through the entry's `--dry-run --mode`.
2. **time** — minute by minute over an EDT week, an EST week and a week with the 1st, the family's crontab lines fire
   exactly at the slot minutes, never two lines in one minute.
3. **effect** — over the same weeks every effective run of a retired line (fired, and every gate in it lets it
   through) is a run of the same mode at the same minute, and every new run is one, except the declared deltas.
4. **gates** — no new fire is a predicted gate refusal in a non-holiday week; fires saved = 87/week.
5. **entry** — refusal outside a slot, dry run writes nothing, real run cwd/env/log/receipt/exit code.
6. **registry** — one ACTIVE row per family (schedules = the crontab lines, match hits only its lines), every
   retired lane RETIRED with `superseded_by`, the candidate crontab leaves nothing undeclared.

### Deliberate deltas (asserted by the tests)

- **B3** reground runs at 21:20 Fri/Sat right after that slot's synth (same invocation, its own lock
  `/tmp/topic_reground.lock`, same log) instead of 21:50; Sun–Thu 21:50 were PEAK_SKIP no-ops.
- **B3** a weekday market holiday loses the 04:20, 05:20 and 12:20–15:20 synth runs the session gate allowed (the
  priority guard still defers 06–11), an early-close day its 13:20–15:20 runs (~70 runs/year; design B3 risk,
  accepted; the long-term answer is an event trigger on new topic rows).
- **B8** no premarket_scalp pass at 09:30 (it collided with the 09:30 market_swing pass under a different lock).
- **B7** the guard's DEFERRED echo lands in `research_scheduler.log` instead of cron mail; with 12–16 it never defers.
- **B1** adds `flock -n /tmp/cio_event_detector.lock` (design B1). The interpreter stays bare `python3`.

### Not folded

- **L381** (`catalyst-momentum-engine-overnight`, `0 18,22 * * *`) stays on its own line: it is the dispatcher shadow
  lane of wave D3 (`config/n8n_run_allowlist.json`). The family has the `overnight` mode (same command) so a later
  fold is a crontab + registry change once Agent A / the operator rule on the D3 shadow row.
- The n8n pilot label `research-scheduler-holdings` (`n8n_coordination_gateway.PILOT_LANES`,
  `report_lane_fire_ledger.PILOT_LANES`) is unchanged; after install the fire ledger finds no live line for that
  RETIRED row (its fires are `research-scheduler` holdings-mode fires). Follow-up: point the pilot at the family lane.

## Install (operator)

Packets: `~/n8n-maturity-verification/packets/b-families-top5/<lane>/` (build/install/rollback, dry-run default,
`CRON_GRANT_ID`, drift refusal, backup, fake-crontab round trip) and `OPERATOR.md` there (grant wording, order,
forced-run proof). Order: merge + deploy this PR first (install refuses until CURRENT serves
`scripts/run_family_slot.py`), then install the five packets back to back. Between deploy and install the five new
lanes read ORPHANED and the retired rows are RETIRED while their lines still run (not a state-drift conflict code).
