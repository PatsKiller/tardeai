Status:      ACTIVE
as_of:       2026-09-01T09:02:00-04:00
Measured at: PROJ /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state
             PSTATE /home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state
Canonical repo path: docs/ops/HOLDINGS_STATE_RECONCILIATION_2026-09-01.md
Authority:   per-file reconciliation plan for two divergent state trees; NOT executed
See also:    AGENTS.md §0 rule 5 · §17 · §18 · docs/ops/CIO_OVERNIGHT_STITCH_2026-09-01.md

# Holdings state — per-file reconciliation plan

**NOTHING HAS BEEN MERGED, MOVED, SYMLINKED OR DELETED.** Both trees are backed up and verified
byte-identical to their sources at
`/home/johnclaw/trade-ai-releases/holdings-reconcile-backup-20260901-0855/` (`diff -rq` → rc=0 for
both). Classifier: `scripts/reconcile_holdings_state_classify.py`, read-only.

## Why there are two trees

Two deploy paths, both live, disagreeing about where truth lives:

| script | links release data dirs to |
|---|---|
| `deploy_portfolio_server.sh:23` (`CANONICAL_SOURCE=$PROJ`) | **`$PROJ`** |
| `cio_phase2_exact_main_deploy.sh` → `link_pipeline_data()` → `lib.persistent_overlay.overlay_data_source()` | **`persistent-state`** |

`[VERIFIED]` The served release is `d276657b7-main-exact-phase2-…`, built by the second path, so the
**server reads `persistent-state`** while **464 crontab lines `cd $PROJ`** and write there. Nobody
chose this: the overlay mechanism landed (its own comments cite 147 of 160 release dirs forking
`logs/`) and the older path was never retired.

## The result: there is no single winner

```
identical (no action) : 50
clear -> PROJ         : 27
clear -> PSTATE       :  5
AMBIGUOUS (operator)  : 25
```

**Each tree is authoritative for different files.** A symlink swap in either direction destroys
real, current data. This is exactly what §0 rule 5 means by *a machine picking one can destroy the
other* — and it is now measured rather than asserted.

## THE FINDING THAT STOPPED THE MERGE — a live writer destroying data daily

Seven `ai_*.json` files are **newer on PROJ and 20–30× smaller**. They are not truncations. They
are error stubs, all written **today between 07:32 and 07:33**:

```json
{ "key": "bond_strategy",
  "text": "Analysis unavailable — all LLMs failed",
  "ts": "2026-09-01T07:33:02.200353" }
```

against the real analysis still held in `persistent-state` from 2026-08-11:

```json
{ "key": "bond_strategy",
  "text": "Okay, here's an analysis of John's bond allocation strategy for his Rollover IRA…" }
```

All seven — `ai_bond_strategy`, `ai_deep_holdings`, `ai_defense_analysis`, `ai_dividend_strategy`,
`ai_ira_opportunities`, `ai_roth_conversion`, `ai_v_strategy` — carry the identical failure text.

**Two separate defects, and the second is worse than the divergence this document was written to
resolve:**

1. **The AI analyst lane is failing** — "all LLMs failed" — consistent with the AS-IS doc's record
   of the paid lane failing closed and the overnight judgment window being retired.
2. **On failure it writes an error stub OVER the last good analysis.** A cache that fails *open*.
   The previous content is not preserved, not versioned, not skipped — it is overwritten with the
   string describing the failure. Every morning the job runs, it destroys another day's copy.

**The only reason the real analyses still exist is the divergence.** `persistent-state` is not
written by the `$PROJ`-rooted job, so it kept the last good copies. **Unifying the trees naively
would have deleted the last surviving copies of all seven.** The bug that this document exists to
fix is currently the only thing preventing that data loss.

That inverts the priority order: **fix the fail-open writer first, then unify.** Unifying first
removes the accidental backstop while the destroyer is still running.

## The classification rule, stated before measuring

```
only one side has the file              -> that side (nothing to lose)
one side strictly newer AND not smaller -> that side ("newer and not smaller")
newer but SMALLER                       -> AMBIGUOUS (truncation / failed-write signature)
append-only store losing lines          -> AMBIGUOUS
risk-critical file                      -> AMBIGUOUS regardless of evidence (§17)
same mtime, different content           -> AMBIGUOUS
```

The newer-but-smaller rule is what caught the seven stubs. Any plan built on "newest wins" —
including the obvious one — destroys them.

## AMBIGUOUS — 25 files needing an operator call

**Risk-critical, never auto-resolved (§17):** `holdings.json` (identical size, same mtime, 2
differing leaves both in `_agent_metadata`), `stops.json` (PROJ 6,538 / PSTATE 5,147 — **stop
levels**), `tax_lots.json`, `trade_journal.json`, `risk_management.json`,
`holdings_symbol_state.json`.

**LLM error stubs — `persistent-state` holds the real content:** the seven `ai_*.json` above.

**Newer-but-smaller, cause not established:** `action_signals.json`, `analyst_data.json`,
`classification_review_queue.json`, `classified_candidates.json`, `earnings_dates.json`,
`lookthrough_themes.json`, `mutual_fund_intelligence.json`, `options_proposals.json`,
`performance_history.json`, `ticker_snapshot_latest.json`, `ytd_daily_pin.json`.

## Recommended order — not executed

1. **Fix the fail-open AI analyst writer** so a failed run preserves the prior file instead of
   overwriting it. Until this ships, unification actively destroys data.
2. **Restore the seven analyses** from `persistent-state` (they are the only copies).
3. **Resolve the six risk-critical files by operator decision**, `stops.json` first.
4. **Apply the 32 clear cases** (27 → PROJ, 5 → PSTATE) into the chosen root.
5. **Then** unify: point `$PROJ/data/portfolios/state` at `persistent-state` and retire
   `deploy_portfolio_server.sh`'s competing link, so one root serves both readers and writers.
6. **Do the swap in a quiet window.** The `*/15 9-16` writers are active during market hours; a
   283 MB directory swap under live writers risks a torn file.

**Nothing in steps 1–6 has been performed.**
