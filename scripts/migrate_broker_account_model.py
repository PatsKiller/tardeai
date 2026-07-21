#!/usr/bin/env python3
"""migrate_broker_account_model.py — Phase 1 broker/account automation model (ADDITIVE only).

Creates 5 new tables (IF NOT EXISTS) and seeds them from the existing `accounts` table + atm_config.yaml.
No destructive schema change; `accounts` and `atm_config.yaml` are left intact (legacy source). Safe to
re-run (idempotent: CREATE IF NOT EXISTS + INSERT ... ON CONFLICT DO NOTHING).

NO live-write enablement: live accounts seeded api_write_enabled=false / automation_mode in
(DISABLED|MANUAL_REVIEW); AUTO_PAPER only for the paper account.
"""
import os, sys

DDL = """
CREATE TABLE IF NOT EXISTS broker_accounts (
  id SERIAL PRIMARY KEY,
  account_key TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  broker TEXT NOT NULL,
  environment TEXT NOT NULL,            -- paper | live | import | read-only
  account_type TEXT,
  is_enabled BOOLEAN DEFAULT TRUE,
  api_read_enabled BOOLEAN DEFAULT FALSE,
  api_write_enabled BOOLEAN DEFAULT FALSE,
  supports_equities BOOLEAN DEFAULT FALSE,
  supports_options BOOLEAN DEFAULT FALSE,
  supports_fractional BOOLEAN DEFAULT FALSE,
  supports_bracket_orders BOOLEAN DEFAULT FALSE,
  supports_stop_orders BOOLEAN DEFAULT FALSE,
  supports_trailing_stops BOOLEAN DEFAULT FALSE,
  supports_cancel_replace BOOLEAN DEFAULT FALSE,
  broker_adapter TEXT,
  connection_status TEXT DEFAULT 'unknown',
  last_sync_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS account_automation_policies (
  id SERIAL PRIMARY KEY,
  account_id INTEGER UNIQUE REFERENCES broker_accounts(id),
  automation_mode TEXT NOT NULL DEFAULT 'DISABLED',     -- DISABLED|MANUAL_REVIEW|AUTO_PAPER|AUTO_LIVE|PAUSED_ENTRIES|EMERGENCY_STOP
  approval_policy TEXT NOT NULL DEFAULT 'PROPOSAL_ONLY', -- PROPOSAL_ONLY|MANUAL_APPROVAL_REQUIRED|AUTO_SUBMIT_AFTER_VALIDATION
  max_automation_allocation_pct NUMERIC,
  max_automation_notional_dollars NUMERIC,
  max_notional_per_trade NUMERIC,
  risk_per_trade_pct NUMERIC,
  max_risk_dollars_per_trade NUMERIC,
  max_new_positions_per_day INTEGER,
  max_concurrent_positions INTEGER,
  max_strategy_allocation_pct NUMERIC,
  max_sector_allocation_pct NUMERIC,
  daily_loss_pause_pct NUMERIC,
  daily_loss_pause_dollars NUMERIC,
  allowed_strategies JSONB,
  disallowed_symbols JSONB,
  allowed_order_types JSONB,
  market_hours_only BOOLEAN DEFAULT TRUE,
  require_fresh_quote BOOLEAN DEFAULT TRUE,
  require_stop_defined BOOLEAN DEFAULT TRUE,
  require_target_defined BOOLEAN DEFAULT TRUE,
  allow_after_hours_queue_only BOOLEAN DEFAULT TRUE,
  source TEXT DEFAULT 'default_seed',                    -- database | default_seed | legacy_import
  updated_by TEXT,
  updated_at TIMESTAMPTZ DEFAULT now(),
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS account_automation_policy_audit (
  id SERIAL PRIMARY KEY,
  account_id INTEGER,
  old_policy JSONB,
  new_policy JSONB,
  changed_by TEXT,
  change_reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS proposal_account_routes (
  id SERIAL PRIMARY KEY,
  proposal_id INTEGER NOT NULL,
  selected_account_id INTEGER REFERENCES broker_accounts(id),
  selected_by TEXT,
  route_status TEXT DEFAULT 'proposed',
  route_reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS broker_capability_checks (
  id SERIAL PRIMARY KEY,
  account_id INTEGER REFERENCES broker_accounts(id),
  check_name TEXT NOT NULL,
  status TEXT NOT NULL,                 -- ok | not_implemented | not_proven | failed | n/a
  detail TEXT,
  last_checked_at TIMESTAMPTZ DEFAULT now(),
  evidence JSONB
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_cap_check ON broker_capability_checks(account_id, check_name);
"""

CAP_CHECKS = ["broker_adapter_present", "auth_configured", "read_api_tested", "positions_sync_tested",
              "orders_api_implemented", "order_confirmation_implemented", "fill_confirmation_tested",
              "cancel_replace_tested", "protective_stop_support_tested", "reconciliation_tested",
              "paper_sandbox_available", "live_write_armed"]


def conn():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def main():
    c = conn(); cur = c.cursor()
    cur.execute(DDL)
    c.commit()
    # seed broker_accounts from accounts (additive, ON CONFLICT DO NOTHING)
    cur.execute("SELECT account_label, broker, mode, api_enabled, auto_execution_capable, routing_adapter FROM accounts")
    accts = cur.fetchall()
    alpaca_atm = {"max_pct_per_trade": 0.05, "max_pct_per_strategy": 20, "max_pct_per_sector": 30,
                  "max_concurrent": 10, "max_new_per_day": 25, "daily_loss_pct_hard_pause": 2.5}
    seeded = 0
    for label, broker, mode, api_enabled, auto_cap, adapter in accts:
        is_paper = (mode == "paper")
        env = "paper" if is_paper else ("import" if broker == "fidelity" else "live")
        # Phase 1: ONLY the paper account (alpaca) has a real trading API. Schwab/Fidelity have NO
        # trading API yet (data may be imported separately) — read+write false until an API is added.
        write = bool(is_paper)
        read = bool(is_paper)
        adapter = adapter or (f"scripts.{broker}_adapter" if broker in ("alpaca", "schwab") else None)
        disp = {"tradeai_automated": "Alpaca Paper", "schwab_rollover_ira": "Schwab Rollover IRA",
                "schwab_roth_ira": "Schwab Roth IRA", "schwab_taxable": "Schwab Taxable",
                "fidelity_401k": "Fidelity 401k"}.get(label, label)
        conn_status = "ok" if is_paper else "no_trading_api"
        cur.execute("""INSERT INTO broker_accounts
            (account_key, display_name, broker, environment, is_enabled, api_read_enabled, api_write_enabled,
             supports_equities, supports_fractional, supports_bracket_orders, supports_stop_orders,
             supports_trailing_stops, supports_cancel_replace, broker_adapter, connection_status, last_sync_at)
            VALUES (%s,%s,%s,%s,TRUE,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s, now())
            ON CONFLICT (account_key) DO NOTHING""",
            (label, disp, broker, env, read, write,
             is_paper, is_paper, is_paper, is_paper, is_paper, is_paper, adapter, conn_status))
        seeded += cur.rowcount
        # policy seed
        cur.execute("SELECT id FROM broker_accounts WHERE account_key=%s", (label,))
        bid = cur.fetchone()[0]
        if is_paper:
            mode_v, appr, src = "AUTO_PAPER", "MANUAL_APPROVAL_REQUIRED", "legacy_import"
            pol = dict(risk_per_trade_pct=float(alpaca_atm["max_pct_per_trade"]) * 100,
                       max_strategy_allocation_pct=alpaca_atm["max_pct_per_strategy"],
                       max_sector_allocation_pct=alpaca_atm["max_pct_per_sector"],
                       max_concurrent_positions=alpaca_atm["max_concurrent"],
                       max_new_positions_per_day=alpaca_atm["max_new_per_day"],
                       daily_loss_pause_pct=alpaca_atm["daily_loss_pct_hard_pause"])
        else:
            mode_v, appr, src = "DISABLED" if broker == "fidelity" else "MANUAL_REVIEW", "PROPOSAL_ONLY", "default_seed"
            pol = dict(risk_per_trade_pct=None, max_strategy_allocation_pct=None, max_sector_allocation_pct=None,
                       max_concurrent_positions=None, max_new_positions_per_day=None, daily_loss_pause_pct=None)
        cur.execute("""INSERT INTO account_automation_policies
            (account_id, automation_mode, approval_policy, risk_per_trade_pct, max_strategy_allocation_pct,
             max_sector_allocation_pct, max_concurrent_positions, max_new_positions_per_day, daily_loss_pause_pct,
             allowed_order_types, source, updated_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'migration_seed')
            ON CONFLICT (account_id) DO NOTHING""",
            (bid, mode_v, appr, pol["risk_per_trade_pct"], pol["max_strategy_allocation_pct"],
             pol["max_sector_allocation_pct"], pol["max_concurrent_positions"], pol["max_new_positions_per_day"],
             pol["daily_loss_pause_pct"], '["market","limit"]', src))
        # capability checks (honest current status)
        import json as _j
        for cn in CAP_CHECKS:
            if is_paper:
                st = "ok" if cn in ("broker_adapter_present", "auth_configured", "read_api_tested",
                                    "positions_sync_tested", "orders_api_implemented", "paper_sandbox_available",
                                    "fill_confirmation_tested", "reconciliation_tested") else \
                     ("n/a" if cn == "live_write_armed" else "ok")
            elif broker == "schwab":
                # No Schwab trading API yet: only the adapter stub exists; everything else not_implemented.
                st = "ok" if cn == "broker_adapter_present" else "not_implemented"
            else:  # fidelity import-only (no trading API)
                st = "n/a"
            cur.execute("""INSERT INTO broker_capability_checks (account_id, check_name, status, detail)
                           VALUES (%s,%s,%s,%s)
                           ON CONFLICT (account_id, check_name) DO UPDATE SET status=EXCLUDED.status, last_checked_at=now()""", (bid, cn, st, f"seed status for {broker}"))
    c.commit()
    cur.execute("SELECT count(*) FROM broker_accounts"); ba = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM account_automation_policies"); ap = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM broker_capability_checks"); cc = cur.fetchone()[0]
    print(f"[migrate] broker_accounts={ba} policies={ap} capability_checks={cc} (new broker_accounts rows this run={seeded})")
    c.close()


if __name__ == "__main__":
    main()
