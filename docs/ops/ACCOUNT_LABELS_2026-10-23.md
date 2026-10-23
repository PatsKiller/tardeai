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

The backend lookup went out first, as its own PR, #2020: config, `account_display.py` and gate `account_display_lib_20261023`. The NVDA Telegram notices reuse it.


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
| `moomoo_taxable_live` | moomoo Taxable | **operator-confirmed** 2026-10-23 (via coordinator) |
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
| Trading: Schwab accounts monitor | key | key, uppercased | grouped per account | the panel header, filter chips and orders column show the name |
| Trading: Proposals (card V4) | key | key with `_` → space | per proposal | name |
| Watch: held / formerly held / last trade / re-entry | no (`last_sells` GROUP BY symbol, `round_trip_view` dropped `life.account`) | no | merged | See the notes below this table. |
| Re-entry exit workbench | key | raw keys | merged, with an accounts list | names, plus a "2 accounts" badge |
| Active Trader session review | key on fills | no | P&L summed per symbol | `you[].account_label`, `metrics.your_accounts`. The name is shown on your buy and sell rows and in the header. |
| Journal / TradeInView log table, detail | key | raw normalized key | per account | names. Journal trades carry `account_label`. |
| CIO Desk: NOW decisions, action book | `accounts[]` | `accounts[0]` only | merged and mislabelled | Cards carry `accounts` + `account_labels` (all of them). The card shows every account chip, plus a "2 accounts" badge when there are two. Action-book rows name their accounts when the row carries them. |
| Home classic (`?view=classic`): stops, winners/losers | raw key; `/api/v2/command` day movers summed per symbol | raw key / none | merged | Stops show names. Day movers carry `accounts`, `account_labels` and `by_account`. A row shows its account name, or "2 accounts" with the per-account split in the tooltip. |

Watch (held / formerly held / last trade / re-entry):
- The held reader (`watch_domains.held_positions`) now also returns `accounts_by_symbol`, read from `positions_current.account_key` or the holdings row's `account`. The public payload shows only a count.
- `last_sells` now returns the most recent sell and its account.
- `round_trip_view` keeps `account` and `account_label`.
- `facts_for` adds `held_accounts`, `held_account_labels`, `last_sell_account` and `last_sell_account_label`.
- The chips read "held · 2 accounts" or "held · Schwab Roth IRA", and "formerly held · sold Oct 22 · Schwab Rollover IRA".
- The detail view says "Sold in <account>".

## Home movers

`moversBars()` (`lib/homeDoNow.ts`) groups `top_movers` by symbol but keeps every account:
- Each group carries the per-account amounts, each with its account name.
- `multi` is true when the symbol is in 2 or more accounts.
- The card shows "SPCX · 2 accounts +$1,995" with an expand control. Expanded, it shows "Schwab Rollover IRA +$1,488" and "Schwab Individual +$507".
- A single-account row shows its account chip.

`shownSum` is the sum of the groups shown, so the footer still reconciles. On the operator's example it reads "Shown +$154 · rest of the book −$117 · day +$37".

The accounts table on Home uses the same names ("Schwab Roth IRA", not "Schwab Roth").

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
