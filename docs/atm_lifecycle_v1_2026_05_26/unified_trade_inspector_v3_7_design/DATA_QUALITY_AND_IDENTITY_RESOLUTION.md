# Identity Resolution

Priority order:
1. paper_trade_id (most specific)
2. lifecycle trace_id
3. proposal_id
4. symbol + strategy_id + account
5. symbol only (least specific, may return multiple)

## Known Cases
- BLMN: #37 (duplicate_submit_race, closed) vs #38 (real open) — inspector must resolve by paper_trade_id
- APPS: #34 (closed, repaired) — inspector shows repair audit trail
- AGNC: #31 (open) — clean lifecycle
- Missed proposals: no paper_trade_id — resolve by proposal_id or symbol+strategy

## Missing Data Handling
- Missing trace: show "No lifecycle trace linked"
- Missing TCA: show "Execution quality not captured"
- Missing stop audit: show "No stop changes recorded"
- Missing backtest: show "No backtest comparison available"
