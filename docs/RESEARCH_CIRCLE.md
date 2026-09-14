# Research Escalation Circle

**Status:** Phase 1 built, dry run by default, not yet wired into the Telegram desk.
**Code:** `scripts/lib/research_circle.py` · runner `scripts/run_research_circle.py` · tests `tests/test_research_circle_20260914.py`.
**Design and measurements:** `docs/architecture/RESEARCH_ESCALATION_2026-09-14.md` §5.
**Authority:** READ_ONLY_ADVISORY. Research and notifications only. `MBI_BEHAVIOR = 0`.

## Why

The operator asked on 2026-09-14 for every research channel to be used. That means Trade-AI's own data,
Yahoo Finance, SEC, SearXNG, Brave, Hermes and DeepSeek. The channels should form an escalation circle
"with some intelligence around it":

- something that reads what comes back, scores it on maturity, and decides whether it suffices or
  the next channel is needed;
- check-ins queued automatically (a week, two weeks);
- everything tracked by GUID.

The same day's measurement found no quality-based escalation. For operator questions, Hermes (one DeepSeek
Flash call over house evidence, no web) was the only step that ran.

## The lifecycle (one `question_guid` per ask)

```
ASKED → GATHERING (lap n) → ANALYZED (lap n) ─┬─ sufficient ─────────────→ ANSWERED ─────────┐
                                              ├─ climb / targeted_lap ──→ GATHERING (lap n+1) │
                                              └─ stop_bound / ask_operator → ANSWERED_PARTIAL ┤
                                                                                              ▼
                                                                                      SCHEDULED (check-in)
                                                         REVISITED → SETTLED   (check-in sweep, Phase 4)
```

- `question_guid = uuid5(namespace, chat_id | message_id | normalised text)`. It sits next to the subject
  GUIDs from the identity spine.
- Rows are append-only in `data/cio/research_circle_ledger.jsonl`. Check-ins go to
  `data/cio/research_circle_checkins.jsonl`.
- The rows are written only with `--apply`.

## One lap

Phase 1 uses only free channels. Each channel returns evidence items with an id (`ev_…`), a kind, a
source, `as_of`, and the text.

| Channel | Items |
|---|---|
| house | the subject dossier through the desk's own gatherer: analysts, earnings, catalysts, news, research, thesis, profile, position; the stored close; re-entry levels |
| Yahoo Finance | live quote; analyst consensus and targets; volume vs 3-month average; earnings date; news (up to 6); **levels computed from daily bars** (20-day support/resistance, 60-day swing low/high, SMA20/50); **volume streak** (completed sessions above 1.5× the 50-session average) |
| SEC | Form 4 rows already ingested (`sec_form4`) |
| SearXNG | news search, falling back to general search when news returns fewer than 2 hits |

Rules that keep the score honest:

- **An undated item is never stamped today.** `as_of` is the date the line itself states
  (`stated_date`); an item with no date counts as stale.
- **Levels are computed, never searched for.**
- **A channel that raises does not end the lap.** Its error is recorded in `channel_errors`.

## The Context Analyzer

1. **Deterministic score** (`score_lap`), per sub-question read from the text (price, levels, analysts,
   news, volume, insiders, research). All adjustments are applied first; the caps come last:
   - 40 for any fresh item;
   - +25 for a second independent source;
   - +15 when numbers agree within 2%;
   - +20 when house and outside both answer;
   - stale-only evidence caps the need at 20;
   - numbers more than 10% apart are listed as contradictions and cap the need at 50.
2. **Model verdict** (`analyze`): DeepSeek Flash through the governed bridge reads the question, the score
   and the evidence packet. It returns JSON with these fields:
   - score, maturity M0–M4;
   - decision `sufficient | climb | targeted_lap | ask_operator | stop_bound`;
   - next channel, missing facts, contradictions;
   - a summary citing evidence ids, a falsifier, and check-in days with a reason.
3. **Grounding.** A verdict is rejected, and the deterministic decision stands, when it:
   - cites an id that is not in the packet;
   - uses a decision or maturity outside the allowed sets;
   - is not valid JSON.

   The model cannot call a lap `sufficient` when the deterministic score is below 40.
4. **Laps** (`run_circle`, bound 2): after `climb` / `targeted_lap`, the analyzer's missing facts become up
   to two search queries (`targeted_queries`). The next lap runs over everything found so far plus those
   results. **A lap that finds nothing new ends the circle without another model call.**

## Check-ins

`plan_checkin` picks the first rule that applies:

1. the day after a dated catalyst found in the evidence;
2. the analyzer's `checkin_days` (1–30) and reason;
3. 14 days for a settled answer on a held name;
4. 7 days otherwise.

## Measured 2026-09-14 (dry runs, nothing written)

**"Do some more research on HPE: good entry, support/resistance, what analysts say, how long has volume been
more than normal"**

- Lap 1:
  - 24 items (house 6, Yahoo 12, SearXNG 6);
  - score 62 (levels 40, analysts 85, volume 40, research 85);
  - verdict `targeted_lap`, M1, next Brave.
- The analyzer found three things:
  - the operator's premise was not supported: volume 0.83× its 3-month average;
  - the Yahoo and house earnings dates disagreed;
  - multi-day volume history was missing. The Yahoo daily-bar levels and volume streak were added as a result.
- Lap 2:
  - two targeted searches, 31 items;
  - still `targeted_lap` → ANSWERED_PARTIAL;
  - check-in in 3 days, because catalysts cluster on 09-11 to 09-14.

**"Why is ELMT up today, what's the news"**

- One lap, 15 items;
- news 85, `sufficient`, M2;
- check-in in 7 days.

## Not in Phase 1

| Phase | Adds |
|---|---|
| 2 | Brave, taken when the analyzer names it (router budgets; SearXNG spill); Hermes over house **and** web evidence; desk wiring behind a flag; pills on the reply |
| 3 | critic cross-check (independent model); DeepSeek Pro judgment for M3/M4 |
| 4 | the check-in sweep (REVISITED → SETTLED, outcome vs falsifier); "push for more" intent; monitors |

## Commands

```bash
python scripts/run_research_circle.py --symbol HPE --question "…"                      # deterministic, dry run
python scripts/run_research_circle.py --symbol HPE --question "…" --analyzer deepseek  # model verdict (1–2 Flash calls)
python scripts/run_research_circle.py --symbol HPE --question "…" --apply              # write ledger + check-in rows
```

The runner needs the database environment for the SEC channel and the house channel. It never sends a message.
