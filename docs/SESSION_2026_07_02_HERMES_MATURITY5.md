# Session 2026-07-02 — Hermes Maturity-5 Program (audit → phases 0–6, one day)

Status:      HISTORICAL
as_of:       2026-07-02T19:10:32-04:00
Measured at: efcc51365 / not measured

**Commits (this session):** `dfa09163` (phases 0–5) · `d9f99893` (A1A doc sync) · `f970ea8f`
(review-gap fixes) · `87b40d96` (phase 6). CI green throughout.
**Canonical design + per-phase status:** [`docs/design/HERMES_MATURITY_5_DESIGN.md`](design/HERMES_MATURITY_5_DESIGN.md).
**Engine reference (closed-loop map, resource before/after, cron map):**
[`docs/HERMES_INTELLIGENCE_ENGINE.md`](HERMES_INTELLIGENCE_ENGINE.md).

## The day in one paragraph

A four-agent due-diligence audit graded Hermes **2/5** — 4,171 symbols scored every 30 minutes
24/7 with 98.6–100% duplicate writes, one self-modifying loop trained on 6-hour price drift via a
multiplicative ratchet, tagging with zero readers, and every outcome-based feedback mechanism
unscheduled or frozen. By end of day, all six phases of the remediation design were implemented,
verified, committed, and live: a governed 800-symbol event-driven universe, an outcome ledger
grading 22,715 historical claims against money, four sample-gated learning loops reading only that
ledger, falsifiable tags, a config-proposal channel, correctness watchdogs wired to escalation,
and an honestly-computed maturity board that scored the system **2.3 → 2.7** the same day and can
only reach 5s through 30-day evidence streaks.

## What each phase shipped (detail in the design doc)

- **P0** — buy-tier case bug (0→1,070), holdings crowd-out (4→27/27 in the cap), no-change write
  skip, 21d retention, 401/403 lane breaker, scorer-liveness check, taxonomy churn fix.
- **P1** — `scope_tier` S0–S3 ledger (`hermes_scope_governor.py`, ≤800 live, audited, converges) +
  `hermes_score_event_feeder.py` (immediate rescore + S3→S1 on real events; restage noise
  filtered) + tier-plan scorer + research-scheduler binding (T1 469→256).
- **P2** — `hermes_outcome_ledger` + `daily_close_cache` + nightly `hermes_outcome_grader.py`:
  promotions/recs vs ±2% 20-session SPY excess, research vs action-within-14d, trades vs realized
  R; `downstream_outcome` filled (was 100% NULL).
- **P3** — drift ratchet FROZEN; `hermes_outcome_learning.py`: clamped shadow-gated weight
  suggestions, learned promotion gates (momentum_catalyst 0.32 precision → 0.75 conf), source
  retirement on outcome yield (8 domains incl. apnews/cnbc), lane-usefulness rotation.
- **P4** — `hermes_tag_engine.py`: strategy-registry vocabulary, continuous quality_score
  (stddev 0.109 vs binary), `hermes_tag_efficacy` (momentum_scalp +0.042 lift; general_research
  −0.292 flagged); taxonomy cron retired.
- **P5** — `hermes_config_governor.py` (rails-pressure → `config_change_proposals`), watchdogs
  #5–#10 → `escalation_queue` (first catch same day), `hermes_maturity_gates.py` (21 computed
  gates, `trend_vs_7d`, daily snapshots).
- **P6** — the write-only surfaces now read Hermes back, fail-open: AI Trade Critique
  (`ai_critique_v3_hermes`), stop advisory (`protection_advisor_v2_hermes`, subordinate to HARD
  RULES), Validation Tracker (`hermes_context`; first reading: 0/2 confirmed scalp trades had
  prior Hermes research).

## Measured same-day results

- Hourly score writes after cutover: 17,632 → 1,781 → 221 → **3/hr** off-hours (~2,500× off-hours
  reduction; projects ~2–4K rows/day vs 157K).
- Universe: 4,171 flat → 800 governed, holdings coverage 87/87 every run.
- External LLM error calls in 24h: 0 (breaker + budget guard).
- Maturity board: 2.3 → 2.7; scope 3→4.

## Ops notes

- Portfolio server re-adopted by systemd (an orphan held :7777; the unit had **8,144** failed
  restarts) — restart also activated the PR #44 reload fix; dashboard serves `maturity_gates`.
- All new crons live: grader 02:50, learning 03:05, tag engine 03:20, retention 03:35, config
  governor 03:40, maturity snapshot 07:20, governor :07/:37, feeder */5, scorer */15.
- Same-day follow-on by parallel session: Multi-Hermes momentum-scalp swarm + exit-intelligence
  daemons (`da83c36d`, `778ceae8`) — built on the Phase 0–6 substrate.

## What matures on its own (no action)

First external-rec verdicts ~Jul 16 (activates lane routing); calibration pairs → first
evidence-gated weight graft in weeks; fallback tags <15% in ~2 weeks; first possible 5s ~early
August after 30-day streaks. Watch `trend_vs_7d` on the maturity board — if it is flat in a month,
the loops are not compounding and that itself will be visible.
