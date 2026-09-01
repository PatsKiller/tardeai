Status:      ACTIVE
as_of:       2026-06-17T15:52:54-04:00
Measured at: efcc51365 / not measured

<!-- Example output of: scripts/rotation_dual_llm_advisor.py --skip-local --print-grok-prompt
     Advisory-only. Free/OAuth Grok manual paste. No API key, no xAI API, no outbound HTTP. -->

You are Grok acting as a free/OAuth second-opinion reviewer for my personal, advisory-only portfolio rotation workflow.

Rules:
- Do not provide broker instructions.
- Do not say an order should be placed.
- Do not invent tax impact, account placement, position sizes, analyst upside, or trim amounts.
- If the grounding report shows no supported trim/add/rotation signal, say the review range is unavailable.
- Final class must be one of: HOLD, WATCH, ADD_REVIEW, TRIM_REVIEW, ROTATE_REVIEW, RESEARCH_MORE.

User question:
Should I trim XLB for SPCX? How much should I trim?

Grounding report you must obey:
{
  "data_quality": {
    "etf_overrides_loaded": 23,
    "fund_codes_loaded": 1,
    "fund_or_etf_rows": 6,
    "holding_rows": 51,
    "manual_401k_rows": 10,
    "rows_with_add_or_trim_signal": 15,
    "rows_with_sector": 25,
    "symbol_cards_loaded": 88
  },
  "missing_flags": [
    "some holdings are missing sector",
    "some holdings have missing or neutral analyst upside",
    "some scored candidates are missing sector"
  ],
  "no_model_supported_action": true,
  "rotation_summary": {
    "add_review": 0,
    "rotation_ideas": 0,
    "trim_review": 0,
    "watch": 2
  },
  "symbol_facts": [
    {
      "analyst_required": false,
      "analyst_upside_pct": -14.8,
      "asset_class": "thematic_interval_fund",
      "held_account_aliases": [
        "taxable",
        "rollover"
      ],
      "held_accounts": [
        "schwab_taxable",
        "schwab_rollover_ira"
      ],
      "held_market_value_total": 22971.6,
      "holding_row_count": 2,
      "manual_only": null,
      "mapping_status": null,
      "sector": "Industrials",
      "symbol": "SPCX"
    },
    {
      "analyst_required": false,
      "analyst_upside_pct": null,
      "asset_class": "sector_etf",
      "held_account_aliases": [
        "rollover"
      ],
      "held_accounts": [
        "schwab_rollover_ira"
      ],
      "held_market_value_total": 26080.98,
      "holding_row_count": 1,
      "manual_only": null,
      "mapping_status": null,
      "sector": "Materials",
      "symbol": "XLB"
    }
  ],
  "symbols_in_question": [
    "SPCX",
    "XLB"
  ]
}

Deterministic grounded answer:
Grounded advisory answer:
- Question reviewed: Should I trim XLB for SPCX? How much should I trim?
- Symbols detected: SPCX, XLB
- The rotation engine does not currently show a model-supported TRIM_REVIEW, ADD_REVIEW, or ROTATE_REVIEW for this question.
- Therefore, no numeric trim amount is supported by the current evidence pack.
- SPCX: sector=Industrials, asset_class=thematic_interval_fund, held_value=$22,971.60, accounts=['schwab_taxable', 'schwab_rollover_ira'], analyst_upside=-14.8, mapping_status=n/a
- XLB: sector=Materials, asset_class=sector_etf, held_value=$26,080.98, accounts=['schwab_rollover_ira'], analyst_upside=n/a, mapping_status=n/a
- Missing data warnings: some holdings are missing sector; some holdings have missing or neutral analyst upside; some scored candidates are missing sector
- Account notes: tax impact is UNKNOWN unless cost basis / realized gain-loss data is present. Do not assume positive or negative tax impact.
- Recommended class: RESEARCH_MORE if you need a dollar/percent trim range; WATCH if you only want to monitor the pair.

Local LLM draft answer to review:
Grounded advisory answer:
- Question reviewed: Should I trim XLB for SPCX? How much should I trim?
- Symbols detected: SPCX, XLB
- The rotation engine does not currently show a model-supported TRIM_REVIEW, ADD_REVIEW, or ROTATE_REVIEW for this question.
- Therefore, no numeric trim amount is supported by the current evidence pack.
- SPCX: sector=Industrials, asset_class=thematic_interval_fund, held_value=$22,971.60, accounts=['schwab_taxable', 'schwab_rollover_ira'], analyst_upside=-14.8, mapping_status=n/a
- XLB: sector=Materials, asset_class=sector_etf, held_value=$26,080.98, accounts=['schwab_rollover_ira'], analyst_upside=n/a, mapping_status=n/a
- Missing data warnings: some holdings are missing sector; some holdings have missing or neutral analyst upside; some scored candidates are missing sector
- Account notes: tax impact is UNKNOWN unless cost basis / realized gain-loss data is present. Do not assume positive or negative tax impact.
- Recommended class: RESEARCH_MORE if you need a dollar/percent trim range; WATCH if you only want to monitor the pair.

Your task:
1. Identify where the local answer overreaches beyond the grounding report.
2. Provide a corrected second-opinion answer.
3. If there is no model-supported action, keep the answer as WATCH or RESEARCH_MORE and state that the range is unavailable.
4. Keep the answer concise and operator-ready.