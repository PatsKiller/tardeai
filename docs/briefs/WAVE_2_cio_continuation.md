<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# CIO Wave 2 continuation

**Status:** recovered verbatim
**Source:** session transcript, operator message 001

---

Claude Code overnight — CIO WAVE 2 continuation.
You are taking over from Grok Build. READ_ONLY_ADVISORY.
Repo: PatsKiller/tardeai. Host CURRENT:
  /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
Exact-main promote after each slice. Multiple agents OK if files do not overlap.

════════════════════════════════════════
0. FIRST ACTIONS (do these before any new feature)
════════════════════════════════════════
A. git fetch; git log --oneline origin/main -25
   Must see merges for #616 #617 #618 #619 #620 (and earlier #592–#615).
B. Confirm CURRENT pin contains #620. If pin lags: exact-main promote ONLY. No new slice yet.
C. Read ALL of:
   docs/ops/CIO_WAVE2_SCOREBOARD.md
   docs/ops/CIO_PIPELINE_CONDUCTOR_CLOSEOUT_2026-08-28.md
D. Resume cursor = first scoreboard row status != DONE. Expected: 12.
E. Write a short NOW block to the scoreboard if pin/counts drifted.

If any of A–B fail: fix pin, update scoreboard, STOP that issue, then continue.

════════════════════════════════════════
1. WHAT ALREADY SHIPPED — DO NOT REDO
════════════════════════════════════════
WAVE 1 (#592–#611): research attach, CASE_SUMMARY 323 ACTIVE,
earnings/new names/live cash/case_summaries on product, book LABELS not merge,
persist product, expire 267 stale drafts, watch_block_summary, NEW_POSITION_IF thesis,
152 outcome checkpoints, support-only lessons, T/D/A voice, C2 TRIM gate,
C3 ingest quarantine (no history DELETE), C5 QA alert 24h dedupe,
rebalancer flags AVOID (job still runs), subject_guid lookup no noisy mint,
persist ≥1 S3 + skip dup open S1, home 2B+2C, telegram_sent false.

WAVE 2:
00 #612 scoreboard
01 #613 held thesis card 19/19 CURRENT
02 #614 PRIM symbol_prim@v1 from paper-trade/sandbox Hermes 48254
     Gate still skips empty / cost-cap / TRUE broker-exec. Does NOT skip paper-trade.
03 #615 observational S1 cap 5: PFLT SCHG RTX LDOS DIV (SCHG S1 later cancelled)
04 #616 Surface A: SCHG/AXTI/FATN EXITED, FANG UNAVAILABLE. Cancelled
     plan_240454cce9cc (SCHG was dust, not a hold).
05 #617 ready/near symbol lists; live READY=0; fires_s7=false
06 #618 earnings days_to_event + as_of
07 #619 commentary=UNAVAILABLE without transcript; cap 10; no dump
08–11 #620 home.coverage + CioHub card + Surface A reentry overlay
     reentry_total 25 NEAR overlay · surface_a_count 70 · queue 43 · NOT MERGED

Live baseline you must not regress:
  NEW_POSITION_IF NKE/PFSI/PRIM/SH/XLU CURRENT
  earnings 10, commentary UNAVAILABLE
  watch_ready 0, watch_block 26, reentry_near 25
  telegram_sent false, fires_s7 false, MBI=0
  SCHG = EXITED (dust 0.2294 sh / ~$8 / 0.0006%). Operator truth.
  FANG = UNAVAILABLE
  Leftover holds without that cap-5 S1: BAH, CSWC, V, XAR, AMANX

Drive (optional, GitHub is SoT):
  folder 1rRSmvAeO37z2PyyrIYtd2C5ngwHsAIqH
  gog --replace
    md   1kNRoyK_Tq8FNUMxrwjNDRB2AZCqnxj0P
    json 1W04_1pATgfewyf8gp-WVIo8cqc26c4WQ
  MCP cannot write Drive. If gog missing: DRIVE=FAIL, continue.

════════════════════════════════════════
2. RAILS (never break — hard-stop the night)
════════════════════════════════════════
READ_ONLY_ADVISORY. No orders/stops/broker/2FA.
MBI=0. Do not loosen ThesisDecisionGate.
Do not enable situation notify. No new Telegram producer.
Do not build ROTATE-as-action.
Do not merge the two reentry books (A vs B stay labeled and separate).
Do not admit AGENT_COMMITMENT as policy.
Do not call a model from cio_run_worker.
Do not touch stop-management / quote-time / 2FA panel (parallel agent).
Do not DELETE historical ticker_prices.
Do not invent prices or fake theses (PRIM stayed honest; FANG stays UNAVAILABLE).
Do not treat SCHG dust as a hold again.
Do not reopen plan_240454cce9cc.
INTERDICT left as found.
safe_text_edit on CRLF files.

Hard-stop night if: tests red after one retry, /health or /v3/cio not 200,
unexpected Telegram burst, MBI/gate change, broker write, CURRENT pin
does not contain the PR you just merged.

════════════════════════════════════════
3. SLICE PROTOCOL (every NN, including extras)
════════════════════════════════════════
1. persist=False dry on CURRENT data. Print would_* / sample.
2. Unit tests that assert behavior (no source-string-only).
3. scripts/ai_local_acceptance.sh
4. One PR. Merge-commit if house rule. Exact-main promote.
5. Update docs/ops/CIO_WAVE2_SCOREBOARD.md + .json in THAT PR
   (status DONE, PR, sha, 5-line LIVE, rails).
6. Optional gog --replace.
7. If --apply exists: dry first; apply only when samples are right.

Multi-agent: if a target file has uncommitted foreign edits you did not write,
SKIP that file, mark SKIP on scoreboard, continue another slice.
You MAY run non-overlapping slices in parallel (e.g. identity vs earnings
renderer) but never two writers on cio_investment_product.py at once.

════════════════════════════════════════
4. WORK QUEUE — start at 12, keep going
════════════════════════════════════════

BATCH DUST / COVERAGE TRUTH (do these first)
12  CUSIP-only held rows labeled instrument_id, not ticker.
12a DUST POLICY: position with market value below a documented threshold
    (use existing cash/holdings fields; suggest <$50 or weight <0.5% —
    pick one, document it) is DUST_RESIDUAL / EXITED for Surface A and
    holdings_thesis_coverage. SCHG is the fixture. Do NOT delete lots.
    Recalc held_n excluding dust. Dry table before apply.
12b Diagnose home.coverage.with_plan=1 vs hundreds of open plans.
    Fix the COUNTER (open S1/S3/S5/S6 on non-dust held tickers) or
    document why 1 is correct. Do NOT mint 100 plans to pretty the number.
12c Observational S1 for leftover real holds BAH CSWC V XAR AMANX.
    Cap 5. Skip if open S1 exists. Skip CUSIP/CASH/DUST. notify false.

BATCH IDENTITY / GRAPH (original 13–21)
13  Measure % subject_guid on NEW_POSITION_IF / reentry / watch. No mint.
14  Register only HELD (non-dust) + ACTIVE-watch missing from identity.registry.
    Dry would_register. --apply only if < 30.
15  1-hop graph_impact: same-sector HELD neighbors, cap 5, class D.
16  Attach graph_impact to S6 names only (SCHD…).
17  identity_lookup_failed ≠ UNRESOLVED on those rows.
18  Regression: new writes never use ticker as security GUID.
19  research_fail_histogram last 7d (truncated / execution-language / cost-cap / other).
20  Skip enqueue of non-retryable execution-language fails.
21  Truncated fails: at most 1 replay per plan/day via existing worker --max.
    No cap raise. No live Flash spend unless operator already has stub path.

BATCH RESEARCH / MEMORY (22–31)
22  hermes_result_id still set on new complete (unit + optional stub --max 1).
23  CASE_SUMMARY still mints on VALID complete (unit).
24  cio_attach_research_backfill dry would_attach == 0.
25  Product: VALID / PARTIAL / FAIL counts.
26  Document attach rule VALID|PARTIAL in ops note. Do not silently tighten.
27  resolve_due_checkpoints dry on the 152. --apply only held non-dust equities
    with real prices. Skip CASH sleeve. No invented PnL.
28  Product: top 8 PROVISIONAL lessons, cannot_become_policy=true.
29  REVIEW_READY count on scoreboard (expect 0 policy).
30  Memory receipts still have memory_type + promotable.
31  RESEARCH_REFERENCE still not ACTIVE.

BATCH HONESTY / DATA QUALITY (32–41)
32  complete_to_checkpoint rate vs lineage health, expose number.
33  Remaining unlabeled voice: temperament.narrative, next_reviews,
    closest-reentries → T/D/A.
34  Surface B labels on evening packet / desk note if still unlabeled.
35  Morning brief earnings length > 0 when product.earnings > 0.
36  Evening cash line = live temperament.cash, not portfolio_implication.
37  Dark-contract scan: no new uncalled helpers this wave.
38  store_consistency never_auto_remediate regression.
39  holdings as_of vs generated_at on product data_quality.
40  Two-writer holdings: detect + print both totals. Do not merge.
41  C2 still blocks TRIM of non-held / dust-only names.

BATCH SAFETY CLOSE (42–50)
42  C3 quarantine path called on ingest; jsonl exists.
43  C5 critical QA dedupe key written.
44  contradicted_by_cio count on ops health; rebalancer still runs.
45  git grep: no new Telegram producer since #611.
46  Record INTERDICT value on scoreboard.
47  scripts/cio_wave2_census.py --json prints NOW block (read-only).
48  gog --replace scoreboard + census. DRIVE=ok or FAIL.
49  docs/ops/CIO_WAVE2_CLOSEOUT_{date}.md vs operator diagram.
50  Checkpoint only. Continue into 51 unless a rail broke.

BATCH FOLLOW-THROUGH (51–80)
51  S3 open-plan count vs S3 candidates (#609 fairness).
52  Held-without-open-plan after 12c should be CUSIP/CASH/DUST only.
53  Surface A vs B leading-5 printed side by side with labels.
54  Watch BLOCK histogram stable; do not promote BLOCK → S7.
55  READY/NEAR named if any reappear; fires_s7 stays false.
56  SpecialistArtifact@v1-lite bind to plan_id WHEN a specialist file already
    exists. Do not invent council types.
57  CIOCouncilSynthesis receipt: empty vs present artifacts (honesty).
58  Outcome observer PROVEN_IDLE vs due after 27.
59  Lineage live_forward_today on /intelligence/lineage.
60  Last 20 cio_run cost_usd distinct values (want 0.0 / absent, not 0.001).
61  advisory_desk_opinion vs hermes_external_research ledger today.
62  Hermes timer listed; last drain claimed/completed.
63  Overlay pending vs structured open_fps (structured should stay idle).
64  Desk pin + stance on product.
65  Symbol thesis IDs vs non-dust held list.
66  NEW_POSITION_IF all CURRENT (PRIM included).
67  Cash band vs cash_pct; HOLD_CASH_FOR why still numeric.
68  Coverage card numbers == census script.
69  CC Investment Books still shows earnings / cash / NEW_POSITION_IF / cases.
70  Home telegram_sent false regression.
71  % guid after 14.
72  graph_impact non-empty for SCHD if sector map has neighbors.
73  Quarantine jsonl last 24h count (may be 0).
74  Last QA critical key (may be suppressed).
75  Rebalancer last contradicted flags.
76  Plan warehouse draft/proposed/cancelled trend since #598.
77  Failed Hermes top 3 error prefixes.
78  Memory CASE_SUMMARY vs RESEARCH_REFERENCE vs lessons.
79  Drive blob timestamps vs GitHub sha (lag report).
80  Overnight closeout + leftover POLICY list only:
    ROTATE-as-action, notify-on, C1 gate the cron, C3 history scrub,
    council types, AGENT_COMMITMENT. STOP coding.

BATCH EXTRA IF STILL GREEN (81–100) — honesty only, no new products
81  Cancel any other observational S1 whose symbol is DUST_RESIDUAL.
82  Surface A former book includes SCHG/AXTI/FATN with EXITED + dust flag.
83  FANG stays UNAVAILABLE with reason (no silent mint).
84  paper-trade research remains eligible for thesis mint (regression on #614).
85  True broker-exec research still skipped (regression on #614).
86  with_research count on coverage uses hermes_result_id not “any plan”.
87  with_case_summary count vs CASE_SUMMARY ACTIVE (expect ~323 or product cap 10
    — label which).
88  Do not put CASE_SUMMARY into DO_NOW (regression).
89  executive_summary still [T]/[D] labeled.
90  portfolio_implication constant absent from HOLD_CASH_FOR why.
91  SPACEX_TEST / TEST symbols never surface as live holds.
92  CUSIP rows never appear as tickers in NEW_POSITION_IF.
93  Identity register does not ingest the 11k researched dump.
94  Worker --drain --max 1 backend stub still claimed=0 when queue idle.
95  COST_CAP_EXCEEDED not treated as a worker bug (process cap).
96  Notify canary flags remain off-by-policy.
97  Two reentry builders still two functions.
98  Authority string READ_ONLY_ADVISORY on product.
99  Update Google Drive blobs if gog works; else DRIVE=FAIL.
100 docs/ops/CIO_WAVE2_OVERNIGHT_CLOSEOUT.md
    NOW numbers, PRs shipped tonight, leftovers, pin.
    STOP. Do not start Wave 3 policy.

════════════════════════════════════════
5. PER-SLICE LINE (always)
════════════════════════════════════════
W2-NN title | CHANGED files | TESTS | PROMOTE sha PR | LIVE 5 | SCOREBOARD yes | DRIVE | STOP?

If context dies: scoreboard is the cursor. Restart by reading it.
Operator returns ~08:00 EDT to Grok. Leave a closeout they can validate.
