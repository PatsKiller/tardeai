# Changelog

## 2026-06-09 — Max-hold time-exit proposals (advisory, approval-gated)

Turns the previously-unenforced `auto_exit_at_max_hold` config into an ACTIONABLE, gated time-exit —
no silent auto-close. `generate_max_hold_exit_proposals.py` (cron 10:20 weekdays) creates a
paper_time_exit_proposal for each open position held past its strategy's max_hold_days. The operator
approves via System/Open-Trades UI or `POST /api/v2/time-exit-proposals/decide`; APPROVE is hard-guarded
(ALPACA_MODE==paper + live_trading_interlock on the trade's account + the existing close_paper_trade
path). Verified: guard chain passes for paper, refuses non-paper, reject path works. `GET
/api/v2/time-exit-proposals` + TimeExitProposals.tsx (Trading → Open Trades). Migration additive
(paper_time_exit_proposals).

## 2026-06-09 — Secrets hard-rule + Command Center secrets modal + DB stability

**HARD RULE — no credential hardcoded anywhere, ever synced to git (enforced):**
`scripts/check_no_secrets.py` + git **pre-commit/pre-push hooks** (`scripts/install_git_hooks.sh`) BLOCK
any commit/push containing an API-key pattern, a secret file (.env/*.key/*.pem/credentials), or any
literal value from `.env`. Verified: blocks a staged Anthropic key; tree clean (3819 files). `.env` +
`config/broker_credentials.env` + `secrets_admin_audit.jsonl` gitignored; Drive sync already excludes
`.env`/keys/credentials.

**Leaked-key response:** a now-DEACTIVATED Anthropic key was found in git *history* only
(`reports/portfolio_live.html`, repeated commits) — current tree clean, `reports/` gitignored, repo
private. (History scrub offered separately.)

**Command Center secrets modal:** System → Admin → "API Keys & Secrets" (`SecretsManager.tsx` +
`scripts/secrets_admin.py`, `GET/POST /api/v2/admin/secrets`). Write-only: lists key names + masked
`••••1234` only, never returns/logs/displays a full value; atomic `.env` (0600) write; audited (key
name only). For rotating ANTHROPIC_API_KEY etc.

**DB stability:** fixed a transaction leak in `unified_stop_supervisor.py` (a SELECT on the shared
db_adapter connection never rolled back → idle-in-transaction → ACCESS-EXCLUSIVE lock pile-up that hit
the connection-slot limit). Added `finally: rollback()`. Backstop: `ALTER ROLE trade_ai SET
idle_in_transaction_session_timeout='5min'` so any future leak self-terminates.

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
