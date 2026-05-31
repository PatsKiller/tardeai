# BUILD: Automated Trade Mode (ATM v1) — Revision 3

**Target machine:** MS-01 (`johnclaw@ms01-openclaw.tail163d14.ts.net`)
**Working tree:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`
**Build date:** 2026-05-22
**Author of prompt:** Claude (chat)
**Executor:** Claude Code on MS-01

---

## Mission

Add an operating mode toggle to Trade AI that auto-approves trade proposals
without human approval input (/ptapprove or equivalent).

ATM is broker-agnostic AND account-agnostic:
- It does NOT assume any specific broker (Alpaca, Schwab, Fidelity, etc.)
- It does NOT assume any specific account type (paper, live, IRA, taxable, 401k)
- It operates across the full account universe defined in the accounts registry
- The execution route for any given proposal is determined by the proposal's
  target_account field and the accounts registry's routing config — NOT by ATM

Goal: build closed-trade sample size (currently ~13, need 30+ overall and 10+ per
strategy) so the learning loop becomes statistically meaningful. John will leave
ATM running unattended for extended periods. The system must be safe to ignore.

## Account Scope

The portfolio spans approximately $1,192,934 across:
- Fidelity 401k
- Schwab Rollover IRA
- Schwab Roth IRA
- Schwab Taxable
- Alpaca paper ($100K simulated, currently the only auto-execution-capable route)

ATM supports per-account caps, per-account concurrent position limits, and
per-account daily entry limits. The set of accounts ATM is allowed to trade in
is configured per-account in atm_config.yaml — never hardcoded.

Reality check: as of the prompt date, the only account with a routing adapter
capable of automated execution is Alpaca paper. Phase 0 handles this honestly
(builds the registry, marks reality as it is) so ATM ships unblocked but the
no-hardcoding discipline is preserved.

## Hard Constraints (READ TWICE)

1. **No hardcoded broker or account name.** Do not write "alpaca", "paper",
   "schwab", "fidelity" as conditionals or assumed defaults anywhere in ATM code.
   All broker/account decisions come from config or the registry at runtime.
2. **No hardcoded "paper" assumption.** ATM does NOT check whether a route is
   paper or live. It calls existing approval functions. Execution mode is governed
   by LLM_DISABLE_LIVE_EXECUTION, ALPACA_MODE, and the registry's mode field.
3. **Existing gates stay HARD.** ATM is additive. Do NOT weaken or bypass:
   - approval_revalidator.py (stop breach, drift, R:R degradation)
   - alpaca_paper_adapter.py hard safety (drift > 5%, stop breach)
   - risk_gate
   - RSI gate (auto-block at promotion)
   - quote-age gate (ATP-5 promoter)
   - 10 existing safety gates in proposal_paper_submitter.check_gates()
   - ATP-3 readiness criteria: quote_checked AND execution_eligible AND
     not_stop_breached AND within_entry_zone AND rr_ratio >= 2.0 AND
     strategy_fit_valid

   Claude Code MUST grep the codebase and produce a comma-separated list of
   exactly which functions/files implement each of these gates, and which ATM
   pre-flight call ensures each one fires. This list goes in the handoff doc.

4. **State file protection.** Run the IRON RULE state check before any deploy:
   ```
   python -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'],len(d.get('holdings',[])))"
   ```
   Must show ~$1,192,934 and ~47 positions. STOP if zero.
5. **Read before diagnosing.** Read existing files before writing new ones. Use
   the audit copy workflow: patch → test on /tmp/audit/ → /mnt/user-data/outputs/
   → SCP.
6. **No partial files.** Every file deployed must be complete and ready to run.
7. **Telegram to BOTH IDs** (6993102664 and 8797974247) on every ATM state change.

## Architecture Summary

ATM = operating mode toggle. State machine: DISABLED → DRY_RUN → ACTIVE → PAUSED.
All transitions audit-logged. All ATM trades tagged with config hash + target
account + B-1 flag for downstream analysis.

Pieces to build:
0. Account registry — verify or create inline
1. Schema migrations
2. Config YAML + DB-backed override (modal-editable)
3. Auto-approver cron with B-1 isolation + same-day-strategy skip
4. Classifier-health helper + account-aware gate evaluator
5. Per-proposal ATM action override (force_approve / force_reject / force_skip)
6. Telegram commands (/atm status, on, off, pause, resume, dryrun, config, last N)
7. Dashboard at /v2/automated-trade-mode with settings modal + queue preview
8. API endpoints
9. Supply telemetry report (After Verification)

## Phase 0 — Account Registry (CREATE IF MISSING; DO NOT STOP)

Audit the existing account model:

```
psql -d trade_ai -c "\dt *account*"
psql -d trade_ai -c "\dt *portfolio*"
psql -d trade_ai -c "\d paper_trade_proposals" | grep -iE 'account|target'
psql -d trade_ai -c "\d paper_trades" | grep -iE 'account|target'
```

**Branch A — registry EXISTS with at least {account_id, broker, mode,
auto_execution_capable, equity_source}**: proceed to Phase 1.

**Branch B — registry MISSING (expected case)**: create it inline as part of
the same migration. Do NOT stop. Build:

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id BIGSERIAL PRIMARY KEY,
    account_label TEXT NOT NULL UNIQUE,
    broker TEXT NOT NULL,            -- 'alpaca', 'schwab', 'fidelity'
    mode TEXT NOT NULL CHECK (mode IN ('paper', 'live')),
    auto_execution_capable BOOLEAN NOT NULL DEFAULT false,
    equity_source TEXT NOT NULL,     -- 'live_api', 'manual', 'holdings_json'
    routing_adapter TEXT,            -- module path, e.g. 'scripts.alpaca_paper_adapter'
    enabled BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT
);

INSERT INTO accounts (account_label, broker, mode, auto_execution_capable,
                      equity_source, routing_adapter, enabled, notes) VALUES
('alpaca_paper',          'alpaca',   'paper', true,  'live_api',      'scripts.alpaca_paper_adapter', true,
 'Only auto-capable account at ATM v1 build time.'),
('schwab_rollover_ira',   'schwab',   'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.'),
('schwab_roth_ira',       'schwab',   'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.'),
('schwab_taxable',        'schwab',   'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.'),
('fidelity_401k',         'fidelity', 'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.')
ON CONFLICT (account_label) DO NOTHING;

ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS target_account TEXT
    REFERENCES accounts(account_label) DEFAULT 'alpaca_paper';
ALTER TABLE paper_trades
    ADD COLUMN IF NOT EXISTS target_account TEXT
    REFERENCES accounts(account_label) DEFAULT 'alpaca_paper';
```

Backfill: every existing pending proposal and open paper trade gets
`target_account='alpaca_paper'`. Document this default explicitly in the handoff
doc — proposals will continue to default there until a proposal generator
upgrade routes by strategy or by John's manual selection.

Telegram both IDs: "ATM Phase 0: accounts registry created with 5 accounts
(alpaca_paper enabled; schwab/fidelity disabled pending routing adapters).
Existing proposals defaulted to alpaca_paper."

Then proceed to Phase 1.

## Phase 1 — Schema (only after Phase 0 clears)

Create `migrations/2026_05_22_atm_v1.sql`:

```sql
-- ATM state singleton
CREATE TABLE IF NOT EXISTS atm_state (
    id INT PRIMARY KEY DEFAULT 1,
    mode TEXT NOT NULL DEFAULT 'disabled'
        CHECK (mode IN ('disabled', 'dry_run', 'active', 'paused')),
    paused_until TIMESTAMPTZ,
    pause_reason TEXT,
    last_state_change_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_state_change_by TEXT NOT NULL DEFAULT 'system',
    last_evaluated_at TIMESTAMPTZ,
    config_hash TEXT,
    daily_loss_pause_armed BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT singleton CHECK (id = 1)
);
INSERT INTO atm_state (id, mode) VALUES (1, 'disabled')
    ON CONFLICT (id) DO NOTHING;

-- State transition log
CREATE TABLE IF NOT EXISTS atm_state_events (
    id BIGSERIAL PRIMARY KEY,
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    old_mode TEXT,
    new_mode TEXT NOT NULL,
    changed_by TEXT NOT NULL,        -- 'telegram:userid', 'dashboard', 'kill_switch', 'system'
    reason TEXT,
    config_hash TEXT
);

-- Decision log (approved AND rejected)
CREATE TABLE IF NOT EXISTS atm_decision_log (
    id BIGSERIAL PRIMARY KEY,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    proposal_id BIGINT NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    target_account TEXT NOT NULL,
    account_broker TEXT NOT NULL,    -- snapshotted
    account_mode TEXT NOT NULL,      -- snapshotted
    decision TEXT NOT NULL CHECK (decision IN (
        'approved', 'rejected', 'deferred',
        'dry_run_approved', 'dry_run_rejected',
        'force_approved', 'force_rejected', 'force_skipped'
    )),
    rejection_reasons JSONB,
    classifier_health NUMERIC(4,3),
    positions_open_account INT,
    positions_open_total INT,
    new_today_account INT,
    new_today_total INT,
    daily_pnl_pct_account NUMERIC(6,3),
    daily_pnl_pct_aggregate NUMERIC(6,3),
    b1_excluded BOOLEAN DEFAULT false,
    config_hash TEXT NOT NULL,
    atm_mode TEXT NOT NULL,
    trade_id BIGINT
);
CREATE INDEX idx_atm_decisions_recent ON atm_decision_log (decided_at DESC);
CREATE INDEX idx_atm_decisions_proposal ON atm_decision_log (proposal_id);
CREATE INDEX idx_atm_decisions_account ON atm_decision_log (target_account, decided_at DESC);

-- Config change history (modal edits)
CREATE TABLE IF NOT EXISTS atm_config_history (
    id BIGSERIAL PRIMARY KEY,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by TEXT NOT NULL,
    old_config JSONB,
    new_config JSONB NOT NULL,
    old_hash TEXT,
    new_hash TEXT NOT NULL,
    change_diff JSONB,
    backup_path TEXT                 -- filesystem path of timestamped backup
);

-- ATM provenance + per-proposal action override
ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS atm_action TEXT
        CHECK (atm_action IN ('force_approve', 'force_reject', 'force_skip')),
    ADD COLUMN IF NOT EXISTS atm_action_set_by TEXT,
    ADD COLUMN IF NOT EXISTS atm_action_set_at TIMESTAMPTZ;

ALTER TABLE paper_trades
    ADD COLUMN IF NOT EXISTS atm_decision_id BIGINT REFERENCES atm_decision_log(id),
    ADD COLUMN IF NOT EXISTS atm_config_hash TEXT,
    ADD COLUMN IF NOT EXISTS atm_during_b1 BOOLEAN DEFAULT false;
CREATE INDEX idx_paper_trades_atm ON paper_trades (atm_decision_id)
    WHERE atm_decision_id IS NOT NULL;
```

Verify:
```
psql -d trade_ai -c "SELECT mode FROM atm_state WHERE id=1;"
psql -d trade_ai -c "SELECT account_label, broker, mode, enabled FROM accounts ORDER BY id;"
# Expected: mode='disabled'; 5 accounts, only alpaca_paper enabled
```

## Phase 2 — Config

Create `config/atm_config.yaml`:

```yaml
# Automated Trade Mode v1 configuration
# Per-account caps. Global state machine. No broker hardcoded.
#
# ATM does NOT control where trades execute. That is governed by:
#   - ALPACA_MODE / LLM_DISABLE_LIVE_EXECUTION (existing env flags)
#   - accounts table routing_adapter / mode fields
#   - the proposal's target_account assignment
version: 1

defaults:
  position_limits:
    max_concurrent: 10
    max_new_per_day: 6
    max_pct_per_trade: 1.0
    max_pct_per_strategy: 25
    max_pct_per_sector: 35
  strategy_filter:
    # TODO: tune after 2 weeks of observed data, target 0.65 once distribution is known
    min_classifier_health: 0.50
    whitelist: []
    blacklist: []
  kill_switches:
    daily_loss_pct_hard_pause: 10.0
  operating_hours:
    start_et: "09:35"
    stop_new_entries_et: "15:30"

# Same-day strategies that the 15-min ATM cron is too slow for.
# ATM skips these with a clear reason; they remain manually approvable.
# Remove from list if/when a faster ATM lane is built.
same_day_skip_strategies:
  - momentum_scalp
  - gap_and_go

# Per-account overrides. account_label must exist in accounts table.
accounts:
  alpaca_paper:
    enabled: true
    position_limits:
      max_concurrent: 15
      max_new_per_day: 10
      max_pct_per_trade: 1.0
  # Other accounts present in registry but ATM-disabled. Modal exposes them
  # for John to flip on after their routing adapters exist.

global:
  daily_loss_pct_hard_pause_aggregate: 10.0   # sum across enabled accounts
  manual_kill_switch_only: true
  config_backup_dir: "config/.atm_config_backups"

# B-1 observation window protection.
# When enabled, ATM rejects Bucket 2 strategies until observation_end.
# This protects the B-1 experiment from ATM-injected decisions.
b1_tracking:
  enabled: true
  observation_end: "2026-05-25"
  exclude_bucket2_during_observation: true
  bucket2_strategies:
    - swing_breakout
    - swing_trade
    - earnings_post_momentum
    - recovery_watch
    - fib_retracement_bounce
```

Create `scripts/atm_config_manager.py`:
- `load_config()` — reads YAML, validates every key in `accounts:` exists in
  the accounts table, returns dict + sha256 hash
- `save_config(new_config, changed_by)` — validates, writes timestamped backup
  to `config/.atm_config_backups/atm_config_<ISO>.yaml`, writes new YAML,
  computes diff, logs to atm_config_history (with backup_path), updates
  atm_state.config_hash
- `get_effective_limits(account_label)` — merges defaults + per-account overrides
- `get_enabled_accounts()` — returns list of account_labels where ATM is active
- `is_bucket2_excluded(strategy_id, now)` — true if b1_tracking.enabled AND
  exclude_bucket2_during_observation AND strategy_id IN bucket2_strategies AND
  now < observation_end
- `is_same_day_skip(strategy_id)` — strategy_id in same_day_skip_strategies

## Phase 3 — Auto-approver cron

Create `scripts/atm_auto_approver.py`:

```
Cron: */15 9-15 * * 1-5
```

Pipeline:

1. **Pre-flight**
   - Check atm_state.mode. If 'disabled' or 'paused', exit silently (heartbeat
     to atm_state.last_evaluated_at).
   - Check current time vs operating_hours.
   - Aggregate kill-switch: sum daily P&L % across enabled accounts. If <= -10%,
     flip to 'paused', log to atm_state_events with changed_by='kill_switch',
     Telegram both IDs with per-account breakdown.
   - Per-account kill-switch: any single enabled account at its hard-pause
     threshold? Pause that account in runtime, log, Telegram. Other accounts
     continue.
   - Load config + hash. Load enabled-accounts list. Load same-day skip list.
     Load Bucket 2 exclusion state.

2. **For each PENDING proposal** (ordered by created_at ASC):

   **a. Per-proposal override check (FIRST):**
   - If `atm_action='force_skip'` → log 'force_skipped'. Continue.
   - If `atm_action='force_reject'` → log 'force_rejected'. Mark proposal rejected.
     Continue.
   - If `atm_action='force_approve'` → skip ATM gates 2c–2e (but still run hard
     gates in 2d). On success, log 'force_approved' and proceed to approval.

   **b. Target account check:**
   - Read `target_account`. If NULL → log 'rejected', reason='no_target_account'.
     Continue.
   - If target_account NOT in enabled-accounts list → log 'deferred',
     reason='account_disabled_in_atm_config'. Continue.
   - Snapshot account_broker, account_mode.

   **c. B-1 + same-day filters:**
   - If `is_bucket2_excluded(strategy_id, now)` → log 'deferred',
     reason='bucket2_b1_observation_active', set b1_excluded=true. Continue.
   - If `is_same_day_skip(strategy_id)` → log 'deferred',
     reason='same_day_strategy_atm_cadence_too_slow'. Continue.

   **d. Existing HARD gates (always run, even for force_approve):**
   - approval_revalidator: stop_not_breached, drift_within_threshold,
     rr_not_degraded
   - alpaca_paper_adapter hard safety (or whichever adapter target_account
     routes to)
   - risk_gate
   - RSI gate
   - quote-age gate
   - ATP-3 readiness: quote_checked, execution_eligible, within_entry_zone,
     rr >= 2.0, strategy_fit_valid
   - If any fail → log 'rejected' with full reason chain. Continue.

   **e. ATM-specific gates (skipped for force_approve):**
   - classifier_health(strategy_id) >= effective.min_classifier_health?
   - strategy in whitelist (if non-empty) and not in blacklist?
   - positions_open_in_account < effective.max_concurrent?
   - new_today_in_account < effective.max_new_per_day?
   - position_size <= effective.max_pct_per_trade * account_equity?
   - strategy concentration in account <= effective.max_pct_per_strategy?
   - sector concentration in account <= effective.max_pct_per_sector?
   - If any fail → log 'rejected' or 'deferred'. Continue.

   **f. Decision:**
   - If mode='dry_run': log 'dry_run_approved' with full snapshot. Do NOT approve.
   - If mode='active': log 'approved' (capture decision id), call the canonical
     approval entry point used by /ptapprove (NOT the broker-specific function).
     If only a broker-specific entry point exists today, note this in the
     handoff doc as a follow-up: the entry point needs to be abstracted before
     non-Alpaca accounts can be ATM-enabled.

     On approve success:
       - Stamp paper_trades row with atm_decision_id, atm_config_hash,
         atm_during_b1 (= b1_tracking.enabled AND now < observation_end)
       - Telegram both IDs:
         "ATM auto-approved: <SYMBOL> <STRATEGY> qty=<N> entry=<P> →
          <ACCOUNT> (<BROKER>/<MODE>)"

3. **End of cycle**
   - Write per-account cycle summary row
   - Update atm_state.last_evaluated_at

Cron entry:
```
*/15 9-15 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/atm_auto_approver.py >> logs/atm.log 2>&1
```

## Phase 4 — Classifier health helper

`scripts/atm_classifier_health.py`:
- `get_health(strategy_id, lookback_days=7) -> float` — most recent
  classifier_health_metric score for the strategy. Returns 0.0 if no data
  (safe — strategy gets blocked until baseline exists).
- Account-agnostic (classifier health is per-strategy).

## Phase 5 — Per-proposal ATM action override

Backend: handled by the schema columns added in Phase 1 and the override check
in Phase 3 step 2a.

Frontend (small, on Paper Proposals page):
- Each proposal card gets two buttons: [⏭ Skip ATM] and [⚡ Force ATM Approve].
- Force Reject is implicit — if John rejects manually, ATM never sees it.
- Both buttons POST to /api/v2/atm/proposal-action:
  ```json
  { "proposal_id": 123, "action": "force_skip" | "force_approve", "set_by": "dashboard" }
  ```
- Visual: skipped proposals get a gray "ATM SKIPPED" badge; force-approve get
  an amber "ATM FORCED" badge.
- Audit: every action sets atm_action_set_by and atm_action_set_at.

## Phase 6 — Telegram handlers

Add to `scripts/telegram_command_handler.py`:

- `/atm status` — mode, paused_until, kill-switch armed, per-enabled-account
  summary, aggregate P&L, last_evaluated_at age
- `/atm on` — flip to ACTIVE. Bot replies with summary of enabled accounts and
  Bucket 2 status, asks "Reply YES within 30s to confirm ACTIVE across {N}
  account(s)." Pending confirmation expires hard at 30s — a later YES requires
  re-issuing /atm on.
- `/atm off` — flip to DISABLED (no confirmation)
- `/atm dryrun` — flip to DRY_RUN
- `/atm pause [4h|24h|until-tomorrow]` — set paused_until
- `/atm pause-account <account_label>` — disable single account at runtime
- `/atm resume` — clear paused_until
- `/atm config` — dump current YAML to chat (truncate long lists with "...")
- `/atm last <N>` — last N decisions (max 20) with account column
- `/atm accounts` — list enabled accounts with their live caps and current usage
- `/atm queue` — list pending proposals next cycle will see, with target_account
  and predicted decision (without committing)

Authorization: only chat IDs 6993102664 and 8797974247.

## Phase 7 — Dashboard

Create `frontend/src/pages/AutomatedTradeMode.tsx`. Route:
`/v2/automated-trade-mode`. Nav label: "Automated Trade Mode" under System menu.

Sections (top to bottom):

1. **Status banner**: mode + last_state_change + last_evaluated_at age.
   Color-coded. If last_evaluated_at > 20min stale, show warning chip.

2. **Per-account strip** (horizontal cards, one per enabled account):
   - Account label | broker/mode badge | positions M/N | new today X/Y | P&L %
   - Click card → filter all tables below to that account

3. **Next cycle preview** (small panel):
   - "Next cycle: HH:MM ET (in M:SS)"
   - "Queue: N proposals, predicted: A approve / R reject / D defer"
   - One-line preview of up to 5 queued proposals (symbol, strategy, target_account,
     predicted_decision)

4. **Control bar**: [Enable] [Disable] [Dry Run] [Pause/Resume] [⚙ Settings]
   Each control confirms via inline dialog before firing.

5. **Today's activity tiles** (4-up):
   Proposals seen | Auto-approved | Rejected | Aggregate Daily P&L

6. **Capacity tiles** (3-up, aggregate across enabled accounts):
   Positions open total / sum of caps | New today total / sum of caps |
   Aggregate daily loss % vs 10% hard pause

7. **Per-strategy health table**:
   strategy_id | classifier_health | eligible? | bucket2_excluded? |
   trades_30d | win_rate | atm_trades_today

8. **Recent decisions table** (last 20):
   decided_at | symbol | strategy | account | broker/mode | decision |
   reasons (truncated) | trade_id (link if approved)
   Click row → expand to show full rejection_reasons JSON

9. **Settings modal** (⚙):
   - Tabbed: [Defaults] [Per-Account] [Global] [B-1 Tracking] [Same-Day Skip]
   - Per-Account tab: one sub-section per account in registry, each with an
     enabled toggle and the full caps form. Labels come from accounts table,
     not hardcoded.
   - Save → POST /api/v2/atm/config
   - Backend: validates, writes timestamped backup to config_backup_dir, writes
     YAML, logs to atm_config_history with backup_path, returns new hash.
   - Toast: "Saved. Hash: <short>. Backup: <filename>. Effective next 15-min cycle."

   Validation:
   - max_concurrent 1-50, max_new_per_day 1-30, max_pct_per_trade 0.1-5.0
   - min_classifier_health 0.0-1.0
   - daily_loss_pct_hard_pause 1.0-20.0
   - observation_end must be a valid future date when b1_tracking.enabled

## Phase 8 — API endpoints

Add to `scripts/api_v2.py`:

- `GET  /api/v2/atm/status` — state + per-account + aggregate + last_evaluated_at
- `POST /api/v2/atm/mode` — body: {mode, changed_by}
- `POST /api/v2/atm/pause-account` — body: {account_label, changed_by}
- `GET  /api/v2/atm/config`
- `POST /api/v2/atm/config`
- `GET  /api/v2/atm/config-history?limit=20`
- `GET  /api/v2/atm/decisions?limit=20&account_label=<optional>`
- `GET  /api/v2/atm/strategy-health`
- `GET  /api/v2/atm/accounts`
- `GET  /api/v2/atm/queue-preview` — pending proposals + predicted next-cycle decision
- `POST /api/v2/atm/proposal-action` — body: {proposal_id, action, set_by}

Auth: existing api_v2.py pattern.

## Phase 9 — Deploy

1. IRON RULE state check.
2. Sandbox: copy entire patch to /tmp/audit/atm/, run unit tests on
   atm_config_manager and atm_auto_approver dry-paths.
3. Migration apply. Verify atm_state singleton + accounts table populated.
4. Deploy scripts + frontend build.
5. Add cron. Tail logs/atm.log for one cycle (should be silent: mode=disabled).
6. Smoke test:
   - mode='disabled' → cron exits silently
   - /atm status → returns "DISABLED" with enabled-accounts summary
   - Dashboard renders, modal opens with accounts loaded from registry
   - Force-skip and force-approve buttons work on Paper Proposals page
   - grep test (below) returns zero hardcoded conditionals
7. IRON RULE state check again.

## Verification Checklist (do not declare done until all pass)

- [ ] Phase 0: accounts table exists with 5 rows; only alpaca_paper enabled
- [ ] Phase 0: paper_trade_proposals and paper_trades have target_account columns
- [ ] atm_state row exists with mode='disabled'
- [ ] All 4 new ATM tables present; paper_trades has 3 new columns;
      paper_trade_proposals has 3 new columns
- [ ] atm_config.yaml validates against accounts table
- [ ] Cron registered and firing
- [ ] Telegram /atm status responds from BOTH chat IDs with per-account breakdown
- [ ] /atm queue command works and predicts decisions without committing
- [ ] Dashboard /v2/automated-trade-mode loads; per-account strip populated
      from registry; queue preview renders
- [ ] Settings modal Per-Account tab lists every account in the registry
- [ ] Config save bumps hash, writes timestamped backup, logs to
      atm_config_history with backup_path
- [ ] Holdings state still shows $1,192,934 / 47 positions
- [ ] All existing safety gates still active. Handoff doc lists each gate
      and which function in atm_auto_approver.py ensures it fires.
- [ ] Bucket 2 exclusion verified by simulation (insert a swing_breakout
      proposal, observe 'deferred' with reason='bucket2_b1_observation_active')
- [ ] Same-day skip verified by simulation (insert a momentum_scalp proposal,
      observe 'deferred' with reason='same_day_strategy_atm_cadence_too_slow')
- [ ] Force-skip and force-approve overrides verified end-to-end
- [ ] grep -rn 'alpaca\|paper\|schwab\|fidelity' scripts/atm_*.py
      frontend/src/pages/AutomatedTradeMode.tsx
      returns ZERO matches in conditionals (only as strings in DB queries,
      YAML values, or comments). Include the grep output in the handoff doc.
- [ ] Aggregate kill switch and per-account kill switch both tested via
      simulated P&L injection
- [ ] /atm on confirmation expires hard at 30s (tested)

## Supply Telemetry (REQUIRED in handoff)

Before declaring ATM ready for John to flip to DRY_RUN, run this query and
include the output in the handoff doc:

```sql
SELECT
  COUNT(*)                                         AS proposals_last_24h,
  COUNT(*) FILTER (WHERE execution_eligibility_status = 'ELIGIBLE')
                                                   AS atp3_ready,
  COUNT(*) FILTER (WHERE quote_checked AND
                         current_price IS NOT NULL AND
                         price_drift_pct < 3.0)    AS likely_atm_approvable
FROM paper_trade_proposals
WHERE created_at > NOW() - INTERVAL '24 hours';
```

Interpretation guidance for the handoff:
- If `proposals_last_24h` < 10 → ATM will not generate meaningful volume.
  Flag to John as upstream pipeline issue, not ATM issue.
- If `atp3_ready` < 5 → ATP-3 gates are blocking everything (the current state
  per atp3_readiness_truth_audit_report). ATM amplifies this, doesn't fix it.
- If `likely_atm_approvable` >= 5 → ATM is ready to ship value. Proceed.

## After Verification

Reply to John, including the supply telemetry numbers:

> "ATM v1 deployed in DISABLED mode.
> Enabled accounts: alpaca_paper. (4 others in registry, disabled pending adapters.)
> Migration applied, cron live, dashboard at /v2/automated-trade-mode.
>
> Supply telemetry last 24h: <N> proposals, <M> ATP-3 ready, <K> ATM-approvable.
> [If K < 5: 'Upstream supply is the bottleneck. Recommend confirming proposal
> generator and quote freshness before flipping to ACTIVE.']
>
> Ready for /atm dryrun in Telegram or dashboard button. Will NOT enable without
> your action."

Do NOT enable ATM. John flips the switch.

## Commit Discipline

- `feat(atm): phase 0 - accounts registry + target_account columns`
- `feat(atm): schema migration for automated trade mode v1`
- `feat(atm): account-aware config manager + yaml with b1 + same-day guards`
- `feat(atm): auto-approver cron with full gate chain + override path`
- `feat(atm): classifier health helper`
- `feat(atm): per-proposal action override (skip/force-approve)`
- `feat(atm): telegram commands /atm *`
- `feat(atm): dashboard with per-account strip + queue preview + settings modal`
- `feat(atm): api endpoints incl queue preview + proposal action`
- `chore(atm): cron entry + deploy + supply telemetry report`

End-of-session handoff: `docs/sessions/ATM_V1_BUILD_<date>.md` covering:
- accounts registry state (which accounts exist, which are enabled)
- the gate-by-function table (which file/function implements each hard gate
  and how atm_auto_approver ensures it fires)
- supply telemetry numbers
- grep output proving no hardcoded broker conditionals
- what was built, what wasn't, current ATM state (should be DISABLED), next steps
- explicit note: "approve_paper_proposal vs approve_proposal abstraction" —
  whether the canonical entry point is broker-agnostic today, and if not,
  what work is needed to make it so before any non-Alpaca account is enabled
- copy the operator runbook to `docs/operator/ATM_RUNBOOK.md` (provided as a
  separate file in the same delivery as this prompt) and update any SQL queries
  in the runbook to match actual column names found during the build
