<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Authorized merge #635 + exact-main promote

**Status:** recovered verbatim
**Source:** session transcript, operator message 010

---

Claude Code — AUTHORIZED: merge #635, exact-main promote, Saturday cash proof.
Operator John Whiting. Do the whole sequence in one pass. Do not stop for
another merge approval.

READ_ONLY_ADVISORY on CIO/Telegram. This sequence MAY write holdings.json
and quote cache ONLY after #635 is on the served CURRENT file.

════════════════════════════════════════
1) MERGE  (authorized)
════════════════════════════════════════
Repo PatsKiller/tardeai. PR #635. CI 5/5 CLEAN/MERGEABLE.

  gh pr merge 635 --merge --delete-branch=false

If gh pr merge is blocked by a classifier, use the GitHub API merge
endpoint for pull 635 (merge method MERGE). That is the same authorized
merge, not a bypass of review — CI is already green.

Confirm:
  gh pr view 635 --json state,mergedAt,mergeCommit
  state=MERGED, mergeCommit != null
  origin/main contains that merge commit and is past b985dbec.

Do not run the repricer until that is true.

════════════════════════════════════════
2) PROMOTE  (authorized)
════════════════════════════════════════
Exact-main promote of portfolio-server CURRENT the same way prior Wave 2
promotes were done (the host script / bay-site path already used for
#632–#634). Wait until CURRENT is the new release.

PIN TRUTH = file content, not git log inside CURRENT
  (release dirs share a gitdir with the deploy worktree; HEAD can lie).

  grep -n total_cash \
    /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/portfolio_repricer.py

PASS only if the served file contains the portfolio_totals total_cash
write + total_cash_source + total_cash_written_at.
If grep is absent: STOP. CURRENT is still #634. Do not reprice.

Also:
  python3 scripts/portfolio_repricer.py --print-targets
  /api/v2/health and /v3/cio 200

════════════════════════════════════════
3) BACKUP then BEFORE table
════════════════════════════════════════
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
export PYTHONPATH=.:scripts

Backup every holdings.json from --print-targets plus
data/portfolios/state/finviz_quote_cache.json to
  data/cio/backups/*pre-sat-cashproof-<UTC>

Print BEFORE from the served holdings.json:
  total_cash (expect 578107.50 fossil)
  cash row sum / total_mv_excluded
  cash_gap
  total_cash_source / written_at (expect missing)
  last_repriced / last_pipeline_run / as_of
  live /api/v3/cio/home temperament.cash vs cash.cash_usd
  live /api/v2/overview cash

════════════════════════════════════════
4) RUN THE REAL REPRICER  (authorized only after step 2 PASS)
════════════════════════════════════════
  python3 scripts/portfolio_repricer.py

Saturday after-hours is expected. This is the Monday 16:10 binary.
If 50% price-jump, 25% total sanity abort, or cash-safety abort:
  restore holdings.json copies from backup, print abort line, STOP.
  That is FAIL, not a fossil left in place quietly.

════════════════════════════════════════
5) AFTER — file AND live payload
════════════════════════════════════════
PASS only if both flip:

  total_cash            ≈ cash row sum (not 578107.50)
  total_cash_source     position_rows
  total_cash_written_at today's UTC (not document as_of)
  cash_gap              < 1
  temperament.cash      == cash.cash_usd == overview cash
  S5 / HOLD_CASH_FOR    a number, not DATA_UNAVAILABLE_UNTIL_RECONCILED
  last_repriced         Saturday ET
  reprice_source        finviz_afterhours
  shares/qty unchanged

If file flipped and /v3/cio still shows 578107.50: persisted product
stale (#622 class). Persist operator product once. No fourth cash writer.

Side effects to record, not revert on PASS:
  quote cache, Saturday ticker_prices upserts, generated_at/last_repriced.

════════════════════════════════════════
6) DOCS + STOP
════════════════════════════════════════
PASS → docs/ops/CIO_CASH_SATURDAY_PROOF_{date}.md
  pin, mergeCommit, grep proof, before/after, live payload, backups.
  Scoreboard: cash writer=repricer, proof=Saturday afterhours, gap live 0.

FAIL → restore backups, docs/ops/CIO_CASH_SATURDAY_PROOF_FAIL_{date}.md

Do not delete api_v2.py:2593.
Do not start LLM-gate / Wave 3.
No Telegram / notify / cap raise / Hermes live.

STOP after the proof doc.
