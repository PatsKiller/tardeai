# CIO data quality — stop ordering and Hermes catalyst identity (2026-10-23)

Task `T-20261023-9a2754`. CI gate `cio_data_quality_20261023` (ANCHOR `CIO_DATA_QUALITY_20261023`), test
`tests/test_cio_data_quality_20261023.py`, fixture `tests/fixtures/cio_data_quality/cio_data_quality_20261023.json`.
Read-only and advisory. `MBI_BEHAVIOR = 0`. No broker call, no model prompt, no live lane, no writer changed.

Two defects found on 2026-10-23.

## 1. Stop ordering — `scripts/lib/cio_prospect_builder.py`

**Defect.** `LIFECYCLE_QUERIES["stop_history"]` reads `stop_lifecycle` ordered by `id` and passes `id AS seq`, and
`cio_prospect_lifecycle.stop_path` sorts by `seq`. `stop_lifecycle` is rewritten newest-first on every scan, so the
row id runs **backwards in time** for one position. NAVN read "raised 1x from 26.02".

**Evidence.** NAVN's rows, read with a read-only session (`enforce_readonly`) on 2026-10-23 at about 14:10 ET:

| id | broker order id | status | stop |
|---|---|---|---|
| 3735550 | 1008390164604 | filled | 26.02 |
| 3735551 | 1008390164603 | replaced | 25.61 |
| 3735555 | 1008380699460 | replaced | 25.51 |
| 3735556 | 1008362273101 | replaced | 24.97 |
| 3735557 | 1008345101300 | replaced | 24.70 |
| 3735558 | 1008345101170 | replaced | 24.31 |
| 3735559 | 1008345100877 | replaced | 24.59 |

In broker order time the stop was set at 24.59, cut to 24.31, then raised 5 times (24.70, 24.97, 25.51, 25.61,
26.02), and filled at 26.02. That matches the operator's "raised 5x".

**Fix.** `order_stops_by_broker_order(rows)` runs in `load_lifecycle_inputs` for every symbol's `stop_history`
rows, for database rows and for captured rows alike. When every row of the symbol has a numeric broker order id,
`seq` becomes that id, `row_id` keeps the table id and `seq_basis = "broker_order_id"`. This is the same rule PR
#2008's Watch code applies in `lib/data_broker/watch_position_facts.lifecycles`, and applying that rule a second
time changes nothing. If even one order id is not numeric, the rows keep the row-id order, because the two
numberings cannot be compared.

**Note.** `tests/fixtures/cio_prospect/navn_20261022.json` came from a coordinator relay that had no order ids. It
lists the path as 24.31 → … → 26.02 with 6 raises. The table shows 24.59 first. That fixture's non-numeric order ids
are unaffected by this change, and its test was left unchanged.

## 2. Hermes catalyst identity — `scripts/lib/hermes_scalp_catalyst_record.py`

**Defect.** `hermes_momentum_catalyst_researcher.py` searches for "<SYM> stock latest news" and uses the first
result's title as `catalyst_summary`. `select_scalp_catalyst` marked every record that was not `no_clear_catalyst`
as FOUND, whatever the result was about. Some examples:

- AARD (Aardvark Therapeutics) resolved to an Archrock (AROC) headline.
- YMAT and INVE resolved to `https://www.nfl.com/news/series/all-news`, which has the title "ALL NEWS".

The YMAT and INVE records in the test fixture are copied verbatim from the 2026-10-23 day file. The AARD record is
reconstructed. The only AARD line in today's day file, from 13:25, says `no_clear_catalyst`, and no day file under
persistent state mentions Archrock. So the fixture's Archrock source row follows the researcher's output format and
is not a copy.

**Rule.** `verify_identity(symbol, record, company_names)` applies the operator ruling of 2026-10-10 that the
matcher is whole-word:

- **What counts as a mention.** The headline (`catalyst_summary`) or its source (`sources[0]`: title, snippet and URL
  slug) must name one of these as a whole word:
  - The **ticker**, in upper case, with an optional `$`. It is never case-folded, so "Host a call" does not name
    HOST.
  - The **company name**, case-insensitive. The name is matched without its legal suffix (Inc, Corp, Ltd, plc, SAB
    de CV, and so on) and without EDGAR markers such as `/NEW/`. Its first word also counts when that word has at
    least 5 letters and is not a common word.
- **Word boundaries are Unicode-aware.** For example, "BETR" is not a whole word inside "Betrüger".
- **Generic index pages are rejected.** A title like "ALL NEWS", "Latest headlines" or "Top stories" is never
  evidence. Neither is a URL for a site home page or a series, category, tag, topic or section page, or a URL that
  ends in /news, /latest or /all-news. A headline taken from such a page is never verified.
- **Outcome.** A record that fails the rule gets the status **`UNVERIFIED_IDENTITY`**, never FOUND. The record's
  `identity` field gives the reason and where the evidence was found.

**Company names.** Each reader reads the SEC ticker map that the state already holds,
`<state>/data/runtime/sec_company_tickers.json`, read-only, and parses it with `sec_name_index`.
`data_broker.scalp_list._company_names` caches it by mtime and size. `scanner_candidate_projection` reads it once per
projection. If the map is missing, only the ticker can match.

**Readers.** Both readers still select records the same way and now pass company names:
`data_broker.scalp_list.get_scalp_catalyst` (used by the AT alert, `unified_momentum_alert.hermes_record` and
`momentum_setup_evidence`) and the `scanner_candidate_projection` Hermes fallback. Every consumer already treats any
status other than FOUND as "no catalyst", so a wrong-company headline is no longer printed as the catalyst.

**Placement.** The validator lives in the existing reviewed module. A new module imported from there would grow the
reviewed `momentum-cache-reconcile` import closure in `tests/test_n8n_executor_env_allowlist_20261009.py`, and that
file is held by another claim (PR #2016). The module stays pure: no environment read, no file I/O, stdlib only.

**Replay.** A read-only replay of the 2026-10-16 to 2026-10-23 day files changed the counts as follows:

| Status | Before | After |
|---|---|---|
| FOUND | 74 | 4 |
| UNVERIFIED_IDENTITY | 0 | 70 |
| NONE_FOUND | 74 | 74 |

The 4 records still FOUND are correct: PEP ("PepsiCo"), AMX ("America Movil"), CLF ("Cleveland-Cliffs") and UNCY
("Unicycive Therapeutics").

Most of the 70 came from these pages:

- the nfl.com "ALL NEWS" page;
- Reuters section pages ("Australia News | Today's Latest Stories", "Weather News …", "Ukraine and Russia at War");
- unrelated headlines (Ethan Allen for YMAT, BioNTech for MEDS).

**Out of scope, for the operator.** The researcher's search query is unchanged. It is a live lane, and this change
is only the validator. A follow-up could have the researcher skip index pages and require an identity match before
it takes `sources[0]`. That is a lane change and the operator's decision (§17).
