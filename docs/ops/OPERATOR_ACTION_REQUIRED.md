# OPERATOR_ACTION_REQUIRED — live advisory notification canary

**Authority:** READ_ONLY_ADVISORY  
**Date:** 2026-08-25  
**Does not change trading, broker, stop, risk, or 2FA authority.**

## One exact control

Live `tradeai-cio-material-scan.service` already runs `scripts/cio_material_scan.py --live` with:

- `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1`
- `CIO_TELEGRAM_INTERDICT=0`
- `delivery_mode=CIO_ONLY_LIVE`

Financial-lane Telegram still stays dry unless:

```text
CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY=1
```

is set on that unit (or its EnvironmentFile). Default is **OFF**. This is the remaining transport gate. R12 did **not** enable it.

## Why not auto-enabled

`scan_office` forces `dry_run=True` when the canary is unset even if `--live` is passed. That is the designed second lock. Enabling it is an operator notification-transport decision, not a code default.

## What will happen if enabled

Natural scans that `decide_notification` classifies as `IMMEDIATE` may send one CIO Telegram card. Current natural scans classify cash/reentry/TRIM as `SUPPRESSED` / `unchanged_replay` and `HOLD_CASH` as `non_action_state`, so enabling the canary alone may still produce intelligent silence until a genuine material generation change.

## Also required for R11 situation engine on the live host

CURRENT is still `1afb1479` (pre-R11). PR #506/#R12 source is not deployed. Deploy of this branch is a separate operator action.

## Do not

- Invent a cash band
- Merge #505
- Uninstall GPU models
- Raise MEMORY_BEHAVIOR_INFLUENCE
