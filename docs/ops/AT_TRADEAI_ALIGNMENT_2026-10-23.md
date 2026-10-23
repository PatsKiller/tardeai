# Active Trader ↔ Trade AI alignment — 2026-10-23

**Asked by the operator, 08:54 ET:** "validate the active trader and also trade AI are aligned."

**Evidence.** All of it was read-only and taken during the session. I made GETs against the served build
(0f5bf2453, `127.0.0.1:7777`) at about 08:58–09:00 ET:

- `/api/v2/trade-ai/scanner`
- `/api/v2/trade-ai/summary`
- `/api/v3/active-trader/alerts?limit=300`

I also read:

- the tail of the AT journal (`persistent-state/data/active_trader/momentum_alerts.jsonl`);
- today's Hermes scalp research (`persistent-state/data/hermes/momentum_catalysts/2026-10-23_catalysts.jsonl`);
- the 08:55 Finviz raw CSV (`data/raw/finviz/2026-10-23/0700/watchlist_setups_20261023_085511.csv`).

**Sample.** SAIQ, plus AARD, BKYI, YMAT, TANH and GIXI. All 14 symbols on today's AT watch also appear in the Trade AI
scanner universe.

**Verdict key.**

| Verdict | Meaning |
|---|---|
| ALIGNED | Same source, same definition and same time, or a difference that is labelled. |
| TIMING ONLY | Same definition, different observation time. The fix is an as-of label. |
| MISMATCH (bug) | Different definition or meaning presented as the same thing, or one surface wrong. |

## Field by field

| Field | Active Trader (alert / journal) | Trade AI (Opportunities row) | Same source? | Same definition? | Same time? | Verdict | Fix |
|---|---|---|---|---|---|---|---|
| **Catalyst** | The `catalyst_line` order is scan headline → Hermes → "none found". The premarket path passes `trade_ai=None`, so it went straight to Hermes: "none found (Hermes researched 08:25 — no clear catalyst)". The evidence appendix said "Verified catalyst: FAILED" (from the Trade AI row's `catalyst_verified=false`). | It printed the scan headline (`yahoo_finance`, `catalyst_verified=false`, confidence 0.0) as THE catalyst. The verification status appeared only in the side panel's "Scanner facts". | Partly. Both read the same scan row, and AT also reads Hermes. | **No.** AT treats an unverified headline as no catalyst. Trade AI presented it as the catalyst. | Scan 08:52 / Hermes 08:25 | **MISMATCH (bug)** | One shared verdict, `catalyst_verdict` (#1989). The page shows an `UNVERIFIED` badge and the reason, with Hermes's verdict and time (this PR). The AT line now prints `catalyst: UNVERIFIED headline — …` (#1991). |
| Catalyst, AARD | (same path) | `catalyst_verified=true`, confidence 1.0, but there is no URL, publication time or method. Hermes "found" *"Archrock Announces Timing for Third Quarter 2026 Results"*, which is a different company. | — | — | — | **MISMATCH (data quality)** | The shared verdict treats a verified flag without proof as an unverified headline. Hermes symbol confusion is a P2 finding, listed below. |
| **Ready / missing** | Evidence appendix: "Momentum evidence 4/5 … Verified catalyst: FAILED". | No readiness verdict at all. The Gate 2 placeholders read "not computed". | Same evidence builder (`build_setup_evidence`) | Yes | — | **MISMATCH (missing on one surface)** | `SetupReadiness@v1` is served on scanner rows and in the projection (#1989). The page has a "Driven by · ready?" block and a `not ready · 4/5` cell (this PR). AT and unified alerts print the same two lines (#1989 / #1991). |
| **Change % / gap** | `gap_pct` 21.76 = last 6.77 against moomoo `prev_close` **5.56**. The appendix "gap PASSED 24.22" comes from the Trade AI row. | Chg +25.76 % (Finviz `Change`). Gap 24.22 % (Finviz `Gap`). That implies a Finviz prior close of about **5.28**. | **No.** moomoo snapshot vs Finviz. | **No.** "Gap" means last vs prev close on AT, open vs prev close on Finviz. "Change" is Finviz's own. The two prior closes differ by 5 %. | 09:00 vs 08:52–08:55 | **MISMATCH (definition + data)** | Labels are proposed below (P3). The 5.56 vs 5.28 prior close needs an operator/data check, because one feed is wrong or adjusted. |
| **RVOL** | The AT journal `rvol` is `null` on premarket rows. The Telegram "RVOL 12.35" came from the Trade AI row via the appendix, at an earlier scan. | `rvol` 12.84 (Finviz Relative Volume at 08:52). The 08:55 CSV says 13.12. | Same (Finviz) | Yes | Scan time differs | **TIMING ONLY** | As-of labels: the run finished time and age (#1990). The appendix value has no time of its own (P3). |
| **Float** | `float_mm` 2.21 | `float_m` 2.21 | Same for SAIQ, TANH, AARD, BKYI and YMAT | Yes | — | **ALIGNED** for 5/6. **GIXI: AT 0.874M vs TA 2.49M**; XRPN: 17.74 vs 15.5 | Report only. GIXI and XRPN floats disagree between the AT candidate and the scan (P2 data finding). |
| **Price / last** | 6.73 (08:55) / 6.77 (09:00), moomoo | 6.64 (08:52 row), Finviz | No | Yes | Different | **TIMING ONLY** | As-of (#1990). |
| **L2** | moomoo 10 levels, spread 14.9 bps, depth ratio 0.191 (ask-heavy), `signals: null` on premarket rows | "L2 veto · 0/5" | Same AT row | **No.** "veto" was AT's whole verdict (`BELOW_PM_VWAP`, `L2_ASK_HEAVY`), not an L2 verdict. The denominator was always 5 even though premarket rows compute only spread and depth. | Same | **MISMATCH (label)** | The table now reads `AT veto · L2 1/2`, with the veto reasons, the time and the computed signals in the tooltip. The panel reads `AT veto` and "1 of 2 computed entry signals lit (5 defined)" (this PR). |
| **Tape** | "tape 94% buys". The journal shows `tape.age_s ≈ 60,900` on **every** premarket row: the prior session's prints. `TAPE_SELLERS` vetoed AARD, BKYI, YMAT, TANH, MEDS and XRPN on that stale tape. | Not shown | — | — | **17 h stale** | **MISMATCH (bug, AT)** | `tape_evidence`: stale tape has no `buy_ratio` (#1991, grant e88bf21e). |
| **Decision vocabulary** | `PREMARKET_WATCH` + `VETO`/`ALERT`. `⚠️ UNVALIDATED` means the same-symbol evidence is below 5/5. | `MANUAL` (`MANUAL_REVIEW`: high-RVOL runner, Entry Desk only, `not_validation_ready`) | No | Different axes: the scanner's route vs AT's verdict vs evidence readiness | — | **MISMATCH (label)** | The MANUAL tooltip now names the meaning and points to the shared ready/not-ready verdict, and the cell shows `not ready · 4/5` (this PR). |
| **Setups counts** | — | Header "SETUPS · LATEST RUN 0 GO · 0 WAIT · 7 NOGO" (latest run, 17 scanned) vs page tiles "0 GO · 19 WAIT · 71 MANUAL REVIEW" (today's universe, 110 rows) | Same payload | **No.** Latest run vs whole-day universe. | Same | **MISMATCH (label)** | Both are named and tooltipped (#1990). |
| **Run time** | Premarket watch every 5 min (`*/5 6-9`) | "7:00 AM slot", but slot 0700 was re-run at 08:02, 08:21, 08:35 and 08:52 | — | — | The label hid the real time | **MISMATCH (label)** | The run line and header show the finished time and age, red after 10 min in the 06:00–12:00 window (#1990). Cadence is covered in #1992. |

Other sample rows, at 08:52 TA and 08:55 AT:

| Symbol | Float AT / TA | Catalyst (TA row) | AT veto reasons |
|---|---|---|---|
| AARD | 12.82 / 12.82 | Yahoo headline (`catalyst_verified=true`, no proof) | `GAP_SMALL`, `BELOW_PM_VWAP`, `TAPE_SELLERS` (stale tape) |
| BKYI | 1.91 / 1.91 | Yahoo, not verified | `BELOW_PM_VWAP`, `L2_ASK_HEAVY`, `TAPE_SELLERS` (stale tape) |
| YMAT | 1.58 / 1.58 | Yahoo, not verified. Hermes "FOUND" a nfl.com "ALL NEWS" page | `BELOW_PM_VWAP`, `TAPE_SELLERS` (stale tape) |
| TANH | 0.67 / 0.67 | None. Hermes: no clear catalyst | `BELOW_PM_VWAP`, `SPREAD_WIDE`, `L2_ASK_HEAVY`, `TAPE_SELLERS` (stale tape) |
| GIXI | **0.874 / 2.49** | `premarket_social`, not verified | `GAP_SMALL`, `PM_VOLUME_THIN`, … |

## PRs

| Area | PR |
|---|---|
| Portfolio strip restored on `/trading` and `/active-trader` | #1988 |
| Run finished time and age; latest run vs universe labels | #1990 |
| Shared `SetupReadiness@v1` (driven by / ready / missing) on the API, projection and Gate 4 alert | #1989 |
| AT alert: readiness lines, labelled headline, stale tape (stacked on #1989) | #1991 |
| Scalp cadence wiring | #1992 |
| Trade AI catalyst verdict, readiness block and AT/L2 label, plus this document | this PR |

## Open for the operator

1. **Prior close disagrees.** SAIQ shows 5.56 on moomoo (AT) and about 5.28 on Finviz (Trade AI). Every AT gap
   and Trade AI change % for the symbol differs by that much. Someone needs to decide which feed is the reference.
2. **Hermes record quality.** AARD resolved to an Archrock (AROC) headline, and YMAT and INVE resolved to a
   nfl.com "ALL NEWS" page, all marked `FOUND`. The shared verdict never treats a Hermes-only catalyst as
   verified, but the records are wrong (P2).
3. **Float disagreements.** GIXI and XRPN floats differ between the AT candidate and the scan (P2).
4. **Focus list.** The operator asked to critique only the top 20 and rotate names in and out. The page should
   lead with the focus list once `feat/premarket-1min-threaded-20261023` serves it; the contract is proposed in
   that branch's thread. Nothing in this PR ranks or critiques.
5. **Premarket catalyst line.** `premarket_watch.py` passes `trade_ai=None` to `catalyst_line`, so the premarket
   heads-up never mentions the scan's (unverified) headline. Its owner is the premarket branch, which is outside
   grant e88bf21e.

## P3 mockups (not built)

- Label "Gap (vs prev close, moomoo)" against "Chg (Finviz)" on both surfaces, and show the prior close used.
- Give each appendix fact its own `observed_at` ("RVOL 12.35 @ 08:21 scan").
