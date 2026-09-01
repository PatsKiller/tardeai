<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3A.3 — grades match the surface

**Status:** recovered verbatim
**Source:** session transcript, operator message 013

---

Claude Code — WAVE 3A.3. Finish last night’s library work. Make grades match the surface.
CURRENT must include French as the calendar grading series (post-3A.2).
READ_ONLY_ADVISORY. MBI=0. No notify. No ROTATE. No book merge.
No cap raise. No cio_run LLM. No second TTL table.
Do not touch research_governance / R1 allowlist. Do not start Wave 3B.

Operator decisions (do these):
1. YES — swap strategy_context / home.seasonality consumer from the
   synthetic file to Ken French. Operator-visible numbers WILL move.
   That is required. Print BEFORE vs AFTER on /v3/cio (or the exact
   payload key) for august_general, september, best_six_months,
   midterm, halloween / worst_six_months.
2. YES — re-grade those live seasonality rows off French the same way
   calendar facts already grade. If a B dies on real crashes, let it
   fall to C. Do not keep B on the synthetic file.
3. NO — do not commit FOMC minutes / Beige Book / FRBSF WP into the
   release. Keep OFFICIAL_URL_ONLY + refresh:event.
4. NO — do not revert the synthetic file; keep it as a named fixture
   for pipeline-determinism tests only. Resolver for OPERATOR surfaces
   must not point at
   reference/library/us_equity_monthly_synthetic_1950_2024.csv
   or tests/fixtures/us_equity_monthly_sample.csv.
5. Leave copyright books C + URL/ISBN. Do not chase full text.

════════════════════════════════════════
A) Surface swap (first, one PR if cleaner)
════════════════════════════════════════
Find every consumer of the synthetic monthly file used for
home.seasonality / strategy_context / desk seasonality banners.
Repoint to the same French series calendar facts already use.
Tests:
  - operator resolve() path does not contain "synthetic" or "tests/fixtures"
  - synthetic file still used only by tests marked determinism
  - midterm / sell-in-may still standalone_sell False, no imperatives
  - SCHD plan still not corpus-closed by a midterm row
Host: /health /v3/cio 200. Paste the BEFORE/AFTER table in
docs/ops/CIO_SEASONALITY_FRENCH_SURFACE_{date}.md

════════════════════════════════════════
B) Finish last night’s public ingest (cap — no grind)
════════════════════════════════════════
If not already on disk + hashed, ingest ONLY:
  - Ken French FF5 + momentum monthly (FF3 already in)
  - FRED: SP500, NASDAQCOM, FEDFUNDS, T10Y2Y, CPIAUCSL, UNRATE, VIXCLS
  - Damodaran implied ERP series from the official NYU data page
    (not the copyright book)
  - Shiller monthly 1871– (Yale) as SECOND series for OOS_START_YEAR=2000
    checks — do not replace French as the primary grading series
Structured facts, context only, with sample_n and as_of:
  spx_vs_ndx_rs_3m / 12m
  vix_regime buckets (<15, 15-25, >25) next-3m SPX distribution
  yield_curve_invert then 12m SPX distribution
  midterm_q2q3_vs_q4 (already have — keep)
No “NDX at X → sell.” Grade D if n < 8.
EDGAR full-text crawler is OUT OF THIS PR (entity source is Wave 3A.4).
Candidates stay 3/3 unless a new MISSING public series appears; cap 3.

════════════════════════════════════════
C) Last-night leftovers that are NOT this PR
════════════════════════════════════════
Do not do: notify-on, ROTATE, merge books, MBI, council, second cron,
api_v2.py:2593 deletion, CASH/dust checkpoint rewrite, Wave 3B,
Fed PDF pin, R1 allowlist edits.

════════════════════════════════════════
D) Verify + stop
════════════════════════════════════════
Dry: eligible jobs stay collapsed (\~8), S5 not 36 Flash jobs, 0 paid calls.
telegram_sent false. cio_run DETERMINISTIC_PRODUCT.
One or two PRs. Exact-main promote. File content is the pin
(not git log inside CURRENT).
Scoreboard: WAVE3A.3 surface=French, synthetic=tests-only,
Fed=URL+event.

STOP when the live seasonality payload grades off French and the
BEFORE/AFTER table is in docs/ops/.
