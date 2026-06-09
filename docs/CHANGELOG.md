# Changelog

## 2026-06-09 — Holdings wipe-guard made mandatory (behavior change)

`protected_holdings_write()` is now mandatory for all 7 holdings/current-state writers (db_adapter,
portfolio_loader, portfolio_server, holdings_reconcile, phase2/phase3 resolvers, patch_holdings_cost_basis)
via `scripts/holdings_guard.py`. Added a catastrophic-drop reject (new total < 50% of last-good) + loud
Telegram alerts on block/restore. A/B split: wipe-guard mandatory for all; basis-preservation opt-in
(`protect_basis=True`, Schwab sync only) so legitimate basis edits aren't reverted. **Closes** the
programmatic-wipe vector; **does NOT close** the deploy/zip-extraction vector (tracked follow-up:
pre-deploy state-guard). Proven: empty→rejected, drop→rejected, forced-failure→restored byte-identical,
normal write OK ($1.24M/48, no false positive), 0 screener/classifier/GO-WAIT/ATM files touched. See
`docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`.

## 2026-06-09 — Schwab Phase 1 scope clarification (docs/git-log only; no behavior change)

> Phase 1 proves safety guards under simulated Schwab failures. It does not prove live Schwab
> connectivity. Live OAuth, real reads, account-hash mapping, true rate limits, token roll-forward
> behavior, and Schwab API payloads remain NOT_PROVEN pending Developer Portal credentials.

- Commit `23f17865` uses "(PROVEN)" in its title to mean the safety guards were proven under simulation.
  It does NOT indicate live Schwab connectivity. See this clarification and
  `docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`.
- Commit `2f19ffba` is the honest Phase-1 doc ("guards proven (simulated) / live NOT_PROVEN").
- No code, config, migration, test, schema, gate, or capability-flag change in this clarification. The
  token manager, protected holdings writer, adapter, guards, and every NOT_PROVEN stub remain
  byte-identical.
