# Phase 113D — Hermes Mock Proposal Packet Template

Status:      HISTORICAL
as_of:       2026-06-01T15:53:13-04:00
Measured at: efcc51365 / not measured

## Template

```json
{
  "hermes_draft_version": "1.0",
  "generated_by": "hermes_ticker_challenger",
  "generated_at": "2026-06-01T10:00:00-04:00",
  "execution_statement": "THIS IS A DRAFT. NO EXECUTION. NO BROKER ACCESS. ADVISORY ONLY.",

  "symbol": "EXAMPLE",
  "company": "Example Corp",
  "sector": "Technology",

  "thesis": {
    "summary": "One-sentence thesis explaining WHY this trade, not WHAT it is.",
    "timeframe": "2-5 days (swing)",
    "direction": "long",
    "strategy_fit": "swing_breakout"
  },

  "evidence": {
    "catalyst": "Earnings beat +15% on 2026-05-30, guidance raised, 3 analyst upgrades",
    "catalyst_verified": true,
    "catalyst_source": "https://...",
    "technical": "Breakout above $42 resistance on 3x volume, RSI 62, MACD bullish cross",
    "fundamental": "P/E 18 vs sector 24, revenue growth 22% YoY",
    "sentiment": "8 positive news articles in 48h, social sentiment 0.72",
    "sources": [
      {"type": "news", "url": "https://...", "date": "2026-05-30"},
      {"type": "db_view", "view": "hermes_v_ticker_context", "symbol": "EXAMPLE"},
      {"type": "browser", "url": "https://finance.yahoo.com/quote/EXAMPLE", "date": "2026-06-01"}
    ]
  },

  "risk": {
    "entry_price": 42.50,
    "stop_price": 40.25,
    "target_price": 47.50,
    "risk_reward_ratio": 2.22,
    "max_loss_pct": 5.29,
    "invalidation": "Close below $40.25 or earnings restatement"
  },

  "portfolio_fit": {
    "account_type": "Taxable",
    "position_size_rationale": "1% portfolio risk = ~$12K position, 300 shares at $42.50",
    "existing_exposure": "No current tech sector positions in taxable account",
    "conflicts": "None identified",
    "tax_consideration": "Short-term capital gains if held < 1 year"
  },

  "why_not_trade": [
    "Hermes has no live quote — entry price from last DB snapshot, may be stale",
    "No Finviz enrichment — fundamentals from DB view only",
    "Catalyst not independently verified by TradeAI pipeline",
    "Position size is theoretical — actual available capital not checked"
  ],

  "required_human_review": {
    "statement": "This draft requires operator review before any action. It is NOT a proposal and cannot be submitted.",
    "review_checklist": [
      "Verify catalyst is still valid",
      "Check current price vs entry level",
      "Verify no conflicting position exists",
      "Review stop level against current support",
      "Confirm account and size fit"
    ]
  },

  "quality_scores": {
    "thesis_clarity": 7,
    "catalyst_evidence": 6,
    "risk_definition": 8,
    "position_size_rationale": 5,
    "stop_exit_logic": 7,
    "source_traceability": 7,
    "conflict_check": 8,
    "portfolio_fit": 6,
    "tax_account_fit": 7,
    "confidence_calibration": 6,
    "composite": 6.6
  }
}
```

## Key Constraints

- `execution_statement` MUST always say "NO EXECUTION"
- `why_not_trade` MUST list at least 2 honest limitations
- `required_human_review.statement` MUST state this is not a proposal
- No `proposal_id`, no `signal_id`, no `paper_trade_id` — these are TradeAI-only fields
- No broker order fields
- No status field that could be confused with proposal status
