# Account names on every position and trade row (2026-10-23)

```
Status:      ACTIVE (code on branch feat/cc-account-labels-20261023; not deployed by this PR)
as_of:       2026-10-23T13:00:00-04:00
Measured at: holdings.json read-only 2026-10-23 13:07 ET (data/portfolios/state/holdings.json); fixtures only for the UI
```

Operator, 2026-10-23 ~13:00 ET (verbatim): "you need to actually put which account right here. Like, for example,
there are two SpaceX and two different accounts." Then: "just a name, not the account numbers."

## The rule

Every Command Center row that shows a position, a held or formerly-held name, a fill, a stop, a P/L or a trade
names the account it belongs to. **It uses the account's name only.** It never shows an account number or masked
digits (no "··1234"), in the UI, the API labels or the tooltips. A symbol held in two accounts is never merged
into one row without saying so. It is either one row per account, or one grouped row ("SPCX · 2 accounts") that
expands to the per-account rows.

## One source for names

| Where | What |
|---|---|
| `config/account_display_names.json` | `names` (account key → name, broker, type, `status`) and `aliases` (`schwab_roth` → `schwab_roth_ira`). Every name is digit-free and unique (test). |
| `scripts/lib/account_display.py` | `account_label(key)`, `canonical_key`, `label_row(s)` (adds `account_id` + `account_label` to copies of the rows), `multi_account_symbols`. A key that looks like an account number (3+ digits, or a masked tail) becomes "Unlabelled account". It is never echoed. |
| `apps/command-center-v3/src/lib/accountLabels.ts` | The same map for the UI: `accountName`, `rowAccountName`, `groupBySymbol`, `multiAccountSymbols`, `accountsBadge`. The test asserts it matches the config. `holdingsRowModel.accountFullName` and Journal's `ACCT_LABEL` now delegate to it. |
| `components/AccountChip.tsx` | `AccountChip` (the name) and `AccountsBadge` ("2 accounts"). |

### Names: confirmed or proposed

| Key | Name | Status |
|---|---|---|
| `schwab_rollover_ira` | Schwab Rollover IRA | from the registry (`holdings.json config.accounts.display_name`) |
| `schwab_roth_ira` (`schwab_roth`) | Schwab Roth IRA | from the registry |
| `schwab_taxable` | Schwab Individual | registry "Schwab Individual (Taxable)", shortened. **Operator to confirm.** |
| `fidelity_rollover_ira` | Fidelity Rollover IRA | from the registry |
| `alpaca_taxable_live` | Alpaca Individual | **proposed** (registry: "Alpaca Taxable (Live · read-only data)") |
| `alpaca_ira_live` | Alpaca IRA | **proposed** |
| `moomoo_taxable_live` | Moomoo Individual | **proposed** (registry: "Moomoo Taxable (Live · read-only data)") |
| `tradeai_automated` | Alpaca Paper | **proposed** (the operator's own example) |

## The live case

Read-only from holdings.json at 13:07 ET:
- SPCX: 200 sh in `schwab_taxable` and 700 sh in `schwab_rollover_ira`.
- SCHD, SCHG and V are each also held in two accounts.

Before this change:
- Home "What moved your book today" listed SPCX twice (+$1,488 and +$507) with no account.
- PR #1975 then summed the two rows into one unlabelled SPCX bar.

## Audit: what each surface showed before this change

| Surface | API carried the account? | UI showed it? | Two accounts | Fixed here |
|---|---|---|---|---|
| Home: movers card | no (`/api/v2/overview` `top_movers`) | no | duplicated, unlabelled. Then merged by #1975. | API now emits `account_id` + `account_label`. UI: a grouped row with a "2 accounts" badge that expands (see "Home movers"). |
| Home: do-now queue | raw keys in evidence | raw keys in the why text | merged per symbol. A stop in one account hid the other account's unprotected shares. | Names in the why text and `evidence.account_labels`. Stops are counted per account, and the money is the unprotected accounts only. |
| Home: accounts table | yes | yes | per account | already right |
| Header / portfolio strip | totals only | n/a | n/a | n/a |
| Portfolio holdings, Returns winners/losers, Tax lots | key; label added on the client | yes | per account | names now come from the one map |
| Returns / Risk: risk bars and heatmap | key | no | duplicated "SPCX" bars | one bar or cell per account, named "SPCX · Schwab Individual" |
| Risk: triggered / no-stop chips | key | no (raw key in the drill subtitle) | duplicated, unlabelled, duplicate React keys | an `AccountChip` on each chip, keyed per account. `/api/v2/risk` positions carry `account_label`. |
| Risk: Recovery | key | yes | per row | already right (uses the one map now) |
| Trading: Open Trades | key + label | yes | per account | the excluded-rows drawer now shows the name instead of the key |
| Trading: Schwab accounts monitor | key | key, uppercased | grouped per account | after batch 9 merges (file held by #2014 / batch 9) |
| Trading: Proposals (card V4) | key | key with `_` → space | per proposal | name |
| Watch: held / formerly held / last trade / re-entry | no (`last_sells` GROUP BY symbol, `round_trip_view` dropped `life.account`) | no | merged | after batch 9 merges (files held by #2008 / batch 9) |
| Re-entry exit workbench | key | raw keys | merged, with an accounts list | names, plus a "2 accounts" badge |
| Active Trader session review | key on fills | no | P&L summed per symbol | `you[].account_label`, `metrics.your_accounts`. The name is shown on your buy and sell rows and in the header. |
| Journal / TradeInView log table, detail | key | raw normalized key | per account | names. Journal trades carry `account_label`. |
| CIO Desk: NOW decisions | `accounts[]` | `accounts[0]` only | merged and mislabelled | cards carry `accounts` + `account_labels` (all of them). UI after batch 9 merges (CioHub.tsx held). |

## Home movers

To be completed once batch 9 merges: grouped row, expand per account, footer sums unchanged.

## Tests

- `tests/test_account_display_labels_20261023.py` (CI gate `account_labels_20261023`). It covers:
  - names only, unique, never a number
  - the TS map mirrors the config
  - overview, risk and journal labels
  - do-now per-account stops
  - CIO accounts
  - Active Trader fills
- `src/lib/accountLabels.test.ts` (in `npm run build`).
- `e2e/account-labels.spec.ts`:
  - fixture: SPCX in two accounts, at 1440 and 412 px
  - Risk chips and per-account heatmap
  - Journal table names
  - Home movers grouped row
  - no account number anywhere on the page
  - screenshots in `~/.cache/rtc/acctlabel/`
