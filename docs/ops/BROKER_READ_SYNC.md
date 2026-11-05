# Broker Read Sync

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 5515-5585 -->
## Moved from AGENTS.md (25.0.1 lines 5515-5585)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **Reach: one entrypoint with a closed step list.** An agent may invoke `scripts/ops/broker_read_sync.sh` (or its
  Python entrypoint `scripts/ops/broker_read_sync.py`) with no argument, `--plan` or `--apply`, and nothing else. The
  steps are hard-coded in `scripts/lib/broker_read_sync_policy.py` `STEPS`, in the operator's order and argv:
  `schwab_position_sync.py`, `schwab_transaction_ingest.py --days 7`, `alpaca_live_read_sync.py`,
  `moomoo_live_read_sync.py`, `snaptrade_sync.py`, `positions_sync.py`, `positions_sync.py --check-fresh` (apply
  only) and `stop_health_check.py --quiet`. No argument reaches a step; running a step script directly is not under
  this grant. Dry run is the default and still reads the brokers live, so it needs the grant too; `--apply` writes our
  own stores (positions, transactions, holdings), never a broker. *Cause (§20): operator request 2026-10-16 (banner);
  the operator ran `sync_all_readonly.sh` by hand from CURRENT the same day, and every agent that needed fresh
  positions had to stop and ask.*
- **The grant: `broker-read`, at most 4 hours, one use per run, revocable.** The agent asks with
  `bin/guard request broker-read --for <≤4h> --uses <n> --reason "<purpose>"`; the operator approves at the keyboard
  (`bin/guard grant broker-read --for 2h --uses 3 --reason "..."`) or by Telegram `/approve <CODE>` (not in
  `REMOTE_FORBIDDEN_SCOPES`), and revokes with `bin/guard revoke broker-read`. `bin/guard grant` refuses a window over
  4 h. The script reads the ledger at the account's real home (`GUARD_APPROVALS_DIR` and `HOME` are ignored) and
  consumes one use before the first step; `--plan` needs no grant. *Cause (§20): §0 rule 2 is the boundary being
  narrowed, and a guard grant is how this file narrows a rail per task (§22 `execution-engineering`, §24.10
  `execution-ops`).*
- **Conditions — each a refusal in code, quoted in the receipt.** The run refuses (exit 2) unless: the grant is
  active (`broker_read_grant_missing`); `lib.trading_lock.lock_state()` says LOCKED for schwab, alpaca, moomoo and
  snaptrade (`trading_lock_not_locked:<broker>`); the Schwab access mode resolves to `read_only` for the step processes
  (`schwab_access_mode_not_read_only`; forced per process with `TRADEAI_SCHWAB_ACCESS_MODE`, while
  `config/schwab_access_mode.yaml` stays as the operator left it); the static capability audit is clean
  (`capability_found:<kind>:<module>`); and it runs from the served release, `~/trade-ai-releases/portfolio-server/CURRENT`,
  which has a `.env` (`not_served_release`, `env_file_missing`; checked by stat). Each step process re-checks the mode
  and the lock after its environment is loaded. *Cause (§20): the operator's conditions of 2026-10-16 ("not trading
  just reading"; Schwab `read_only`); the SPCX incident of 2026-10-14 (the trading lock and the access-mode switch).*
- **No credential value reaches the agent.** The orchestrator never opens `.env`: each step runs as `bash --noprofile
  --norc -c` that sources `.env` inside its own process and then execs the step runner, with `PYTHONPATH`,
  `PYTHONSTARTUP`, `BASH_ENV`, `LD_PRELOAD` and similar injection variables removed first. All step output is scrubbed
  of token-like strings (JWTs, bearer values, `key=value` secrets, query-string secrets, long opaque runs) before it is
  printed or stored. §24.7 is unchanged: the agent itself never reads, copies or prints `.env` or a credential file.
  *Cause (§20): §24.7 and the 2026-10-14 directive "cookies/.env are operator-only".*
- **No re-auth, 2FA, token refresh or flag change is reachable.** In every step process the runner replaces
  `schwab_token_manager` `seed_token`, `exchange_code`, `reauth_url`, `approve_http_refresh`, `_refresh_access_token`
  and `init_key` with a refusal, refuses every non-GET/HEAD HTTP request to a broker host (which blocks an OAuth token
  refresh as well as an order route), and refuses importing the approval and 2FA services. When a broker reports no or
  an invalid login token the run stops with `needs_operator_reauth` (exit 3); re-auth stays the operator's
  (`schwab_token_manager.py reauth-url` / `exchange-code`). It sets no live/paper flag and never writes the access-mode
  switch or the unlock file. *Cause (§20): operator conditions of 2026-10-16; `schwab_token_manager.py` gates HTTP
  refresh behind an operator approval, and schwab-py's own client refresh would bypass it.*
- **No order route, no stop write: excluded and pinned by CI.** Stop managers, stop sync, stop writers, the options
  lifecycle, defense execution, the order pilots, the approval/2FA services, order transports, the API server and
  `scripts/active_trader/**` are never a step and are refused at import in every step process
  (`broker_read_sync_policy.EXCLUDED`; one reasoned read exemption, `scripts/lib/fidelity_stop_sync.py`, which has no
  broker, network or order capability). Inside what can still load, every order-write function
  (`schwab_transport` `place_order`, `replace_order`, `cancel_order`, `cancel_order_for_replace`; `moomoo.client`
  `MoomooClient.place_order` and `unlock_trade`; the futu SDK trade context) is replaced with a refusal. The static audit
  reuses `scripts/audit_lane_transitive_capabilities.py` over each step's effective import closure and fails on an
  excluded entrypoint, an excluded module on an eager import chain, an unstubbed order or re-auth function, an
  order-route write, or a direct sender. `tests/test_broker_read_sync_20261016.py` pins the step list byte for byte and
  fails if any excluded family is added. Underneath, every order write in the repo is dominated by
  `assert_trading_unlocked` (`tests/test_trading_lock_coverage_20261014.py`). *Cause (§20): measured 2026-10-16 at
  `766914db2` — the full static import closure of every step, lazy imports included, is about 1,145 modules and
  reaches 10 order-capable modules through `schwab_transport.py`; an "order-free closure" claim would have been false,
  so the closure was made smaller by construction (effective closure 252–643 modules, 2–3 stubbed transports).*
- **Proof.** Each run writes `BrokerReadSyncReceipt@v1` to `<persistent-state>/data/runtime/broker_read_sync/`: the
  preflight (grant, lock per broker, access mode, audit), each step's argv, rc, status and scrubbed output tail, and the
  per-account status the steps print (§0 rule 8). A guard trip stops the run (exit 4). *Cause (§20): §0 rules 7–8.*
- **Not under this grant.** Every other part of §0 rule 2: calling a broker any other way, `place_order`, an order
  route, a live flag, 2FA, reading a credential, the unlock file, `config/schwab_access_mode.yaml` (a `config-write`
  decision for the operator), the token manager's CLI, and editing any `STEPS` entry without a reviewed PR. *Cause
  (§20): the operator's "not trading just reading".*
- **Open gaps, stated.** The guard binds the tier, not the purpose: the reason text is the record. The Claude Code
  PreToolUse hook has no `broker-read` rule; the script enforces the grant itself, and the Cursor classifier maps the
  script (except `--plan`) to `broker-read`. The static audit does not walk dynamic imports or third-party SDK code; the
  runtime import, HTTP and subprocess guards cover those. A step that reads must still tolerate a refused lazy import
  of an excluded module; a step that cannot shows `guard_tripped` and the run stops. The scope must be installed in
  `bin/guard` and `.cursor/hooks/guard-lib.sh` (operator-only guard configuration, carried in this PR for review), and
  the Telegram `/approve` path works only once the release that runs the callback poller carries the tier. *Cause
  (§20): §22 "Guard is not a universal boundary"; §24.10's stated gaps.*

<!-- moved from AGENTS.md 25.0.1 lines 5873-5896 -->
## Moved from AGENTS.md (25.0.1 lines 5873-5896)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **Reach: a closed set of read lanes, nothing by analogy.** n8n may schedule and trigger only the lanes
  `n8n_broker_read_carveout.READ_LANES` lists: the eight §24.11 steps (`broker_read_sync_policy.STEPS`, same scripts
  and argv) and the market-data reads `options_chain_snapshot.py` and `sweep_schwab_instruments.py`, each admitted
  only while the §24.11 static audit (`broker_read_sync_policy.audit()`, `excluded_family`, `runtime_denied`) is clean
  for it. A lane's command is exactly its script and one of its argv forms: no wrapper, extra argument, pipe or second
  command. Adding a lane is a reviewed PR to that tuple. *Cause (§20): operator 2026-10-22 (banner); measured
  2026-10-22 on `2d8fc9574`: both market-data reads pass the §24.11 audit with no finding.*
- **Preconditions — each a refusal in code.** A carve-out lane runs only while `CARVEOUT_STATUS` is `ACTIVE`, every
  broker trading lock is LOCKED (`broker_read_sync.lock_states()`: schwab, alpaca, moomoo, snaptrade), and the Schwab
  access mode the operator's switch resolves is `read_only` (`broker_read_sync.resolved_child_mode()` without a
  per-process override), not merely forced so for the step. `runtime_refusals()` returns `carveout_not_active`,
  `trading_lock_not_locked:<broker>` or `schwab_access_mode_not_read_only`, and an unreadable state refuses too.
  *Cause (§20): the operator's "only doing reading … not doing any trading"; the §24.11 conditions of 2026-10-16.*
- **Execution stays on the host; n8n holds no token.** n8n fires the lane through the relay and the allowlisted
  executor (§23.3); the step runs on the host from the served release and sources `.env` inside its own process, as
  §24.11 does, and n8n never receives, stores or forwards a broker credential, token or cookie. *Cause (§20): §23.14
  — a stolen relay bearer must not be able to place an order or render a secret; 12.0.0, "n8n still never holds a
  broker credential".*
- **The never-list does not move.** Orders, stop writes, cancel, replace, order preflight, 2FA, `place_order`, live
  and paper flags, paper execution, senders, re-auth and token refresh, and every `broker_read_sync_policy.EXCLUDED`
  family stay never dispatcher-eligible; `NEVER_TOKENS` refuses them even when `ACTIVE`. Changing a read lane into one
  that writes, or widening any lane's reach, is §17. An agent never fires, forces or re-stages a carve-out lane; §0
  rule 2 and §24.11 still govern every agent broker read. *Cause (§20): §0 rules 1–2; the SPCX incident of
  2026-10-14.*
