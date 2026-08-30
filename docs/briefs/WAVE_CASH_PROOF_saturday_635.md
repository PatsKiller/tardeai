<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Saturday cash-fossil proof of #635

**Status:** recovered verbatim
**Source:** session transcript, operator message 009

---

Claude Code — Saturday proof of #635. Close the cash fossil. Not a docs PR.

GOAL
Prove on CURRENT that the Monday writer path sets
  portfolio_totals.total_cash = sum(is_cash position rows)
and the live CIO payload sees cash_gap < 1.
Do this NOW so we do not wait for Monday 16:10.

PRECONDITIONS
1. PR #635 merged (merge commit). Exact-main promote CURRENT.
   Pin must contain the portfolio_repricer.py total_cash write
   (the update({...}) block + total_cash_source + total_cash_written_at).
   If #635 is not on CURRENT, STOP. Do not run the old repricer.
2. Host:
   cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
   export PYTHONPATH=.:scripts
3. Rails: no Telegram, no notify-on, no cap raise, no Hermes --backend live,
   no stop-management files, no ticker_prices DELETE.
   A Saturday reprice WRITE is authorized for this proof only.

BACKUP (required before any write)
  holdings = data/portfolios/state/holdings.json
             (and every path printed by:
              python3 scripts/portfolio_repricer.py --print-targets)
  quote    = data/portfolios/state/finviz_quote_cache.json
Copy each existing file to
  data/cio/backups/holdings.json.pre-sat-cashproof-$(date -u +%Y%m%dT%H%M%SZ)
Same for quote cache. Print backup paths.

BEFORE (print, do not edit)
  total_cash
  total_mv_excluded
  cash row sum (is_cash lots)
  cash_gap
  total_cash_source / total_cash_written_at (expect missing or fossil 578107.50)
  last_repriced / last_pipeline_run / as_of
  temperament.cash vs cash.cash_usd via /api/v3/cio/home if up

RUN THE REAL JOB (same argv cron uses)
  python3 scripts/portfolio_repricer.py
Saturday is after-hours; _is_market_hours is false. That is fine.
Expect Finviz after-hours marks + totals recalc.
If the process hits 50% price-jump reject, 25% total sanity abort, or
the 50% cash-safety abort from #634: STOP, restore backups, print the
abort line. That is a failed proof, not a silent leave-fossil.

AFTER (file + live payload — merge commit is not the proof)
From holdings.json AND from curl localhost:7777/api/v3/cio/home:
  total_cash              ≈ cash row sum
  total_cash_source       position_rows
  total_cash_written_at   today's UTC stamp (not document as_of)
  cash_gap                < 1
  temperament.cash        == cash.cash_usd == /api/v2/overview cash
  S5 / HOLD_CASH_FOR      a number, not DATA_UNAVAILABLE_UNTIL_RECONCILED
  last_repriced           Saturday ET timestamp
  reprice_source          finviz_afterhours

PASS only if file AND live payload both flip.
If file flipped and /v3/cio still shows 578107.50: persisted product
is stale (same class as #622). Rebuild/persist operator product persist=True
once, or document the exact cache key. Do not add a fourth cash writer.

SIDE EFFECTS TO RECORD (do not revert if PASS)
  - finviz_quote_cache.json touched
  - ticker_prices rows for CURRENT_DATE (Saturday) upserted — leave them
  - generated_at / last_repriced moved
Positions/shares must be unchanged. If share counts moved, restore backup.

IF FAIL
Restore holdings.json (all --print-targets copies) from backup.
Leave quote cache unless it is obviously corrupt.
Write docs/ops/CIO_CASH_SATURDAY_PROOF_FAIL_{date}.md with abort text.

IF PASS
docs/ops/CIO_CASH_SATURDAY_PROOF_{date}.md
  pin, before/after table, live payload numbers, backups, side effects.
  Scoreboard: cash_gap live 0, writer=repricer, proof=Saturday afterhours.
Do not delete api_v2.py:2593 in this pass.
Do not start LLM-gate / Wave 3.

STOP after the proof doc + live numbers.
