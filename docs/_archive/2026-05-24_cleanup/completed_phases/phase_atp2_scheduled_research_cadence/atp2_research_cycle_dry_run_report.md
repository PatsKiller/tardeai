# ATP-2 Research Cycle Report
Generated: 2026-05-19T21:39:08.259570

## eod
_End-of-day paper trade and proposal summary_

**open_trade_count:** 0
**closed_today_count:** 1
**pending_proposal_count:** 5
**stale_proposal_count:** 0
**total_pnl_today:** 56.07
**open_trades:** 0 items
**closed_today:** 1 items
  - id=21, symbol=INFU, pnl=56.07, exit_reason=target_hit
**stale_proposals:** 0 items
**run_mode:** dry_run
**run_at:** 2026-05-19T21:39:08.259570

## evening
_Afterhours candidate readiness snapshot_

**total_candidates:** 1311
**by_readiness_status:**
  - ready_for_review: 39
  - blocked_by_strategy_fit: 331
  - watchpool_candidate: 186
  - no_fit: 136
  - needs_data: 619
**top_candidates:** 20 items
  - symbol=BKKT, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=CPSH, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=DRVN, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=GCTS, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=GOVX, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=KULR, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=LMRI, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=TLSI, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=VUZI, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - symbol=ZDAI, readiness=ready_for_review, strategy=momentum_scalp, score=77
  - ... and 10 more
**run_mode:** dry_run
**run_at:** 2026-05-19T21:39:08.259570

## overnight
_Data freshness gaps and lesson memory patterns_

**total_tracked_symbols:** 1655
**symbols_with_fresh_data:** 1402
**symbols_stale_gt_24h:** 253
**stale_symbol_list:** 50 items
  - ABR
  - ACH
  - AEHL
  - AGRO
  - AHG
  - AHR
  - AIRJ
  - AMBO
  - AMT
  - AORT
  - ... and 40 more
**lesson_patterns:** 10 items
  - category=holding_period, pattern_key=momentum_scalp_time_stop_drag_holding_period, count=2, strategy=momentum_scalp, lesson=GCTS (momentum_scalp): Time stop triggered — setup did not move within the allowed window. Small loss incurred, time sto
  - category=data_quality, pattern_key=swing_breakout_broker_sync_issue_data_quality, count=1, strategy=swing_breakout, lesson=XMTR (swing_breakout): Order was never filled on broker or position was phantom — execution pipeline created a trade rec
  - category=broker_sync, pattern_key=swing_trade_broker_sync_issue_broker_sync, count=1, strategy=swing_trade, lesson=FLYW (swing_trade): Position was closed externally on Alpaca — either a manual close on the broker side, a margin call, 
  - category=manual_intervention, pattern_key=swing_breakout_stale_manual_exit_manual_intervention, count=1, strategy=swing_breakout, lesson=INFU (swing_breakout): Closed manually/stale — no explicit exit rule fired, position was closed by operator discretion. 
  - category=data_quality, pattern_key=screener_broker_sync_issue_data_quality, count=1, strategy=screener, lesson=EVC (screener): Order was never filled on broker or position was phantom — execution pipeline created a trade record but
  - category=data_quality, pattern_key=momentum_scalp_broker_sync_issue_data_quality, count=1, strategy=momentum_scalp, lesson=FLYW (momentum_scalp): Order was never filled on broker or position was phantom — execution pipeline created a trade rec
  - category=holding_period, pattern_key=momentum_scalp_time_stop_drag_holding_period, count=1, strategy=momentum_scalp, lesson=GCTS (momentum_scalp): Time stop triggered — setup did not move within the allowed window. Small loss incurred, time sto
  - category=entry_timing, pattern_key=earnings_catalyst_spread_slippage_entry_timing, count=1, strategy=earnings_catalyst, lesson=BLBD (earnings_catalyst): Stopped out instantly at -0.05R — entry price was likely too aggressive, spread was too wide, 
  - category=exit_discipline, pattern_key=earnings_catalyst_none_exit_discipline, count=1, strategy=earnings_catalyst, lesson=INFU (earnings_catalyst): Target hit at 1.4R — exit discipline followed, strategy plan executed as designed
  - category=stop_quality, pattern_key=dividend_growth_compounder_none_stop_quality, count=1, strategy=dividend_growth_compounder, lesson=FLYW (dividend_growth_compounder): Stop hit at 0.2R — within acceptable R risk. Entry quality was adequate, stop placeme
**run_mode:** dry_run
**run_at:** 2026-05-19T21:39:08.259570

## premarket_4am
_Pre-market scan data: gap and rvol movers_

**total_scanned:** 100
**high_gap_count:** 29
**high_rvol_count:** 58
**top_movers_by_gap:** 15 items
  - symbol=GOVX, gap_pct=146.34, rvol=20.29, score=41, catalyst=GeoVax Highlights Strategic Importance of Domestic MVA-Based Preparedness Infras
  - symbol=CODX, gap_pct=42.34, rvol=301.13, score=46, catalyst=Co-Diagnostics Develops Ebola Assay Strategy Following Recent Global Outbreak Al
  - symbol=ZDAI, gap_pct=26.21, rvol=14.35, score=37, catalyst=All Resolutions Passed at DirectBooking Technology Extraordinary General Meeting
  - symbol=BKKT, gap_pct=16.17, rvol=8.27, score=38, catalyst=Bakkt Leans Into Stablecoin Payments After Sharp Q1 Revenue Drop
  - symbol=GCTS, gap_pct=12.57, rvol=12.72, score=44, catalyst=GCTS: GCT Semiconductor Reports Revenue Growth After Two Years of Declines [Yaho
  - symbol=CPSH, gap_pct=12.42, rvol=9.36, score=41, catalyst=CPS Technologies Q1 Earnings Call Highlights [Yahoo Finance]
  - symbol=CVU, gap_pct=11.78, rvol=4.65, score=35, catalyst=CPI Aerostructures Reports First Quarter 2026 Results
  - symbol=PIII, gap_pct=9.71, rvol=18.45, score=30, catalyst=Trump Rattled Markets Again and These 3 Forgotten Stocks Under $30 Were the Unli
  - symbol=DSGN, gap_pct=9.67, rvol=11.14, score=29, catalyst=This Biotech Leader Ran Up As Much As 18% — And Then Lost It All
  - symbol=KULR, gap_pct=8.89, rvol=10.45, score=32, catalyst=KULR Technology Expands Space Business With Argo Space Battery Deal
  - ... and 5 more
**top_movers_by_rvol:** 15 items
  - symbol=CODX, rvol=301.13, change_pct=56.93, score=46
  - symbol=GOVX, rvol=20.29, change_pct=79.67, score=41
  - symbol=PIII, rvol=18.45, change_pct=19.57, score=30
  - symbol=ZDAI, rvol=14.35, change_pct=22.76, score=37
  - symbol=AVEX, rvol=13.72, change_pct=-2.41, score=28
  - symbol=GCTS, rvol=12.72, change_pct=40.98, score=44
  - symbol=GOSS, rvol=12.06, change_pct=1.76, score=23
  - symbol=DSGN, rvol=11.14, change_pct=-25.54, score=29
  - symbol=SOXS, rvol=10.67, change_pct=10.0, score=30
  - symbol=KULR, rvol=10.45, change_pct=8.89, score=32
  - ... and 5 more
**run_mode:** dry_run
**run_at:** 2026-05-19T21:39:08.259570

## premarket_7am
_Due diligence priorities from strategy fit + afterhours readiness_

**strong_moderate_fits:** 50
**with_readiness_snapshot:** 50
**priorities:** 30 items
  - symbol=ZDAI, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=TLSI, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=VUZI, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=DRVN, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=GOVX, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=GCTS, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=BKKT, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=CPSH, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=LMRI, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - symbol=KULR, strategy=momentum_scalp, match_strength=STRONG, fit_score=77, readiness=ready_for_review, ah_score=77
  - ... and 20 more
**run_mode:** dry_run
**run_at:** 2026-05-19T21:39:08.259570

## premarket_9am
_Final pre-market ranking of ready candidates_

**ready_count:** 39
**ranked_candidates:** 30 items
  - symbol=BKKT, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=CPSH, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=DRVN, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=GCTS, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=GOVX, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=KULR, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=LMRI, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=TLSI, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=VUZI, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - symbol=ZDAI, strategy=momentum_scalp, score=77, readiness=ready_for_review, quote_ok=fresh, proposal_allowed=False
  - ... and 20 more
**run_mode:** dry_run
**run_at:** 2026-05-19T21:39:08.259570

## proposal_revalidation
_Pending proposal freshness and validity check_

**total_pending:** 5
**by_revalidation_status:**
  - needs_refresh: 5
**proposals:** 5 items
  - proposal_id=102, symbol=INGM, strategy=dividend_growth_compounder, status=PENDING, age_hours=4.7, quote_age_hours=7.2, quote_fresh=False, revalidation_status=needs_refresh
  - proposal_id=101, symbol=SIF, strategy=defense_thesis, status=PENDING, age_hours=4.7, quote_age_hours=276.8, quote_fresh=False, revalidation_status=needs_refresh
  - proposal_id=100, symbol=NVST, strategy=recovery_watch, status=PENDING, age_hours=7.7, quote_age_hours=299.7, quote_fresh=False, revalidation_status=needs_refresh
  - proposal_id=99, symbol=CODX, strategy=swing_trade, status=PENDING, age_hours=8.7, quote_age_hours=12.0, quote_fresh=False, revalidation_status=needs_refresh
  - proposal_id=98, symbol=DOC, strategy=reit_income, status=PENDING, age_hours=8.7, quote_age_hours=315.9, quote_fresh=False, revalidation_status=needs_refresh
**run_mode:** dry_run
**run_at:** 2026-05-19T21:39:08.259570
