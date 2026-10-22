/** Captured from the live API 2026-10-22 ~11:00 ET (trimmed to the fields the desk reads). Test-only fixture.
 *  Values here were computed by the server functions the glossary cites; the tests check the TS mirrors
 *  reproduce them. Regenerate only from a real capture, never by hand-editing numbers. */
/* eslint-disable */
export const FIXTURE: Record<string, any> = {
 "proposals": {
  "ok": true,
  "data": {
   "generated_at": "2026-10-22T13:30:15.509681+00:00",
   "scan_status": "LEGACY_PARTIAL",
   "market_session": "REGULAR",
   "coverage": {
    "inventory_count": 5646,
    "status_counts": {
     "PENDING": 5642,
     "EVALUATED": 4
    },
    "source_receipts": {
     "holdings": {
      "status": "COMPLETE",
      "observed_at": "2026-10-22"
     },
     "watchlist": {
      "status": "COMPLETE",
      "rows": 5639,
      "as_of": "2026-10-22T13:29:48.577555+00:00"
     },
     "reentry": {
      "status": "COMPLETE",
      "rows": 94,
      "membership_as_of": "2026-10-22T13:29:48.593899+00:00",
      "as_of": "2026-10-22T13:29:29.125074+00:00",
      "research_snapshot_rows": 92,
      "membership_basis": "reentry resistance preference plus 365-day exit ledger; uncapped"
     }
    }
   },
   "universe_census": {
    "inventory_count": 5646
   },
   "income_screen": {
    "reasons": {
     "PREMIUM_BELOW_FLOOR": {
      "count": 1,
      "symbols": [
       "SCHD"
      ]
     },
     "IV_UNKNOWN": {
      "count": 1,
      "symbols": [
       "DNP"
      ]
     },
     "NO_EXECUTABLE_CREDIT": {
      "count": 2,
      "symbols": [
       "XLU",
       "ACM"
      ]
     },
     "THESIS_ABANDONED": {
      "count": 1,
      "symbols": [
       "V"
      ]
     }
    },
    "total": 5,
    "drops": [
     {
      "symbol": "SCHD",
      "strategy": "covered_call",
      "reason": "PREMIUM_BELOW_FLOOR",
      "strike": 36.0,
      "premium": 0.08,
      "oi": 1025,
      "bid_ask_spread_pct": null
     },
     {
      "symbol": "DNP",
      "strategy": "any",
      "reason": "IV_UNKNOWN"
     },
     {
      "symbol": "XLU",
      "strategy": "credit_spread",
      "reason": "NO_EXECUTABLE_CREDIT",
      "detail": "sell 39.5p at bid 0.05 - buy 39p at ask 0.15 = -0.1 (mid 0.01)",
      "short_strike": 39.5,
      "long_strike": 39.0,
      "session": "PRE_MARKET"
     },
     {
      "symbol": "ACM",
      "strategy": "credit_spread",
      "reason": "NO_EXECUTABLE_CREDIT",
      "detail": "sell 55p at bid 0.0 - buy 52.5p at ask 2.95 = None (mid 0.05)",
      "short_strike": 55.0,
      "long_strike": 52.5,
      "session": "PRE_MARKET"
     },
     {
      "symbol": "V",
      "strategy": "protective_put",
      "reason": "THESIS_ABANDONED",
      "detail": "CIO asked for more research 3 times; archived rather than looping"
     }
    ],
    "liquidity_deferred": {
     "count": 3,
     "session": "PRE_MARKET",
     "symbols": [
      "SCHG",
      "XAR",
      "XLB"
     ],
     "note": "market closed: quotes are not live; liquidity is checked at the open"
    }
   },
   "entry_directional_dropped": [
    {
     "symbol": "AESI",
     "entry_state": "BUY_READY",
     "reason": "EDGE_BELOW",
     "edge_attempted": true
    },
    {
     "symbol": "ACM",
     "entry_state": "ENTRY_NEAR",
     "reason": "EDGE_BELOW",
     "edge_attempted": true
    }
   ],
   "scan_capacity": {
    "status": "DISABLED",
    "priority_symbol_count": 5646,
    "refresh_interval_minutes": 15.0,
    "minimum_chain_requests_per_minute": 376.4,
    "configured_requests_per_minute": null,
    "best_case_refresh_minutes": null,
    "provider_capacity_verified": false,
    "assumption": "One fresh request per distinct priority symbol; excludes retries and projection time.",
    "next_action": "Measure shared provider allowance and full-run throughput before enabling the existing worker."
   },
   "review_counts": {
    "READY_FOR_REVIEW": 0,
    "NEEDS_RESEARCH": 1,
    "NEEDS_DATA": 2,
    "BLOCKED": 2,
    "APPROVED_AWAITING_QUOTES": 0,
    "READY_FOR_PREFLIGHT": 0,
    "REJECTED_OR_EXPIRED": 0
   },
   "proposals": [
    {
     "id": "opt_protective_put_SPCX_account_a_148p0000_20261120_d20261022",
     "strategy": "protective_put",
     "symbol": "SPCX",
     "account": "account_a",
     "side": "BUY",
     "option_type": "put",
     "strike": 148.0,
     "expiration": "2026-11-20",
     "dte": 29,
     "contracts": 6,
     "premium": 4.65,
     "premium_total": 2790.0,
     "underlying_price": 154.12,
     "shares_held": 600.0,
     "breakeven": 158.77,
     "put_breakeven": 143.35,
     "floor_value": 86010.0,
     "edge_score": 68.4,
     "desk_tier": "B",
     "oi": 476,
     "volume": 0,
     "bid": 4.4,
     "ask": 4.65,
     "bid_ask_spread_pct": 5.52,
     "quote_time": "2026-10-21T20:00:00.269000+00:00",
     "premium_basis": "ask",
     "price_source": {
      "source": "schwab_chain_underlying",
      "as_of": "2026-10-22T13:30:02.416900+00:00",
      "replaced": 146.03
     },
     "market_session": "REGULAR",
     "chain_fetched_at": "2026-10-22T13:29:58.947068+00:00",
     "chain_age_seconds": 5228.4,
     "quote_age_seconds": 68227.1,
     "thesis_state": "POPULATED",
     "options_thesis": {
      "pin": "opt_19e3db3f-ea61-59a7-9091-a369ee6e58d9@v4",
      "version": 4,
      "missing_required": [],
      "pending_operator": [
       "position_sizing_rationale",
       "cio_approval_record"
      ],
      "thesis_gate_state": "POPULATED"
     },
     "thesis_blocks": [
      {
       "code": "awaiting_cio_decision",
       "reason": "no CIO decision issued yet"
      }
     ],
     "flags": [
      {
       "key": "INSURANCE",
       "label": "Insurance",
       "tone": "blue"
      },
      {
       "key": "NOT_APPROVABLE",
       "label": "Not approvable: awaiting CIO decision",
       "tone": "red"
      },
      {
       "key": "THESIS_COMPLETE",
       "label": "Thesis complete",
       "tone": "green"
      }
     ],
     "review_workflow": {
      "state": "BLOCKED",
      "reason": "option_chain_stale chain age 5228.4s exceeds cap",
      "next_action": "Resolve the recorded policy or evidence block",
      "owner": "CIO / operator",
      "live_submit": false,
      "decision_guid": null,
      "proposal_id": "opt_protective_put_SPCX_account_a_148p0000_20261120_d20261022",
      "option_strategy_guid": "19e3db3f-ea61-59a7-9091-a369ee6e58d9",
      "options_thesis_pin": "opt_19e3db3f-ea61-59a7-9091-a369ee6e58d9@v4",
      "decision_scope": "this strategy and account; ticker decisions are context only"
     },
     "purpose": "INSURANCE",
     "approvable": false,
     "broker": "schwab",
     "enterprise": {
      "live_eligible": false,
      "blocks": [
       {
        "code": "awaiting_cio_decision",
        "reason": "no CIO decision issued yet"
       },
       {
        "code": "quote_stale",
        "reason": "quote age 68227.1s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "quote_age_seconds": 68227.1
        }
       },
       {
        "code": "option_chain_stale",
        "reason": "chain age 5228.4s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "chain_age_seconds": 5228.4
        }
       }
      ],
      "liquidity": {
       "pass": true,
       "oi": 476,
       "volume": 0,
       "bid_ask_spread_pct": 5.52,
       "mid": 4.53,
       "issues": []
      },
      "earnings": {
       "in_blackout": false,
       "event_date": null
      }
     },
     "lifecycle": {
      "stage": "CIO_REVIEW_FAILED",
      "timeline": [
       {
        "stage": "CREATED",
        "at": "2026-10-22T09:15:49.568861+00:00",
        "pin": "opt_19e3db3f-ea61-59a7-9091-a369ee6e58d9@v1"
       },
       {
        "stage": "CIO_REVIEW_QUEUED",
        "at": "2026-10-22T09:22:02.222506+00:00",
        "status": "LLM_ERROR"
       },
       {
        "stage": "CIO_REVIEW_FAILED",
        "at": "2026-10-22T09:22:02.318188+00:00",
        "reason": "POLICY_NOT_ALLOWED",
        "status": "LLM_ERROR"
       },
       {
        "stage": "CIO_REVIEW_FAILED",
        "at": "2026-10-22T09:37:02.381599+00:00",
        "reason": "POLICY_NOT_ALLOWED",
        "status": "LLM_ERROR"
       },
       {
        "stage": "CIO_REVIEW_FAILED",
        "at": "2026-10-22T09:52:04.124893+00:00",
        "reason": "POLICY_NOT_ALLOWED",
        "status": "LLM_ERROR"
       }
      ]
     },
     "economics": {
      "floor_value_after_premium": 86010.0,
      "option_cost_total": 2790.0,
      "put_breakeven": 143.35,
      "hedged_max_loss_from_mark": 6462.0,
      "insured_shares": 600,
      "protection_scenarios": [
       {
        "move_pct": -30,
        "stock_pl": -27741.6,
        "hedged_pl": -6462.0,
        "loss_reduction": 21279.6
       },
       {
        "move_pct": -20,
        "stock_pl": -18494.4,
        "hedged_pl": -6462.0,
        "loss_reduction": 12032.4
       },
       {
        "move_pct": -10,
        "stock_pl": -9247.2,
        "hedged_pl": -6462.0,
        "loss_reduction": 2785.2
       }
      ]
     },
     "combined_exposure": {
      "symbol": "SPCX",
      "ideas": [
       {
        "id": "opt_protective_put_SPCX_account_a_148p0000_20261120_d20261022",
        "strategy": "protective_put",
        "account": "account_a",
        "strike": 148.0,
        "expiration": "2026-11-20",
        "contracts": 6
       },
       {
        "id": "opt_protective_put_SPCX_account_c_148p0000_20261120_d20261022",
        "strategy": "protective_put",
        "account": "account_c",
        "strike": 148.0,
        "expiration": "2026-11-20",
        "contracts": 2
       }
      ],
      "scenarios": [
       {
        "move_pct": -30,
        "price": 107.88,
        "options_only_pl": 28372.8,
        "shares_pl": -36988.8,
        "whole_position_pl": -8616.0
       },
       {
        "move_pct": -20,
        "price": 123.3,
        "options_only_pl": 16043.2,
        "shares_pl": -24659.2,
        "whole_position_pl": -8616.0
       },
       {
        "move_pct": -10,
        "price": 138.71,
        "options_only_pl": 3713.6,
        "shares_pl": -12329.6,
        "whole_position_pl": -8616.0
       },
       {
        "move_pct": 0,
        "price": 154.12,
        "options_only_pl": -3720.0,
        "shares_pl": 0.0,
        "whole_position_pl": -3720.0
       },
       {
        "move_pct": 10,
        "price": 169.53,
        "options_only_pl": -3720.0,
        "shares_pl": 12329.6,
        "whole_position_pl": 8609.6
       }
      ],
      "scenario_basis": "Hypothetical if all shown ideas were selected, not existing commitments. Options-only, shares and whole-position P/L at the same price on that expiration date; shares are marked from today's spot, no basis or fees"
     },
     "committee_memo": {
      "plain_summary": "This is insurance on your SPCX shares. Reduce the risk of shares you already own. You pay $2,790 for the right to sell 600 SPCX at $148 until 2026-11-20, however low the price goes. Breakeven at expiry: $143.35 (-7.0% from today's $154.12)."
     },
     "options_decision_packet": {
      "cio_approved": false,
      "model": {
       "ensemble_present": false,
       "note": "A model score is not a CIO disposition."
      }
     }
    },
    {
     "id": "opt_protective_put_SPCX_account_c_148p0000_20261120_d20261022",
     "strategy": "protective_put",
     "symbol": "SPCX",
     "account": "account_c",
     "side": "BUY",
     "option_type": "put",
     "strike": 148.0,
     "expiration": "2026-11-20",
     "dte": 29,
     "contracts": 2,
     "premium": 4.65,
     "premium_total": 930.0,
     "underlying_price": 154.12,
     "shares_held": 200.0,
     "breakeven": 158.77,
     "put_breakeven": 143.35,
     "floor_value": 28670.0,
     "edge_score": 68.4,
     "desk_tier": "B",
     "oi": 476,
     "volume": 0,
     "bid": 4.4,
     "ask": 4.65,
     "bid_ask_spread_pct": 5.52,
     "quote_time": "2026-10-21T20:00:00.269000+00:00",
     "premium_basis": "ask",
     "price_source": {
      "source": "schwab_chain_underlying",
      "as_of": "2026-10-22T13:30:02.416900+00:00",
      "replaced": 146.03
     },
     "market_session": "REGULAR",
     "chain_fetched_at": "2026-10-22T13:29:58.947068+00:00",
     "chain_age_seconds": 5228.4,
     "quote_age_seconds": 68227.1,
     "thesis_state": "POPULATED",
     "options_thesis": {
      "pin": "opt_f327c7ac-a016-59d6-9bc0-d6740e00a103@v4",
      "version": 4,
      "missing_required": [],
      "pending_operator": [
       "position_sizing_rationale",
       "cio_approval_record"
      ],
      "thesis_gate_state": "POPULATED"
     },
     "thesis_blocks": [
      {
       "code": "awaiting_cio_decision",
       "reason": "no CIO decision issued yet"
      }
     ],
     "flags": [
      {
       "key": "INSURANCE",
       "label": "Insurance",
       "tone": "blue"
      },
      {
       "key": "NOT_APPROVABLE",
       "label": "Not approvable: awaiting CIO decision",
       "tone": "red"
      },
      {
       "key": "THESIS_COMPLETE",
       "label": "Thesis complete",
       "tone": "green"
      }
     ],
     "review_workflow": {
      "state": "BLOCKED",
      "reason": "option_chain_stale chain age 5228.4s exceeds cap",
      "next_action": "Resolve the recorded policy or evidence block",
      "owner": "CIO / operator",
      "live_submit": false,
      "decision_guid": null,
      "proposal_id": "opt_protective_put_SPCX_account_c_148p0000_20261120_d20261022",
      "option_strategy_guid": "f327c7ac-a016-59d6-9bc0-d6740e00a103",
      "options_thesis_pin": "opt_f327c7ac-a016-59d6-9bc0-d6740e00a103@v4",
      "decision_scope": "this strategy and account; ticker decisions are context only"
     },
     "purpose": "INSURANCE",
     "approvable": false,
     "broker": "schwab",
     "enterprise": {
      "live_eligible": false,
      "blocks": [
       {
        "code": "awaiting_cio_decision",
        "reason": "no CIO decision issued yet"
       },
       {
        "code": "quote_stale",
        "reason": "quote age 68227.1s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "quote_age_seconds": 68227.1
        }
       },
       {
        "code": "option_chain_stale",
        "reason": "chain age 5228.4s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "chain_age_seconds": 5228.4
        }
       }
      ],
      "liquidity": {
       "pass": true,
       "oi": 476,
       "volume": 0,
       "bid_ask_spread_pct": 5.52,
       "mid": 4.53,
       "issues": []
      },
      "earnings": {
       "in_blackout": false,
       "event_date": null
      }
     },
     "lifecycle": {
      "stage": "CIO_REVIEW_FAILED",
      "timeline": [
       {
        "stage": "CREATED",
        "at": "2026-10-22T09:15:49.239704+00:00",
        "pin": "opt_f327c7ac-a016-59d6-9bc0-d6740e00a103@v1"
       },
       {
        "stage": "CIO_REVIEW_QUEUED",
        "at": "2026-10-22T09:22:02.522349+00:00",
        "status": "LLM_ERROR"
       },
       {
        "stage": "CIO_REVIEW_FAILED",
        "at": "2026-10-22T09:22:02.612896+00:00",
        "reason": "POLICY_NOT_ALLOWED",
        "status": "LLM_ERROR"
       },
       {
        "stage": "CIO_REVIEW_FAILED",
        "at": "2026-10-22T09:37:02.617473+00:00",
        "reason": "POLICY_NOT_ALLOWED",
        "status": "LLM_ERROR"
       },
       {
        "stage": "CIO_REVIEW_FAILED",
        "at": "2026-10-22T09:52:04.329623+00:00",
        "reason": "POLICY_NOT_ALLOWED",
        "status": "LLM_ERROR"
       }
      ]
     },
     "economics": {
      "floor_value_after_premium": 28670.0,
      "option_cost_total": 930.0,
      "put_breakeven": 143.35,
      "hedged_max_loss_from_mark": 2154.0,
      "insured_shares": 200,
      "protection_scenarios": [
       {
        "move_pct": -30,
        "stock_pl": -9247.2,
        "hedged_pl": -2154.0,
        "loss_reduction": 7093.2
       },
       {
        "move_pct": -20,
        "stock_pl": -6164.8,
        "hedged_pl": -2154.0,
        "loss_reduction": 4010.8
       },
       {
        "move_pct": -10,
        "stock_pl": -3082.4,
        "hedged_pl": -2154.0,
        "loss_reduction": 928.4
       }
      ]
     },
     "combined_exposure": {
      "symbol": "SPCX",
      "ideas": [
       {
        "id": "opt_protective_put_SPCX_account_a_148p0000_20261120_d20261022",
        "strategy": "protective_put",
        "account": "account_a",
        "strike": 148.0,
        "expiration": "2026-11-20",
        "contracts": 6
       },
       {
        "id": "opt_protective_put_SPCX_account_c_148p0000_20261120_d20261022",
        "strategy": "protective_put",
        "account": "account_c",
        "strike": 148.0,
        "expiration": "2026-11-20",
        "contracts": 2
       }
      ],
      "scenarios": [
       {
        "move_pct": -30,
        "price": 107.88,
        "options_only_pl": 28372.8,
        "shares_pl": -36988.8,
        "whole_position_pl": -8616.0
       },
       {
        "move_pct": -20,
        "price": 123.3,
        "options_only_pl": 16043.2,
        "shares_pl": -24659.2,
        "whole_position_pl": -8616.0
       },
       {
        "move_pct": -10,
        "price": 138.71,
        "options_only_pl": 3713.6,
        "shares_pl": -12329.6,
        "whole_position_pl": -8616.0
       },
       {
        "move_pct": 0,
        "price": 154.12,
        "options_only_pl": -3720.0,
        "shares_pl": 0.0,
        "whole_position_pl": -3720.0
       },
       {
        "move_pct": 10,
        "price": 169.53,
        "options_only_pl": -3720.0,
        "shares_pl": 12329.6,
        "whole_position_pl": 8609.6
       }
      ],
      "scenario_basis": "Hypothetical if all shown ideas were selected, not existing commitments. Options-only, shares and whole-position P/L at the same price on that expiration date; shares are marked from today's spot, no basis or fees"
     },
     "committee_memo": {
      "plain_summary": "This is insurance on your SPCX shares. Reduce the risk of shares you already own. You pay $930 for the right to sell 200 SPCX at $148 until 2026-11-20, however low the price goes. Breakeven at expiry: $143.35 (-7.0% from today's $154.12)."
     },
     "options_decision_packet": {
      "cio_approved": false,
      "model": {
       "ensemble_present": false,
       "note": "A model score is not a CIO disposition."
      }
     }
    },
    {
     "id": "opt_protective_put_SCHG_account_a_35p0000_20261218_d20261022",
     "strategy": "protective_put",
     "symbol": "SCHG",
     "account": "account_a",
     "side": "BUY",
     "option_type": "put",
     "strike": 35.0,
     "expiration": "2026-12-18",
     "dte": 57,
     "contracts": 20,
     "premium": 1.15,
     "premium_total": 2300.0,
     "underlying_price": 35.42,
     "shares_held": 2000.0,
     "breakeven": 36.57,
     "put_breakeven": 33.85,
     "floor_value": 67700.0,
     "edge_score": 65.6,
     "desk_tier": "B",
     "oi": 9,
     "volume": 1,
     "bid": 0.45,
     "ask": 1.15,
     "bid_ask_spread_pct": 87.5,
     "quote_time": "2026-10-22T13:30:01.579000+00:00",
     "premium_basis": "ask",
     "price_source": {
      "source": "schwab_chain_underlying",
      "as_of": "2026-10-22T13:30:02.420709+00:00",
      "replaced": 35.21
     },
     "market_session": "REGULAR",
     "chain_fetched_at": "2026-10-22T13:30:02.282330+00:00",
     "chain_age_seconds": 5225.1,
     "quote_age_seconds": 5225.8,
     "thesis_state": "POPULATED",
     "options_thesis": {
      "pin": "opt_57731a10-bada-5c1c-ab11-18b3a71aa856@v1",
      "version": 1,
      "missing_required": [],
      "pending_operator": [
       "position_sizing_rationale",
       "cio_approval_record"
      ],
      "thesis_gate_state": "POPULATED"
     },
     "thesis_blocks": [
      {
       "code": "awaiting_cio_decision",
       "reason": "no CIO decision issued yet"
      }
     ],
     "flags": [
      {
       "key": "INSURANCE",
       "label": "Insurance",
       "tone": "blue"
      },
      {
       "key": "NOT_APPROVABLE",
       "label": "Not approvable: enterprise block",
       "tone": "red"
      },
      {
       "key": "THESIS_COMPLETE",
       "label": "Thesis complete",
       "tone": "green"
      }
     ],
     "review_workflow": {
      "state": "NEEDS_DATA",
      "reason": "OI 9 < 50; volume 1 < 5; spread 87.5% > 12.0%",
      "next_action": "Validate quotes during the regular session",
      "owner": "Quote validation",
      "live_submit": false,
      "decision_guid": null,
      "proposal_id": "opt_protective_put_SCHG_account_a_35p0000_20261218_d20261022",
      "option_strategy_guid": "57731a10-bada-5c1c-ab11-18b3a71aa856",
      "options_thesis_pin": "opt_57731a10-bada-5c1c-ab11-18b3a71aa856@v1",
      "decision_scope": "this strategy and account; ticker decisions are context only"
     },
     "purpose": "INSURANCE",
     "approvable": false,
     "broker": "schwab",
     "enterprise": {
      "live_eligible": false,
      "blocks": [
       "OI 9 < 50",
       "volume 1 < 5",
       "spread 87.5% > 12.0%",
       {
        "code": "awaiting_cio_decision",
        "reason": "no CIO decision issued yet"
       },
       {
        "code": "quote_stale",
        "reason": "quote age 5225.8s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "quote_age_seconds": 5225.8
        }
       },
       {
        "code": "option_chain_stale",
        "reason": "chain age 5225.1s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "chain_age_seconds": 5225.1
        }
       }
      ],
      "liquidity": {
       "pass": false,
       "oi": 9,
       "volume": 1,
       "bid_ask_spread_pct": 87.5,
       "mid": 0.8,
       "issues": [
        "OI 9 < 50",
        "volume 1 < 5",
        "spread 87.5% > 12.0%"
       ]
      },
      "earnings": {
       "in_blackout": false,
       "event_date": null
      }
     },
     "lifecycle": {
      "stage": null,
      "timeline": []
     },
     "economics": {
      "floor_value_after_premium": 67700.0,
      "option_cost_total": 2300.0,
      "put_breakeven": 33.85,
      "hedged_max_loss_from_mark": 3140.0,
      "insured_shares": 2000,
      "protection_scenarios": [
       {
        "move_pct": -30,
        "stock_pl": -21252.0,
        "hedged_pl": -3140.0,
        "loss_reduction": 18112.0
       },
       {
        "move_pct": -20,
        "stock_pl": -14168.0,
        "hedged_pl": -3140.0,
        "loss_reduction": 11028.0
       },
       {
        "move_pct": -10,
        "stock_pl": -7084.0,
        "hedged_pl": -3140.0,
        "loss_reduction": 3944.0
       }
      ]
     },
     "combined_exposure": {
      "symbol": null,
      "ideas": null,
      "scenarios": null,
      "scenario_basis": null
     },
     "committee_memo": {
      "plain_summary": "This is insurance on your SCHG shares. Reduce the risk of shares you already own. You pay $2,300 for the right to sell 2000 SCHG at $35 until 2026-12-18, however low the price goes. Breakeven at expiry: $33.85 (-4.4% from today's $35.42)."
     },
     "options_decision_packet": {
      "cio_approved": false,
      "model": {
       "ensemble_present": false,
       "note": "A model score is not a CIO disposition."
      }
     }
    },
    {
     "id": "opt_protective_put_XAR_account_a_205p0000_20261218_d20261022",
     "strategy": "protective_put",
     "symbol": "XAR",
     "account": "account_a",
     "side": "BUY",
     "option_type": "put",
     "strike": 205.0,
     "expiration": "2026-12-18",
     "dte": 57,
     "contracts": 1,
     "premium": 5.6,
     "premium_total": 560.0,
     "underlying_price": 219.54,
     "shares_held": 100.0,
     "breakeven": 225.14,
     "put_breakeven": 199.4,
     "floor_value": 19940.0,
     "edge_score": 62.7,
     "desk_tier": "B",
     "oi": 0,
     "volume": 0,
     "bid": 1.0,
     "ask": 5.6,
     "bid_ask_spread_pct": 139.39,
     "quote_time": "2026-10-21T20:00:00.036000+00:00",
     "premium_basis": "ask",
     "price_source": {
      "source": "schwab_chain_underlying",
      "as_of": "2026-10-22T13:30:02.413171+00:00",
      "replaced": 224.53
     },
     "market_session": "REGULAR",
     "chain_fetched_at": "2026-10-22T13:30:00.870836+00:00",
     "chain_age_seconds": 5226.5,
     "quote_age_seconds": 68227.4,
     "thesis_state": "POPULATED",
     "options_thesis": {
      "pin": "opt_4b6b74c8-de3d-5593-be83-be924253e0b8@v1",
      "version": 1,
      "missing_required": [
       "exit_criteria"
      ],
      "pending_operator": [
       "position_sizing_rationale",
       "cio_approval_record"
      ],
      "thesis_gate_state": "POPULATED"
     },
     "thesis_blocks": [
      {
       "code": "thesis_missing_exit_criteria",
       "reason": "options thesis record has no exit criteria"
      }
     ],
     "flags": [
      {
       "key": "INSURANCE",
       "label": "Insurance",
       "tone": "blue"
      },
      {
       "key": "NOT_APPROVABLE",
       "label": "Not approvable: enterprise block",
       "tone": "red"
      },
      {
       "key": "THESIS_INCOMPLETE",
       "tone": "amber",
       "label": "Thesis missing: exit criteria"
      }
     ],
     "review_workflow": {
      "state": "NEEDS_RESEARCH",
      "reason": "Missing: exit_criteria",
      "next_action": "Complete the existing thesis and research gaps",
      "owner": "Research / CIO",
      "live_submit": false,
      "decision_guid": null,
      "proposal_id": "opt_protective_put_XAR_account_a_205p0000_20261218_d20261022",
      "option_strategy_guid": "4b6b74c8-de3d-5593-be83-be924253e0b8",
      "options_thesis_pin": "opt_4b6b74c8-de3d-5593-be83-be924253e0b8@v1",
      "decision_scope": "this strategy and account; ticker decisions are context only"
     },
     "purpose": "INSURANCE",
     "approvable": false,
     "broker": "schwab",
     "enterprise": {
      "live_eligible": false,
      "blocks": [
       "OI 0 < 50",
       "volume 0 < 5",
       "spread 139.4% > 12.0%",
       {
        "code": "thesis_missing_exit_criteria",
        "reason": "options thesis record has no exit criteria"
       },
       {
        "code": "quote_stale",
        "reason": "quote age 68227.4s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "quote_age_seconds": 68227.4
        }
       },
       {
        "code": "option_chain_stale",
        "reason": "chain age 5226.5s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "chain_age_seconds": 5226.5
        }
       }
      ],
      "liquidity": {
       "pass": false,
       "oi": 0,
       "volume": 0,
       "bid_ask_spread_pct": 139.39,
       "mid": 3.3,
       "issues": [
        "OI 0 < 50",
        "volume 0 < 5",
        "spread 139.4% > 12.0%"
       ]
      },
      "earnings": {
       "in_blackout": false,
       "event_date": null
      }
     },
     "lifecycle": {
      "stage": null,
      "timeline": []
     },
     "economics": {
      "floor_value_after_premium": 19940.0,
      "option_cost_total": 560.0,
      "put_breakeven": 199.4,
      "hedged_max_loss_from_mark": 2014.0,
      "insured_shares": 100,
      "protection_scenarios": [
       {
        "move_pct": -30,
        "stock_pl": -6586.2,
        "hedged_pl": -2014.0,
        "loss_reduction": 4572.2
       },
       {
        "move_pct": -20,
        "stock_pl": -4390.8,
        "hedged_pl": -2014.0,
        "loss_reduction": 2376.8
       },
       {
        "move_pct": -10,
        "stock_pl": -2195.4,
        "hedged_pl": -2014.0,
        "loss_reduction": 181.4
       }
      ]
     },
     "combined_exposure": {
      "symbol": null,
      "ideas": null,
      "scenarios": null,
      "scenario_basis": null
     },
     "committee_memo": {
      "plain_summary": "This is insurance on your XAR shares. Reduce the risk of shares you already own. You pay $560 for the right to sell 100 XAR at $205 until 2026-12-18, however low the price goes. Breakeven at expiry: $199.40 (-9.2% from today's $219.54)."
     },
     "options_decision_packet": {
      "cio_approved": false,
      "model": {
       "ensemble_present": false,
       "note": "A model score is not a CIO disposition."
      }
     }
    },
    {
     "id": "opt_protective_put_XLB_account_a_48p0000_20261218_d20261022",
     "strategy": "protective_put",
     "symbol": "XLB",
     "account": "account_a",
     "side": "BUY",
     "option_type": "put",
     "strike": 48.0,
     "expiration": "2026-12-18",
     "dte": 57,
     "contracts": 5,
     "premium": 0.67,
     "premium_total": 335.0,
     "underlying_price": 51.17,
     "shares_held": 506.327,
     "breakeven": 51.84,
     "put_breakeven": 47.33,
     "floor_value": 23665.0,
     "edge_score": 58.4,
     "desk_tier": "C",
     "oi": 2766,
     "volume": 0,
     "bid": 0.18,
     "ask": 0.67,
     "bid_ask_spread_pct": 115.29,
     "quote_time": "2026-10-21T20:15:00.089000+00:00",
     "premium_basis": "ask",
     "price_source": {
      "source": "schwab_chain_underlying",
      "as_of": "2026-10-22T13:30:02.409029+00:00",
      "replaced": null
     },
     "market_session": "REGULAR",
     "chain_fetched_at": "2026-10-22T13:30:00.233107+00:00",
     "chain_age_seconds": 5227.2,
     "quote_age_seconds": 67327.3,
     "thesis_state": "POPULATED",
     "options_thesis": {
      "pin": "opt_32fd863f-a3d5-5f87-8c6e-6ea59c755cff@v3",
      "version": 3,
      "missing_required": [],
      "pending_operator": [
       "position_sizing_rationale",
       "cio_approval_record"
      ],
      "thesis_gate_state": "POPULATED"
     },
     "thesis_blocks": [
      {
       "code": "awaiting_cio_decision",
       "reason": "no CIO decision issued yet"
      }
     ],
     "flags": [
      {
       "key": "INSURANCE",
       "label": "Insurance",
       "tone": "blue"
      },
      {
       "key": "NOT_APPROVABLE",
       "label": "Not approvable: enterprise block",
       "tone": "red"
      },
      {
       "key": "THESIS_COMPLETE",
       "label": "Thesis complete",
       "tone": "green"
      }
     ],
     "review_workflow": {
      "state": "NEEDS_DATA",
      "reason": "spread 114.0% > 12.0%",
      "next_action": "Validate quotes during the regular session",
      "owner": "Quote validation",
      "live_submit": false,
      "decision_guid": null,
      "proposal_id": "opt_protective_put_XLB_account_a_48p0000_20261218_d20261022",
      "option_strategy_guid": "32fd863f-a3d5-5f87-8c6e-6ea59c755cff",
      "options_thesis_pin": "opt_32fd863f-a3d5-5f87-8c6e-6ea59c755cff@v3",
      "decision_scope": "this strategy and account; ticker decisions are context only"
     },
     "purpose": "INSURANCE",
     "approvable": false,
     "broker": "schwab",
     "enterprise": {
      "live_eligible": false,
      "blocks": [
       "spread 114.0% > 12.0%",
       {
        "code": "awaiting_cio_decision",
        "reason": "no CIO decision issued yet"
       },
       {
        "code": "quote_stale",
        "reason": "quote age 67327.3s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "quote_age_seconds": 67327.3
        }
       },
       {
        "code": "option_chain_stale",
        "reason": "chain age 5227.2s exceeds cap",
        "severity": "hard",
        "source": "options_desk_enterprise",
        "function": "evaluate_hard_risk_blocks",
        "snapshot": {
         "chain_age_seconds": 5227.2
        }
       }
      ],
      "liquidity": {
       "pass": false,
       "oi": 2766,
       "volume": 0,
       "bid_ask_spread_pct": 113.95,
       "mid": 0.43,
       "issues": [
        "spread 114.0% > 12.0%"
       ]
      },
      "earnings": {
       "in_blackout": false,
       "event_date": null
      }
     },
     "lifecycle": {
      "stage": "CREATED",
      "timeline": [
       {
        "stage": "CREATED",
        "at": "2026-10-22T05:10:34.107007+00:00",
        "pin": "opt_32fd863f-a3d5-5f87-8c6e-6ea59c755cff@v1"
       }
      ]
     },
     "economics": {
      "floor_value_after_premium": 23665.0,
      "option_cost_total": 335.0,
      "put_breakeven": 47.33,
      "hedged_max_loss_from_mark": 1920.0,
      "insured_shares": 500,
      "protection_scenarios": [
       {
        "move_pct": -30,
        "stock_pl": -7675.5,
        "hedged_pl": -1920.0,
        "loss_reduction": 5755.5
       },
       {
        "move_pct": -20,
        "stock_pl": -5117.0,
        "hedged_pl": -1920.0,
        "loss_reduction": 3197.0
       },
       {
        "move_pct": -10,
        "stock_pl": -2558.5,
        "hedged_pl": -1920.0,
        "loss_reduction": 638.5
       }
      ]
     },
     "combined_exposure": {
      "symbol": null,
      "ideas": null,
      "scenarios": null,
      "scenario_basis": null
     },
     "committee_memo": {
      "plain_summary": "This is insurance on your XLB shares. Reduce the risk of shares you already own. You pay $335 for the right to sell 500 XLB at $48 until 2026-12-18, however low the price goes. Breakeven at expiry: $47.33 (-7.5% from today's $51.17)."
     },
     "options_decision_packet": {
      "cio_approved": false,
      "model": {
       "ensemble_present": false,
       "note": "A model score is not a CIO disposition."
      }
     }
    }
   ]
  }
 },
 "intents": {
  "ok": true,
  "data": {
   "status": "ok",
   "advisory_only": true,
   "mode": "send",
   "intents": [
    {
     "goals": [
      "accumulate",
      "income"
     ],
     "plays": {
      "leap_call": {
       "min_dte": 300,
       "min_delta": 0.7
      },
      "covered_call": {
       "dte": [
        20.0,
        50.0
       ],
       "delta": [
        0.03,
        0.2
       ],
       "accounts": {
        "account_c": 1,
        "account_a": 3
       },
       "min_strike": 230.0
      },
      "cash_secured_put": {
       "dte": [
        25.0,
        45.0
       ],
       "delta": [
        0.15,
        0.35
       ],
       "strike_max": 157.85
      }
     },
     "status": "active",
     "symbol": "SPCX",
     "created_at": "2026-10-05T16:59:53+00:00",
     "updated_at": "2026-10-05T16:59:53+00:00",
     "thesis_source": "Morgan Stanley (Adam Jonas) PT 300, bull 600; street consensus 236.71 (21 analysts)",
     "thesis_target": 300.0,
     "earnings_estimate": "2026-11-03",
     "avoid_earnings_cross": true,
     "directive_id": 17,
     "matches": {
      "contract": "options-intent-match-v1",
      "directive_id": 17,
      "symbol": "SPCX",
      "intent_updated_at": "2026-10-05T16:59:53+00:00",
      "as_of": "2026-10-22T14:45:02+00:00",
      "thesis_target": 300.0,
      "earnings": {
       "date": "2027-02-09",
       "source": "options desk earnings gate"
      },
      "plays": {
       "cash_secured_put": [
        {
         "contract": "SPCX  261120P00144000",
         "exp": "2026-11-20",
         "strike": 144.0,
         "dte": 29,
         "bid": 5.35,
         "ask": 5.45,
         "mid": 5.4,
         "iv": 50.12,
         "delta": -0.347,
         "oi": 149,
         "volume": 6,
         "spread_pct": 1.9,
         "quote_time": "2026-10-22T14:45:01.705000+00:00",
         "play": "cash_secured_put",
         "credit_per_contract": 540.0,
         "collateral_per_contract": 14400.0,
         "return_pct": 3.75,
         "annualized_pct": 47.2,
         "breakeven": 138.6,
         "breakeven_vs_spot_pct": -8.04,
         "delta_magnitude_pct": 35,
         "crosses_earnings": false,
         "contract_guid": "cc7e0fe1-a1fb-56ff-b1b9-fc0e7e844211",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "SPCX  261120P00143000",
         "exp": "2026-11-20",
         "strike": 143.0,
         "dte": 29,
         "bid": 5.0,
         "ask": 5.1,
         "mid": 5.05,
         "iv": 50.228,
         "delta": -0.33,
         "oi": 173,
         "volume": 40,
         "spread_pct": 2.0,
         "quote_time": "2026-10-22T14:45:02.324000+00:00",
         "play": "cash_secured_put",
         "credit_per_contract": 505.0,
         "collateral_per_contract": 14300.0,
         "return_pct": 3.531,
         "annualized_pct": 44.4,
         "breakeven": 137.95,
         "breakeven_vs_spot_pct": -8.47,
         "delta_magnitude_pct": 33,
         "crosses_earnings": false,
         "contract_guid": "add86e47-f0e5-5aed-8937-8e300fcabedc",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "SPCX  261120P00142000",
         "exp": "2026-11-20",
         "strike": 142.0,
         "dte": 29,
         "bid": 4.65,
         "ask": 4.75,
         "mid": 4.7,
         "iv": 50.548,
         "delta": -0.313,
         "oi": 757,
         "volume": 138,
         "spread_pct": 2.1,
         "quote_time": "2026-10-22T14:45:01.580000+00:00",
         "play": "cash_secured_put",
         "credit_per_contract": 470.0,
         "collateral_per_contract": 14200.0,
         "return_pct": 3.31,
         "annualized_pct": 41.7,
         "breakeven": 137.3,
         "breakeven_vs_spot_pct": -8.9,
         "delta_magnitude_pct": 31,
         "crosses_earnings": false,
         "contract_guid": "8c35e563-c6c7-503d-a339-4184dec5ec53",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "SPCX  261120P00141000",
         "exp": "2026-11-20",
         "strike": 141.0,
         "dte": 29,
         "bid": 4.3,
         "ask": 4.45,
         "mid": 4.375,
         "iv": 50.588,
         "delta": -0.296,
         "oi": 171,
         "volume": 38,
         "spread_pct": 3.4,
         "quote_time": "2026-10-22T14:45:01.580000+00:00",
         "play": "cash_secured_put",
         "credit_per_contract": 437.5,
         "collateral_per_contract": 14100.0,
         "return_pct": 3.103,
         "annualized_pct": 39.1,
         "breakeven": 136.625,
         "breakeven_vs_spot_pct": -9.35,
         "delta_magnitude_pct": 30,
         "crosses_earnings": false,
         "contract_guid": "30e572b4-ca91-5720-a435-f6377a0585c4",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "SPCX  261120P00140000",
         "exp": "2026-11-20",
         "strike": 140.0,
         "dte": 29,
         "bid": 4.0,
         "ask": 4.1,
         "mid": 4.05,
         "iv": 50.851,
         "delta": -0.279,
         "oi": 20468,
         "volume": 2205,
         "spread_pct": 2.5,
         "quote_time": "2026-10-22T14:45:02.189000+00:00",
         "play": "cash_secured_put",
         "credit_per_contract": 405.0,
         "collateral_per_contract": 14000.0,
         "return_pct": 2.893,
         "annualized_pct": 36.4,
         "breakeven": 135.95,
         "breakeven_vs_spot_pct": -9.8,
         "delta_magnitude_pct": 28,
         "crosses_earnings": false,
         "contract_guid": "8d04869c-1b62-5dca-b777-cd8459ea9bd2",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        }
       ],
       "covered_call": [],
       "leap_call": [
        {
         "contract": "SPCX  281215C00100000",
         "exp": "2028-12-15",
         "strike": 100.0,
         "dte": 785,
         "bid": 74.4,
         "ask": 75.95,
         "mid": 75.175,
         "iv": 49.31,
         "delta": 0.83,
         "oi": 8137,
         "volume": 73,
         "spread_pct": 2.1,
         "quote_time": "2026-10-22T14:45:01.731000+00:00",
         "play": "leap_call",
         "cost_per_contract": 7517.5,
         "stock_cost_100": 15071.0,
         "time_value": 24.465,
         "time_value_pct": 16.23,
         "contract_guid": "41fd0476-bc81-5667-a8bc-cd56ef17d801",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "SPCX  271217C00120000",
         "exp": "2027-12-17",
         "strike": 120.0,
         "dte": 421,
         "bid": 51.15,
         "ask": 52.25,
         "mid": 51.7,
         "iv": 48.989,
         "delta": 0.758,
         "oi": 4529,
         "volume": 2,
         "spread_pct": 2.1,
         "quote_time": "2026-10-22T14:45:02.076000+00:00",
         "play": "leap_call",
         "cost_per_contract": 5170.0,
         "stock_cost_100": 15071.0,
         "time_value": 20.99,
         "time_value_pct": 13.93,
         "contract_guid": "21aac90a-0dbe-5bde-adf1-19ceb2bd588a",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "SPCX  281215C00130000",
         "exp": "2028-12-15",
         "strike": 130.0,
         "dte": 785,
         "bid": 59.95,
         "ask": 60.9,
         "mid": 60.425,
         "iv": 46.726,
         "delta": 0.719,
         "oi": 4143,
         "volume": 2,
         "spread_pct": 1.6,
         "quote_time": "2026-10-22T14:45:02.204000+00:00",
         "play": "leap_call",
         "cost_per_contract": 6042.5,
         "stock_cost_100": 15071.0,
         "time_value": 39.715,
         "time_value_pct": 26.35,
         "contract_guid": "5b7400ed-da03-5f33-849c-0e8b82f496df",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "SPCX  271217C00125000",
         "exp": "2027-12-17",
         "strike": 125.0,
         "dte": 421,
         "bid": 48.35,
         "ask": 49.45,
         "mid": 48.9,
         "iv": 48.418,
         "delta": 0.734,
         "oi": 3210,
         "volume": 6,
         "spread_pct": 2.2,
         "quote_time": "2026-10-22T14:45:02.365000+00:00",
         "play": "leap_call",
         "cost_per_contract": 4890.0,
         "stock_cost_100": 15071.0,
         "time_value": 23.19,
         "time_value_pct": 15.39,
         "contract_guid": "b415b0a0-614e-5fd5-8890-4809e5112ab5",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        }
       ]
      },
      "errors": [],
      "shares_by_account": {
       "account_c": 200.0,
       "account_a": 600.0
      },
      "spot": 150.72,
      "quote_time": "2026-10-22T14:45:02.204000+00:00",
      "covered_call_floor": 230.0,
      "empty_reasons": {
       "covered_call": "no liquid contract fits DTE [20.0, 50.0] \u00b7 delta [0.03, 0.2] \u00b7 strike \u2265 230.0 \u00b7 expiring before earnings 2027-02-09"
      }
     }
    },
    {
     "goals": [],
     "plays": {
      "leap_call": {
       "min_dte": 300,
       "min_delta": 0.7
      }
     },
     "source": "operator",
     "status": "active",
     "symbol": "NFLX",
     "created_at": "2026-10-06T13:18:48.144854+00:00",
     "updated_at": "2026-10-06T13:18:48.144870+00:00",
     "thesis_source": null,
     "thesis_target": null,
     "earnings_estimate": null,
     "avoid_earnings_cross": false,
     "directive_id": 1311,
     "matches": {
      "contract": "options-intent-match-v1",
      "directive_id": 1311,
      "symbol": "NFLX",
      "intent_updated_at": "2026-10-06T13:18:48.144870+00:00",
      "as_of": "2026-10-22T14:45:06+00:00",
      "thesis_target": null,
      "earnings": {
       "date": "2027-01-19",
       "source": "options desk earnings gate"
      },
      "plays": {
       "leap_call": [
        {
         "contract": "NFLX  281215C00050000",
         "exp": "2028-12-15",
         "strike": 50.0,
         "dte": 785,
         "bid": 25.65,
         "ask": 26.5,
         "mid": 26.075,
         "iv": 33.041,
         "delta": 0.815,
         "oi": 3731,
         "volume": 1,
         "spread_pct": 3.3,
         "quote_time": "2026-10-22T14:45:07.034000+00:00",
         "play": "leap_call",
         "cost_per_contract": 2607.5,
         "stock_cost_100": 6607.0,
         "time_value": 10.005,
         "time_value_pct": 15.14,
         "contract_guid": "5b93cae2-8ff3-590c-ac16-3ed7a000b67f",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "NFLX  281215C00040000",
         "exp": "2028-12-15",
         "strike": 40.0,
         "dte": 785,
         "bid": 32.2,
         "ask": 33.6,
         "mid": 32.9,
         "iv": 35.096,
         "delta": 0.91,
         "oi": 2455,
         "volume": 1,
         "spread_pct": 4.3,
         "quote_time": "2026-10-22T14:45:01.288000+00:00",
         "play": "leap_call",
         "cost_per_contract": 3290.0,
         "stock_cost_100": 6607.0,
         "time_value": 6.83,
         "time_value_pct": 10.34,
         "contract_guid": "55eea040-08e8-5b3d-8ed0-bf5e7ce9964e",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "NFLX  280616C00040000",
         "exp": "2028-06-16",
         "strike": 40.0,
         "dte": 603,
         "bid": 30.8,
         "ask": 32.0,
         "mid": 31.4,
         "iv": 36.349,
         "delta": 0.924,
         "oi": 1788,
         "volume": 1,
         "spread_pct": 3.8,
         "quote_time": "2026-10-22T14:45:07.039000+00:00",
         "play": "leap_call",
         "cost_per_contract": 3140.0,
         "stock_cost_100": 6607.0,
         "time_value": 5.33,
         "time_value_pct": 8.07,
         "contract_guid": "c5eb1f12-a106-5542-bbc2-e080415ecf60",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        },
        {
         "contract": "NFLX  280616C00050000",
         "exp": "2028-06-16",
         "strike": 50.0,
         "dte": 603,
         "bid": 23.65,
         "ask": 24.65,
         "mid": 24.15,
         "iv": 33.762,
         "delta": 0.827,
         "oi": 1554,
         "volume": 15,
         "spread_pct": 4.1,
         "quote_time": "2026-10-22T14:45:06.030000+00:00",
         "play": "leap_call",
         "cost_per_contract": 2415.0,
         "stock_cost_100": 6607.0,
         "time_value": 8.08,
         "time_value_pct": 12.23,
         "contract_guid": "ea90d013-fcf6-57cd-84e5-b311e16b0005",
         "desk_status": "NOT_STAGED",
         "next_action": "Account allocation and an account-specific thesis are required before proposal review"
        }
       ]
      },
      "errors": [],
      "shares_by_account": {},
      "spot": 66.07,
      "quote_time": "2026-10-22T14:45:07.112000+00:00",
      "empty_reasons": {}
     }
    }
   ],
   "match_count": 13,
   "unstaged_count": 13
  }
 },
 "execStatus": {
  "ok": true,
  "data": {
   "options_execution_enabled": true,
   "policy_ENABLED_commit": true,
   "armed_for_execution": true,
   "approve_phrase": "APPROVE OPTIONS EXECUTION 2026-10-22",
   "revoke_phrase": "REVOKE OPTIONS EXECUTION",
   "note": "Both DB approve AND options_execution_policy.ENABLED=True commit required for live submit."
  }
 },
 "openPositions": {
  "ok": true,
  "data": {
   "monitored_at": "2026-10-22T13:30:17.089481+00:00",
   "position_count": 0,
   "still_working": 0,
   "needs_action_count": 0,
   "book_greeks": {
    "leg_count": 0,
    "net_delta_shares": 0.0,
    "net_delta_notional": 0.0,
    "net_gamma": 0.0,
    "net_theta_per_day": 0.0,
    "net_vega": 0.0,
    "by_underlying": {}
   },
   "positions": [],
   "alerts": [],
   "summary": {
    "itm_count": 0,
    "otm_count": 0,
    "total_unrealized_pnl": 0
   },
   "filtered_count": 0,
   "filter_facets": {
    "total": 0,
    "by_source": {},
    "by_route": {},
    "by_broker": {},
    "by_option_type": {},
    "by_side": {},
    "needs_action": 0,
    "paper_only": 0
   },
   "unified_count": 0,
   "monitored_count": 0,
   "paper_lab_retired": true
  }
 }
}
