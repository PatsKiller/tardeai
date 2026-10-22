/** Watch prospects fixture, captured 2026-10-22 ~11:30 ET. 'prospects' is the output of scripts/lib/data_broker/watch_prospects.build_watch_prospects run over the captured live payloads (Watch cards, cio_opportunity_projection, re-entry desk) with small lane caps so the fixture stays short; 'alerts' is the captured GET /api/v2/watch/alerts/list (active rows). Test-only. Regenerate only from a real capture, never by hand-editing numbers.
 *  Lives outside src/lib so the UI-standards colour scan does not read symbols like '#129' as colours. */
/* eslint-disable */
export const FIXTURE: { prospects: any; alerts: any } = {
 "prospects": {
  "ok": true,
  "schema": "WatchProspects@v1",
  "generated_at": "2026-10-22T15:30:00+00:00",
  "source": "interim_adapter",
  "interim": true,
  "source_label": "interim — CIO prospect store not live",
  "sources": {
   "conviction": {
    "store": "data/cio/cio_opportunity_projection.json",
    "domain": "opportunity_assessment",
    "as_of": "2026-10-22T15:00:24.699999+00:00"
   },
   "stage": {
    "projection": "watch_intelligence.compose_universe",
    "standards": "watch_decision.v1"
   },
   "trade_ai": {
    "projection": "rockville decision_projection"
   },
   "held": {
    "reader": "watch_domains.held_positions(surface='watch')",
    "source": "positions_store.positions_current",
    "as_of": null,
    "stale": null
   },
   "reentry": {
    "projection": "reentry_decision_desk",
    "rows": 92
   }
  },
  "curation": {
   "one_membership": true,
   "caps": {
    "actionable": 5,
    "forming": 6,
    "reentry": 6,
    "manage": 8,
    "expired": 5
   },
   "sort_order": "lane, then conviction (high first), then decision priority",
   "expiry": "a non-held name whose decision expired or was invalidated is Expired; held names stay in Manage"
  },
  "lanes": [
   {
    "id": "actionable",
    "label": "Actionable now",
    "hint": "can be proposed",
    "count": 5,
    "cap": 5,
    "items": [
     {
      "symbol": "CACI",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Caci International Inc",
      "lane": "actionable",
      "stage": "actionable",
      "why": "Re-entry desk: ready to review",
      "summary": "Re-entry desk: ready to review. Previously owned; conviction 71 with R:R 3.4x — a re-entry would make sense if the setup confirms.",
      "conviction": 70.7,
      "conviction_rank": 361,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 71.9,
        "weight": 0.22,
        "detail": "RSI 48, neutral, confluence 0; strategy-qualified, base 87",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 80.1,
        "weight": 0.22,
        "detail": "R:R 3.4x · risk 3.13% · reward 10.67%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 80.7,
        "weight": 0.18,
        "detail": "buy · 15 analysts · +19.0% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 52.6,
        "weight": 0.15,
        "detail": "1W +0.9%, 1M +0.6%, RVOL 0.88",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.425070+00:00",
      "conviction_stale": false,
      "stance": "RE_ENTER",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Not on the Watch universe — seen only by the re-entry desk",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $620.00–$628.00",
       "level_ref": 620.0,
       "inside": true,
       "distance_pct": null,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "propose",
       "label": "Propose",
       "href": null,
       "seed": {
        "entry_ref": 628.0,
        "stop_ref": 604.0,
        "target_ref": 690.0
       },
       "reason": "Opens the existing Propose form. You size it; it goes to Proposals for your approval."
      },
      "price": 624.7,
      "price_as_of": "2026-10-22T15:00:03.429441+00:00",
      "rsi": 54.4,
      "held": false,
      "trade_ai_state": null,
      "decision": null,
      "reentry_state": "READY TO REVIEW",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "—",
        "source": "rockville decision_projection",
        "joined": false
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#361 · 71 · RE_ENTER",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Ready To Review",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.425070+00:00",
      "expires_at": "2026-10-26T15:00:03.429441+00:00",
      "stale": false
     },
     {
      "symbol": "BXMT",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Blackstone Mortgage Trust, Inc.",
      "lane": "actionable",
      "stage": "actionable",
      "why": "Review entry",
      "summary": "Review entry. Not owned; conviction 66 — worth tracking until the factors or the setup improve.",
      "conviction": 66.1,
      "conviction_rank": 577,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 53.9,
        "weight": 0.22,
        "detail": "RSI 33, bearish, confluence 0; strategy-qualified, base 71",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 100.0,
        "weight": 0.22,
        "detail": "R:R 5.1x · risk 5.27% · reward 26.83%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 85.0,
        "weight": 0.18,
        "detail": "buy · 7 analysts · +59.2% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 16.6,
        "weight": 0.15,
        "detail": "1W -5.4%, 1M -18.9%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.423562+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $10.12–$10.66",
       "level_ref": 10.12,
       "inside": true,
       "distance_pct": null,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "propose",
       "label": "Propose",
       "href": null,
       "seed": {
        "entry_ref": 10.66,
        "stop_ref": 9.71,
        "target_ref": 13.0
       },
       "reason": "Opens the existing Propose form. You size it; it goes to Proposals for your approval."
      },
      "price": 10.545,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 19.4,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 75.2,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#577 · 66 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.423562+00:00",
      "expires_at": "2026-10-23T18:36:06.670173-04:00",
      "stale": false
     },
     {
      "symbol": "ACIO",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "The fund is an actively-managed exchange-traded fund (“ETF”) that seeks to achieve its investment objective principally by investing in a portfolio of U.S.-listed equity securities of any market capitalization and buying put options or an options collar on the same underlying equity securities",
      "lane": "actionable",
      "stage": "actionable",
      "why": "Review entry",
      "summary": "Review entry. Not owned; conviction 65 — worth tracking until the factors or the setup improve.",
      "conviction": 64.7,
      "conviction_rank": 642,
      "conviction_coverage": 0.5,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 78.0,
        "weight": 0.22,
        "detail": "RSI 52, bullish; technical posture, base 68",
        "source": "hermes_score_components"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 49.4,
        "weight": 0.15,
        "detail": "1W -0.2%, 1M -0.1%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental",
       "analyst",
       "risk_reward"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.375476+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Analyst factor not scored",
       "Risk reward factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $46.85–$47.15",
       "level_ref": 46.85,
       "inside": true,
       "distance_pct": null,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "propose",
       "label": "Propose",
       "href": null,
       "seed": {
        "entry_ref": 47.15,
        "stop_ref": 46.55,
        "target_ref": 47.9
       },
       "reason": "Opens the existing Propose form. You size it; it goes to Proposals for your approval."
      },
      "price": 47.11,
      "price_as_of": "2026-10-22T11:00:58.016594-04:00",
      "rsi": 52.17,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 64.3,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#642 · 65 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.375476+00:00",
      "expires_at": "2026-10-24T17:50:20.472236-04:00",
      "stale": false
     },
     {
      "symbol": "AESI",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Atlas Energy Solutions Inc. produces proppants and",
      "lane": "actionable",
      "stage": "actionable",
      "why": "Review entry",
      "summary": "Review entry. Not owned; conviction 53 — worth tracking until the factors or the setup improve.",
      "conviction": 53.2,
      "conviction_rank": 1065,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 30.4,
        "weight": 0.22,
        "detail": "RSI 28, bearish, confluence 0; technical posture, base 40",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 90.9,
        "weight": 0.22,
        "detail": "R:R 4.3x · risk 8.06% · reward 34.41%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 80.4,
        "weight": 0.18,
        "detail": "buy · 13 analysts · +103.6% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 5.8,
        "weight": 0.15,
        "detail": "1W -10.3%, 1M -19.7%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 34.2,
        "weight": 0.1,
        "detail": "ROE -0.0993, ProfitMargin -0.1108",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.380340+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $9.15–$9.50 (+6.3%)",
       "level_ref": 9.15,
       "inside": false,
       "distance_pct": 6.3,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "propose",
       "label": "Propose",
       "href": null,
       "seed": {
        "entry_ref": 9.5,
        "stop_ref": 8.55,
        "target_ref": 12.5
       },
       "reason": "Opens the existing Propose form. You size it; it goes to Proposals for your approval."
      },
      "price": 8.61,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 27.73,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 66.9,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#1065 · 53 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.380340+00:00",
      "expires_at": "2026-10-24T17:32:23.242182-04:00",
      "stale": false
     },
     {
      "symbol": "NVST",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Envista Holdings Corporation, together with its subsidiaries, develops, manufactures, markets, and sells dental products in the United States, China, and internationally. The company",
      "lane": "actionable",
      "stage": "actionable",
      "why": "Review entry",
      "summary": "Review entry. No live decision packet.",
      "conviction": null,
      "conviction_rank": null,
      "conviction_coverage": null,
      "conviction_components": [],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": null,
      "conviction_stale": false,
      "stance": null,
      "stance_family": null,
      "whats_missing": [
       "No CIO conviction yet — not in the curator's universe",
       "No complete entry plan (zone and invalidation)",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "—",
       "level_ref": null,
       "inside": false,
       "distance_pct": null,
       "observed_by": null
      },
      "next_action": {
       "kind": "propose",
       "label": "Propose",
       "href": null,
       "seed": {
        "entry_ref": null,
        "stop_ref": null,
        "target_ref": null
       },
       "reason": "Opens the existing Propose form. You size it; it goes to Proposals for your approval."
      },
      "price": 23.705,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 36.49,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 62.2,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "not in the curator universe",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-19T19:48:21.893025-04:00",
      "expires_at": "2026-10-23T19:48:21.893025-04:00",
      "stale": false
     }
    ],
    "overflow": []
   },
   {
    "id": "forming",
    "label": "Setup forming",
    "hint": "distance to trigger",
    "count": 90,
    "cap": 6,
    "items": [
     {
      "symbol": "ABLV",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Able View Global Inc.",
      "lane": "forming",
      "stage": "setup_forming",
      "why": "Setup not confirmed yet",
      "summary": "Setup not confirmed yet. Not owned; conviction 76 — worth tracking until the factors or the setup improve.",
      "conviction": 76.3,
      "conviction_rank": 117,
      "conviction_coverage": 0.72,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 67.5,
        "weight": 0.22,
        "detail": "RSI 56, bullish, confluence 0; strategy-qualified, base 63",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 78.6,
        "weight": 0.22,
        "detail": "R:R 3.3x · risk 25.93% · reward 85.19%",
        "source": "risk_reward"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 100.0,
        "weight": 0.15,
        "detail": "1W +1.0%, 1M +117.5%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental",
       "analyst"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.373192+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Analyst factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $1.30–$1.40 (-34.0%)",
       "level_ref": 1.4,
       "inside": false,
       "distance_pct": -34.0,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 2.12,
        "rsi": 55.79,
        "entry_low_ref": 1.3,
        "entry_high_ref": 1.4
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 2.12,
      "price_as_of": "2026-10-22T11:00:38.874067-04:00",
      "rsi": 55.79,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "candidate",
       "category_label": "Watchlist Candidate",
       "priority": "medium",
       "priority_score": 48.0,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#117 · 76 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.373192+00:00",
      "expires_at": "2026-10-28T18:29:50.611717-04:00",
      "stale": false
     },
     {
      "symbol": "RARE",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Ultragenyx Pharmaceutical Inc.",
      "lane": "forming",
      "stage": "setup_forming",
      "why": "Setup not confirmed yet",
      "summary": "Setup not confirmed yet. Not owned; conviction 74 — worth tracking until the factors or the setup improve.",
      "conviction": 73.7,
      "conviction_rank": 215,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 50.3,
        "weight": 0.22,
        "detail": "RSI 34, bearish, confluence 0; strategy-qualified, base 63",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 100.0,
        "weight": 0.22,
        "detail": "R:R 6.9x · risk 7.12% · reward 49.15%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 85.0,
        "weight": 0.18,
        "detail": "buy · 19 analysts · +76.9% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 67.8,
        "weight": 0.15,
        "detail": "1W +4.8%, 1M +6.7%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.576049+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $14.50–$15.00 (-6.8%)",
       "level_ref": 15.0,
       "inside": false,
       "distance_pct": -6.8,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 16.1,
        "rsi": 42.23,
        "entry_low_ref": 14.5,
        "entry_high_ref": 15.0
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 16.1,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 42.23,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "candidate",
       "category_label": "Watchlist Candidate",
       "priority": "medium",
       "priority_score": 44.0,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#215 · 74 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.576049+00:00",
      "expires_at": "2026-10-27T18:31:49.426871-04:00",
      "stale": false
     },
     {
      "symbol": "ABM",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "ABM Industries Incorporated, through its subsidiaries",
      "lane": "forming",
      "stage": "setup_forming",
      "why": "Setup not confirmed yet",
      "summary": "Setup not confirmed yet. Not owned; conviction 73 — worth tracking until the factors or the setup improve.",
      "conviction": 73.1,
      "conviction_rank": 240,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 91.2,
        "weight": 0.22,
        "detail": "RSI 63, bullish; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 84.1,
        "weight": 0.22,
        "detail": "R:R 3.7x · risk 2.35% · reward 8.74%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 57.6,
        "weight": 0.18,
        "detail": "none · 7 analysts · +6.1% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 61.6,
        "weight": 0.15,
        "detail": "1W +2.8%, 1M +5.1%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 70.9,
        "weight": 0.1,
        "detail": "ROE 0.0919, ProfitMargin 0.0182, ForwardPE 11.56",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.373363+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "No fresh entry plan, synthesis or review",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $46.70–$47.10 (-11.4%)",
       "level_ref": 47.1,
       "inside": false,
       "distance_pct": -11.4,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 53.19,
        "rsi": 71.61,
        "entry_low_ref": 46.7,
        "entry_high_ref": 47.1
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 53.19,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 71.61,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "candidate",
       "category_label": "Watchlist Candidate",
       "priority": "medium",
       "priority_score": 42.4,
       "status": "needs_data",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#240 · 73 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.373363+00:00",
      "expires_at": null,
      "stale": false
     },
     {
      "symbol": "ARHS",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Arhaus, Inc.",
      "lane": "forming",
      "stage": "setup_forming",
      "why": "Setup not confirmed yet",
      "summary": "Setup not confirmed yet. Not owned; conviction 69 — worth tracking until the factors or the setup improve.",
      "conviction": 69.2,
      "conviction_rank": 432,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 66.5,
        "weight": 0.22,
        "detail": "RSI 59, bullish, confluence 0; strategy-qualified, base 63",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 75.0,
        "weight": 0.22,
        "detail": "R:R 3.0x · risk 6.52% · reward 19.57%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 59.1,
        "weight": 0.18,
        "detail": "buy · 13 analysts · -7.7% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 84.9,
        "weight": 0.15,
        "detail": "1W +8.2%, 1M +15.4%, RVOL 0.67",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.396870+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $9.05–$9.35 (-18.9%)",
       "level_ref": 9.35,
       "inside": false,
       "distance_pct": -18.9,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 11.53,
        "rsi": 67.57,
        "entry_low_ref": 9.05,
        "entry_high_ref": 9.35
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 11.53,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 67.57,
      "held": false,
      "trade_ai_state": "STALE",
      "decision": {
       "rule_id": "candidate",
       "category_label": "Watchlist Candidate",
       "priority": "medium",
       "priority_score": 48.0,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "STALE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#432 · 69 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.396870+00:00",
      "expires_at": "2026-10-26T19:42:09.758791-04:00",
      "stale": false
     },
     {
      "symbol": "CRL",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Charles River Laboratories International, Inc.",
      "lane": "forming",
      "stage": "setup_forming",
      "why": "Setup not confirmed yet",
      "summary": "Setup not confirmed yet. Not owned; conviction 68 — worth tracking until the factors or the setup improve.",
      "conviction": 68.5,
      "conviction_rank": 466,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 72.8,
        "weight": 0.22,
        "detail": "RSI 76, bullish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 50.0,
        "weight": 0.22,
        "detail": "R:R 2.0x · risk 4.5% · reward 9.0%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 65.7,
        "weight": 0.18,
        "detail": "buy · 15 analysts · -8.5% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 100.0,
        "weight": 0.15,
        "detail": "1W +12.5%, 1M +24.3%, RVOL 0.69",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.442094+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $285.00–$292.00 (-16.5%)",
       "level_ref": 292.0,
       "inside": false,
       "distance_pct": -16.5,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 349.7,
        "rsi": 75.59,
        "entry_low_ref": 285.0,
        "entry_high_ref": 292.0
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 349.7,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 75.59,
      "held": false,
      "trade_ai_state": "STALE",
      "decision": {
       "rule_id": "plan_near",
       "category_label": "Reward",
       "priority": "medium",
       "priority_score": 62.0,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "STALE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#466 · 68 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.442094+00:00",
      "expires_at": "2026-10-23T19:32:17.614848-04:00",
      "stale": false
     },
     {
      "symbol": "AMWL",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "American Well Corporation, an enterprise platform and software company, delivers digitally enabling hybrid care in the United States and internationally. The company offers Amwell Platform",
      "lane": "forming",
      "stage": "setup_forming",
      "why": "Setup not confirmed yet",
      "summary": "Setup not confirmed yet. Not owned; conviction 68 — worth tracking until the factors or the setup improve.",
      "conviction": 68.3,
      "conviction_rank": 471,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 70.5,
        "weight": 0.22,
        "detail": "RSI 59, bullish, confluence 0; strategy-qualified, base 71",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 85.2,
        "weight": 0.22,
        "detail": "R:R 3.8x · risk 5.96% · reward 22.81%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 37.6,
        "weight": 0.18,
        "detail": "none · 5 analysts · -9.9% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 84.4,
        "weight": 0.15,
        "detail": "1W +13.0%, 1M +7.0%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.393104+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "No fresh entry plan, synthesis or review",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $11.20–$11.60 (-19.0%)",
       "level_ref": 11.6,
       "inside": false,
       "distance_pct": -19.0,
       "observed_by": "entry plan"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 14.315,
        "rsi": 47.43,
        "entry_low_ref": 11.2,
        "entry_high_ref": 11.6
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 14.315,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 47.43,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "candidate",
       "category_label": "Watchlist Candidate",
       "priority": "medium",
       "priority_score": 47.0,
       "status": "needs_data",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#471 · 68 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.393104+00:00",
      "expires_at": null,
      "stale": false
     }
    ],
    "overflow": [
     "AAME",
     "AMGN",
     "XLU",
     "ABOVE",
     "ACII",
     "DBGI",
     "ABSZX",
     "ACLX",
     "ABG",
     "ACLS",
     "ACCO",
     "TX",
     "ABOS",
     "AAMI",
     "ABCB",
     "SWBI",
     "AAAU",
     "AAEQ",
     "AAVM",
     "AAXJ",
     "AB",
     "ABLS",
     "ABR",
     "ACCL",
     "ACEI",
     "ACES",
     "ACGO",
     "ACIW",
     "PRGO",
     "ACLC",
     "RYAM",
     "AAPB",
     "IEP",
     "XLE",
     "AAPX",
     "AAUM",
     "ACIU",
     "ACLZ",
     "XLK",
     "AAPE",
     "ABEQ",
     "ABLG",
     "JBTM",
     "EQX",
     "ABIG",
     "JAN",
     "XLF",
     "ACDC",
     "ACHX",
     "ABCS",
     "AAPY",
     "ACCS",
     "ABFL",
     "ACKY",
     "ABVE",
     "ABLD",
     "AACO",
     "AAT",
     "ACGC",
     "AACB",
     "AACPU",
     "AB-DISC-Z",
     "ABNY",
     "ACGCU",
     "ABB",
     "ABNG",
     "ABI",
     "AACP",
     "AAUS",
     "AACI",
     "AAAD",
     "AAUA",
     "ABUF",
     "AADR",
     "AAAA",
     "ACGR",
     "ABOT",
     "AAPR",
     "ACEP",
     "AAA",
     "AAAP",
     "ABXB",
     "ACLO",
     "AAAC"
    ]
   },
   {
    "id": "reentry",
    "label": "Re-entry near",
    "hint": "sold, near your level",
    "count": 19,
    "cap": 6,
    "items": [
     {
      "symbol": "DT",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Dynatrace, Inc.",
      "lane": "reentry",
      "stage": "re_entry",
      "why": "Sold; near your re-entry level",
      "summary": "Sold; near your re-entry level. Previously owned; conviction 79 with R:R 5.4x — a re-entry would make sense if the setup confirms.",
      "conviction": 78.8,
      "conviction_rank": 45,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 78.8,
        "weight": 0.22,
        "detail": "RSI 59, bullish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 100.0,
        "weight": 0.22,
        "detail": "R:R 5.4x · risk 4.14% · reward 22.52%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 69.0,
        "weight": 0.18,
        "detail": "buy · 34 analysts · -1.0% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 75.8,
        "weight": 0.15,
        "detail": "1W +6.0%, 1M +11.5%, RVOL 1.26",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.461271+00:00",
      "conviction_stale": false,
      "stance": "RE_ENTER",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "stance_vs_synthesis",
        "summary": "Today's desk synthesis says AVOID; conviction says RE_ENTER",
        "a": {
         "value": "RE_ENTER",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.461271+00:00"
        },
        "b": {
         "value": "AVOID",
         "source": "watchlist_final_synthesis",
         "at": null
        }
       }
      ],
      "next_trigger": {
       "label": "zone $54.80–$56.20 (-11.5%)",
       "level_ref": 56.2,
       "inside": false,
       "distance_pct": -11.5,
       "observed_by": "re-entry desk"
      },
      "next_action": {
       "kind": "resolve_conflict",
       "label": "Resolve conflict",
       "href": null,
       "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."
      },
      "price": 63.52,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 59.18,
      "held": false,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "reentry_watch",
       "category_label": "Re-Entry",
       "priority": "medium",
       "priority_score": 48.0,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": "WAIT",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#45 · 79 · RE_ENTER",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Wait",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.461271+00:00",
      "expires_at": "2026-10-26T15:00:03.429441+00:00",
      "stale": false
     },
     {
      "symbol": "FATN",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "FatPipe, Inc.",
      "lane": "reentry",
      "stage": "re_entry",
      "why": "Sold; near your re-entry level",
      "summary": "Sold; near your re-entry level. Previously owned; conviction 76 with R:R 4.8x — a re-entry would make sense if the setup confirms.",
      "conviction": 76.0,
      "conviction_rank": 129,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 62.0,
        "weight": 0.22,
        "detail": "RSI 54, neutral, confluence 0; strategy-qualified, base 63",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 97.5,
        "weight": 0.22,
        "detail": "R:R 4.8x · risk 9.8% · reward 47.06%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 100.0,
        "weight": 0.18,
        "detail": "strong_buy · 4 analysts · +91.9% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 50.2,
        "weight": 0.15,
        "detail": "1W +4.2%, 1M -6.8%, RVOL 0.75",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.474185+00:00",
      "conviction_stale": false,
      "stance": "RE_ENTER",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "trade_ai_block",
        "summary": "Trade AI deterministic fail — not actionable until it passes (the stance says RE_ENTER)",
        "a": {
         "value": "RE_ENTER",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.474185+00:00"
        },
        "b": {
         "value": "DETERMINISTIC_FAIL",
         "source": "rockville decision_projection (Trade AI)",
         "at": "2026-10-22T11:00:03.429441-04:00"
        }
       }
      ],
      "next_trigger": {
       "label": "zone $4.90–$5.25",
       "level_ref": 4.9,
       "inside": true,
       "distance_pct": null,
       "observed_by": "re-entry desk"
      },
      "next_action": {
       "kind": "resolve_conflict",
       "label": "Resolve conflict",
       "href": null,
       "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."
      },
      "price": 5.21,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 53.6,
      "held": false,
      "trade_ai_state": "DETERMINISTIC_FAIL",
      "decision": {
       "rule_id": "reentry_near",
       "category_label": "Re-Entry",
       "priority": "high",
       "priority_score": 82.0,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Set a re-entry alert"
      },
      "reentry_state": "NEAR ENTRY",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DETERMINISTIC FAIL",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#129 · 76 · RE_ENTER",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Near Entry",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.474185+00:00",
      "expires_at": "2026-10-26T15:00:03.429441+00:00",
      "stale": false
     },
     {
      "symbol": "KBR",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "KBR Inc",
      "lane": "reentry",
      "stage": "re_entry",
      "why": "Sold; near your re-entry level",
      "summary": "Sold; near your re-entry level. Previously owned; conviction 74 with R:R 4.7x — a re-entry would make sense if the setup confirms.",
      "conviction": 74.4,
      "conviction_rank": 182,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 69.7,
        "weight": 0.22,
        "detail": "RSI 57, bearish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 95.9,
        "weight": 0.22,
        "detail": "R:R 4.7x · risk 3.3% · reward 15.38%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 74.2,
        "weight": 0.18,
        "detail": "buy · 7 analysts · +18.3% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 62.4,
        "weight": 0.15,
        "detail": "1W +2.5%, 1M +6.1%, RVOL 0.81",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.522172+00:00",
      "conviction_stale": false,
      "stance": "RE_ENTER",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Not on the Watch universe — seen only by the re-entry desk",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $36.00–$36.80 (-1.9%)",
       "level_ref": 36.8,
       "inside": false,
       "distance_pct": -1.9,
       "observed_by": "re-entry desk"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 37.515,
        "rsi": 63.82,
        "entry_low_ref": 36.0,
        "entry_high_ref": 36.8
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 37.515,
      "price_as_of": "2026-10-22T15:00:03.429441+00:00",
      "rsi": 63.82,
      "held": false,
      "trade_ai_state": null,
      "decision": null,
      "reentry_state": "NEAR ENTRY",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "—",
        "source": "rockville decision_projection",
        "joined": false
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#182 · 74 · RE_ENTER",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Near Entry",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.522172+00:00",
      "expires_at": "2026-10-26T15:00:03.429441+00:00",
      "stale": false
     },
     {
      "symbol": "ANET",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Arista Networks, Inc.",
      "lane": "reentry",
      "stage": "re_entry",
      "why": "Sold; near your re-entry level",
      "summary": "Sold; near your re-entry level. Previously owned; conviction 74 with R:R 4.7x — a re-entry would make sense if the setup confirms.",
      "conviction": 73.7,
      "conviction_rank": 216,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 67.7,
        "weight": 0.22,
        "detail": "RSI 35, neutral, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 96.6,
        "weight": 0.22,
        "detail": "R:R 4.7x · risk 4.18% · reward 19.78%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 95.8,
        "weight": 0.18,
        "detail": "strong_buy · 29 analysts · +41.6% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 34.3,
        "weight": 0.15,
        "detail": "1W +0.2%, 1M -13.4%, RVOL 1.24",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.393631+00:00",
      "conviction_stale": false,
      "stance": "RE_ENTER",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "trade_ai_block",
        "summary": "Trade AI deterministic fail — not actionable until it passes (the stance says RE_ENTER)",
        "a": {
         "value": "RE_ENTER",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.393631+00:00"
        },
        "b": {
         "value": "DETERMINISTIC_FAIL",
         "source": "rockville decision_projection (Trade AI)",
         "at": "2026-10-22T11:00:03.429441-04:00"
        }
       }
      ],
      "next_trigger": {
       "label": "zone $176.77–$182.50 (+2.6%)",
       "level_ref": 176.77,
       "inside": false,
       "distance_pct": 2.6,
       "observed_by": "re-entry desk"
      },
      "next_action": {
       "kind": "resolve_conflict",
       "label": "Resolve conflict",
       "href": null,
       "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."
      },
      "price": 172.33,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 35.08,
      "held": false,
      "trade_ai_state": "DETERMINISTIC_FAIL",
      "decision": {
       "rule_id": "reentry_watch",
       "category_label": "Re-Entry",
       "priority": "medium",
       "priority_score": 57.2,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": "WAIT",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DETERMINISTIC FAIL",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#216 · 74 · RE_ENTER",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Wait",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.393631+00:00",
      "expires_at": "2026-10-26T15:00:03.429441+00:00",
      "stale": false
     },
     {
      "symbol": "UBER",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Uber Technologies Inc",
      "lane": "reentry",
      "stage": "re_entry",
      "why": "Sold; near your re-entry level",
      "summary": "Sold; near your re-entry level. Previously owned; conviction 73 with R:R 4.4x — a re-entry would make sense if the setup confirms.",
      "conviction": 73.2,
      "conviction_rank": 237,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 69.8,
        "weight": 0.22,
        "detail": "RSI 53, bearish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 92.9,
        "weight": 0.22,
        "detail": "R:R 4.4x · risk 3.39% · reward 15.04%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 93.1,
        "weight": 0.18,
        "detail": "strong_buy · 48 analysts · +53.2% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 36.8,
        "weight": 0.15,
        "detail": "1W -5.1%, 1M -2.6%, RVOL 0.95",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.623428+00:00",
      "conviction_stale": false,
      "stance": "RE_ENTER",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Not on the Watch universe — seen only by the re-entry desk",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $67.22–$68.50",
       "level_ref": 67.22,
       "inside": true,
       "distance_pct": null,
       "observed_by": "re-entry desk"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 68.205,
        "rsi": 49.15,
        "entry_low_ref": 67.22,
        "entry_high_ref": 68.5
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 68.205,
      "price_as_of": "2026-10-22T15:00:03.429441+00:00",
      "rsi": 49.15,
      "held": false,
      "trade_ai_state": null,
      "decision": null,
      "reentry_state": "NEAR ENTRY",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "—",
        "source": "rockville decision_projection",
        "joined": false
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#237 · 73 · RE_ENTER",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Near Entry",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.623428+00:00",
      "expires_at": "2026-10-26T15:00:03.429441+00:00",
      "stale": false
     },
     {
      "symbol": "QCOM",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Qualcomm Inc",
      "lane": "reentry",
      "stage": "re_entry",
      "why": "Sold; near your re-entry level",
      "summary": "Sold; near your re-entry level. Previously owned; conviction 72 with R:R 4.7x — a re-entry would make sense if the setup confirms.",
      "conviction": 72.3,
      "conviction_rank": 277,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 77.4,
        "weight": 0.22,
        "detail": "RSI 47, bullish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 96.6,
        "weight": 0.22,
        "detail": "R:R 4.7x · risk 4.42% · reward 20.94%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 61.5,
        "weight": 0.18,
        "detail": "hold · 30 analysts · +10.1% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 52.7,
        "weight": 0.15,
        "detail": "1W +3.4%, 1M -3.4%, RVOL 0.57",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.573418+00:00",
      "conviction_stale": false,
      "stance": "RE_ENTER",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Not on the Watch universe — seen only by the re-entry desk",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "zone $167.00–$171.50 (-1.8%)",
       "level_ref": 171.5,
       "inside": false,
       "distance_pct": -1.8,
       "observed_by": "re-entry desk"
      },
      "next_action": {
       "kind": "set_alert",
       "label": "Set alert",
       "href": null,
       "seed": {
        "price": 174.585,
        "rsi": 49.52,
        "entry_low_ref": 167.0,
        "entry_high_ref": 171.5
       },
       "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."
      },
      "price": 174.585,
      "price_as_of": "2026-10-22T15:00:03.429441+00:00",
      "rsi": 49.52,
      "held": false,
      "trade_ai_state": null,
      "decision": null,
      "reentry_state": "NEAR ENTRY",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "—",
        "source": "rockville decision_projection",
        "joined": false
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#277 · 72 · RE_ENTER",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Near Entry",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.573418+00:00",
      "expires_at": "2026-10-26T15:00:03.429441+00:00",
      "stale": false
     }
    ],
    "overflow": [
     "DXCM",
     "SMCI",
     "AXTI",
     "TRX",
     "RGNT",
     "ALXO",
     "PHIO",
     "JEPQ",
     "BJDX",
     "ARKG",
     "IBIO",
     "DFSC",
     "FCNTX"
    ]
   },
   {
    "id": "manage",
    "label": "Manage (held)",
    "hint": "protect, add, trim",
    "count": 20,
    "cap": 8,
    "items": [
     {
      "symbol": "NAVN",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Navan, Inc.",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Not owned; conviction 88 — worth tracking until the factors or the setup improve.",
      "conviction": 87.7,
      "conviction_rank": 1,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 89.3,
        "weight": 0.22,
        "detail": "RSI 66, bullish; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 97.6,
        "weight": 0.22,
        "detail": "R:R 4.8x · risk 4.21% · reward 20.24%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 83.3,
        "weight": 0.18,
        "detail": "strong_buy · 15 analysts · +14.6% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 100.0,
        "weight": 0.15,
        "detail": "1W +5.6%, 1M +35.5%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.546451+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "stance_vs_synthesis",
        "summary": "Today's desk synthesis says SELL; conviction says WATCH",
        "a": {
         "value": "WATCH",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.546451+00:00"
        },
        "b": {
         "value": "SELL",
         "source": "watchlist_final_synthesis",
         "at": null
        }
       },
       {
        "kind": "ownership",
        "summary": "Held per the broker-synced holdings; the conviction record treats it as not owned",
        "a": {
         "value": "not_owned",
         "source": "cio_opportunity_projection.position_status",
         "at": "2026-10-22T15:00:22.546451+00:00"
        },
        "b": {
         "value": "held",
         "source": "positions_store.positions_current",
         "at": null
        }
       }
      ],
      "next_trigger": {
       "label": "support $19.41",
       "level_ref": 19.41,
       "inside": false,
       "distance_pct": -28.4,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "protect",
       "label": "Protect first",
       "href": "/v3/trading?tab=Open+Trades&symbol=NAVN",
       "reason": "A risk rule fired for this held name (a sell/trim synthesis or a Trade AI block). Open Trades shows its stop and protection."
      },
      "price": 27.115,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 69.71,
      "held": true,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "held_negative",
       "category_label": "Risk",
       "priority": "high",
       "priority_score": 68.8,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review the held position"
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#1 · 88 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T11:16:59.568213-04:00",
      "expires_at": "2026-10-26T11:16:59.568213-04:00",
      "stale": false
     },
     {
      "symbol": "SPCX",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Space Exploration Technologies Corp.",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Conviction 80 with R:R 6.0x; an add would fit if price holds above the invalidation level.",
      "conviction": 80.3,
      "conviction_rank": 18,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 79.9,
        "weight": 0.22,
        "detail": "RSI 58, bullish, confluence 5; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 100.0,
        "weight": 0.22,
        "detail": "R:R 6.0x · risk 6.67% · reward 40.0%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 88.2,
        "weight": 0.18,
        "detail": "buy · 34 analysts · +68.9% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 60.3,
        "weight": 0.15,
        "detail": "1W +3.0%, 1M +3.6%, RVOL 1.16",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.594053+00:00",
      "conviction_stale": false,
      "stance": "ADD",
      "stance_family": "positive",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "stance_vs_review",
        "summary": "CIO conviction says ADD; the CIO watch review says HOLD",
        "a": {
         "value": "ADD",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.594053+00:00"
        },
        "b": {
         "value": "HOLD",
         "source": "watchlist CIO review",
         "at": "2026-09-02T20:21:21.458657+00:00"
        }
       }
      ],
      "next_trigger": {
       "label": "support $146.03",
       "level_ref": 146.03,
       "inside": false,
       "distance_pct": -2.5,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "resolve_conflict",
       "label": "Resolve conflict",
       "href": null,
       "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."
      },
      "price": 149.765,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 58.46,
      "held": true,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "plan_near",
       "category_label": "Reward",
       "priority": "medium",
       "priority_score": 78.0,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": "CURRENTLY HELD",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#18 · 80 · ADD",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Currently Held",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.594053+00:00",
      "expires_at": "2026-10-25T17:59:17.915428-04:00",
      "stale": false
     },
     {
      "symbol": "NVDA",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "NVIDIA Corporation",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Conviction 78 with R:R 4.9x; an add would fit if price holds above the invalidation level.",
      "conviction": 78.5,
      "conviction_rank": 49,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 71.4,
        "weight": 0.22,
        "detail": "RSI 45, neutral, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 98.9,
        "weight": 0.22,
        "detail": "R:R 4.9x · risk 3.97% · reward 19.48%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 95.7,
        "weight": 0.18,
        "detail": "strong_buy · 59 analysts · +52.7% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 42.1,
        "weight": 0.15,
        "detail": "1W -0.0%, 1M -6.5%, RVOL 0.74",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 97.0,
        "weight": 0.1,
        "detail": "ROE 1.1721, ProfitMargin 0.6366, ForwardPE 13.56",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.553421+00:00",
      "conviction_stale": false,
      "stance": "ADD",
      "stance_family": "positive",
      "whats_missing": [
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "support $214.03",
       "level_ref": 214.03,
       "inside": false,
       "distance_pct": 0.2,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "review_add",
       "label": "Review add-on",
       "href": "/v3/watch/intelligence/NVDA",
       "reason": "The CIO stance on this held name is ADD; review the add-on idea or leave it."
      },
      "price": 213.62,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 45.16,
      "held": true,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 70.8,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#49 · 78 · ADD",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.553421+00:00",
      "expires_at": "2026-10-25T17:44:35.140058-04:00",
      "stale": false
     },
     {
      "symbol": "NOC",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Northrop Grumman Corporation",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Conviction 74 with R:R 4.5x; an add would fit if price holds above the invalidation level.",
      "conviction": 73.8,
      "conviction_rank": 211,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 64.0,
        "weight": 0.22,
        "detail": "RSI 38, bearish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 93.4,
        "weight": 0.22,
        "detail": "R:R 4.5x · risk 2.87% · reward 12.81%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 71.5,
        "weight": 0.18,
        "detail": "buy · 24 analysts · +15.3% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 70.1,
        "weight": 0.15,
        "detail": "1W +5.1%, 1M +8.3%, RVOL 1.38",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 79.8,
        "weight": 0.1,
        "detail": "ROE 0.2696, ProfitMargin 0.1048, ForwardPE 16.65",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.550472+00:00",
      "conviction_stale": false,
      "stance": "ADD",
      "stance_family": "positive",
      "whats_missing": [
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "support $473.61",
       "level_ref": 473.61,
       "inside": false,
       "distance_pct": -13.9,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "review_add",
       "label": "Review add-on",
       "href": "/v3/watch/intelligence/NOC",
       "reason": "The CIO stance on this held name is ADD; review the add-on idea or leave it."
      },
      "price": 550.255,
      "price_as_of": "2026-10-22T11:00:32.262675-04:00",
      "rsi": 66.5,
      "held": true,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "plan_near",
       "category_label": "Reward",
       "priority": "medium",
       "priority_score": 54.8,
       "status": "active",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": "CURRENTLY HELD",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#211 · 74 · ADD",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Currently Held",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.550472+00:00",
      "expires_at": "2026-10-25T17:52:11.340925-04:00",
      "stale": false
     },
     {
      "symbol": "RTX",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "RTX Corporation",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Conviction 73 with R:R 5.9x; an add would fit if price holds above the invalidation level.",
      "conviction": 72.8,
      "conviction_rank": 254,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 69.1,
        "weight": 0.22,
        "detail": "RSI 52, bearish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 100.0,
        "weight": 0.22,
        "detail": "R:R 5.9x · risk 3.04% · reward 17.92%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 76.1,
        "weight": 0.18,
        "detail": "buy · 23 analysts · +19.7% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 50.5,
        "weight": 0.15,
        "detail": "1W -1.1%, 1M +2.2%, RVOL 1.94",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 65.1,
        "weight": 0.1,
        "detail": "ROE 0.1202, ProfitMargin 0.0828, ForwardPE 24.09",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.581332+00:00",
      "conviction_stale": false,
      "stance": "ADD",
      "stance_family": "positive",
      "whats_missing": [
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "stance_vs_review",
        "summary": "CIO conviction says ADD; the CIO watch review says HOLD",
        "a": {
         "value": "ADD",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.581332+00:00"
        },
        "b": {
         "value": "HOLD",
         "source": "watchlist CIO review",
         "at": "2026-09-02T20:21:15.414348+00:00"
        }
       }
      ],
      "next_trigger": {
       "label": "support $180.28",
       "level_ref": 180.28,
       "inside": false,
       "distance_pct": -6.3,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "resolve_conflict",
       "label": "Resolve conflict",
       "href": null,
       "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."
      },
      "price": 192.39,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 51.65,
      "held": true,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "plan_ready_strong",
       "category_label": "High Conviction Opportunity",
       "priority": "critical",
       "priority_score": 87.6,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": "CURRENTLY HELD",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#254 · 73 · ADD",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Currently Held",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.581332+00:00",
      "expires_at": "2026-10-25T18:14:19.266165-04:00",
      "stale": false
     },
     {
      "symbol": "LDOS",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Leidos Holdings, Inc., together with its subsidiaries",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Conviction 72 with R:R 3.7x; an add would fit if price holds above the invalidation level.",
      "conviction": 72.2,
      "conviction_rank": 282,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 68.8,
        "weight": 0.22,
        "detail": "RSI 59, bearish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 84.2,
        "weight": 0.22,
        "detail": "R:R 3.7x · risk 3.02% · reward 11.29%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 66.8,
        "weight": 0.18,
        "detail": "buy · 15 analysts · +15.9% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 68.4,
        "weight": 0.15,
        "detail": "1W +5.2%, 1M +6.8%, RVOL 1.00",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 84.4,
        "weight": 0.1,
        "detail": "ROE 0.2767, ProfitMargin 0.078, ForwardPE 10.05",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.528038+00:00",
      "conviction_stale": false,
      "stance": "ADD",
      "stance_family": "positive",
      "whats_missing": [
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "stance_vs_review",
        "summary": "CIO conviction says ADD; the CIO watch review says HOLD",
        "a": {
         "value": "ADD",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.528038+00:00"
        },
        "b": {
         "value": "HOLD",
         "source": "watchlist CIO review",
         "at": "2026-09-02T20:20:47.203484+00:00"
        }
       }
      ],
      "next_trigger": {
       "label": "support $113.54",
       "level_ref": 113.54,
       "inside": false,
       "distance_pct": -13.8,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "resolve_conflict",
       "label": "Resolve conflict",
       "href": null,
       "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."
      },
      "price": 131.69,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 59.33,
      "held": true,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 62.4,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": "CURRENTLY HELD",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#282 · 72 · ADD",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Currently Held",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.528038+00:00",
      "expires_at": "2026-10-23T18:48:13.350240-04:00",
      "stale": false
     },
     {
      "symbol": "BAH",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Booz Allen Hamilton Holding Corporation",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Conviction 72 with R:R 3.7x; an add would fit if price holds above the invalidation level.",
      "conviction": 71.9,
      "conviction_rank": 297,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 74.5,
        "weight": 0.22,
        "detail": "RSI 56, neutral, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 84.0,
        "weight": 0.22,
        "detail": "R:R 3.7x · risk 3.16% · reward 11.78%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 59.1,
        "weight": 0.18,
        "detail": "hold · 13 analysts · +10.2% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 67.0,
        "weight": 0.15,
        "detail": "1W +3.1%, 1M +9.0%, RVOL 0.76",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 85.9,
        "weight": 0.1,
        "detail": "ROE 0.6811, ProfitMargin 0.0696, ForwardPE 11.14",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.403310+00:00",
      "conviction_stale": false,
      "stance": "ADD",
      "stance_family": "positive",
      "whats_missing": [
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "stance_vs_review",
        "summary": "CIO conviction says ADD; the CIO watch review says HOLD",
        "a": {
         "value": "ADD",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.403310+00:00"
        },
        "b": {
         "value": "HOLD",
         "source": "watchlist CIO review",
         "at": "2026-09-02T20:20:28.187700+00:00"
        }
       }
      ],
      "next_trigger": {
       "label": "support $67.33",
       "level_ref": 67.33,
       "inside": false,
       "distance_pct": -12.8,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "resolve_conflict",
       "label": "Resolve conflict",
       "href": null,
       "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."
      },
      "price": 77.24,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 56.31,
      "held": true,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 62.5,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#297 · 72 · ADD",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.403310+00:00",
      "expires_at": "2026-10-23T19:15:24.128523-04:00",
      "stale": false
     },
     {
      "symbol": "CSWC",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Capital Southwest Corporation",
      "lane": "manage",
      "stage": "held",
      "why": "Held — managed, never entered",
      "summary": "Held — managed, never entered. Owned; conviction 68 — nothing in the factors argues for a change today.",
      "conviction": 68.1,
      "conviction_rank": 480,
      "conviction_coverage": 1.0,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 62.8,
        "weight": 0.22,
        "detail": "RSI 36, bearish, confluence 0; strategy-qualified, base 87",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 83.5,
        "weight": 0.22,
        "detail": "R:R 3.7x · risk 2.75% · reward 10.12%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 70.4,
        "weight": 0.18,
        "detail": "buy · 6 analysts · +10.8% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 43.5,
        "weight": 0.15,
        "detail": "1W -2.2%, 1M -1.8%, RVOL 0.80",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       },
       {
        "key": "fundamental",
        "label": "Fundamental",
        "value": 88.9,
        "weight": 0.1,
        "detail": "ROE 0.1108, ProfitMargin 0.4767, ForwardPE 9.66",
        "source": "fundamental_data"
       }
      ],
      "conviction_missing": [],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.444763+00:00",
      "conviction_stale": false,
      "stance": "HOLD",
      "stance_family": "neutral",
      "whats_missing": [
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "support $22.38",
       "level_ref": 22.38,
       "inside": false,
       "distance_pct": -0.7,
       "observed_by": "watch card support"
      },
      "next_action": {
       "kind": "open_position",
       "label": "View position",
       "href": "/v3/trading?tab=Open+Trades&symbol=CSWC",
       "reason": "Held; nothing argues for a change today. Open Trades shows the position."
      },
      "price": 22.54,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 35.77,
      "held": true,
      "trade_ai_state": "MANAGING",
      "decision": {
       "rule_id": "plan_ready",
       "category_label": "Reward",
       "priority": "high",
       "priority_score": 69.4,
       "status": "active",
       "actionable": true,
       "actionable_blocked_by": null,
       "action_hint": "Review entry"
      },
      "reentry_state": "CURRENTLY HELD",
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "MANAGING",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#480 · 68 · HOLD",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "Currently Held",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.444763+00:00",
      "expires_at": "2026-10-23T18:46:11.054384-04:00",
      "stale": false
     }
    ],
    "overflow": [
     "SRNE",
     "PFLT",
     "V",
     "SCHG",
     "JEPI",
     "XLI",
     "SCHD",
     "XLB",
     "BND",
     "XAR",
     "DIV",
     "AMANX"
    ]
   },
   {
    "id": "expired",
    "label": "Expired",
    "hint": "collapsed, auto-closed",
    "count": 67,
    "cap": 5,
    "items": [
     {
      "symbol": "CVS",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "CVS Health Corporation",
      "lane": "expired",
      "stage": "expired",
      "why": "Signal invalidated",
      "summary": "Signal invalidated. Not owned; conviction 78 — worth tracking until the factors or the setup improve.",
      "conviction": 78.5,
      "conviction_rank": 50,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 77.3,
        "weight": 0.22,
        "detail": "RSI 63, bullish, confluence 0; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 95.9,
        "weight": 0.22,
        "detail": "R:R 4.7x · risk 2.61% · reward 12.2%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 85.5,
        "weight": 0.18,
        "detail": "strong_buy · 25 analysts · +23.2% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 62.6,
        "weight": 0.15,
        "detail": "1W +1.0%, 1M +8.9%, RVOL 1.48",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.447432+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "—",
       "level_ref": null,
       "inside": false,
       "distance_pct": null,
       "observed_by": null
      },
      "next_action": {
       "kind": "none",
       "label": "—",
       "reason": "Signal closed; it returns when new evidence arrives.",
       "href": null
      },
      "price": 93.805,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 63.11,
      "held": false,
      "trade_ai_state": "DETERMINISTIC_FAIL",
      "decision": {
       "rule_id": "plan_near",
       "category_label": "Reward",
       "priority": "medium",
       "priority_score": 57.6,
       "status": "invalidated",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DETERMINISTIC FAIL",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#50 · 78 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.447432+00:00",
      "expires_at": "2026-10-25T17:52:27.803905-04:00",
      "stale": false
     },
     {
      "symbol": "STDN",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Standard Nuclear, Inc.",
      "lane": "expired",
      "stage": "expired",
      "why": "Signal expired",
      "summary": "Signal expired. Not owned; conviction 77 — worth tracking until the factors or the setup improve.",
      "conviction": 77.2,
      "conviction_rank": 91,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 70.0,
        "weight": 0.22,
        "detail": "RSI 60, bullish, confluence 0; strategy-qualified, base 71",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 89.8,
        "weight": 0.22,
        "detail": "R:R 4.2x · risk 9.24% · reward 38.66%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 95.0,
        "weight": 0.18,
        "detail": "strong_buy · 9 analysts · +45.9% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 62.6,
        "weight": 0.15,
        "detail": "1W +4.9%, 1M +2.3%, RVOL 0.60",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.595416+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "—",
       "level_ref": null,
       "inside": false,
       "distance_pct": null,
       "observed_by": null
      },
      "next_action": {
       "kind": "none",
       "label": "—",
       "reason": "Signal closed; it returns when new evidence arrives.",
       "href": null
      },
      "price": 11.99,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 46.53,
      "held": false,
      "trade_ai_state": "STALE",
      "decision": {
       "rule_id": "plan_ready_strong",
       "category_label": "High Conviction Opportunity",
       "priority": "high",
       "priority_score": 79.5,
       "status": "expired",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "STALE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#91 · 77 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.595416+00:00",
      "expires_at": "2026-10-20T19:33:21.466241-04:00",
      "stale": true
     },
     {
      "symbol": "MDLN",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Medline Inc",
      "lane": "expired",
      "stage": "expired",
      "why": "Signal invalidated",
      "summary": "Signal invalidated. Not owned; conviction 74 — worth tracking until the factors or the setup improve.",
      "conviction": 74.3,
      "conviction_rank": 187,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 85.6,
        "weight": 0.22,
        "detail": "RSI 52, neutral; strategy-qualified, base 95",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 81.0,
        "weight": 0.22,
        "detail": "R:R 3.5x · risk 3.61% · reward 12.55%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 85.9,
        "weight": 0.18,
        "detail": "buy · 26 analysts · +28.5% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 46.4,
        "weight": 0.15,
        "detail": "1W -3.5%, 1M +2.9%, RVOL 0.61",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.537288+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [
       {
        "kind": "stance_vs_synthesis",
        "summary": "Today's desk synthesis says AVOID; conviction says WATCH",
        "a": {
         "value": "WATCH",
         "source": "cio_opportunity_projection",
         "at": "2026-10-22T15:00:22.537288+00:00"
        },
        "b": {
         "value": "AVOID",
         "source": "watchlist_final_synthesis",
         "at": null
        }
       }
      ],
      "next_trigger": {
       "label": "—",
       "level_ref": null,
       "inside": false,
       "distance_pct": null,
       "observed_by": null
      },
      "next_action": {
       "kind": "none",
       "label": "—",
       "reason": "Signal closed; it returns when new evidence arrives.",
       "href": null
      },
      "price": 34.45,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 51.58,
      "held": false,
      "trade_ai_state": "STALE",
      "decision": {
       "rule_id": "plan_near",
       "category_label": "Reward",
       "priority": "medium",
       "priority_score": 65.6,
       "status": "invalidated",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "STALE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#187 · 74 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.537288+00:00",
      "expires_at": "2026-10-23T18:55:44.722234-04:00",
      "stale": false
     },
     {
      "symbol": "ABX",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "Abacus Global Management, Inc.",
      "lane": "expired",
      "stage": "expired",
      "why": "Signal invalidated",
      "summary": "Signal invalidated. Not owned; conviction 74 — worth tracking until the factors or the setup improve.",
      "conviction": 74.1,
      "conviction_rank": 194,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 39.9,
        "weight": 0.22,
        "detail": "RSI 40, bearish, confluence 0; technical posture, base 50",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 100.0,
        "weight": 0.22,
        "detail": "R:R 8.2x · risk 6.33% · reward 51.9%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 100.0,
        "weight": 0.18,
        "detail": "none · 6 analysts · +59.9% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 67.7,
        "weight": 0.15,
        "detail": "1W +7.3%, 1M +2.5%, RVOL 0.85",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.374338+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "—",
       "level_ref": null,
       "inside": false,
       "distance_pct": null,
       "observed_by": null
      },
      "next_action": {
       "kind": "none",
       "label": "—",
       "reason": "Signal closed; it returns when new evidence arrives.",
       "href": null
      },
      "price": 8.63,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 51.75,
      "held": false,
      "trade_ai_state": "DETERMINISTIC_FAIL",
      "decision": {
       "rule_id": "candidate",
       "category_label": "Watchlist Candidate",
       "priority": "medium",
       "priority_score": 47.0,
       "status": "invalidated",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DETERMINISTIC FAIL",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#194 · 74 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.374338+00:00",
      "expires_at": null,
      "stale": false
     },
     {
      "symbol": "URGN",
      "security_guid": null,
      "issuer_guid": null,
      "identity_status": null,
      "company": "UroGen Pharma Ltd.",
      "lane": "expired",
      "stage": "expired",
      "why": "Signal expired",
      "summary": "Signal expired. Not owned; conviction 74 — worth tracking until the factors or the setup improve.",
      "conviction": 73.6,
      "conviction_rank": 219,
      "conviction_coverage": 0.9,
      "conviction_components": [
       {
        "key": "technical",
        "label": "Technical",
        "value": 70.7,
        "weight": 0.22,
        "detail": "RSI 45, neutral, confluence 0; strategy-qualified, base 87",
        "source": "hermes_score_components"
       },
       {
        "key": "risk_reward",
        "label": "Risk/Reward",
        "value": 100.0,
        "weight": 0.22,
        "detail": "R:R 5.2x · risk 7.14% · reward 37.14%",
        "source": "risk_reward"
       },
       {
        "key": "analyst",
        "label": "Analyst",
        "value": 94.4,
        "weight": 0.18,
        "detail": "strong_buy · 8 analysts · +71.7% to mean target",
        "source": "yahoo_analyst_targets_history"
       },
       {
        "key": "momentum",
        "label": "Momentum",
        "value": 26.1,
        "weight": 0.15,
        "detail": "1W -3.1%, 1M -14.8%",
        "source": "price_stats"
       },
       {
        "key": "portfolio_fit",
        "label": "Portfolio Fit",
        "value": 60.0,
        "weight": 0.13,
        "detail": "no concentration flag",
        "source": "portfolio_snapshot"
       }
      ],
      "conviction_missing": [
       "fundamental"
      ],
      "conviction_source": "cio_opportunity_projection",
      "conviction_as_of": "2026-10-22T15:00:22.625101+00:00",
      "conviction_stale": false,
      "stance": "WATCH",
      "stance_family": "neutral",
      "whats_missing": [
       "Fundamental factor not scored",
       "Identity unresolved (no CONFIRMED security GUID)"
      ],
      "conflicts": [],
      "next_trigger": {
       "label": "—",
       "level_ref": null,
       "inside": false,
       "distance_pct": null,
       "observed_by": null
      },
      "next_action": {
       "kind": "none",
       "label": "—",
       "reason": "Signal closed; it returns when new evidence arrives.",
       "href": null
      },
      "price": 34.825,
      "price_as_of": "2026-10-22T11:00:03.429441-04:00",
      "rsi": 39.47,
      "held": false,
      "trade_ai_state": "DATA_UNAVAILABLE",
      "decision": {
       "rule_id": "plan_near",
       "category_label": "Reward",
       "priority": "medium",
       "priority_score": 73.7,
       "status": "expired",
       "actionable": false,
       "actionable_blocked_by": null,
       "action_hint": null
      },
      "reentry_state": null,
      "surfaces": [
       {
        "surface": "Home",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Trade AI",
        "value": "DATA UNAVAILABLE",
        "source": "rockville decision_projection",
        "joined": true
       },
       {
        "surface": "Options",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Open Trades",
        "value": "not held",
        "source": "positions_store.positions_current",
        "joined": true
       },
       {
        "surface": "Telegram",
        "value": "not joined (interim)",
        "source": null,
        "joined": false
       },
       {
        "surface": "Opportunities (CIO curator)",
        "value": "#219 · 74 · WATCH",
        "source": "cio_opportunity_projection",
        "joined": true
       },
       {
        "surface": "Re-entry desk",
        "value": "—",
        "source": "reentry_decision_desk",
        "joined": true
       }
      ],
      "evidence_at": "2026-10-22T15:00:22.625101+00:00",
      "expires_at": "2026-10-19T19:21:11.952344-04:00",
      "stale": true
     }
    ],
    "overflow": [
     "AGI",
     "BETA",
     "AHCO",
     "ABSI",
     "AA",
     "ACAD",
     "CECO",
     "ABEV",
     "AAL",
     "ABCL",
     "KTOS",
     "ACI",
     "ABNB",
     "ACA",
     "NUAI",
     "EIX",
     "ACB",
     "METC",
     "ABVC",
     "AYA",
     "LRN",
     "ABAT",
     "AAOI",
     "ABEO",
     "AMCX",
     "ACET",
     "ABTC",
     "ACHV",
     "ACH",
     "COMP",
     "MRLN",
     "ACGL",
     "RDDT",
     "ABBV",
     "FTH",
     "AAPL",
     "AZN",
     "ACIC",
     "UPST",
     "ABT",
     "ACHR",
     "AAON",
     "AAOX",
     "AAOG",
     "A",
     "AACG",
     "AAOZ",
     "AAP",
     "AAPU",
     "AARD",
     "ACHC",
     "ABVX",
     "AALG",
     "AAPG",
     "AAUC",
     "ABTS",
     "ABUS",
     "ACEL",
     "AAPW",
     "AADX",
     "AAPD",
     "ACAA"
    ]
   }
  ],
  "counts": {
   "actionable": 5,
   "forming": 90,
   "reentry": 19,
   "manage": 20,
   "expired": 67,
   "conflicts": 13,
   "total": 201
  },
  "authority": "READ_ONLY_ADVISORY",
  "mbi_behavior": 0,
  "provider_calls": 0
 },
 "alerts": {
  "ok": true,
  "data": {
   "ok": true,
   "alerts": [
    {
     "id": 115,
     "symbol": "V",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 359.58,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-10-05T10:10:02.077231-04:00",
     "last_fired_at": null,
     "note": "ladder#136 T2 price trigger"
    },
    {
     "id": 113,
     "symbol": "JEPI",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 55.91,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-10-02T17:50:01.939599-04:00",
     "last_fired_at": null,
     "note": "ladder#134 T2 price trigger"
    },
    {
     "id": 110,
     "symbol": "XLB",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 48.54,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-10-02T10:10:02.232403-04:00",
     "last_fired_at": null,
     "note": "ladder#131 T2 price trigger"
    },
    {
     "id": 76,
     "symbol": "WMT",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 103.1,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-09-16T10:10:01.530037-04:00",
     "last_fired_at": null,
     "note": "ladder#83 T2 price trigger"
    },
    {
     "id": 70,
     "symbol": "XLI",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 7.49,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-09-14T10:10:01.293957-04:00",
     "last_fired_at": null,
     "note": "ladder#74 T2 price trigger"
    },
    {
     "id": 71,
     "symbol": "JEPI",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 22.14,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-09-14T10:10:01.293957-04:00",
     "last_fired_at": null,
     "note": "ladder#76 T2 price trigger"
    },
    {
     "id": 61,
     "symbol": "WMT",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 102.62,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-09-08T17:50:01.467447-04:00",
     "last_fired_at": null,
     "note": "ladder#62 T2 price trigger"
    },
    {
     "id": 41,
     "symbol": "QCOM",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 145.43,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-08-21T10:10:01.864474-04:00",
     "last_fired_at": null,
     "note": "ladder#39 T2 price trigger"
    },
    {
     "id": 38,
     "symbol": "SPY",
     "directive_id": null,
     "condition_type": "price_cross_above",
     "threshold": 769.03,
     "recurring": true,
     "cooldown_days": 1,
     "active": true,
     "created_at": "2026-08-05T17:50:01.863038-04:00",
     "last_fired_at": "2026-10-21T12:00:14.145427-04:00",
     "note": "defense hedge: SPY bounce day — hedge entry window (SH)"
    },
    {
     "id": 40,
     "symbol": "SH",
     "directive_id": null,
     "condition_type": "price_cross_above",
     "threshold": 37.12,
     "recurring": true,
     "cooldown_days": 1,
     "active": true,
     "created_at": "2026-08-05T17:50:01.863038-04:00",
     "last_fired_at": null,
     "note": "defense hedge: SH +15% — take remaining profits"
    },
    {
     "id": 39,
     "symbol": "SH",
     "directive_id": null,
     "condition_type": "price_cross_above",
     "threshold": 34.86,
     "recurring": true,
     "cooldown_days": 1,
     "active": true,
     "created_at": "2026-08-05T17:50:01.863038-04:00",
     "last_fired_at": null,
     "note": "defense hedge: SH +8% — take profits on HALF"
    },
    {
     "id": 37,
     "symbol": "QCOM",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 147.61,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-08-04T10:10:01.665928-04:00",
     "last_fired_at": null,
     "note": "ladder#33 T2 price trigger"
    },
    {
     "id": 36,
     "symbol": "QCOM",
     "directive_id": null,
     "condition_type": "price_cross_below",
     "threshold": 144.18,
     "recurring": false,
     "cooldown_days": 5,
     "active": true,
     "created_at": "2026-08-03T10:10:01.942417-04:00",
     "last_fired_at": null,
     "note": "ladder#32 T2 price trigger"
    },
    {
     "id": 17,
     "symbol": "PSQ",
     "directive_id": null,
     "condition_type": "price_cross_above",
     "threshold": 29.18,
     "recurring": true,
     "cooldown_days": 1,
     "active": true,
     "created_at": "2026-07-18T14:34:43.486079-04:00",
     "last_fired_at": null,
     "note": "defense hedge: PSQ +15% — take remaining profits"
    },
    {
     "id": 16,
     "symbol": "PSQ",
     "directive_id": null,
     "condition_type": "price_cross_above",
     "threshold": 27.4,
     "recurring": true,
     "cooldown_days": 1,
     "active": true,
     "created_at": "2026-07-18T14:34:43.486079-04:00",
     "last_fired_at": null,
     "note": "defense hedge: PSQ +8% — take profits on HALF"
    },
    {
     "id": 15,
     "symbol": "QQQ",
     "directive_id": null,
     "condition_type": "price_cross_above",
     "threshold": 730.94,
     "recurring": true,
     "cooldown_days": 1,
     "active": true,
     "created_at": "2026-07-18T14:34:43.486079-04:00",
     "last_fired_at": "2026-10-20T09:00:05.408214-04:00",
     "note": "defense hedge: QQQ bounce day — hedge entry window (PSQ)"
    }
   ],
   "active_count": 16
  }
 }
}
