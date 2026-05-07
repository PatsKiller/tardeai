#!/usr/bin/env python3
"""session16b_seed_strategy_metadata.py — Seed metadata for watchlist-era strategies."""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

db_password = os.getenv("DB_PASSWORD")
if not db_password:
    raise RuntimeError("DB_PASSWORD missing from .env")

import psycopg2

conn = psycopg2.connect(
    host="127.0.0.1", port=5432, dbname="trade_ai",
    user="trade_ai", password=db_password
)
cur = conn.cursor()

# Check which columns exist
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'strategy_registry'
""")
existing_cols = {r[0] for r in cur.fetchall()}

METADATA = {
    "core_growth_compounder": {
        "description": "Buy-and-hold core growth positions. Large-cap quality compounders with 10%+ earnings growth, strong moats.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,fidelity_401k,taxable",
    },
    "core_index": {
        "description": "Passive index fund core. SPY/QQQ/VTI allocation for broad market exposure and beta baseline.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,fidelity_401k,taxable",
    },
    "covered_call_income": {
        "description": "Covered-call ETFs (JEPI, JEPQ) for monthly income generation. Yield focus with downside buffer.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,taxable",
    },
    "defense_thesis": {
        "description": "Defense/aerospace concentrated thesis. LMT, RTX, NOC, KTOS — AI + WWIII catalyst, long-term conviction.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,taxable",
    },
    "dividend_growth_compounder": {
        "description": "Dividend growth stocks with 5+ years of increases. Yield-on-cost optimization for retirement income.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,taxable",
    },
    "high_yield_income_bdc": {
        "description": "BDC and high-yield income vehicles. 8%+ yield, IRA-only placement due to tax treatment.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira",
    },
    "international_dividend": {
        "description": "International dividend ETFs for geographic diversification. Ex-US income exposure.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,taxable",
    },
    "recovery_watch": {
        "description": "Positions below cost basis being monitored for recovery or tax-loss harvest. Thesis still intact but underwater.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,taxable",
    },
    "reit_income": {
        "description": "REIT income positions. Real estate exposure with 4%+ yield. IRA-preferred due to non-qualified dividends.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira",
    },
    "speculative_growth": {
        "description": "Small/mid-cap speculative growth. Higher risk, early-stage companies with asymmetric upside potential.",
        "timeframe": "swing_3_to_21d",
        "account_fit": "taxable,roth_ira",
    },
    "swing_trade": {
        "description": "General swing trades. 3-21 day holds based on technical setups and catalyst timing.",
        "timeframe": "swing_3_to_21d",
        "account_fit": "taxable,rollover_ira,roth_ira",
    },
    "bond_income": {
        "description": "Bond and fixed-income positions. BND, treasury ladders, CD equivalents for stability and income.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,fidelity_401k,taxable",
    },
    "tax_loss_harvest": {
        "description": "Tax-loss harvesting candidates. Positions with realized losses available for offset against gains.",
        "timeframe": "position_long",
        "account_fit": "taxable",
    },
    "cash_or_stable": {
        "description": "Cash, money market, or stable value positions. Dry powder for deployment during pullbacks.",
        "timeframe": "position_long",
        "account_fit": "rollover_ira,roth_ira,fidelity_401k,taxable",
    },
    "invalid_non_security": {
        "description": "Non-security line items. Cash sweeps, pending settlements, and non-tradable entries.",
        "timeframe": "n/a",
        "account_fit": "all",
    },
}

updated = 0
skipped = 0
for strategy_id, meta in METADATA.items():
    # Only update if description is missing or blank
    cur.execute("""
        SELECT strategy_id, description
        FROM strategy_registry WHERE strategy_id = %s
    """, [strategy_id])
    row = cur.fetchone()
    if not row:
        print(f"  {strategy_id}: not in registry — skipping")
        skipped += 1
        continue

    existing_desc = row[1]
    if existing_desc and existing_desc.strip():
        print(f"  {strategy_id}: already has description — skipping")
        skipped += 1
        continue

    set_parts = []
    values = []
    for col, val in meta.items():
        if col in existing_cols and val:
            set_parts.append(f"{col} = %s")
            values.append(val)

    if not set_parts:
        skipped += 1
        continue

    values.append(strategy_id)
    cur.execute(f"""
        UPDATE strategy_registry
        SET {', '.join(set_parts)}, updated_at = NOW()
        WHERE strategy_id = %s
    """, values)

    if cur.rowcount > 0:
        print(f"  {strategy_id}: updated ({', '.join(meta.keys())})")
        updated += 1
    else:
        skipped += 1

conn.commit()
conn.close()

print(f"\nUpdated {updated} strategies, skipped {skipped}")
