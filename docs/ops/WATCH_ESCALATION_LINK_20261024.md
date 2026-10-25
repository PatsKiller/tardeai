# ASK item 9: correct the escalation My Watchlist link

Design-Task: DSN-20261024-watch-escalation-link-P1-T1

Worker `codex-watch-escalation-link-20261024`; claim `20261024T224046Z-codex-43e44b43`.
Accepted base `d635873e1063efb8a9ff8e8ce542654ed2ef7654` (SITE PR #2076).

## Cause and change

`process_watchlist_agent_jobs.py` sent `Review at: /v2/watchlist?symbol=TSLA`. Notification normalization replaced the legacy path with `/v3/watch?tab=watchlist`, leaving the original `?symbol=TSLA` attached. That produced two query separators. `watchlist` is also a legacy tab that redirects to Classic; today's operator list is `my-watchlist`.

The actual escalation sender now uses a pure message constructor, which calls the existing central `build_dashboard_url("/v3/watch", {"tab": "my-watchlist", "symbol": symbol})`. The resulting configured-host URL has `?tab=my-watchlist&symbol=TSLA`. Symbol values are encoded as query values, including spaces, ampersands and fragment characters. The message prefix, synthesis/confidence/reasons, producer identity, priority and escalation criteria remain unchanged.

The shared URL builder and execution-related helpers are untouched. This source change corrects the identified escalation writer, without running it or sending a notification. Current CIO-view alignment belongs to the separate Ask item 8 package. The current My Watchlist page retains `symbol` in the URL but does not auto-open that row; this is a separate frontend limitation, not evidence that this link selects a detail record.

## Verification

Five new isolated fixture tests pass with the PostgreSQL driver hidden:

- The actual constructor survives central notification normalization, targets the current WatchHub slug and has exactly one query separator.
- Symbols containing punctuation or query/fragment syntax remain one encoded value.
- The actual sender AST expression is executed with a recording fake; message text and `priority=P2` / producer metadata are retained. The worker module is never imported or run.
- The worker's scripts-only import layout reaches the same central builder as the package layout.

The CI gate is registered through `scripts.lib.ci_gates.render`. Both strict real-tree CIO checks pass (2), and dark-contract, retention, coverage and host-path guards pass with no new violations. The generated documentation index passes. There are no frontend changes requiring a new native build; the tab contract is checked against the accepted WatchHub source. There are no model, provider, database, scheduler, broker or real messaging calls. Source publication and live notification verification remain coordinator/operator work.
