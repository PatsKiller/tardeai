# Premarket Observation Harness — Architecture

## Composition (thin root over deterministic modules)
```
run_active_trader_premarket_observation.py   (composition root; CLI; git-SHA read for auth)
  ├─ market_calendar.py                 ExchangeCalendar Protocol + NyseCalendar (2026-27, fail-closed)
  ├─ premarket_observation.py           windows · ObservationEvent · Level2Metrics · cross-checks
  │                                      · VerdictPolicy + evaluate() · DataOnlyQuoteAdapter Protocol
  │                                      · ExtendedHoursSubscriptionRequest · ObservationController FSM
  ├─ premarket_symbol_selector.py       pure representative-symbol selector (read-only)
  ├─ premarket_observation_schedule.py  transient-unit renderer · ObservationAuthorizationMarker
  └─ active_trader.moomoo.{features,replay,gateway,ast_guard,secret_render}  (Stage 5, reused)
```

## Design rules
- **Deterministic core:** all business logic is pure over an event list; same events -> byte-identical
  metrics + verdicts (replay-equality). No wall-clock sleeping, no network, no SDK import in the core.
- **Single time axis:** ET seconds-since-midnight derived from timezone-aware receive timestamps; used
  for both window classification and gap accounting. Naive datetimes are rejected at boundaries.
- **Injected dependencies:** the controller takes clock, sleeper, calendar, adapter, storage — tests
  drive it with fake time and a fake data-only adapter; OpenD/SDK never touched.
- **Data-only adapter Protocol:** only quote/data methods; no trade context/method; no generic invoke.
- **No live authority:** the live executable refuses without an owner authorization marker; the
  scheduler renderer never invokes systemd-run/systemctl/at/cron.
- **Storage reuse:** WAL (checksummed, crash-recoverable) -> verified zstd Parquet -> replay, via the
  existing Stage 5 replay module; raw high-frequency data stays local (never Git/Drive/email).

## Live runtime (later, authorized only)
06:55-10:05 ET, SIGTERM/SIGINT -> one safe teardown path, no busy-wait, no auto-retry after an
auth/agreement/security failure.
