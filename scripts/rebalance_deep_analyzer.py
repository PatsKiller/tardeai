#!/usr/bin/env python3
"""rebalance_deep_analyzer.py — gemma3:27b monthly portfolio rebalance analysis.

Tier 1 of the two-tier rebalance system:
  - gemma3:27b (BATCH_OVERNIGHT): Full monthly analysis, zero API cost
  - Anthropic Sonnet (CRITICAL_CLOUD): Weekly verification (see rebalance_verifier.py)

Called by: deep overnight queue runner (job_type='rebalance_analysis')
Schedule: Monthly (1st of month, or stale >35d) via queue builder
"""

import argparse
import json
import os
import re
import sys
import yaml
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from cio_agent_contract import build_rebalance_json_schema, extract_json_object, merge_structured_into_result

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _get_db():
    import psycopg2, psycopg2.extras
    env_vars = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    conn = psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )
    return conn


def load_portfolio_context(conn):
    """Load all inputs needed for rebalance analysis."""
    import psycopg2.extras
    ctx = {}

    # Holdings
    with open(ROOT / "data/portfolios/state/holdings.json") as f:
        hdata = json.load(f)
    ctx["holdings"] = hdata.get("holdings", [])
    ctx["portfolio_totals"] = hdata.get("portfolio_totals", {})
    ctx["total_value"] = hdata["portfolio_totals"]["total_value"]

    # Portfolio accounts YAML (target allocations)
    accounts_path = ROOT / "assets/portfolio_accounts.yaml"
    if accounts_path.exists():
        with open(accounts_path) as f:
            ctx["accounts"] = yaml.safe_load(f)
    else:
        ctx["accounts"] = {}

    # Personal situation
    personal_path = ROOT / "data/portfolios/state/personal_situation.json"
    if personal_path.exists():
        with open(personal_path) as f:
            ctx["personal"] = json.load(f)
    else:
        ctx["personal"] = {}

    # Recent CIO decisions
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("""
            SELECT symbol, action, rationale, created_at
            FROM cio_decisions
            WHERE created_at > NOW() - INTERVAL '30 days'
            ORDER BY created_at DESC LIMIT 10
        """)
        ctx["cio_decisions"] = [dict(r) for r in cur.fetchall()]
    except Exception:
        ctx["cio_decisions"] = []

    # Annual income from dividends
    try:
        cur.execute("""
            SELECT SUM(annual_income) as total, COUNT(DISTINCT symbol) as payers
            FROM dividend_history
            WHERE record_date > NOW() - INTERVAL '90 days'
        """)
        row = cur.fetchone()
        ctx["annual_income"] = float(row["total"] or 0)
        ctx["dividend_payers"] = int(row["payers"] or 0)
    except Exception:
        ctx["annual_income"] = 0
        ctx["dividend_payers"] = 0

    # Days since last analysis
    try:
        cur.execute("""
            SELECT generated_at FROM rebalance_analysis_results
            ORDER BY generated_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            ctx["days_since_last"] = (datetime.now() - row["generated_at"].replace(tzinfo=None)).days
        else:
            ctx["days_since_last"] = 999
    except Exception:
        ctx["days_since_last"] = 999

    return ctx


def build_prompt(ctx):
    """Build the full rebalance prompt for gemma3:27b."""
    holdings = ctx["holdings"]
    total_value = ctx["total_value"]
    personal = ctx.get("personal", {})
    accounts = ctx.get("accounts", {})
    income = ctx.get("annual_income", 0)
    income_target = personal.get("annual_income_target", 55000)
    income_gap = income_target - income

    # Holdings table
    lines = []
    for h in sorted(holdings, key=lambda x: x.get("market_value", 0), reverse=True):
        sym = h.get("symbol", "")
        val = h.get("market_value", 0)
        pct = h.get("portfolio_pct", 0)
        acct = h.get("account_type", h.get("account", ""))
        div_y = h.get("dividend_yield", 0) or 0
        lines.append(f"  {sym:<10} ${val:>10,.0f} ({pct:>5.1f}%) {acct:<14} yield:{div_y:.1f}%")

    # Target allocations from accounts YAML
    target_lines = []
    for acct_key, acct_data in accounts.get("accounts", {}).items():
        targets = acct_data.get("target_allocation", {})
        if targets:
            name = acct_data.get("display_name", acct_key)
            target_lines.append(f"  {name}:")
            for cat, pct in targets.items():
                target_lines.append(f"    {cat}: {pct}%")

    # CIO decisions
    cio_lines = [f"  {d['symbol']}: {d['action']} — {(d.get('rationale') or '')[:60]}"
                 for d in ctx.get("cio_decisions", [])]

    prompt = f"""You are a senior portfolio advisor performing a monthly rebalance analysis.

PORTFOLIO: ${total_value:,.0f} | Income: ${income:,.0f}/yr (target ${income_target:,.0f}, gap ${income_gap:,.0f})
Dividend payers: {ctx.get('dividend_payers', 0)} | Days since last analysis: {ctx.get('days_since_last', '?')}

PERSONAL CONSTRAINTS (NON-NEGOTIABLE):
- SSDI recipient — earned income above $1,620/mo triggers review (dividends OK)
- MFS filing (married filing separately, lived apart)
- IRMAA: MAGI > $103K triggers Medicare surcharge. Current MAGI ~$23,600/yr
- No 10% early withdrawal penalty (age 58.5+)
- Roth conversion sweet spot: up to $50K/yr. 2026 conversions done: $35,000
- DO NOT recommend actions pushing MAGI above $103K
- Visa (V) ~26% concentration, held since 2008 IPO — trim slowly, no large tax events

ALL POSITIONS:
{chr(10).join(lines)}

TARGET ALLOCATIONS:
{chr(10).join(target_lines) if target_lines else '  [No target allocations found]'}

RECENT CIO DECISIONS:
{chr(10).join(cio_lines) if cio_lines else '  None'}

{build_rebalance_json_schema()}

CONSTRAINTS: Never sell V in large blocks (embedded gains). Roth conversions near $35K limit.
Prioritize income in tax-deferred. Max 3% per position on new buys."""

    return prompt


def run_analysis(conn, queue_id=None, dry_run=False):
    """Main analysis. Returns result dict."""
    print("[rebalance] Loading portfolio context...")
    ctx = load_portfolio_context(conn)
    print(f"[rebalance] Portfolio: ${ctx['total_value']:,.0f} | "
          f"Positions: {len(ctx['holdings'])} | Stale: {ctx['days_since_last']}d")

    prompt = build_prompt(ctx)
    print(f"[rebalance] Prompt: {len(prompt):,} chars")

    if dry_run:
        print(f"[rebalance] DRY RUN — prompt preview:\n{prompt[:600]}")
        return {"dry_run": True, "prompt_length": len(prompt)}

    # Call gemma via local_llm
    from local_llm import generate
    print("[rebalance] Calling gemma3-overnight (BATCH_OVERNIGHT)...")
    start = datetime.now()
    response = generate(prompt, timeout=420)
    elapsed = (datetime.now() - start).total_seconds()
    print(f"[rebalance] LLM completed in {elapsed:.0f}s")

    if not response:
        return {"error": "No LLM response", "elapsed": elapsed}

    # Parse JSON from response
    parsed = extract_json_object(response)
    if parsed:
        parsed = merge_structured_into_result(parsed)
    else:
        try:
            match = re.search(r"\{.+\}", response, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
            else:
                parsed = {"parse_error": "No JSON found", "raw_response": response[:3000]}
        except Exception as e:
            parsed = {"parse_error": str(e), "raw_response": response[:3000]}

    # Save to DB
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO rebalance_analysis_results (
            analysis_tier, portfolio_value, yaml_health_score,
            holdings_snapshot, executive_summary, recommendations,
            v_concentration_plan, bond_ballast_assessment, yaml_gaps,
            model_primary, stale_days_at_run, queue_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, [
        "gemma3_monthly", ctx["total_value"],
        parsed.get("yaml_health_score"),
        json.dumps({"count": len(ctx["holdings"]), "total_value": ctx["total_value"]}),
        parsed.get("executive_summary", ""),
        json.dumps(parsed.get("recommendations", [])),
        parsed.get("v_concentration_plan", ""),
        parsed.get("bond_ballast_assessment", ""),
        json.dumps(parsed.get("yaml_gaps", [])),
        os.getenv("LOCAL_LLM_MODEL", "gemma3-overnight"),
        ctx["days_since_last"], queue_id,
    ])
    result_id = cur.fetchone()[0]

    # Update llm_intelligence_cache so /v2/rebalance shows fresh content
    top3 = parsed.get("top_3_actions", [])
    recs = parsed.get("recommendations", [])
    cache = parsed.get("executive_summary", "") + "\n\n"
    if top3:
        cache += "TOP ACTIONS:\n" + "\n".join(f"{i+1}. {a}" for i, a in enumerate(top3))
    if recs:
        cache += "\n\nRECOMMENDATIONS:\n"
        for r in recs[:5]:
            cache += f"- {r.get('account','?')}: {r.get('action','?')} {r.get('symbol','?')} — {r.get('rationale','')}\n"

    cur.execute("""
        INSERT INTO llm_intelligence_cache (section, content, generated_at)
        VALUES ('rebalance_suggestions', %s, NOW())
        ON CONFLICT (section) DO UPDATE SET
            content = EXCLUDED.content, generated_at = EXCLUDED.generated_at
    """, [cache])
    conn.commit()
    print(f"[rebalance] Saved result id={result_id}, updated cache")

    return {
        "result_id": result_id,
        "yaml_health_score": parsed.get("yaml_health_score"),
        "recommendation_count": len(parsed.get("recommendations", [])),
        "top_3_actions": top3,
        "executive_summary": parsed.get("executive_summary", "")[:200],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    conn = _get_db()
    result = run_analysis(conn, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    conn.close()
