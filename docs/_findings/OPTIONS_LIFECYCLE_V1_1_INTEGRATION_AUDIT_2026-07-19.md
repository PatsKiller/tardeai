# Options Lifecycle v1.1 — Integration Audit (read-only, 2026-07-19)

Status:      HISTORICAL
as_of:       2026-07-19T10:39:52-04:00
Measured at: efcc51365 / not measured

## Canonical map (source → identity → journal path)

| Flow | Canonical source | Identity | Journal identity today | Gap |
|---|---|---|---|---|
| Lifecycle strategies | options_strategy_positions/legs | strategy_position_id, roll_root_id, OCC per leg | **NONE** | no journal bridge |
| Equity trade instances | trade_instances (353) | trade_uid UNIQUE; UNIQUE(source_table, source_trade_id) | itself (canonical registry) | no options source_system |
| Closed equity journal | trade_closed (154) ← schwab_round_trips DELETE-rebuild | dedupe_key ('srt:'‖id); trade_key=symbol:account:close_date | itself | equity semantics only |
| Header journal tiles | state/trade_journal.json (legacy FIFO CSV) | file | separate basis, labeled | leave untouched |
| Options journal table | journal_options_groups | group_key | **ORPHAN — zero readers/writers** | superseded by v1.1 bridge |
| Per-ticker performance | /api/v2/journal/by-ticker over trade_closed | symbol | realized equity only | no option component, no dividends, no combined |
| Dividends | trade_transactions (Dividend actions) | dedupe_key date|action|symbol|qty|acct | per-ticker sums exist (journal_ticker_lifecycle, portfolio_tax) | not joined to attribution |
| Manual executions | manual_execution_log | serial id; (origin_type, origin_id) | journaled flag | no strategy_position link |
| Telegram delivery | telegram_outbox + alert_events.telegram_* ; router dedupe is IN-MEMORY | message ids | n/a | lifecycle alerts now persist own delivery evidence (v1.1 P8) |
| Defense 2FA | defense_order_intents.twofa_code/_requested_at | intent_key UNIQUE | audit table | untouched; lifecycle has its own challenge columns (v1.1 P2) |

## Where double counting could occur (and the rules preventing it)

1. **trade_closed vs lifecycle outcomes** — trade_closed is DELETE-rebuilt from
   schwab_round_trips for `account LIKE 'schwab%'`; inserting option strategies
   there would be destroyed on rebuild AND double-count against the lifecycle
   outcome ledger. RULE: the bridge writes **trade_instances only**
   (source_table='options_strategy_positions'), never trade_closed.
2. **Grouping by underlying+date** — two CSCO strategies opened the same day
   would merge; a roll spanning dates would split. RULE: journal identity is
   `strategy_position_id + roll_root_id + account_key + underlying`; trade_uid
   = 'options_strategy_positions:<spid>'; the UNIQUE(source_table,
   source_trade_id) constraint makes the bridge idempotent by construction.
3. **Covered-call premium vs stock return** — premium must never inflate stock
   price return. RULE (P6): stock, options, dividends, fees are separate
   components; combined is their sum; raw stock return is never relabeled.
4. **Assignment** — share delivery must not count option P&L twice. RULE:
   option leg realizes premium-only economics; share basis shift lands in the
   stock component; the attribution invariant (stock + options + dividends −
   fees = combined) catches any leak.
5. **journal_options_groups** — orphan (defined 2026-06-28, zero readers or
   writers repo-wide). Marked SUPERSEDED by the v1.1 bridge; left frozen.

## Journal identity (authoritative, per validation verdict)

```
strategy_position_id + roll_root_id + account_key + underlying
```
Events: OPEN / PARTIAL_FILL / ADJUST / ROLL / PARTIAL_CLOSE / CLOSE /
EXPIRE_WORTHLESS / ASSIGNED / EXERCISED / CANCELLED — persisted in
`options_journal_events`, emitted ONLY from fill/expiry/assignment evidence
(never from proposals, alerts, ticket creation, or 2FA).

## Existing infrastructure reused (never duplicated)

- trade_instances upsert pattern (ON CONFLICT (source_table, source_trade_id)).
- Free-seat LLM lanes: llm_lane (:8645 grok / :8646 chatgpt) via the Defense
  oversight quota config — options oversight gets its own table + triggers;
  PAID lanes DISABLED by default in options lifecycle policy.
- Drive sync: scripts/sync-docs-to-drive.sh hourly at :05 (gog CLI,
  Trade_AI_Docs_v2). Parity checker added on top of its manifest.
- Telegram: router gate + delivery evidence now persisted on lifecycle alerts.
