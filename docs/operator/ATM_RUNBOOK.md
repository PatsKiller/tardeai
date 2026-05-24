# ATM Operator Runbook

**Audience:** John (operator)
**System:** Trade AI v12 — Automated Trade Mode (ATM v1)
**Last updated:** 2026-05-21
**Location on MS-01:** `docs/operator/ATM_RUNBOOK.md`

---

## What ATM Is

ATM (Automated Trade Mode) is a toggle that lets the system auto-approve trade
proposals without you clicking `/ptapprove`. It does not change *what* trades
the system finds, only whether a human is required to approve them.

ATM is broker-agnostic. Today only the Alpaca paper account is wired for
automated execution, but the architecture supports flipping on Schwab/Fidelity
accounts when their routing adapters exist — no code changes needed, just
config.

**ATM does not control paper vs live.** That is governed by `ALPACA_MODE` and
`LLM_DISABLE_LIVE_EXECUTION` environment flags and the `accounts` table.

---

## States

| State | Meaning |
|---|---|
| **DISABLED** | ATM does nothing. Cron runs but exits silently. Default. |
| **DRY_RUN** | ATM evaluates every proposal and logs what it *would* have done, but does not approve anything. Use to validate behavior. |
| **ACTIVE** | ATM auto-approves proposals that pass all gates. |
| **PAUSED** | Manual or kill-switch pause. No new approvals. `paused_until` field controls auto-resume. |

State transitions are logged to `atm_state_events` with timestamp, old state,
new state, who/what triggered the change, and config hash at the time.

---

## The Three Ways to Control ATM

### 1. Telegram (mobile, fastest)

| Command | What it does |
|---|---|
| `/atm status` | Current mode, paused_until, kill-switch status, per-account summary, last-evaluated-at age |
| `/atm on` | Flip to ACTIVE. Requires `YES` confirmation reply within 30s. |
| `/atm off` | Flip to DISABLED. No confirmation. |
| `/atm dryrun` | Flip to DRY_RUN. |
| `/atm pause 4h` | Pause for 4 hours. Auto-resume after. |
| `/atm pause 24h` | Pause for 24 hours. |
| `/atm pause until-tomorrow` | Pause until next market open. |
| `/atm pause-account alpaca_paper` | Pause one account only; others continue. |
| `/atm resume` | Clear pause, return to prior mode. |
| `/atm config` | Dump current YAML config to chat. |
| `/atm last 10` | Last 10 decisions with symbol/strategy/decision/reason. |
| `/atm accounts` | List enabled accounts with current caps and usage. |
| `/atm queue` | Show pending proposals next cycle will evaluate, with predicted decisions. |

Authorized chat IDs: 6993102664 (Footmannyc) and 8797974247 (John).

### 2. Dashboard (full visibility)

**URL:** `https://ms01-openclaw.tail163d14.ts.net/v2/automated-trade-mode`
**SSH tunnel fallback:** `http://127.0.0.1:7777/v2/automated-trade-mode`

Buttons at the top: Enable / Disable / Dry Run / Pause / Resume / ⚙ Settings.

### 3. Per-proposal overrides (Paper Proposals page)

On any proposal card:
- **⏭ Skip ATM** — ATM never touches this proposal. It stays in your manual queue.
- **⚡ Force ATM Approve** — ATM auto-approves on next cycle, bypassing ATM-specific gates. Hard safety gates (stop breach, drift, R:R, RSI, quote-age) still apply.

---

## What Each Dashboard Section Tells You

**Status banner.** Color = mode. Watch for the "last evaluated" age — if it's
>20 min and you expect ATM to be running, the cron may have died.

**Per-account strip.** One card per enabled account. M/N positions, X/Y new
today, current day P&L %. Click a card to filter all tables below.

**Next cycle preview.** Countdown to next 15-min cron tick + queued proposals
with predicted decisions. Use this to see what ATM is about to do before it
does it.

**Today's activity tiles.** Proposals seen, auto-approved, rejected, aggregate
daily P&L. If "seen" is high but "approved" is near zero, gates are blocking.
Look at the recent decisions table for the reason chain.

**Capacity tiles.** How much room left under the caps. If "new today" is at the
cap and you want more, raise `max_new_per_day` in the modal.

**Per-strategy health table.** Shows classifier_health, eligible flag, B-1
exclusion status, 30-day trade history, today's ATM trades for each strategy.
Strategies with `classifier_health < 0.50` (default threshold) are blocked.
Strategies in the Bucket 2 list are blocked until 2026-05-25.

**Recent decisions table.** Last 20 with full reason JSON on click. The truth
about what ATM is doing and why.

---

## Settings Modal — Every Knob

Open via the ⚙ button. Five tabs:

### Defaults
Fallback values for any account that doesn't override them.

| Knob | Default | Range | What it does |
|---|---|---|---|
| max_concurrent | 10 | 1-50 | Max open positions across all enabled accounts (overridden per-account) |
| max_new_per_day | 6 | 1-30 | Max new entries per day per account |
| max_pct_per_trade | 1.0 | 0.1-5.0 | Max % of account equity per single trade |
| max_pct_per_strategy | 25 | 1-50 | Max % of open positions in one strategy |
| max_pct_per_sector | 35 | 1-50 | Max % of open positions in one sector |
| min_classifier_health | 0.50 | 0.0-1.0 | Strategies below this score are blocked. **Raise to 0.65 after 2 weeks of clean data.** |
| whitelist | [] | — | If non-empty, only these strategies are ATM-eligible |
| blacklist | [] | — | These strategies are always blocked |
| daily_loss_pct_hard_pause | 10.0 | 1.0-20.0 | Daily loss % that auto-pauses ATM. Non-negotiable safety. |
| start_et | "09:35" | — | ATM ignores proposals before this (avoids first 5min volatility) |
| stop_new_entries_et | "15:30" | — | ATM stops opening new positions after this |

### Per-Account
One sub-section per account in the registry. Each has:
- Enabled toggle (off by default for non-alpaca_paper accounts)
- All the position_limits knobs above (overrides defaults)

**Current state:** Only `alpaca_paper` is enabled and ATM-capable. To enable
Schwab or Fidelity, a routing adapter must be built first.

### Global
- daily_loss_pct_hard_pause_aggregate: 10% across all enabled accounts combined
- manual_kill_switch_only: true (means only the 10% hard pause is automatic; everything else needs you)

### B-1 Tracking
- `enabled`: true until 2026-05-25
- `exclude_bucket2_during_observation`: true (Bucket 2 strategies deferred from ATM)
- Bucket 2 list: swing_breakout, swing_trade, earnings_post_momentum, recovery_watch, fib_retracement_bounce

After 5/25, flip `exclude_bucket2_during_observation` to false (or let
`observation_end` auto-expire it).

### Same-Day Skip
Strategies the 15-min cron is too slow for. Default list:
- momentum_scalp
- gap_and_go

These remain manually approvable. Remove from list if/when a faster ATM lane
exists.

### Every Save
- Writes timestamped backup to `config/.atm_config_backups/`
- Logs old + new + diff to `atm_config_history` with backup path
- New config hash effective on next 15-min cycle
- Toast: "Saved. Hash: <short>. Backup: <filename>."

---

## Kill Switches

Two automatic, the rest manual.

### Aggregate hard pause (automatic)
- **Trigger:** Sum of daily P&L % across all enabled accounts <= -10%
- **Action:** Mode flips to PAUSED. `changed_by='kill_switch'` logged. Telegram alert to both IDs with per-account breakdown.
- **Recovery:** Manual. You decide when to `/atm resume`.

### Per-account hard pause (automatic)
- **Trigger:** Any single enabled account's daily P&L % <= its account-level threshold (default 10%)
- **Action:** That account is disabled in runtime. Other accounts continue.
- **Recovery:** `/atm pause-account` toggle in dashboard, or modal flip.

### Manual pause via Telegram
- `/atm pause 4h` — most common. Auto-resume after 4 hours.
- `/atm off` — full disable until you flip it back.

### Cron-died detection
- `atm_state.last_evaluated_at` updated every cycle.
- Dashboard shows warning chip if > 20 min stale during market hours.
- No auto-action — you check Termius/Blink to see why.

---

## Morning Checklist (5 minutes)

Open `/v2/automated-trade-mode` on phone or laptop.

1. **Status banner color** — green (ACTIVE) is expected. Red or yellow → read the reason.
2. **last_evaluated_at age** — should be within last 15 min during market hours.
3. **Daily P&L** — if anywhere near 5%, pay attention. If past 7%, consider manual pause to assess.
4. **Today's activity tiles** — proposals seen vs approved tells you if gates are too tight.
5. **Recent decisions table** — scan for unexpected rejection reasons. `bucket2_b1_observation_active` and `same_day_strategy_atm_cadence_too_slow` are expected until 5/25 and possibly forever, respectively.
6. **Per-strategy health table** — any strategy at `classifier_health < 0.40` is degraded; consider adding to blacklist temporarily.

If everything is green: walk away. Check again at lunch.

---

## End-of-Day Checklist (3 minutes)

1. **Total ATM-approved trades today** — building toward the 30+ closed sample.
2. **Closed trades from today** — what did ATM produce? Look at /v2/paper-proposals "Closed Trades" section, filter by `opened_via=atm_v1`.
3. **Recent decisions** — anything rejected for a reason that looks wrong? Note it for tomorrow.
4. **/atm queue** before close — sometimes worth force-approving or skipping the tail end if quotes are stale.

---

## Weekly Review (15 minutes, Sundays)

1. **Closed trade count** — what's the cumulative ATM sample size? Target: 30+ overall, 10+ per strategy.
2. **Win rate by strategy, ATM trades only** — query:
   ```sql
   SELECT strategy_id, COUNT(*), AVG(CASE WHEN outcome_verdict='WIN' THEN 1.0 ELSE 0 END) AS win_rate
   FROM paper_trades
   WHERE atm_decision_id IS NOT NULL AND closed_at > NOW() - INTERVAL '7 days'
   GROUP BY strategy_id ORDER BY COUNT(*) DESC;
   ```
3. **Classifier health drift** — any strategy whose health score dropped >0.10 this week? Add to blacklist or lower its allocation.
4. **Reasons-for-rejection histogram** — what's ATM rejecting most? If "max_new_per_day" hits often, raise the cap. If "classifier_health" hits often, lower the threshold (slightly).
5. **Config tuning** — make changes in the modal. Every change is backed up and logged.

---

## When Things Go Wrong

### "ATM hasn't auto-approved anything in hours"
- Check `/atm queue` — are there proposals pending?
- Check `/atm status` — mode = ACTIVE? Paused?
- Check Recent Decisions table — what reasons are firing?
- Most common cause: upstream proposal generator producing zero proposals (ATP-3 quote-age gate blocking everything). ATM is downstream — fix supply first.

### "ATM auto-approved something I would have rejected"
- Use the per-proposal "Skip ATM" button on similar future proposals in the queue.
- Look at the decision's classifier_health score and consider raising `min_classifier_health`.
- Add the strategy to blacklist temporarily.
- Worst case: `/atm off`, fix config, `/atm dryrun` for a day, then `/atm on`.

### "10% daily loss hard-pause fired"
- Telegram alert will explain which accounts contributed.
- Don't immediately resume. Read the closed trades. Identify the root cause.
- If structural (bad data feed, classifier corruption), `/atm off` for the day.
- If just a bad-luck cluster, `/atm resume` in the morning with a lowered `max_new_per_day` for a day or two.

### "last_evaluated_at is stale by 30+ min"
- SSH to MS-01 (Tailscale: `ssh johnclaw@ms01-openclaw.tail163d14.ts.net`).
- `tail -100 logs/atm.log` — what was the last cron iteration doing?
- `crontab -l | grep atm` — confirm cron entry exists.
- `systemctl status cron` — confirm cron daemon alive.
- If cron is fine but script erroring, the log will show why.

### "Modal config save errored"
- Check `config/.atm_config_backups/` — last good backup is there.
- `git diff config/atm_config.yaml` to see if the YAML is malformed.
- Revert: `cp config/.atm_config_backups/atm_config_<latest>.yaml config/atm_config.yaml`
- Restart server (or wait for next cycle to reload).

### "I want to undo ATM entirely"
- `/atm off` (immediate)
- The cron stays installed but exits silently every cycle when `mode='disabled'`
- To rip it out completely: `crontab -e` remove the line; tables and code stay (no data loss).

---

## Key Files & Locations on MS-01

| What | Where |
|---|---|
| Config YAML | `config/atm_config.yaml` |
| Config backups | `config/.atm_config_backups/atm_config_<ISO>.yaml` |
| Auto-approver | `scripts/atm_auto_approver.py` |
| Config manager | `scripts/atm_config_manager.py` |
| Classifier health | `scripts/atm_classifier_health.py` |
| Cron log | `logs/atm.log` |
| Dashboard page | `frontend/src/pages/AutomatedTradeMode.tsx` |
| Telegram handler | `scripts/telegram_command_handler.py` (search for `/atm`) |
| API endpoints | `scripts/api_v2.py` (search for `/api/v2/atm`) |
| State machine | `atm_state` table (singleton row) |
| Decision log | `atm_decision_log` table |
| Config history | `atm_config_history` table |
| State events | `atm_state_events` table |
| Accounts registry | `accounts` table |

---

## Database Quick Queries

### Current ATM state
```sql
SELECT mode, paused_until, last_state_change_at, last_state_change_by,
       last_evaluated_at, config_hash, daily_loss_pause_armed
FROM atm_state WHERE id=1;
```

### Today's ATM decisions
```sql
SELECT decided_at, symbol, strategy_id, target_account, decision,
       (rejection_reasons->0)->>'gate' AS first_blocker,
       trade_id
FROM atm_decision_log
WHERE decided_at::date = CURRENT_DATE
ORDER BY decided_at DESC;
```

### ATM trades closed in last 7 days
```sql
SELECT pt.symbol, pt.strategy_id, pt.target_account, pt.outcome_verdict,
       pt.pnl_dollars, pt.r_multiple, pt.opened_at, pt.closed_at,
       adl.config_hash, pt.atm_during_b1
FROM paper_trades pt
JOIN atm_decision_log adl ON pt.atm_decision_id = adl.id
WHERE pt.closed_at > NOW() - INTERVAL '7 days'
ORDER BY pt.closed_at DESC;
```

### Why was a specific proposal rejected
```sql
SELECT decided_at, decision, rejection_reasons
FROM atm_decision_log
WHERE proposal_id = <PROPOSAL_ID>
ORDER BY decided_at DESC LIMIT 5;
```

### Strategy health right now
```sql
SELECT strategy_id, MAX(measured_at) AS last_measured,
       (array_agg(score ORDER BY measured_at DESC))[1] AS latest_score
FROM classifier_health_metric
WHERE measured_at > NOW() - INTERVAL '7 days'
GROUP BY strategy_id
ORDER BY latest_score DESC;
```

**Note:** Column names (`measured_at`, `score`) are assumed; if the actual
`classifier_health_metric` table uses different names, Claude Code should
update this query during the build and note the correction in the handoff doc.

### Config change history
```sql
SELECT changed_at, changed_by, new_hash, change_diff->'changed' AS changes
FROM atm_config_history
ORDER BY changed_at DESC LIMIT 10;
```

---

## Roadmap Beyond v1

These are *not* in v1. Track in `BOT_MATURITY_ROADMAP_v1.md`.

| Item | Trigger to build |
|---|---|
| Faster ATM lane for momentum_scalp / gap_and_go | After ATM v1 has 60 days of clean data and the architecture is stable |
| Schwab routing adapter | When you decide to move beyond paper |
| Fidelity routing adapter | When the 401k loan is repaid and you want 401k assets ATM-capable |
| Abstract `approve_paper_proposal` → `approve_proposal` | Before any non-Alpaca account is ATM-enabled |
| Auto-tune classifier_health threshold based on observed precision/recall | After 30+ closed trades |
| Per-strategy daily P&L kill switch (beyond aggregate) | If you see one strategy account for most losses |
| Live-money 60-day shadow validation | After ATM v1 has 60 days of paper data and no structural issues |

---

## One-Liner Summary for Your Phone Lock Screen Notes App

> ATM = auto-approve paper trades. `/atm on/off/dryrun/pause/status` in Telegram.
> Dashboard: `/v2/automated-trade-mode`. 10% daily-loss = auto-pause. Bucket 2
> blocked until 5/25. Momentum scalp & gap-and-go always skipped. Default
> classifier_health threshold 0.50, raise to 0.65 in 2 weeks. Check morning,
> lunch, end-of-day. Walk away if green.
