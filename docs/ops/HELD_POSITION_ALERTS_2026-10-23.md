# Held-position alerts: account names, real stops, promo and tiny positions (P1 2026-10-23, NVDA)

Status:      ACTIVE
as_of:       2026-10-23T17:55:00Z
Measured at: origin/main d42fa803d + PR #2020 (account_display); live pin 80e93c99f (read-only: files + DB in a read-only transaction; no :7777 traffic)

## What happened

At 13:37 ET (Telegram message 60312, `operator_conversation_turns` 1337) the operator was paged:

> 🚨 STOP HIT — NVDA (held, 0.133 sh) $211.70 · quote 6m · unusual news volume (5× normal) · stop $213.00 …
> ▶️ Action: review exit — price is through your plan stop

Operator: "This is a hallucination. I don't own NVIDIA." Later: "Momo gave me that for free for opening my
account. Okay, so on these notices, we need to tag what account it came from."

## Root cause `[VERIFIED]`

| # | Finding | Evidence |
|---|---|---|
| 1 | The position is real: a moomoo account-opening reward. The page never named the account, so it could not be recognised. | `holdings.json` row NVDA, account `moomoo_taxable_live`, 0.133 sh, $28.15, `cost_basis` null, source `moomoo_live_read`, `broker_source` `broker_position_snapshot`, updated 2026-10-23T17:30:03Z; sync receipt `data/runtime/sync_receipts/moomoo_taxable_live.json` ok, n_rows 2 (NVDA + $500 cash). No transaction row exists in any store: `trade_transactions`, `paired_trade_transactions` 0 rows; `holdings.json.transactions` empty. The sync reads positions only (`position_list_query`), not deals. |
| 2 | First seen as held between 2026-09-28 13:00 and 16:00 ET. | `material_changes` NVDA `universe_reason` `watchlist` at 13:00:01 ET, `held+watchlist` from 16:00:02 ET; `cio_entry_states` first `held:true` 2026-09-29 09:00 ET. 91 `held` changes since; 31 SENT as pages, 35 in digests. |
| 3 | The moomoo account was retired on 2026-09-01 ("account closed by operator; feed dead since 2026-08-03") but its feed came back; `account_summaries.moomoo_taxable_live` now reads `retired: true` and `state: LIVE` at once. | `~/trade-ai-releases/holdings-moomoo-retire-20260901-131731/RETIRED_moomoo_taxable_live.json` (its tripwire: "If anything reads moomoo_taxable_live after this date, the retirement was premature"). Not fixed here: broker read code (execution-engineering grant). |
| 4 | "stop $213.00" was not a stop anyone set. It is the stop of a watchlist ENTRY plan: an LLM proposal for a would-be buy, below a 218.50–224.50 buy zone. | `watchlist_entry_plans` id 23236, created 2026-10-21 17:44 ET, `model_used` grok-3-mini, `prompt_version` entry_planner_v1, `proposal_tag` NEEDS_CONFIRMATION, writer `scripts/watchlist_entry_planner.py`. `notify_material_change._watch_context` reads the newest entry plan of the last 7 days for any symbol. No real stop exists: `manual_broker_stops` 0 rows (table empty), `stop_last_known` / `stop_confirmations` / `synthetic_stops` / `fidelity_monitored_stops` / `stop_lifecycle` 0 NVDA rows. |
| 5 | `classify` paged STOP HIT for any held name whose price was at or below the plan stop, with the fixed text "your plan stop". | `scripts/notify_material_change.py` (before this PR): `if held: if lv["hit_stop"]: … STOP_HIT`; `_ACTION["STOP_HIT"] = "review exit — price is through your plan stop"`. |
| 6 | The chart was Telegram's link-preview cache, not Finviz. | The page's preview URL was a constant per symbol (`chart.ashx?cs=l&t=NVDA&tf=d&s=linear&ct=candle_stick`). Fetching it on 2026-10-23 (before 17:55Z) returned HTTP 200 image/png 25,502 bytes headed "Oct 23" (Apr–Oct axis), byte-identical with an extra `_ts` parameter. Telegram caches previews by URL across all of Telegram, so an image first fetched on a Dec 11 was replayed. |
| 7 | `HIT:5bac68b6` in the footer is the ticker HIT (Health In Tech) bound from the words "STOP HIT". | `operator_subject_resolver.resolve_subjects("🚨 STOP HIT — NVDA (held, 0.133 sh)", book=[])` → `HIT 5bac68b6-5456-5bfe-853b-79f40644a815 registry`, `NVDA 245a0597-2bf6-5d3a-a84a-737d39fb1648 registry`. `NVDA:245a0597` is NVDA's `subject_guid`; material change id 46440, `change_guid` 2a4dad7d-6a3c-5aab-83be-9ba2436a631c, news_burst 8 articles vs baseline 1.61 (4.97×), `notify_outcome` SENT at 13:37:17 ET. `7626d49d` is the comms editor message guid (sha of chat + body + time; not stored in a table). |

## What changed

| Where | Change |
|---|---|
| `scripts/lib/held_position_alerts.py` (new) | Per-account rows by NAME (account_display, PR #2020; never digits); tags `promo/reward` (listed in policy, or no cost basis and $0 < value < `promo_max_usd`) and `tiny/untracked` (value < `de_minimis_usd`); stop/exit eligibility with opt-in; stop owner ("your stop" only for an operator-set stop; "Schwab stop order" for a broker-reported one); system level names; `held_account_line` for the comms editor; `scan()` + CLI for the regression list. |
| `config/held_position_alerts.json` (new) | `de_minimis_usd` 100, `promo_max_usd` 100, `exclude_tiny_from_stop_exit_alerts` true, `exclude_promo_from_stop_exit_alerts` true, `comms_editor_account_tag` true, `opt_in` [], `promo_positions` [moomoo NVDA, operator-confirmed]. Env override `TRADEAI_HELD_POSITION_ALERTS`. |
| `scripts/notify_material_change.py` | STOP HIT only on a real stop (`_real_stop`: `stop_last_known` live statuses, `manual_broker_stops` active). A system plan level crossed on a held name goes to the digest: "below system entry-plan level $213.00 (not a stop you set)". STOP/TARGET/BIG MOVE pages skip tiny/promo positions unless opted in. Every page and digest line names each holding account with its shares. TARGET HIT says "system entry-plan target (not a target you set)". The chart preview is omitted unless the quote is fresh. |
| `scripts/lib/comms_editor.py` | Any outbound notice about a held position (says held / holding / position / stop / exit / trim / sell) whose subjects are held, and which does not already name the account, gets `📁 Held in SYM: <account> <n> sh (tag)`. This is the shared chokepoint, so every template is covered. |
| `scripts/lib/telegram_rich.py` | `chart_image_url` carries `&v=<UTC minute>`: every send is fetched fresh. |
| `scripts/lib/operator_subject_resolver.py` | `HIT` joins the alert-chrome stop list. |

The NVDA replay (`tests/test_held_position_alerts_20261023.py`) now produces no page, and the digest line reads
`NVDA $211.70 · held · moomoo Taxable 0.133 sh (promo/reward) · … · below system entry-plan level $213.00 (not a stop you set)`.

## Regression scan `[VERIFIED]` 2026-10-23 ~17:50Z, live holdings.json, read-only

`python3 -m scripts.lib.held_position_alerts --holdings <holdings.json>` lists 15 positions that the new policy keeps
out of stop and exit pages (they stay in holdings and digests):

| Symbol | Account | Shares | Value | Cost | Tag |
|---|---|---|---|---|---|
| NVDA | moomoo Taxable | 0.133 | $28.15 | none | promo/reward |
| PFLT | Schwab Individual | 1.146 | $7.21 | $10.98 | tiny |
| SCHG | Schwab Individual | 0.23 | $8.01 | $7.00 | tiny |
| SCHD | Schwab Individual | 0.548 | $19.30 | $17.36 | tiny |
| LDOS | Schwab Individual | 0.227 | $30.97 | $40.16 | tiny |
| CSWC | Schwab Individual | 3.594 | $79.86 | $86.25 | tiny |
| DIV | Schwab Individual | 4.679 | $89.52 | $92.33 | tiny |
| RTX | Schwab Individual | 0.495 | $94.79 | $102.34 | tiny |
| 12507E201 | Schwab Individual | 7 | $0.00 | none | tiny (dead line) |
| XLI | Schwab Rollover IRA | 0.044 | $7.30 | $7.97 | tiny |
| JEPI | Schwab Rollover IRA | 0.394 | $22.42 | $22.37 | tiny |
| BND | Schwab Rollover IRA | 0.776 | $55.29 | $55.83 | tiny |
| SRNE | Schwab Rollover IRA | 1,000 | $0.50 | $13,177.95 | tiny |
| 543354104 | Schwab Rollover IRA | 3,000 | $0.00 | $4,762.95 | tiny (dead line) |
| 628518102 | Schwab Rollover IRA | 125 | $0.00 | none | tiny (dead line) |

"your stop / plan stop" wording found (`grep -rniE "your (plan |trailing |hard )?stop"` over scripts, config, CC v3 src):
`scripts/notify_material_change.py` `_ACTION["STOP_HIT"]` (fixed here) and `TARGET_HIT` "your plan target" (fixed here);
`apps/command-center-v3/src/pages/RotationIntelligence.tsx:493` "toward your stop discipline" (generic advice, not a level; left);
`scripts/open_trade_monitor.py:303` (comment only).

## Not fixed here (owners)

- The retired moomoo account is live again (finding 3). Broker read code: needs an `execution-engineering` grant to change, or an operator decision to un-retire the account record.
- `watchlist_strategy_cards` NVDA thesis (tax_agent) calls it "a $29, 0.1-share stub … in an IRA": wrong account; the card writer does not read account names.
- Each page is captured twice in `operator_conversation_turns` (1337 and 1338, same text, 5 ms apart).

## Tests and gate

`tests/test_held_position_alerts_20261023.py` (hermetic: fixtures; no DB, network, broker or Telegram), gate
`config/ci_gates/held_position_alerts_20261023.json`. Existing goldens updated for the account name and stop owner.
