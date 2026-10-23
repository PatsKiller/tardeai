---
id: DSN-20261023-account-labels
title: Account names on every row, alert and notice (never numbers)
status: IN_PROGRESS
approval: 'approved (operator 2026-10-23: "just a name, not the account numbers")'
source: 'PR #2020 (feat/account-display-lib-20261023)'
summary: One display name per account; promo/reward positions tagged and kept out of stop/exit alerts; stops labelled by provenance.
phases:
- id: DSN-20261023-account-labels-P1
  title: 'account_display lib — #2020 (green, lands first)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-account-labels-P1-T1
    title: 'Land #2020 account_display lib in batch 10'
    status: PROPOSED
    areas:
    - scripts/lib/account_display.py
- id: DSN-20261023-account-labels-P2
  title: CC v3 position/trade rows carry the account name (claim acctlabel, branch feat/cc-account-labels-20261023)
  status: IN_PROGRESS
- id: DSN-20261023-account-labels-P3
  title: Telegram/notice account tags + promo exclusion (NVDA PR, DSN-20261023-nvda-false-alert)
  status: IN_PROGRESS
---

Backfill 2026-10-23. Finding: #1975 moversBars summed SPCX across accounts into one bar (fixed for duplicates; the
account label lands with P2).
