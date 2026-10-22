# CIO prospect shadow build — comparison vs today's surfaces (2026-10-22)

```
Status:      SHADOW EVIDENCE — input to the operator's §17 decisions (AGENTS.md §26); nothing here is live
as_of:       2026-10-22T20:10:34Z (16:10 ET, just after the close, so expires_at = evidence_at + 26 h)
Measured at: scripts/cio_prospect_shadow_build.py --dry-run --compare --state-root ~/trade-ai-releases/persistent-state
             (read-only file inputs; no DB session; no store written). Watch top ideas: ONE read-only GET of
             /api/v3/data-broker/watch-intelligence?view=top_ideas&page_size=50 at 19:45:51Z (rank top_ideas.v2).
```

Architecture: [`CIO_PROSPECT_DATA_FOUNDATION.md`](CIO_PROSPECT_DATA_FOUNDATION.md) §7 P1. Reproduce:
`.venv/bin/python scripts/cio_prospect_shadow_build.py --dry-run --compare --watch-surface-json <capture> --report-md <out>`.

**What this run did not read** (stated so nobody reads more into it): the six DB inputs (decision_packets,
cio_decisions, cio_entry_states, trade_ai_scans, watchlist_items, operator_starred_symbols) — the agent may not load
DB credentials (§24.7); the lane reads them with `--with-db` on a READ ONLY session. So no prospect here reached stage
`actionable` (that needs an entry state or an actionable packet), `scanner_score` is empty, and operator stars/adds
are not yet protected members. `fused_score`, `catalyst_grade` and `regime_fit` have no producer and are carried as
missing components, never invented.

## Highlights

1. **The NVDA case reproduces exactly.** NVDA is held; the opportunity curator says `ADD` (78.1), thesis
   `symbol_nvda@v8` (2026-10-05) says `watch`, and its InstrumentRecord is `WATCH:NVDA`. The prospect shows stage
   `held`, stance `ADD`, and two recorded conflicts (`stance`, `subject_key_kind`), next action "CIO: resolve 2
   conflicts with a recorded reason". Today no surface shows either conflict.
2. **SPCX** (`ADD` vs thesis `watch`), **ANET / MCD / WMT / DT** (`RE_ENTER` vs `watch`), **RTX / LDOS** (`ADD` vs
   thesis `hold`), **NOC** (`ADD` vs `watch`), **BAH** (`ADD` vs thesis `hold` and spine `WATCH`) and **SCHD**
   (`TRIM` vs `hold`): **22 prospects carry 26 conflicts** (22 stance, 3 subject_key_kind, 1 Hermes lifecycle vs
   curator) — shown on the record, never resolved. HOLD-vs-watch is deliberately not a conflict (the same "no new
   action" posture from a held and a watched book).
3. **Watch ranks something else entirely.** Of Watch's 22 top ideas (`top_ideas.v2`), only ANET, NVDA and SPCX are in
   the shadow top 50; the rest are held income/ETF names (BND, DIV, JEPI, SCHD, SCHG, XAR, XLB, XLI, AMANX ...) because
   `top_ideas.v2` scores street rating + packet state + starred/held bonuses and reads no CIO conviction or thesis.
   Moving Watch onto the prospect ranking is the §17 "what is ranked onto an operator surface" decision.
4. **Home and Telegram agree with each other** (both read `cio_opportunity_projection.json`; Telegram's conviction
   line is the same number, rank and stance). Home's best opportunities (preset top5: NAVN, ASST, BHVN, P, BRCC) —
   NAVN, ASST, BHVN are in the shadow top 50; P and BRCC fall to #132/#72 because the prospect conviction blends the
   curator's score (45%) with Hermes, the spine thesis quality and the persisted unified edge.
5. **Identity is the gate.** 191 of 1,844 symbols have no CONFIRMED registry GUID (foreign listings such as 2330.TW
   and ASML.AS, class shares BRK-B/BF-B, and some held/re-entry names such as CACI) and get no prospect — "identity
   unresolved", never a placeholder.
6. **Watchlist curation (proposed, nothing written):** with the proposed caps, 205 members are kept and 1,194 would be
   proposed out (setup_forming 348 vs cap 40; watching 979 vs cap 120); the 20 held names with a GUID are protected. The caps and
   `min_conviction` 60 are in `config/cio_prospect_watchlist_rules.json` (status PROPOSED) for the operator to set.

## Build

- universe 1844 symbols → **1653 prospects** (one per security_guid); 191 identity unresolved (no prospect, by rule); 0 duplicate GUID aliases; 0 errors
- by stage: {"held": 20, "re_entry": 43, "setup_forming": 348, "watching": 1242}
- **22 prospects carry 26 recorded conflicts** (shown, never resolved)
- held set: 23 symbols from `positions_context (holdings_accounts via lib.portfolio_positions)`; a held symbol without a CONFIRMED GUID has no prospect
- watchlist curation (proposed, nothing written): {"keep": 205, "propose_out": 1194}; by stage {"actionable": {"cap": 20, "members": 0, "over_cap": 0, "protected": 0}, "exit": {"cap": 20, "members": 0, "over_cap": 0, "protected": 0}, "held": {"cap": null, "members": 20, "over_cap": 0, "protected": 20}, "proposed": {"cap": 15, "members": 0, "over_cap": 0, "protected": 0}, "re_entry": {"cap": 25, "members": 43, "over_cap": 18, "protected": 0}, "setup_forming": {"cap": 40, "members": 348, "over_cap": 308, "protected": 0}, "watching": {"cap": 120, "members": 979, "over_cap": 859, "protected": 0}}

Sources read:

| source | status | rows | as_of |
|---|---|---|---|
| opportunity | ok | 1589 | 2026-10-22T20:00:33.056682+00:00 |
| theses | ok | 690 | 2026-10-22T17:41:22.252231+00:00 |
| spine | ok | 297 | 2026-10-22T19:30:48.493119Z |
| instrument_records | ok | 52 | 2026-10-22T20:02:12.656221+00:00 |
| reentry | ok | 93 | 2026-10-22T20:09:53.320694+00:00 |
| hermes | ok | 5646 | 2026-10-22T20:07:20.350745+00:00 |
| scanner | ok | 538 | 2026-10-22T13:02:47.311453+00:00 |
| decision_packets | not_read (no read-only db_query injected) | 0 | None |
| cio_decisions | not_read (no read-only db_query injected) | 0 | None |
| entry_states | not_read (no read-only db_query injected) | 0 | None |
| scanner_db | not_read (no read-only db_query injected) | 0 | None |
| watchlist_items | not_read (no read-only db_query injected) | 0 | None |
| starred | not_read (no read-only db_query injected) | 0 | None |

## Comparison — top 50 shadow prospects + Home best opportunities + Watch top ideas

- subjects compared: 71 — **agree 56, differ 15**
- stance differences 0; conviction differences (≥10 pts) 5; subjects whose inputs disagree 12
- shadow top 50 ∩ Home (opportunity rank) top 50: 18
- Home best opportunities (preset top5): ['NAVN', 'ASST', 'BHVN', 'P', 'BRCC'] — in shadow top: ['NAVN', 'ASST', 'BHVN']
- Watch top ideas (captured watch_top_ideas.json (rank_version top_ideas.v2, generated_at 2026-10-22T19:45:51.705342+00:00, 22 top ideas)): ['ANET', 'NVDA', 'SPCX', 'V', 'PFLT', 'RTX', 'NOC', 'LDOS', 'CSWC', 'DT', 'BAH', 'BND', 'DIV', 'JEPI', 'AMANX', 'SCHD', 'SCHG', 'SRNE', 'XAR', 'XLB', 'XLI', 'ZETA'] — in shadow top: ['ANET', 'NVDA', 'SPCX']
- Telegram conviction line: scripts/lib/opportunity_alert.enrich reads the same projection; suppressed when older than 26h (projection age 0.17 h)

| symbol | shadow rank · stage · stance · conviction | Home rank · stance · conviction | Watch | Telegram line | verdict |
|---|---|---|---|---|---|
| ASST | #1 · setup_forming · WATCH · 82.84 | #2 · WATCH · 86.6 · **best** | — | Conviction 87/100 · #2 · WATCH | agree |
| PDSB | #2 · setup_forming · WATCH · 80.62 | #9 · WATCH · 82.1 | — | Conviction 82/100 · #9 · WATCH | agree |
| BHVN | #3 · setup_forming · WATCH · 79.56 | #4 · WATCH · 85.0 · **best** | — | Conviction 85/100 · #4 · WATCH | agree |
| NAVN | #4 · held · ADD · 79.04 | #1 · ADD · 86.8 · **best** | — | Conviction 87/100 · #1 · ADD | agree |
| XRPN | #5 · setup_forming · WATCH · 77.74 | #3 · WATCH · 86.5 | — | Conviction 86/100 · #3 · WATCH | agree |
| NVDA | #6 · held · ADD · 76.78 | #80 · ADD · 77.7 | #2 | Conviction 78/100 · #80 · ADD | inputs disagree: stance, subject_key_kind |
| DHR | #7 · setup_forming · WATCH · 76.04 | #144 · WATCH · 75.6 | — | Conviction 76/100 · #144 · WATCH | agree |
| ELF | #8 · setup_forming · WATCH · 75.28 | #99 · WATCH · 76.9 | — | Conviction 77/100 · #99 · WATCH | agree |
| VST | #9 · setup_forming · WATCH · 75.08 | #32 · WATCH · 79.3 | — | Conviction 79/100 · #32 · WATCH | agree |
| HNGE | #10 · setup_forming · WATCH · 75.0 | #67 · WATCH · 77.9 | — | Conviction 78/100 · #67 · WATCH | agree |
| MCK | #11 · setup_forming · WATCH · 74.86 | #69 · WATCH · 77.8 | — | Conviction 78/100 · #69 · WATCH | agree |
| CDW | #12 · setup_forming · WATCH · 74.43 | #71 · WATCH · 77.8 | — | Conviction 78/100 · #71 · WATCH | agree |
| AJG | #13 · setup_forming · WATCH · 74.32 | #17 · WATCH · 80.3 | — | Conviction 80/100 · #17 · WATCH | agree |
| MDLN | #14 · setup_forming · WATCH · 74.18 | #187 · WATCH · 74.3 | — | Conviction 74/100 · #187 · WATCH | agree |
| HAFN | #15 · setup_forming · WATCH · 73.94 | #226 · WATCH · 73.5 | — | Conviction 74/100 · #226 · WATCH | agree |
| INDV | #16 · setup_forming · WATCH · 73.92 | #14 · WATCH · 80.5 | — | Conviction 80/100 · #14 · WATCH | agree |
| SYF | #17 · setup_forming · WATCH · 73.92 | #26 · WATCH · 79.5 | — | Conviction 80/100 · #26 · WATCH | agree |
| HAS | #18 · setup_forming · WATCH · 73.84 | #199 · WATCH · 74.1 | — | Conviction 74/100 · #199 · WATCH | agree |
| DCTH | #19 · setup_forming · WATCH · 73.52 | #114 · WATCH · 76.3 | — | Conviction 76/100 · #114 · WATCH | agree |
| TSM | #20 · setup_forming · WATCH · 73.52 | #180 · WATCH · 74.6 | — | Conviction 75/100 · #180 · WATCH | agree |
| SBET | #21 · setup_forming · WATCH · 73.26 | #337 · WATCH · 71.0 | — | Conviction 71/100 · #337 · WATCH | agree |
| SBS | #22 · setup_forming · WATCH · 73.26 | #153 · WATCH · 75.3 | — | Conviction 75/100 · #153 · WATCH | agree |
| TGS | #23 · setup_forming · WATCH · 73.26 | #85 · WATCH · 77.5 | — | Conviction 78/100 · #85 · WATCH | agree |
| SPCX | #24 · held · ADD · 73.25 | #48 · ADD · 78.4 | #3 | Conviction 78/100 · #48 · ADD | inputs disagree: stance |
| DDOG | #25 · setup_forming · WATCH · 73.16 | #272 · WATCH · 72.4 | — | Conviction 72/100 · #272 · WATCH | agree |
| ADIL | #26 · setup_forming · WATCH · 72.94 | #25 · WATCH · 79.6 | — | Conviction 80/100 · #25 · WATCH | agree |
| ATEC | #27 · setup_forming · WATCH · 72.9 | #27 · WATCH · 79.5 | — | Conviction 80/100 · #27 · WATCH | agree |
| ANET | #28 · re_entry · BUY_SETUP · 72.68 | #297 · RE_ENTER · 71.8 | #1 | Conviction 72/100 · #297 · RE_ENTER | inputs disagree: stance |
| DLXY | #29 · setup_forming · WATCH · 72.46 | #66 · WATCH · 77.9 | — | Conviction 78/100 · #66 · WATCH | agree |
| SW | #30 · setup_forming · WATCH · 72.46 | #164 · WATCH · 75.1 | — | Conviction 75/100 · #164 · WATCH | agree |
| MCD | #31 · re_entry · BUY_SETUP · 72.42 | #239 · RE_ENTER · 73.1 | — | Conviction 73/100 · #239 · RE_ENTER | inputs disagree: stance |
| J | #32 · setup_forming · WATCH · 72.37 | #56 · WATCH · 78.2 | — | Conviction 78/100 · #56 · WATCH | agree |
| PLTR | #33 · setup_forming · WATCH · 72.34 | #303 · WATCH · 71.7 | — | Conviction 72/100 · #303 · WATCH | agree |
| WMT | #34 · re_entry · BUY_SETUP · 72.33 | #161 · RE_ENTER · 75.2 | — | Conviction 75/100 · #161 · RE_ENTER | inputs disagree: stance |
| AGI | #35 · setup_forming · WATCH · 72.32 | #369 · WATCH · 70.4 | — | Conviction 70/100 · #369 · WATCH | agree |
| APEI | #36 · setup_forming · WATCH · 72.28 | #42 · WATCH · 78.6 | — | Conviction 79/100 · #42 · WATCH | agree |
| MSTR | #37 · setup_forming · WATCH · 72.22 | #7 · WATCH · 82.6 | — | Conviction 83/100 · #7 · WATCH | conviction: shadow 72.22 vs home 82.6 |
| MU | #38 · setup_forming · WATCH · 72.07 | #371 · WATCH · 70.3 | — | Conviction 70/100 · #371 · WATCH | agree |
| ALLE | #39 · setup_forming · WATCH · 72.03 | #30 · WATCH · 79.3 | — | Conviction 79/100 · #30 · WATCH | agree |
| HITI | #40 · setup_forming · WATCH · 71.9 | #63 · WATCH · 77.9 | — | Conviction 78/100 · #63 · WATCH | agree |
| AGBK | #41 · setup_forming · WATCH · 71.86 | #54 · WATCH · 78.3 | — | Conviction 78/100 · #54 · WATCH | agree |
| CCL | #42 · setup_forming · WATCH · 71.86 | #19 · WATCH · 80.0 | — | Conviction 80/100 · #19 · WATCH | agree |
| CF | #43 · setup_forming · WATCH · 71.68 | #332 · WATCH · 71.1 | — | Conviction 71/100 · #332 · WATCH | agree |
| DSX | #44 · watching · WATCH · 71.62 | #396 · WATCH · 69.7 | — | Conviction 70/100 · #396 · WATCH | agree |
| MH | #45 · setup_forming · WATCH · 71.5 | #74 · WATCH · 77.7 | — | Conviction 78/100 · #74 · WATCH | agree |
| ASPN | #46 · setup_forming · WATCH · 71.48 | #278 · WATCH · 72.2 | — | Conviction 72/100 · #278 · WATCH | agree |
| DH | #47 · setup_forming · WATCH · 71.42 | #45 · WATCH · 78.5 | — | Conviction 78/100 · #45 · WATCH | agree |
| AMTM | #48 · setup_forming · WATCH · 71.36 | #31 · WATCH · 79.3 | — | Conviction 79/100 · #31 · WATCH | agree |
| AEYE | #49 · setup_forming · WATCH · 71.18 | #229 · WATCH · 73.4 | — | Conviction 73/100 · #229 · WATCH | agree |
| SMMT | #50 · setup_forming · WATCH · 70.98 | #148 · WATCH · 75.4 | — | Conviction 75/100 · #148 · WATCH | agree |
| P | #131 · setup_forming · WATCH · 66.8 | #5 · WATCH · 84.5 · **best** | — | Conviction 84/100 · #5 · WATCH | conviction: shadow 66.8 vs home 84.5 |
| BRCC | #73 · setup_forming · WATCH · 69.82 | #6 · WATCH · 84.0 · **best** | — | Conviction 84/100 · #6 · WATCH | conviction: shadow 69.82 vs home 84.0 |
| V | #176 · held · HOLD · 65.98 | #748 · HOLD · 62.0 | #4 | Conviction 62/100 · #748 · HOLD | agree |
| PFLT | #443 · held · HOLD · 60.57 | #615 · HOLD · 65.2 | #5 | Conviction 65/100 · #615 · HOLD | agree |
| RTX | #549 · held · ADD · 58.24 | #170 · ADD · 74.9 | #6 | Conviction 75/100 · #170 · ADD | conviction: shadow 58.24 vs home 74.9; inputs disagree: stance |
| NOC | #675 · held · ADD · 56.07 | #137 · ADD · 75.8 | #7 | Conviction 76/100 · #137 · ADD | conviction: shadow 56.07 vs home 75.8; inputs disagree: stance |
| LDOS | #112 · held · ADD · 67.44 | #236 · ADD · 73.2 | #8 | Conviction 73/100 · #236 · ADD | inputs disagree: stance |
| CSWC | #548 · held · HOLD · 58.24 | #495 · HOLD · 67.7 | #9 | Conviction 68/100 · #495 · HOLD | agree |
| DT | #59 · re_entry · BUY_SETUP · 70.48 | #38 · RE_ENTER · 78.8 | #10 | Conviction 79/100 · #38 · RE_ENTER | inputs disagree: stance |
| BAH | #183 · held · ADD · 65.83 | #240 · ADD · 73.1 | #11 | Conviction 73/100 · #240 · ADD | inputs disagree: stance |
| BND | #1037 · held · HOLD · 48.66 | #1152 · HOLD · 50.5 | #12 | Conviction 50/100 · #1152 · HOLD | agree |
| DIV | #925 · held · HOLD · 51.17 | #1201 · HOLD · 48.9 | #13 | Conviction 49/100 · #1201 · HOLD | agree |
| JEPI | #624 · held · HOLD · 57.1 | #962 · HOLD · 56.3 | #14 | Conviction 56/100 · #962 · HOLD | inputs disagree: subject_key_kind |
| AMANX | #1331 · held · HOLD · 38.5 | #1228 · HOLD · 47.6 | #15 | Conviction 48/100 · #1228 · HOLD | agree |
| SCHD | #780 · held · TRIM_REVIEW · 54.18 | #1071 · TRIM · 52.9 | #16 | Conviction 53/100 · #1071 · TRIM | inputs disagree: stance |
| SCHG | #740 · held · HOLD · 54.98 | #1035 · HOLD · 53.9 | #17 | Conviction 54/100 · #1035 · HOLD | agree |
| SRNE | #319 · held · HOLD · 62.73 | #487 · HOLD · 67.9 | #18 | Conviction 68/100 · #487 · HOLD | agree |
| XAR | #1297 · held · HOLD · 40.35 | #1166 · HOLD · 50.0 | #19 | Conviction 50/100 · #1166 · HOLD | agree |
| XLB | #986 · held · HOLD · 49.87 | #1072 · HOLD · 52.9 | #20 | Conviction 53/100 · #1072 · HOLD | agree |
| XLI | #1052 · held · HOLD · 48.17 | #1064 · HOLD · 53.1 | #21 | Conviction 53/100 · #1064 · HOLD | agree |
| ZETA | #314 · re_entry · WATCH · 62.8 | #679 · WATCH · 63.7 | #22 | Conviction 64/100 · #679 · WATCH | agree |

MBI_BEHAVIOR = 0: stance is posture and priority; reference levels are information, never orders.
