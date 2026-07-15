# Transfer-Aware Position Tracking & YTD Performance

**Status:** Active (wired into Schwab/SnapTrade holdings write + CC v3 Returns)  
**Date:** 2026-07-15

## Problem

Mid-year **Fidelity 401k → Rollover IRA** renames, **Fidelity → Schwab** rollovers, and yearly **Traditional IRA → Roth** ladder conversions break naive NAV performance:

- Per-account YTD looks like a wipeout or jackpot (money left/entered the account).
- Aggregate portfolio YTD disagrees with the sum of real accounts.
- Fidelity multi-day periods (1W/1M/…) go blank after the account key changes.
- New lots look like purchases instead of continuation of the same holding.

## Model

### Holdings row provenance (JSON SSOT)

| Field | Meaning |
|-------|---------|
| `original_source_account` | First known source sleeve (e.g. `fidelity_rollover_ira`) |
| `current_account` | Live account key |
| `transfer_history[]` | Movements: date, from/to, shares, basis if known, type |
| `system_shares` / `broker_actual_shares` | Same dual book as share reconciliation |
| `performance_adjusted` / `adjusted_for_transfer` | Residual path should treat lot as transfer-aware |
| `normalized_after_transfer` / `transfer_display_note` | UI status + note |

### Postgres audit (migration `2026_07_23_position_transfer_history.sql`)

| Table | Purpose |
|-------|---------|
| `position_transfer_history` | Durable transfer ledger (type, confidence, status, basis) |
| `position_normalization_log` | Immutable auto/manual normalize + stop-impact flags |
| `position_transfer_notifications` | Operator notices (rollover active / Roth ladder season) |

Transfer types: `fidelity_to_schwab` · `traditional_to_roth` · `external_rollover` · `internal_transfer` · `other`.

## Detection & normalize

On every holdings write through `protected_holdings_write` (Schwab + SnapTrade):

1. `lib.cost_basis_transfer.detect_transfers` pairs cross-account share moves.
2. `lib.position_transfer_normalize.process_and_normalize`:
   - Classifies transfer type
   - High-confidence → auto basis carry-forward + provenance stamp
   - Persists DB history + normalization audit
   - Flags live stop qty mismatch (replace-mode 2FA; no auto cancel)
   - Opens transfer notification when batch normalizes

CLI / API:

| Method | Path |
|--------|------|
| GET | `/api/v2/holdings/transfer-history` |
| GET | `/api/v2/holdings/transfer-notifications` |
| POST | `/api/v2/holdings/transfer-notifications/dismiss` |
| POST | `/api/v2/holdings/transfer-detect` |

## Performance calculation

Module: `scripts/portfolio_period_quality.py` (called from `api_v2.portfolio_performance`).

### Household residual (≈ market)

For **YTD only**, NAV change is split into estimated **market P/L** vs **net flow** using consecutive household snapshots so internal transfers do not look like losses/gains.

### Fidelity economic sleeve

`fidelity_401k` + `fidelity_rollover_ira` are one economic sleeve. Missing 1W/1M/3M/6M/1Y cells are filled from **linked** snapshot history after the rename.

### Portfolio aggregates

All-accounts periods prefer **Σ of per-account display** so Fidelity (or any sleeve) is never dropped from 1W/1M when history was sparse.

### Daily YTD pin

| Item | Detail |
|------|--------|
| File | `data/portfolios/state/ytd_daily_pin.json` |
| Behavior | First successful YTD compute of the calendar day freezes ≈ market display values |
| Path hygiene | Outlier/partial snapshots (e.g. single-day 10% wipe stubs) are excluded from residual path |
| End value | Live holdings at pin time; residual path uses live end after filter |
| Force refresh | `YTD_PIN_FORCE=1` or delete the pin file |
| Not pinned | 1D market day, header total / today P&L, 1W–1Y NAV fills |

### UI notes (CC v3 Returns)

- `ex-transfers` · `includes Fidelity rollover` · `Roth conversion – performance carried forward`
- Transfer notifications banner when rollover/Roth batch normalizes
- Position detail: transfer history section; holdings table provenance chip

## Related

- Share drift / DRIP: `docs/features/share-reconciliation.md`
- Cost-basis carry-forward: `scripts/lib/cost_basis_transfer.py`
- Performance history rebuild: `scripts/portfolio_performance_history.py` (includes `fidelity_rollover_ira` + linked 401k anchors)

## Tests

```bash
.venv/bin/pytest tests/test_position_transfer_normalize.py tests/test_cost_basis_transfer.py -q
```

## Non-goals

- Perfect TWR / money-weighted returns (residual is approximate)
- Auto-replace of live Schwab stops after transfer
- Silent basis fabrication without source position or Fidelity PDF anchor
