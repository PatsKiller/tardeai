# Symbol-thesis job repair (2026-10-09)

Your request: "fix the thesis job". It came after BRCC, ranked #2 by the CIO, showed "No CIO thesis on file".

## What the ledger showed (2026-10-04 to 10-09)

`data/cio/symbol_thesis_acquisition_ledger.jsonl` had **315 runs and 6 PUBLISHED**, about one thesis a day.

| Status | Runs | Cause |
|---|---|---|
| BLOCKED | 160 | Evidence floor not met. Mostly the same symbols every hour on unchanged evidence (AA 58 times, AAP 55 times, IRDM 19). |
| SYNTHESIS_FAILED | 108 | 48 `DEFERRED_TO_OFFPEAK`, 43 `DEDUPE_SKIP`, 17 `parse:no_json_object` |
| LLM_BUDGET_EXHAUSTED | 41 | 17:17 ET run: 3 Flash calls per run, several of them wasted on the failures above |
| PUBLISHED | 6 | |

Root causes:

1. **The hourly retry loop.** `symbol_news_curation_monitor`, run hourly by the health tick, re-runs every open
   priority request. A request that never publishes stays open for 7 days. A symbol blocked on unchanged evidence was
   retried every hour.
2. **The off-peak deferral loses the answer.** Outside the window, `governed_flash_call` defers the prompt to
   `llm_deferred_requests`. The drain re-asks it but keeps no answer for this caller (the table has no response
   column). The provider's evidence dedupe then refuses the identical evidence on every later attempt
   (`DEDUPE_SKIP … consumer may release_completed`) and returns an empty answer. The symbol is poisoned.
3. **Truncation.** Thesis synthesis runs on process `watchlist_steph_flash_narrative` with `max_output_tokens`
   1600. The HPE and TELO replies end mid-sentence, so the JSON never closes and parsing fails.

The evidence gate itself works. A dry run of the 12 oldest open requests with the job's Python found 10 ready for
synthesis and 2 blocked. An earlier run with the wrong interpreter (system `python3`, no numpy) made RAG look broken;
it is not.

## Fixes

| Fix | Where |
|---|---|
| **Backoff:** skip a symbol whose last 3 rows within 24 h are BLOCKED with identical evidence counts. Not ledgered; it resumes when the counts change. | `run_symbol_thesis_acquisition.blocked_backoff` |
| **Wait, don't defer:** outside the off-peak window (`llm_deferral.evaluate`), status `WAITING_FOR_OFFPEAK`. No call, no budget spent, nothing queued; the request stays open for the next in-window run. | `offpeak_wait`, `run_one` |
| **DEDUPE_SKIP:** release the stale completion (`release_completed`) and ask once more, the same remedy as `options_cio_review`. An unparseable answer is also released, so it cannot poison the next attempt. | `symbol_thesis_synthesis` |
| **Output budget 1600 → 3200 tokens.** Same remedy as 2026-08-20 (800 → 1600). Cost caps unchanged ($1/day, 180 calls/day). | `config/llm_process_registry.json`, `max_tokens` default |
| **Per-run LLM budget 3 → 6, timeout 300 → 900 s.** | `run_governed_symbol_thesis_acquisition.sh` |

Gate: `thesis_job_fix_20261009`.
Verify the next day with the ledger: count `PUBLISHED`, and expect `DEDUPE_SKIP` and `parse:no_json_object` near zero.
