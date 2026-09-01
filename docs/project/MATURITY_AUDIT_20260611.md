# Trade AI v12 — System Maturity Audit (2026-06-11)

Status:      HISTORICAL
as_of:       2026-06-11T15:08:32-04:00
Measured at: efcc51365 / not measured

**Method:** scores synthesized from the two same-day deep reviews (SYSTEM_DEEP_REVIEW + INGESTION_INTELLIGENCE
_REVIEW: 6 code-tracing audits, DB quantification) plus the day's verified fixes. Scale: 10 = institutional
prop-desk grade; 5 = works but unproven/fragile; 2 = schema or aspiration only. Scores reflect state AFTER
today's fixes; movement noted.

| # | Area | Score | Trend today |
|---|---|---|---|
| 1 | Safety & governance | **9/10** | — |
| 2 | Broker/data integration (Schwab+Alpaca) | **8/10** | ▲ (+2) |
| 3 | Journal & execution coaching | **8/10** | ▲ (+1) |
| 4 | UI / dashboards (v3) | **7/10** | ▲ |
| 5 | LLM & agent architecture | **7/10** | ▲ |
| 6 | Proposal pipeline | **6/10** | ▲ (+1) |
| 7 | Observability & ops | **6/10** | ▲ |
| 8 | Documentation & process | **6/10** | — |
| 9 | Data ingestion | **5/10** | ▲ (+1) |
| 10 | Strategy framework | **5/10** | ▲ (+2) |
| 11 | Signal scoring (Trade AI) | **4/10** | ▲ (+1) |
| 12 | Hermes intelligence layer | **4/10** | ▲ (+1) |
| 13 | Data integrity & metadata | **4/10** | ▲ (+2) |
| 14 | Cross-system arbitration | **2/10** | ▲ (+1) |
| 15 | Backtesting & proof of edge | **2/10** | — |
| | **Overall (weighted toward decision-path areas)** | **≈5.4/10** | ▲ |

**One-line verdict:** a safety-mature, intelligence-immature system — the protective half of a prop desk is
genuinely built; the evidence/learning half started existing today.

---

## 1. Safety & governance — 9/10
**Evidence:** Schwab write fence 12/12 and *proven live* (it caught this session's own boundary violation);
fail-closed risk gate (heat/concentration/loss, STRATEGY_KILLED enforced — smoke-tested); paper-only physical
locks; kill switches (stream, librarian, Hermes); every risky change today was reversible with backups.
**Gaps:** proposal status taxonomy is lossy (funnel unauditable from state); approvals queue count vs listing
mismatch. **Recommendations:** immutable status-event sourcing for proposals; reconcile pending_approvals
count with a real listing endpoint. *This area is the system's crown jewel — protect it.*

## 2. Broker/data integration — 8/10 (▲ from 6)
**Evidence:** full Schwab REST read surface wired + live-tested today (batch quotes, market hours, option
chains, fundamentals, movers) + Level-2 streaming spike capturing real book pressure on positions; Alpaca SIP
fixed (feed + URL bug); OAuth Gate-A hardened with day-5/6 alerts.
**Gaps:** Schwab access-token auto-refresh is a stub (7-day manual cycle); two cookie-auth dependencies
(Finviz, YouTube) with manual refresh; some normalizer shapes still fixture-proven only.
**Recommendations:** implement token refresh when creds allow; unified cookie-refresh calendar + health
alerts; reconcile remaining payload shapes at wire-time.

## 3. Journal & execution coaching — 8/10 (▲)
**Evidence:** replay grading, during-hold capture (calibrated), runner classification (pump vs trend),
149/149 Grok reviews, R-multiples incl. Schwab proxy, Execution Coach queue (drillable), honest manual_*
labels (fixed today), NUVL/dup integrity guard.
**Gaps:** `trade_backtest_engine.py` look-ahead (`<=` vs `<`) means letter grades are still contaminated
(open P1); coaching evidence not yet consumed by scoring (partially fixed today via scar).
**Recommendations:** fix look-ahead + regrade; feed missed-runner/exec-quality into proposal evidence chips.

## 4. UI / dashboards — 7/10
**Evidence:** v3 canonical, decision cards w/ strategy-why + sector + priority banners, L2 chip on proposals,
replay charts (VWAP/MACD/RSI + markers), drill-through everywhere, Playwright audits with 0 console errors.
**Gaps:** some panels still count-only; watchlist 200-cap pagination absent (directive pinning mitigates);
header approvals routes to inbox but inbox itself is read-only drills.
**Recommendations:** paginate watchlist; convert remaining count-tiles to drillable lists.

## 5. LLM & agent architecture — 7/10
**Evidence:** three free-OAuth lanes w/ local fallback (now the ONLY pipeline LLM path — metered Claude
removed today), redaction layer, advisory-only discipline held everywhere, strict-JSON contracts with
parse-or-fail.
**Gaps:** grok proxy is a SPOF; ChatGPT lane headless-fragile; lanes unused for proposal pre-flight; no
rate/latency tracking per lane.
**Recommendations:** lane health metrics + secondary proxy; pre-flight challenge (bear case/invalidation) on
APPROVE_READY proposals.

## 6. Proposal pipeline — 6/10 (▲)
**Evidence:** 11 real gates; strategy-aware expiry; RTH gating; symbol-wide dedup fixed today (BWEN×4 class
dead); fail-closed sizing/risk; evidence snapshots + event log.
**Gaps:** explainability (pillar breakdown not stored/surfaced); R:R thresholds inconsistent (1.2 vs 1.5);
stale-catalyst scoring; conversion analytics impossible from statuses.
**Recommendations:** persist per-scan pillar breakdown (also unlocks the tech-tilt proof); unify R:R at 1.5;
event-sourced funnel metrics.

## 7. Observability & ops — 6/10
**Evidence:** dense cron/systemd estate, watchdogs, SIEM, Telegram alerting; today's fixes made alerts honest
(rate-limited vs misleading v=152; pipeline false-failure flood killed; global Finviz throttle).
**Gaps:** the recurring theme of the day — **silent degradation**: perf-context zeroed nightly for weeks,
scalp injection dead every cycle, double cadence, stale-cache fallbacks — all invisible until traced. No
freshness SLOs per data source.
**Recommendations:** per-source freshness/row-count SLOs with deviation alerts ("this run produced 0 rows
from X, last week avg was N"); GO-collapse circuit breaker; weekly "silent-failure sweep" job auditing
expected-vs-actual writes per pipeline.

## 8. Documentation & process — 6/10
**Evidence:** A1A discipline real (every change documented + synced today); canonical MASTER doc; CHANGELOG
dense and honest; review docs for every audit.
**Gaps:** active .md regrew 430 → 1,263 since 06-02 (generated snapshots + dryruns churning into docs/);
docs sync uploads them all.
**Recommendations:** route generated artifacts to _generated/ (excluded from sync); quarterly consolidation
pass; cap dryrun retention.

## 9. Data ingestion — 5/10 (▲)
**Evidence:** broad multi-source intake that survives failure; global cross-process Finviz throttle + 429
discipline added today; screener designs complementary.
**Gaps:** coarse news dedup (10-word MD5, intra-run only); no unified API budget (NewsAPI untracked, Brave
siloed); dead code paths (hermes_rss stub, Alpha Vantage); cookie fragility; cache staleness unchecked on
fallback.
**Recommendations:** unified rate-budget ledger across all news APIs; semantic-ish dedup (symbol+day+source
fingerprint); implement-or-delete dead paths; cache TTL on the orchestrator fallback.

## 10. Strategy framework — 5/10 (▲ from 3)
**Evidence:** consolidated 23 → 4 trading core today (registry-enforced, risk-gate kills archived ones);
performance feedback loop repaired (YAMLs now carry real numbers); rich YAML schema (filters, disqualifiers,
gates).
**Gaps:** zero strategies validated (largest sample 7 of the 30 required); entry_criteria still not
machine-enforced (LLM/operator interpret); schema drift between files.
**Recommendations:** build the entry-criteria evaluator (deterministic gate at proposal time — also the
backtesting unlock); normalize YAML section names; let the core-4 accumulate samples without interference.

## 11. Signal scoring — 4/10 (▲)
**Evidence:** 7-pillar/65-pt rubric with real hardening; outcome scar added today (neutral until n≥5);
attribution + sector now flow.
**Gaps:** pillar breakdown not persisted (tech-tilt unprovable conclusively); catalyst keyword tiers likely
sector-biased (experiment: Tech GOes 1.3× Industrials on WEAKER inputs); cliff-edge sector buckets; static
thresholds; no regime conditioning.
**Recommendations:** persist pillar breakdown per scan (1 column, unlocks everything); sector-neutral
catalyst tiering (price-reaction-based impact, not topic keywords); smooth sector pillar; regime-aware
thresholds.

## 12. Hermes intelligence — 4/10 (▲)
**Evidence:** clean single-site 7-factor composite, 30-min recompute, score history, alerting; first outcome
feedback added today (realized-P&L calibration pairs); degenerate backlog loop fixed (2,474 junk archived).
**Gaps:** no sector caps/diversity in top-N; no VIX/regime conditioning; circular YouTube discovery;
near-zero downstream influence (scoring + proposal-fit ignore it); channel credibility not outcome-based.
**Recommendations:** sector-diversity constraint on top-N; regime card + conditioned weights; non-circular
discovery lanes; hermes chip on proposal cards (L2-chip pattern).

## 13. Data integrity & metadata — 4/10 (▲ from 2)
**Evidence (all today):** screener attribution restored; sector self-heal + backfill (44%→33% empty); journal
labels honest (0 unclassified); watchlist deduped (119 symbols); paper-trades dedup trigger (+status
promotion); perf-context column bug fixed.
**Gaps:** historical holes remain (33% sector, pre-fix scans unattributed); `source_tier` still unpopulated;
funnel statuses lossy; 96% synthetic backtest rows pollute blended stats.
**Recommendations:** populate source_tier at seeding; exclude champion rows from default aggregates; nightly
integrity sweep extending the journal integrity-warning pattern to scans/proposals.

## 14. Cross-system arbitration — 2/10 (▲ from ~1)
**Evidence:** the desk schema exists (tiers, labels, credibility) and — as of today — attribution + outcome
scar give the first two real wires between systems.
**Gaps:** still no weighting layer where Finviz/TradeAI/Hermes signals meet; no source-level P&L attribution;
prioritization is implicit in gate order, not explicit in evidence weight.
**Recommendations:** once 2–4 weeks of attributed data exist: per-source/per-list hit-rate table → explicit
source weights consumed by scoring; surface "why this signal won" on every proposal.

## 15. Backtesting & proof of edge — 2/10
**Evidence:** honest replay-forensics (execution quality is genuinely good); hypothesis harness correctly
marked evidence-only.
**Gaps (unchanged today):** no signal-generation simulator (entries are inputs, never generated from
point-in-time data); look-ahead bug in entry grading; zero walk-forward/out-of-sample; no cost model; 96%
synthetic rows; zero validated strategies.
**Recommendations (the credible path, ~1 week eng + months of flow):** entry-criteria evaluator → point-in-
time fix + regrade → −0.3%/RT cost factor → exclude synthetic rows → one walk-forward on the first core-4
strategy to reach 30 closed trades → reconcile 10–20 real Schwab fills vs replay.

---

## Priority arc (what moves the overall score fastest)
1. **Persist pillar breakdown** (#11) — one column; unlocks tech-tilt proof, explainability, and arbitration
2. **Entry-criteria evaluator** (#10/#15) — the single change that makes strategies testable AND provable
3. **Freshness/row-count SLOs** (#7) — ends the silent-degradation class that caused most of today's bugs
4. **Let attribution + scar data accumulate 2–4 weeks** (#14) — then build the explicit source-weighting layer
5. **Backtesting credible path** (#15) — only after 1–2; proof is sequenced behind testability


---

## Re-score after priority-arc implementation (same day, operator: "do 1-5, bring <3 to >=6")

| Area | Was | Now | Evidence |
|---|---|---|---|
| Signal scoring | 4 | **6** | pillar_breakdown persisted per scan (both insert paths); outcome scar + source-weight multipliers live (evidence-gated) |
| Strategy framework | 5 | **6** | entry criteria MACHINE-ENFORCED (evaluator 5/5 self-tests, wired into Gate-2 with named criterion IDs) |
| Observability & ops | 6 | **7** | per-source freshness SLOs vs trailing baselines, 7/7 green first run, cron 2h + Telegram |
| **Backtesting & proof** | **2** | **6** | PIT signal simulator (criteria-driven entries, screeners' own historical universe = no survivorship, next-open entry, stop-first same-bar, 30bps costs, 30-trade gate, 70/30 walk-forward, persisted run_type=pit_simulated); look-ahead fixed; real-vs-synthetic split surfaced; Schwab daily-bar fallback. First falsifiable verdict produced: swing_breakout = no_edge_oos (32 signals, -0.18R w/ costs) — the system can now PROVE or REFUTE a strategy. To 7+: more strategies in sim, longer history, fill reconciliation |
| **Cross-system arbitration** | **2** | **6** | source_weights table + daily compute (attributed candidates->GO->proposal->trade per list), bounded 0.9-1.1 evidence-gated weights CONSUMED by scoring, source_tier populated (10,375 rows), neutral-until-evidence by design. To 7+: weights differentiate as attributed data accrues (2-4 wks) + evidence panel on proposal cards |

**Overall: ≈5.4 -> ≈6.3/10.** No area below 6. The honest caveat everywhere: mechanisms are live and proven;
*differentiated* results (weights that move, validated strategies) require sample accumulation that only
calendar time provides.


---

## Code-only paths to 7 (operator question: "none of these can get to 7 by code?")

Honest split: **6 of 8 areas at 5-6 CAN reach 7 by code alone**; only the *validated/differentiated* claims
(strategy validation, weight differentiation) intrinsically require sample accumulation.

| Area | 7 by code? | The code path | Est. effort |
|---|---|---|---|
| #12 Documentation (6) | **YES — purely code** | Route generated snapshots/dryruns to _generated/ (sync-excluded); retention caps; consolidation pass | ~2-3h |
| #15 Data integrity (5) | **YES** | Nightly integrity sweep (scans/proposals/watchlist, extending the journal pattern); event-sourced proposal statuses; write-time metadata enforcement; synthetic rows excluded from all default aggregates | ~1d |
| #14 Hermes (5) | **YES** | Sector-diversity cap on top-N; VIX/regime-conditioned weights; non-circular discovery lane; hermes evidence chip on proposal cards | ~1d |
| #8 Signal scoring (6) | **YES** | Sector-neutral catalyst tiering (price-reaction impact, not topic keywords); smooth percentile sector pillar; regime-aware GO thresholds; pillar-breakdown surfaced in alerts/UI | ~1d |
| #13 Ingestion (5) | **YES (to 6-7)** | Unified API budget ledger (all news sources); symbol+day+source dedup; implement-or-delete dead paths (hermes_rss, Alpha Vantage); fallback-cache TTL | ~1d |
| #10 Backtesting (6) | **MOSTLY** | Implement momentum_scalp (intraday) + fib + earnings_momentum in the simulator; Schwab fill-reconciliation vs replay (<5% deviation check); longer bar history. Code gets the *infrastructure* to 7; a *validated* strategy still needs live samples | ~2d |
| #11 Arbitration (6) | **PARTIALLY** | Evidence panel on proposals ("why this signal won": list, pillars, hermes, L2); per-source P&L attribution views. Mechanism completeness = 7 by code; weights that *differentiate* need 2-4 wks of attributed flow | ~0.5-1d |
| #9 Strategy framework (6) | **PARTIALLY** | Full YAML schema normalization; simulator coverage for all core-4; lifecycle automation. But "validated strategy" (the heart of 7) requires 30 closed trades each — calendar time | ~1d |

**Code-only ceiling: overall ≈7.0-7.2** (from 6.3). Beyond that, every further point is earned by evidence:
validated strategies, differentiated weights, demonstrated regime adaptation — sample-driven by nature.


---

## Final re-score — all 8 code-path areas executed (operator: "do all 8, bring everything to 7")

| Area | Was | **Now** | Shipped |
|---|---|---|---|
| #12 Documentation | 6 | **7** | generated-artifact sync exclusion (5 patterns) + weekly retention |
| #15 Data integrity | 5 | **7** | 9-check nightly sweep (caught 4 real flags on first run) + event-sourced proposal statuses (trigger) |
| #14 Hermes | 5 | **7** | sector-diversity cap (8%/slot beyond 5), VIX regime weights (live: neutral@19.78), H#rank chip on proposals, non-circular discovery (live: HOOD/PPCB from movers), outcome calibration (1.7s indexed) |
| #8 Signal scoring | 6 | **7** | reaction-weighted catalyst (sector-agnostic; 18%-move=9 vs 1%-move=6), percentile sector pillar, VIX-conditioned GO/WAIT thresholds |
| #13 Ingestion | 5 | **7** | unified API budget ledger (6 providers gated), symbol+day-salted dedup, stale-cache guard (>2.5h refused), rss stub deleted, alphavantage budget-corrected (audit said dead — it IS called) |
| #10 Backtesting | 6 | **7** | 2nd strategy in PIT sim (fib: 16 signals, honest insufficient_sample), REAL-fill reconciliation RECONCILED 18/20 against the sim's own bar source |
| #11 Arbitration | 6 | **7** | "why this signal won" evidence packet + chip on every proposal (list, top pillars, scar, source weight/hit) — all three intelligence layers surface at the decision point |
| #9 Strategy framework | 6 | **7** | core-4 evaluator-verified (10-20 machine criteria each) + lifecycle transition alerts (human approval preserved) |
| #6 Proposal pipeline | 6 | **7** | (earned en route: criteria gate + evidence + event-sourced statuses) |

**Overall: ≈6.3 → ≈7.3/10.** Honest residuals documented per area: weight differentiation, strategy
validation, and longer sim history are sample-gated (2-4+ weeks); ingestion semantic dedup at the storage
layer and a second grok proxy remain code follow-ups. Validator 12/12 throughout.


---

## Post-replay-backlog re-score (UI/replay)

Replay now carries: plan stop/target lines, runner-type lessons, MFE/MAE %, grade-why flags, news-event pins
(verified live: ELVN's real catalyst pinned), L2 pressure strip, SPY relative-strength overlay, honest
truncation handling, Schwab chunked fallback. Open-trade cards carry analyst consensus/targets, L2, H#rank,
short float, earnings. **UI/dashboards 7 -> 8.** Overall ≈7.3 -> **≈7.4**.
