# Positions — one source of truth (design, 2026-10-05)

Operator, 2026-10-05: *"Why are we using holdings.json when we converted it to a database six months ago? …
I need to make sure this type of error won't happen again."* and *"All of the alerts — the source of truth
should be the Command Center for all data … each individual process should not be going out looking for
its own data sources."*

## What happened, twice

| | April–July 2026 | October 2026 |
|---|---|---|
| Store | DB `holdings` table (writer died 2026-04-19) and `holdings_json_mirror` (died 2026-05-09) | `holdings.json` rows |
| Failure | readers kept consuming April data for months; nothing alarmed | `current_price` frozen inside each row; the holdings API preferred it over the live quote |
| Detection | operator, by eye | operator, by eye (SPCX $136.46 vs Schwab $171.09) |
| Common cause | a stored copy of a fact silently stopped being refreshed, and readers could not tell | same |

PR #58 (2026-07-03) retired the dead table and mirror and pointed readers at holdings.json. That fixed the
symptom and kept the cause: there is still no single writer with a freshness heartbeat, and ~290 files read
the store directly, each choosing its own field.

## Rules

1. **A position record holds facts, not marks.** Quantity, cost basis (with its source), account, lots,
   broker confirmation time. A price stored on it is at most a fallback mark that travels with its own
   `as_of`. Display price, value and P&L are computed **at read time**.
2. **One accessor.** `scripts/lib/portfolio_positions.py` — `load_store()`, `resolve_mark()`,
   `value_and_pl()`, `per_share_cost()`. The price is the Command Center data-broker quote
   (`lib.data_broker.market_quote.get_price_batch` → `market_quotes`, with `as_of`), then the Finviz live cache
   the repricer reads, then the stored mark flagged with its age. `current_price` is never read. Stale beyond
   `config/portfolio_positions.yaml price_stale_after_s` → shown as stale, never as live.
3. **One writer per fact.** Broker facts (qty, average price, market value at confirmation) are written by
   the broker read syncs only (Schwab position sync; moomoo / Alpaca read syncs; Fidelity manual entry).
   Marks are written by the repricer only. Closed trades are written by `schwab_journal_builder.py` only
   (it already rebuilds `trade_closed` from `schwab_round_trips`).
4. **Every writer has a heartbeat; every stale writer is a health finding.** The April failure lasted
   months because nothing measured the writer. Each writer stamps `written_at`; the health agent raises a
   finding when it is older than its contract.
5. **Divergent copies are reported, never auto-resolved** (AGENTS.md §0 rule 5). Where the operator's
   cost anchors and the broker's basis differ, both are shown (`cost_basis`, `cost_basis_broker`,
   `cost_basis_note`) until the operator decides.
6. **Reconciliation is continuous.** `scripts/portfolio_reconcile.py` (read-only) compares every open
   position and every sale with the broker; the lane `portfolio-broker-reconciliation` runs it on a schedule
   once approved, and a non-empty result is a health finding.

## Target architecture

```
broker read syncs ─┐                                   ┌─ holdings.json  (generated, read-only export,
(Schwab / moomoo / │   positions table (DB)            │   with as_of + tripwire if older than the table)
 Alpaca / manual)  ├─► one row per account×symbol ─────┤
                   │   qty · cost · lots · confirmed_at│
repricer ──────────┘   (no display price)              └─ lib/portfolio_positions (the only reader API)
data broker quotes ──────────────────────────────────────► resolve_mark → value_and_pl → every surface
```

- **Authoritative store:** a DB `positions` table written only by the broker syncs (and the Fidelity
  manual path), keyed account×symbol, with `confirmed_at` per row and a writer heartbeat row.
- **holdings.json** becomes a generated export of that table, regenerated after every sync; a tripwire
  fails health if the export is older than the table.
- **Readers** go through `lib/portfolio_positions` only.

## Migration plan (phases)

| Phase | Scope | Proof |
|---|---|---|
| **1 — this PR** | accessor; holdings / accounts-live / analyst-detail priced through it; repricer keeps the legacy `current_price` alias equal to the mark; stale anchors not scaled; REALIZED/TRADING clean + disclosed; builder trade dates; reconciliation tool + report; ratchet freezing the 288 direct readers | `tests/test_portfolio_price_truth_20261005.py`; reconciliation after-run: 0 price/value mismatches |
| 2 | migrate the highest-traffic readers (stop management, risk, protection, CIO evidence, Telegram producers) to the accessor, shrinking the allowlist; health finding from the reconciliation lane | allowlist count falls each PR |
| 3 | DB `positions` table + single-writer syncs + heartbeat; holdings.json generated from it with the tripwire | writer heartbeat finding fires in a drill |
| 4 | retire stored marks on position rows (`price`, `current_price`, `canonical_mark` move to the quote store); remaining readers migrated; allowlist empty | ratchet allowlist = ∅ |

## Operator decisions (AGENTS.md §17)

1. Approve the reconciliation lane schedule (proposed cron in `config/lane_registry.json`).
2. Cost basis policy where the April anchors and broker basis disagree (keep anchors, or broker supersedes).
3. Supply Schwab's Realized Gain/Loss export for the 33 basis-unknown sells, or accept them as disclosed
   exclusions from REALIZED.
4. Approve phase 3 (new DB table + export) when phase 2 is done.
