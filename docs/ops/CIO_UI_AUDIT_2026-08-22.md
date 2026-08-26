# UI audit — /v3/advisory + CIO Office tabs (every tab)

**Authority:** READ_ONLY_ADVISORY. `MEMORY_BEHAVIOR_INFLUENCE=0`.  
**Captured:** 2026-08-23 00:05–00:16 UTC from ms01-openclaw `localhost:7777`.  
**Server:** CURRENT pin `5e91225a` `portfolio_server.py` (started Aug 21). UI `cc-v3 3.14+mt3l99fh` built 2026-08-21.  
**Raw payloads (untruncated):** Drive [UI_AUDIT_DUMP.md](https://drive.google.com/file/d/1pPqmKAfV9da93Q69i_ieERYdu27wlKoo/view) (13.8 MB). Local `~/ui-audit-2026-08-22/`.  
**This file is the canonical per-tab result.** Do not overlay it onto CURRENT `docs/` (pin integrity = git archive hashes of `SOURCE_COMMIT`).

**CURRENT pin constraint:** `scripts/`+`docs/` must match `5e91225a`. Aug 22 Telegram T1/T2 overlay (13 files + 2 extras) was restored 2026-08-23; backup `~/archives/current-pin-overlay-2026-08-22/`. Honesty **code** lands on `origin/main` (`fix/cio-ui-honesty-2026-08-22`). Live `:7777` stays the audited pin until an exact-main re-promote.

## L2 — What live `coverage_pct 2.4` was counting

Not `/v3/advisory`. That page reads `GET /api/v3/advisory` → `advisory_desk_latest.json` and **does not emit coverage_pct**.

`2.4` is `GET /api/v3/cio/universe-theses` (CIO tab UNIVERSE & THESES), pin formula:

```
coverage_pct = 100 * CURRENT / material_universe = 100 * 3 / 124 = 2.4
```

`material_universe=124` is held+reentry+material watch in the **process `_CACHE`**, frozen since `portfolio_server` started 2026-08-21 19:36 EDT. It is **not** 22 holdings. `current_thesis=3` is the same stale cache. The 80-row list on the same payload is a different function (`build_coverage_report`, uncached) and shows 22/22 HELD CURRENT. Fifth denominator, not a rounding of 13.6 / 54.55 / 77.3.

Worktree #460 against live jsonl: held **17 CURRENT / 5 THIN / 77.3% substantive**.

---

**Fix status (origin/main, not the pin):**
| P0 | Status |
|---|---|
| Process `_CACHE` vs jsonl mtime (metrics 3 vs list 22 CURRENT) | code on this branch |
| `thesis_summary[:400]` / history `[:300]` | code on this branch |
| `substantive_pct` + THIN vs CURRENT in universe API/UI | code on this branch |
| Operator-facing `DATA_UNAVAILABLE` as thesis body | code on this branch |
| `daily_thesis_changes` rendered | code on this branch |
| SCHD weight 16.84 vs 17.95; TRIM MV vs notional; V $0 | still live on pin; not in this PR (decision/home builders) |
| Sector `current_pct` all null | still live on pin |
| Report 100% traceability with 32/65 fields | still live on pin |
| Investment-product `what_changed.material=false` after remint | still live on pin |
| NOC price above zone labeled in-zone | still live on pin |

---

## C — tonight, labeled (two stores, three numbers)

| Surface | Number | What it actually is |
|---|---|---|
| Live `cio_theses.jsonl` (inode 3064869, shared pin↔rebuild) | **16 CURRENT / 5 THIN / 1 unset** of 22 holdings | `payload.mint_state`. THIN = JEPI, QCOM, SCHG, XAR, XLB. ARKX `mint_state` unset. NOC/PFLT `mint_state=CURRENT`, `summary` **2000 chars** (mint cap), research rec was 2579 / 2064. |
| `/api/v3/cio/universe-theses` **metrics** (live :7777) | **current_thesis=3, coverage_pct=2.4, material=124** | `universe_metrics()` via process `_CACHE` from attach.py. This is **not** 12/22 and **not** 17/22. `substantive_pct` is **absent**. |
| Same endpoint **symbols[]** list | **22/22 HELD = CURRENT** (NOC `symbol_noc@v3`) | `build_coverage_report()` uncached. Contradicts metrics on the same JSON. |
| `/api/v3/cio/symbol-thesis/NOC` (live :7777) | **RESEARCH_REQUIRED** + `DATA_UNAVAILABLE — no living symbol thesis` | Same `_CACHE`. Card does not read the 2000-char living summary. |
| Fresh pin-module (no cache, not what :7777 serves) | metrics **71/120 = 59.2% coverage**; NOC card **CURRENT** but `core_thesis` **[:400]** | `classify_symbol` hard-truncates `thesis_summary` to 400. Still not 2579. Still no `substantive_pct`. Still no THIN. |
| `thesis_change_cards.jsonl` | **735 cards** | **Not read by any CC v3 tab.** `daily_thesis_changes` is in the universe-theses JSON and **is not rendered**. Investment-product `what_changed.material=false, items=[]` after tonight’s remint. |

**Does the page show `substantive_pct`?** No. Coverage only (`coverage_pct` 2.4). That is the fake-green M1 was built to prevent, inverted: the list is all-green CURRENT while the quality grade (THIN) and substantive_pct are invisible.

**THIN vs CURRENT visually distinct?** No. UI has one badge `thesis_state` (coverage_state). JEPI/QCOM/SCHG/XAR/XLB render identically to NOC/PFLT.

**Live 12/22 vs dry-run 17/22?** The page shows **neither**. Live store tonight is **16/22 CURRENT + 5 THIN**. The page shows **3 (stale cache metric)** and **22/22 CURRENT (list)**.

**Full untruncated thesis?** No. Live JSONL summary is already 2000 (not 2579). The serving API returns DATA_UNAVAILABLE. Even a cache-flush would serve **[:400]**. History rows are `summary[:300]`.

**94 thesis_change_cards in the UI?** No. 735 exist on disk. Zero tabs render them.

---

## Tab 1 — Advisory Desk (`/v3/advisory`)

**Purpose:** Operator desk of holdings / watch / re-entry / allocation rows with Flash/Pro opinions. Marketed as a desk (Run now, Ack, rate).
**Reads:** `GET /api/v3/advisory` (3.80 MB, 147 rows); class filters `holding|watchlist|watchlist_hub|closed_journal|allocation`; `GET /api/v3/advisory/run-status`. Cache file `data/runtime/advisory_desk_latest.json`.

| Checklist | Result | Evidence |
|---|---|---|
| A DATA_UNAVAILABLE as user text | **FAIL** | 4,894 occurrences in JSON; 318 field_state nodes on 137/147 rows. `FieldStateView` maps state `DATA_UNAVAILABLE` to `reason` or the string **“data unavailable”**. Expanded Memory/Analyst cards print `unavailable`. |
| A Internal IDs | **FAIL** | User-facing Pro synthesis contains `ALLOC:cash:schwab_rollover_ira`, `ALLOC:equity`, `ALLOC:alternatives`. Expanded Evidence lists `hermes_health`, `ticker_enrichment_cache`, `agent_opinion: risk_agent`, `agent_opinion: tax_agent`. `row_id` is machine form. |
| A Placeholder `?` / Zone ?–? | **FAIL (once is enough)** | 5 closed_journal rows `MISSING PLAN` have `entry_zone_display: null` → UI **“unavailable”**. 10 `MISSING MARKET` have price null. Not the literal `Zone ?–?` string in this snapshot; the empty zone still renders. |
| A Raw float precision | **FAIL in payload / mostly hidden in UI** | `current_mark: 34.520012121701086` (SCHD taxable). UI uses `*_display` / `fmtPrice` so the table shows `$34.52`. Payload still ships the lie-precision. Weighted avg basis `$31` via `fmtUSD` **toFixed(0)** — $31 not $31.21. |
| A None / null / NaN | **FAIL in payload** | 33,122 `null`. 329 field_states `display: "None"` (all on DU/NA states; UI maps those). No user-facing `NaN` this snapshot. |
| A Unrendered markdown / raw HTML | **PASS this snapshot** | Synthesis is a plain paragraph. |
| A Stale timestamp, no age | **FAIL** | Stamp row *has* age (PRICES EXPIRED 2026-08-21 16:45 · 3.0d). **Contradiction:** header `FACTS AS OF CURRENT` / `cache 46s CURRENT` while `HOLDINGS_SOURCE_FRESHNESS=EXPIRED` and banner DESK_STALE. Expanded “As of 2026-08-14” on the mark has **no age**. Flash/Pro **EXPIRED 3.0d** labeled PRIOR SYNTHESIS. |
| B R:R 0.0:1 | **PASS this snapshot** | No `0.0:1`. NOC reentry why includes `R:R 2.55`. |
| B Invalidation below price on longs | **INCONCLUSIVE / related FAIL** | 25 RE_ENTER rows have zones. NOC (held) stop $528 < price $551 (correct direction). 5 MISSING PLAN + 10 MISSING MARKET have no invalidation at all. |
| B Sized $ without capital context | **FAIL** | Telegram brief: `SCHD TRIM $216,111` — that is **market value**, not trim size. Rollover SCHD MV $216,110.86; CIO NOW trim −$48,113. Two different dollars for the same TRIM. `cash_free_unearmarked_usd=0`. Investable $321,391 is earmarked-aware on Capital Plan, **not attached to the TRIM row**. |
| B Percentages / weights ≠ 100 | **WARN** | Banner `PLAUSIBILITY_OK` “weight sum within bounds”. Not shown as a 100% stack on this tab. |
| B Quote from failed feed | **FAIL** | `price_clock.reprice_source=finviz_afterhours`, freshness EXPIRED, age 98,574s. Holdings `canonical_price_key: finviz`, `external_quote_stale_vs_session: true`. 13-row DATA_CONFLICT (PFLT, NOC, RTX, LDOS, SPCX, BAH, CSWC, V, …). No literal `Quote: alpaca ❌` this snapshot; `alpaca_taxable_live` appears as a cash **account**, not a failed quote. |
| C substantive_pct | **FAIL** | Not on this page. |
| C THIN vs CURRENT | **FAIL** | Not on this page. |
| C live 16/22 vs 17/22 vs 12/22 | **FAIL** | Desk does not show mint quality. |
| C untruncated thesis | **FAIL** | Advisory `why_call` is a one-liner (`Held 194 days`). No living thesis body. |
| C 94/735 change cards | **FAIL** | Absent. |
| D What can I do / what writes | Ack / Snooze / Useful / `Not useful · DISAGREE_THESIS` → `POST /api/v3/advisory/{ack,snooze,rate}`. Run now → `POST /api/v3/advisory/run-now` (rebuilds Flash/Pro, **does not refresh quotes/technicals** — page even says this). Drill opens the drawer. **No Agree/Need-data/Dismiss on the desk row** (those exist only on the CIO thesis card). Feedback journal on disk: **1 test row** (`UBER` DEFER, `otf_2b71dde9966c46a7`). |
| D Dead controls | Run now is wired (202 status). Last successful run **2026-08-19 23:39Z**. Class buttons `watch` / `reentry` are **wrong names** (API 17 KB stub vs real `watchlist`/`closed_journal`). |
| D Read-only dressed as desk | **FAIL** | “Run now”, Ack, rate. Promotion `NOT_PROMOTED`. Authority READ_ONLY_ADVISORY. |
| E 09:15 emit-zero | **FAIL (the emit gap, visible)** | Schedule chip: **Mon 2026-08-24 09:15 EDT**. Cadence weekdays 09:15. Last run **Fri 8/19**. Page still shows 147 rows + PRIOR SYNTHESIS. systemd `tradeai-advisory-shadow-session.timer` has `AGENT_DECISION_PAYLOAD=1` but drop-in says **“Shadow session does not yet call emit_decision_payload (B.2)”**. Log: `live=False`. **Zero `DecisionPayload` files** under rebuild `data/`. Advisory notif broker writes SHADOW DIGEST fingerprints, not DecisionPayload@v1. |
| E Steph | **Not a tab here.** Synthesis mentions no Steph. `tax_agent` / `risk_agent` appear as evidence domain strings. |
| E Guardian / Ledger / Morgan as empty tabs | **Not tabs on this page.** |

**Defect count (this tab): 18 FAIL + 1 WARN.** Screenshot: `screenshots/01-advisory-desk.png`.

---

## Tab 2 — CIO NOW (`/v3/cio?tab=cio-now`)

**Purpose:** Decision-first office home. “What needs a decision.”
**Reads:** `GET /api/v3/cio/home` → `cio_now.decisions` (5 shown of 7); `GET /api/v3/cio/dispositions`.

| Checklist | Result | Evidence |
|---|---|---|
| A DATA_UNAVAILABLE | **FAIL** | Freshness board qualities include `DATA_UNAVAILABLE` for thesis, hermes, analyst, sector, technical, research, tax. Card line **“Why? evidence”** is a placeholder, not a thesis. |
| A Internal IDs | **FAIL** | Every card: `ID dec_c3c9ef4b1402` (`shortDecisionId` still prefix `dec_`). Notification suppression shows `dec_c3c9ef4b14020eb5` in JSON. |
| A Zone ? | n/a this tab | |
| A Raw floats | **FAIL** | `recommended_delta_usd: -48113.3` (one decimal). UI `$48K` (fmtUsd thousands, **toFixed(0)**). |
| A None/null | **FAIL** | `Why? evidence` ; target weight 14.2% vs current 17.9% with stale quote. |
| A Markdown/HTML | PASS | |
| A Stale ts no age | **FAIL** | Freshness text `quote: stale · market value: stale` with **no as-of clock** on the card. Holdings source 2026-08-21 20:45Z. |
| B R:R 0.0:1 | n/a | |
| B Invalidation inverted | n/a | |
| B Sized $ w/o capital | **FAIL P0** | SCHD **−$48K** on the card. Capital Plan investable is $321K / free unearmarked **$0**, not shown here. V TRIM **+$0 / recommended $0** while advisory TRIM and a “scenario trim would be $12,308”. SPCX TRIM $0 vs scenario $2,737. |
| B % don’t sum | **FAIL** | SCHD current weight **17.9%** here vs advisory **16.84%** vs concentration `top_weight_pct: 17.95`. Three numbers. |
| B Failed-feed quote | **FAIL** | `quote.pass=false quality=STALE source=finviz`. Action still sized. Schwab token revoked in heartbeat. |
| C substantive / THIN / 16/22 / full thesis / cards | **FAIL all** | `why_now: "Advisory TRIM — SCHD"`. No thesis body. Thesis quality DATA_UNAVAILABLE on the freshness board **while jsonl has symbol_schd@v3 CURRENT**. |
| D Actions / writes | ACK/DEFER/DONE/REJECT/RATE → `POST /api/v3/cio/decision/{decision_id}/disposition`. Writes `decision_dispositions.jsonl`. Live map has **1** SCHD reject (`dec_5866156741de9046`, 2026-08-15) which is **not** the current `dec_c3c9ef4b14020eb5`. Learning cannot start on tonight’s decisions. |
| D Dead | Buttons are wired; they write a different decision_id than the card if the operator’s last click was the Aug 15 id. |
| D Read-only as desk | Disposition chrome present. Correctly READ_ONLY. |

**Defect count: 14 FAIL.** Screenshot: `screenshots/02-cio-now.png` (worst: SCHD −$48K + V +$0).

---

## Tab 3 — UNIVERSE & THESES

**Purpose:** Living theses for the material universe.
**Reads:** `/api/v3/cio/universe-theses`, `/api/v3/cio/agent-research-ops`, on click `/api/v3/cio/symbol-thesis/{SYM}` + `/api/v3/cio/intelligence/{SYM}`. Feedback POST `/api/v3/cio/intelligence/{SYM}/feedback`.

| Checklist | Result | Evidence |
|---|---|---|
| A DATA_UNAVAILABLE | **FAIL P0** | NOC card **CASE: `DATA_UNAVAILABLE — no living symbol thesis`**. WHY OWN: `DATA_UNAVAILABLE`. Same for PFLT API. Intelligence `thesis.summary: DATA_UNAVAILABLE`. |
| A Internal IDs | **FAIL** | `symbol_noc` next to the ticker. History `vsymbol_noc@v3`. Queue request_ids `str_20bafc14c0b95e2f` in ask-thesis JSON (not on card). |
| A Zone ? | **FAIL-adjacent** | Technical summary `Zone 540 → 550` with **price 551.11 above the zone high**. Intelligence still says “+0.2% from the entry zone”. |
| A Raw floats | **FAIL** | `Price 551.11` unrounded from 551.11. RSI 46.5. |
| A None/null | **FAIL** | COUNTER `—`, CIO ACTION `—`, NEXT REVIEW `—`. `thesis_version: null` on the card API while list shows `@v3`. |
| A Markdown | PASS | |
| A Stale ts | **FAIL** | History dates `2026-08-22` with no time/age. Intelligence as_of is now. Ops strip **Oldest queued 2026-08-18 06:30** with no age chip. |
| B R:R | Technical has Stop 528 Target 610 Price 551 → true R:R ≈ 2.56, **not displayed**. | |
| B Invalidation | Stop 528 < 551 on a long — direction OK. Zone high 550 < price — “in zone” copy is wrong. | |
| B Sized $ | n/a | |
| B % | Metrics **Coverage 2.4** next to a list of 22/22 CURRENT. **P0 wrong number.** Material 124 vs Current thesis 3 vs Research required 121 (3+121=124; the 22 CURRENT holdings are not in that 3). |
| B Failed quote | Technical price 551.11 with no source/as-of on the card. | |
| C substantive_pct | **FAIL** | Metric is `coverage_pct` only. |
| C THIN vs CURRENT | **FAIL** | JEPI/QCOM/SCHG/XAR/XLB = CURRENT in the list, THIN in jsonl. Identical chrome. |
| C live vs dry-run | **FAIL** | Page is **stale process cache (3)** + **uncached list (22 CURRENT)** + **live store 16/22+5 THIN**. Not labeled. |
| C untruncated thesis | **FAIL P0** | Card shows the stub/unavailable, not 2579/2000. Code path even when cache-fresh is `[:400]`. |
| C 735 cards | **FAIL** | `daily_thesis_changes` in JSON (NEW 6, RESEARCH_REQUIRED 341). **UI never renders it.** |
| D Actions / writes | Agree/Disagree/Interested/Defer/Need data/Dismiss → POST feedback `channel=command_center`. **This is the only disposition control that matches the journal schema.** Journal still has **1 UBER test row**. Fail-soft: `if (!r.ok) return` with **no error toast**. |
| D Dead | Feedback can no-op silently. Research ops is read-only. |
| D | Strip “Intelligence engine ops. Advisory only.” Honest. Card is dressed as a living thesis and is not. |

**Defect count: 16 FAIL.** Screenshot: `screenshots/03b-noc-thesis-card.png` + `03-universe-theses-noc.png`.

Ops strip extras (same tab): Queued **1195**, completed today **0**, failed today **4** `LLM_ERROR`, Maria queued **947**, **Steph queued 108**, risk_agent 114 — while Agents catalog says Steph DESIGNED/disabled.

---

## Tab 4 — INVESTMENT BOOKS

**Purpose:** Four canonical CIO books (temperament / reentry / opportunity / action).
**Reads:** `GET /api/v3/cio/investment-product` (product_id `prod_fe9f117a83f8b9ff`, trigger RESEARCH_COMPLETED, as_of 2026-08-22T23:01Z).

| Checklist | Result | Evidence |
|---|---|---|
| A DATA_UNAVAILABLE | **FAIL** | `CURRENT_HOLDINGS_THESIS` `why_still_held: DATA_UNAVAILABLE` for AMANX/ARKX **and** CUSIPs, even when `thesis_state: CURRENT`. Reentry note literally contains the token `DATA_UNAVAILABLE`. UI prints `r.why ?? r.why_still_held`. |
| A Internal IDs | **FAIL** | Product IDs behind `<details>`: `prod_fe9f117a83f8b9ff`. `run_id` in JSON. |
| A Zone ? | Zone strings like `Zone 79.15–98.94` on RKLB WATCH_CLOSELY (numeric, not `?`). |
| A Raw floats | Present in JSON. |
| A None | `governed_verdict: null` on **all 63** reentry names → table column **—**. |
| A Markdown | PASS | |
| A Stale ts | product as_of 23:01Z, no age on the tab. |
| B R:R 0.0:1 | PASS this snapshot | |
| B Invalidation | AVOID AXTI `Signal ABOVE_ZONE; 440.98% vs exit` — percent vs exit not invalidation vs price. |
| B Sized $ | CASH HOLD_CASH_FOR has no dollar. |
| B % | n/a | |
| B Quotes | Desk statuses IN_ZONE/NEAR without quote health. |
| C What changed tonight | **FAIL P0** | UI: `trigger RESEARCH_COMPLETED · no material investment change` and items `—`. Tonight reminted 22 holdings + 735 cards. `thesis_changes_today` is **in the JSON and not rendered**. |
| C THIN | CURRENT_HOLDINGS_THESIS uses coverage_state, not mint_state. |
| C thesis body | Only `why_still_held` which is DATA_UNAVAILABLE. |
| C cards | Not shown. |
| D Actions | **None.** Show-all reentry names is a local `useState`. Read-only report dressed as books. |
| D Dead | none | |

**Defect count: 8 FAIL.**

---

## Tab 5 — CAPITAL PLAN

**Purpose:** Cash sources/uses, deploy vs investable.
**Reads:** `home.capital_plan`.

| Checklist | Result | Evidence |
|---|---|---|
| A DATA_UNAVAILABLE | PASS this tab | |
| A Internal IDs | JSON keys `total_prospective_raise_usd` not shown. |
| A Floats | UI `$321K` / `$355K` rounding. Payload 321391.0, 355230.55. |
| A Stale | No as-of on the six stat tiles (home as_of is in the hub subtitle). |
| B Sized $ vs capital | **This tab IS the capital context** — but CIO NOW / Advisory TRIM do not link here. |
| B % | Post-plan cash 20.0% vs band 20–25%. Resulting cash $257K = reserve. |
| B Double-count visual | **FAIL** | Uses: New positions **$320K** and Fundable deploy request **$320K** as separate lines; Total deploy **$448K** = 320+128. Footnote explains; the table still lists $320 twice. |
| D Actions | **None.** Read-only. |
| Deploy exceeds investable | Honest banner: $355,231 vs $321,391 by $33,840 funded only by prospective raise. |

**Defect count: 3 FAIL.** Screenshot: `screenshots/05-capital-plan.png`.

---

## Tab 6 — PORTFOLIO POSTURE

**Purpose:** Thesis, concentration, sector tilts, performance, tax.
**Reads:** `home.posture`.

| Checklist | Result | Evidence |
|---|---|---|
| A DATA_UNAVAILABLE | Sector `current_pct: null` on **all 7 tilts** → UI `fmtPct(null)` = **—**. |
| A Internal IDs | Constraint codes `cash_band_min_pct: 20.0` shown via `cioLabel`. |
| B % don’t sum | **FAIL P0** | 7 sector rows, current all null, **sum 0**. Targets 5+8+10+3+6+5+3=40, not 100. `sector_target_honesty.all_targets_placeholder=false` (claims they are real). |
| B Concentration | SCHD 17.95% vs fire 16.5 vs policy 12 — three thresholds, no link to the −$48K card. |
| C thesis | Desk OS blurb (“Mature desk OS … defensive_observe”), **not** the living symbol theses. |
| D Actions | **None.** Read-only. |

**Defect count: 4 FAIL.**

---

## Tab 7 — OPPORTUNITIES

**Purpose:** Watch / reentry / rotation chips + YouTube queue.
**Reads:** `home.opportunities`; `GET /api/v2/cio/youtube-research-queue`.

| Checklist | Result | Evidence |
|---|---|---|
| A | Watch chips include **AMANX/DXCM/SCHD/SPCX/V as “Trim”** sourced from advisory — those are **holdings**, not watch candidates. |
| B | Reentry chips labeled **signal: Hold** for READY/NEAR names (`Re-entry READY TO REVIEW — AVAV`). |
| C | `research_gaps: []` → UI “None.” Universe tab says 121 research required. |
| D | YouTube queue `count: 0` “queue not built yet”. No actions. Read-only. |
| D Dead | YouTube panel is empty, not 404. |

**Defect count: 4 FAIL.**

---

## Tab 8 — REPORT

**Purpose:** Institutional report coverage + Generate now.
**Reads:** `home.report`; Generate → `GET /api/v2/cio/report-v2`.

| Checklist | Result | Evidence |
|---|---|---|
| A | `render_errors: ["pdf renderer unavailable in this environment"]` shown in amber. |
| A Internal | source SHA behind details. |
| B | Fields **32/65**, unavailable 4, quality flags 30, traceability **100%**. 100% traceability with 32/65 fields is a **green lie**. |
| D | **Generate now** is a real GET. No disposition. |

**Defect count: 2 FAIL.**

---

## Tab 9 — EVIDENCE / AUDIT

**Purpose:** Provenance, hashes, run IDs, internal codes. (This tab is *supposed* to leak machine tokens.)
**Reads:** `home.evidence`.

| Checklist | Result | Evidence |
|---|---|---|
| A Internal IDs | **By design** `run_ids` `0000178744…`, `hb-264ac2630b23`, SHA-256. Collapsed. |
| A | `report_id: null`. Run ids `ts: null`. |
| C | `source_refs` include `cio_theses_projection.json` sha — not the jsonl living store. |
| D | **None.** Link to Advisory / Agents / System. Read-only and labeled as such. |

**Defect count: 2 FAIL (null timestamps; projection vs jsonl).** Not P0 — this is the audit drawer.

---

## Tab 10 — NOTIFICATION GATE

**Purpose:** IMMEDIATE / DIGEST / CC_ONLY / SUPPRESSED lineages.
**Reads:** `/api/v3/maturity/notification-gate`, `/api/v3/maturity/heartbeat`.

| Checklist | Result | Evidence |
|---|---|---|
| A Internal IDs | **FAIL** | Table columns: `decision_lineage_id` `cash_posture:CASH`, `freshness:BOOK`, `position:ACHV:RESEARCH`; `dedupe_state: ntf_776de03bf16113f7159d2760`; generation hashes. |
| A | 134 lineages, 2,678 audit rows. Scanner: scans 119, immediate **0**, suppressed **357**, last Telegram 2026-08-22 16:15Z. Silence copy is honest. |
| D | **None.** Read-only. |

**Defect count: 1 FAIL (ID leak in the operator table).**

---

## Tab 11 — TELEGRAM RECEIPTS

**Purpose:** Prove what was actually sent.
**Reads:** `/api/v3/maturity/telegram-receipts`.

| Checklist | Result | Evidence |
|---|---|---|
| A Internal IDs | **FAIL** | `dedupe_key: ntf_prod_5a1f55eb5253394d` (`prod_` leak). message_id 295. |
| A | `delivery_mode: PREPARE_ONLY` but `dedicated_cio_delivered: true` and last success 16:15Z. Copy explains the paradox. `credentials_ready: false` vs delivered true. |
| D | **None.** Read-only. Honest empty-vs-receipts. |

**Defect count: 2 FAIL.**

---

## Tab 12 — SENSES EVIDENCE

**Purpose:** Financial Senses receipts. Shadow-only.
**Reads:** `/api/v3/maturity/senses`.

| Checklist | Result | Evidence |
|---|---|---|
| A | `lesson: null`. Heartbeat senses `EXPECTED_IDLE`, receipts 0 today. |
| D | **None.** |

**Defect count: 1 FAIL (idle not labeled as a report).**

---

## Tab 13 — Agents Runtime + Maturity scoreboard (`/v3/agents`)  [E]

**Purpose:** Agent catalog, maturity scoreboard, learning/memory/promotion/cases.
**Reads:** fixture catalog + `/api/v3/maturity/*` (heartbeat, learning, memory, cases, promotions, influence, autonomy-health).

| Agent | Appears? | Lifecycle on scoreboard | Enabled in catalog | Runtime | Lie? |
|---|---|---|---|---|---|
| **Steph** | Yes (scoreboard + catalog) | **SHADOW** | Catalog `DESIGNED` **enabled: false** | NOT RUN; but research-ops **queued 108** | **Yes — three states at once** |
| **Guardian Risk** (`risk_agent`) | Yes | DESIGNED | enabled false | NOT RUN; research-ops queued **114** | Tab for an agent that does not run |
| **Ledger Tax** | **Two rows**: `ledger` and `tax_agent` | DESIGNED / DESIGNED | enabled false | NOT RUN | Duplicate tab + no runtime |
| **Morgan** | **Yes on scoreboard (SHADOW)**; **not** in `AGENT_RUNTIME_CATALOG` (16 canonical) | SHADOW NOT RUN | n/a in catalog | NOT RUN | Scoreboard 21 vs catalog 16 |
| Alex | SHADOW / DESIGNED mixed | NOT RUN | research-ops queued 1 | |
| Maria | DESIGNED in catalog, queued **947** | NOT RUN today (completed_today 0) | |

| Checklist | Result | Evidence |
|---|---|---|
| A Internal IDs | agent_id, memory_id in Memory table (40 rows). |
| C | Scoreboard `0 of 21 eligible`, sample gate **0%**, 17 need attention, as_of **2026-08-12** adapter STALE, source UNAVAILABLE, badge **LIVE** anyway. |
| D Learning | Lessons exist (12 RATIFIED_CONTEXT). Disposition outcomes **3 rows** (ACK/DONE/DEFER from 2026-08-20), `eligible_runs: 0`, MBI=0. Memory control POSTs exist (dispute/retract/expire) and are gated. Promotions `[]`. |
| D Dead | PREVIEW toggle is front-end-only (honest title). Promote/Activate **absent** (good). |
| E | Guardian / Ledger / Morgan / Steph **appear with no runtime**. That is the UI lie. |

**Defect count: 8 FAIL.** Screenshot: `screenshots/04-agents-steph.png`.

---

## Defect totals (do not collapse “once”)

| Tab | FAIL |
|---|---|
| Advisory Desk | 18 |
| CIO NOW | 14 |
| Universe & Theses | 16 |
| Investment Books | 8 |
| Capital Plan | 3 |
| Portfolio Posture | 4 |
| Opportunities | 4 |
| Report | 2 |
| Evidence / Audit | 2 |
| Notification Gate | 1 |
| Telegram Receipts | 2 |
| Senses Evidence | 1 |
| Agents / Maturity | 8 |
| **Total (with dupes across tabs)** | **83** |

Unique P0 number-lies are listed below without collapsing.

---

## Three worst offenders (screenshots)

1. **Universe thesis card for NOC** — list CURRENT / card RESEARCH_REQUIRED / `DATA_UNAVAILABLE — no living symbol thesis` while jsonl has 2000-char CURRENT mint. `screenshots/03b-noc-thesis-card.png`
2. **CIO NOW SCHD −$48K + V TRIM +$0** with `ID dec_…`, DATA CONFLICT, stale finviz, `Why? evidence`. `screenshots/02-cio-now.png`
3. **Advisory Desk emit gap** — 147 rows, PRIOR SYNTHESIS 8/19, next run Mon 09:15, `ALLOC:cash:schwab_rollover_ira` in the prose, FACTS CURRENT vs PRICES EXPIRED. `screenshots/01-advisory-desk.png`

---

## Prioritized fix list (do not implement in this audit)

### P0 — wrong number

1. **Kill attach.py `_CACHE` in the long-lived :7777 process** (or never cache across jsonl mtime). Same page: metrics 3/2.4% vs list 22/22 CURRENT vs card RESEARCH_REQUIRED.
2. **Stop truncating `thesis_summary` to `[:400]`** (`symbol_thesis_coverage.classify_symbol`). Serve the living summary (2000 now; 2579 in research). History `[:300]` same bug class.
3. **Surface `mint_state` THIN vs CURRENT and `substantive_pct`.** Coverage-only is the fake-green. Holdings live **16 CURRENT / 5 THIN**, not 2.4%, not 22/22, not 12/22, not 17/22.
4. **SCHD weight 16.84 vs 17.95 vs 17.9** — one number, one as-of, one account-scope.
5. **SCHD TRIM dollars:** brief uses **MV $216,111**; CIO NOW uses **−$48,113**; advisory why_call has **no dollar**. Pick the trim notional and show investable/free next to it. Free unearmarked is $0.
6. **V (and SPCX) TRIM recommended_delta_usd = 0.0** while the card is a Trim and a scenario trim exists ($12,308 / $2,737). This is the R:R 0.0:1 class: a computed zero that is not the truth.
7. **Sector tilt current_pct all null (sum 0)** while honesty says targets are real.
8. **Report traceability 100% with 32/65 fields.**
9. **Investment-product `what_changed.material=false`** the same night 22 holdings were reminted.
10. **NOC “in zone” copy while price 551.11 > zone high 550.**

### P1 — machine tokens in operator chrome

1. Do not render the string `DATA_UNAVAILABLE` in CASE / WHY OWN / why_still_held. Map to “No living thesis” **and** fail the quality gate — never as the thesis body.
2. Stop showing `dec_…` / `prod_…` / `symbol_noc` / `ALLOC:cash:schwab_rollover_ira` / `ntf_prod_…` outside Evidence/Audit.
3. Evidence domain ids (`hermes_health`, `ticker_enrichment_cache`) on the Advisory expand.
4. Notification-gate table of raw lineage ids.
5. Agents scoreboard vs catalog vs research-ops queue (Steph SHADOW / DESIGNED / 108 queued).
6. Feedback fail-soft with no toast; journal still 1 UBER test row.
7. `FieldStateView` fallback “data unavailable” is still the token.

### P2 — cosmetics / labeling

1. Advisory `fmtUSD` toFixed(0) on sub-$1k basis.
2. Uses-of-funds lists $320K twice.
3. Opportunities chips calling holdings “watch”.
4. Reentry governed_verdict column all em-dashes.
5. Senses / Opportunities / Posture / Capital Plan are read-only reports; say so in the tab label.
6. SPA shell HTML is not the desk — any scraper that curls `/v3/advisory` without JS will lie.

---

## Explicit emit-gap (Advisory E)

```
AGENT_DECISION_PAYLOAD=1          # drop-in 30-decision-payload.conf
# "Shadow session does not yet call emit_decision_payload (B.2)"
advisory_shadow_session.log       live=False  last 2026-08-21
run_now last finished             2026-08-19T23:39:35Z
next_run_et                       Mon 2026-08-24 09:15 EDT
page content                      147 rows + PRIOR SYNTHESIS
DecisionPayload files             0
```

The screenshot of 147 rows with a 09:15 chip and an Aug 19 synthesis **is** the emit gap made visible.
