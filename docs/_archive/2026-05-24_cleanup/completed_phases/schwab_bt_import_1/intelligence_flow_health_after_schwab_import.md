# Intelligence Flow Health Report

Generated: 2026-05-23T01:17:52.184424+00:00

## Summary
- Accounts: 5 (1 enabled)
- Trades: 31 (5 open, 11 closed)
- Enrichment symbols: 2034
- RAG documents: 16543
- Backtest runs: 33
- Closed trades missing backtest: 3
- Hardcoding warnings: 2

## Accounts

| Label | Broker | Mode | Enabled |
|---|---|---|---|
| alpaca_paper | alpaca | paper | True |
| schwab_rollover_ira | schwab | live | False |
| schwab_roth_ira | schwab | live | False |
| schwab_taxable | schwab | live | False |
| fidelity_401k | fidelity | live | False |

## Trades by Account

| Account | Total | Open | Closed |
|---|---|---|---|
| ALPACA_PAPER | 24 | 3 | 9 |
| TOS_PAPER | 7 | 2 | 2 |

## Closed Trades Missing Backtest

- #21 INFU (earnings_catalyst) account=ALPACA_PAPER
- #30 AGNC (reit_income) account=TOS_PAPER
- #32 CMCSA (dividend_growth_compounder) account=TOS_PAPER

## Hardcoding Warnings

- atm_auto_approver.py:255 defaults to 'alpaca_paper' if target_account NULL
- paper_trade_proposals.proposed_account defaults to 'TOS_PAPER' in schema
