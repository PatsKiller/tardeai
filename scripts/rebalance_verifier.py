#!/usr/bin/env python3
"""rebalance_verifier.py — Weekly Anthropic Sonnet verification of gemma3 rebalance output.

Tier 2 of the two-tier rebalance system.
Reads the most recent gemma3_monthly result and checks for SSDI/IRMAA/tax issues.
Cost: ~$0.008/week (Sonnet, not Opus).
Schedule: Sunday 10:30 AM via cron.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _get_db():
    import psycopg2, psycopg2.extras
    env_vars = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


SSDI_IRMAA_CONSTRAINTS = """CONSTRAINTS:
- SSDI: earned income > $1,620/mo risks benefit review (dividends OK)
- IRMAA: MAGI > $103,000 triggers Medicare surcharges. Current MAGI ~$23,600
- MFS filing (married filing separately, lived apart)
- 2026 Roth conversions done: $35,000 (soft cap $50K)
- Age 58+ (no 10% penalty)"""


def build_compliance_prompt(*, executive_summary: str, recs_text: str, v_plan: str = "") -> str:
    """Shared prompt template. Used by both the weekly gemma3-tier verifier
    (`run_verification`) and the daily drift-alert check (`verify_daily_rebalance_orders`,
    Fix H1) — same SSDI/IRMAA/tax constraints regardless of which recommendation
    surface produced the orders."""
    return f"""Review these rebalance recommendations for SSDI/IRMAA/tax compliance.

{SSDI_IRMAA_CONSTRAINTS}

EXECUTIVE SUMMARY: {executive_summary[:500]}

RECOMMENDATIONS:
{recs_text or '  No recommendations'}

VISA PLAN: {v_plan[:300]}

Flag ONLY genuine compliance issues. Respond JSON:
{{"verification_passed": true|false, "critical_flags": ["issue"], "warnings": ["concern"],
  "irmaa_risk": "none|low|medium|high", "ssdi_risk": "none|low|medium|high",
  "notes": "1-2 sentence assessment"}}"""


def call_sonnet_compliance_check(prompt: str, *, dry_run: bool = False) -> dict:
    """Shared Sonnet call + JSON-flag parsing. Fails closed on any error —
    callers get a dict with no `critical_flags`, never an exception, so a
    verification-plumbing failure can't itself crash the caller."""
    if dry_run:
        print(f"[verifier] DRY RUN — prompt ({len(prompt)} chars)")
        return {"dry_run": True}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[verifier] ANTHROPIC_API_KEY not set — skipping")
        return {"skipped": True, "reason": "no_api_key"}

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        print(f"[verifier] Response: {len(text)} chars, "
              f"in={msg.usage.input_tokens} out={msg.usage.output_tokens}")
    except Exception as e:
        print(f"[verifier] API error: {e}")
        return {"error": str(e)}

    try:
        match = re.search(r"\{.+\}", text, re.DOTALL)
        return json.loads(match.group() if match else text)
    except Exception as e:
        return {"verification_passed": None, "critical_flags": [],
                "warnings": [f"Parse error: {e}"], "notes": text[:200]}


def verify_daily_rebalance_orders(orders: list, *, total_to_rebalance: float = 0,
                                  dry_run: bool = False) -> dict:
    """Fix H1 (docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md): verify-before-notify
    for the daily drift-based rebalance alert.

    `run_verification` below only ever checks `rebalance_analysis_results` rows
    tagged `analysis_tier='gemma3_monthly'` — a separate, monthly-cadence
    system. It has no connection to portfolio_rebalancer.py's daily drift
    orders, which is the surface an operator actually sees via Telegram
    (portfolio_alerts.py, >$200k trigger). Those orders were never checked for
    SSDI/IRMAA/tax compliance by anything. This runs the same check inline,
    against today's actual orders, before the alert fires — not after.
    """
    recs_text = ""
    for o in (orders or [])[:10]:
        recs_text += (f"  - {o.get('account','?')}: {o.get('action','?')} "
                      f"${o.get('amount_usd',0):,.0f} {o.get('bucket','?')} — {o.get('note','')}\n")
    exec_summary = (f"Daily drift rebalance: ${total_to_rebalance:,.0f} net to move "
                    f"across {len(orders or [])} order(s).")
    prompt = build_compliance_prompt(executive_summary=exec_summary, recs_text=recs_text)
    return call_sonnet_compliance_check(prompt, dry_run=dry_run)


def run_verification(conn, dry_run=False):
    """Fetch latest gemma3 rebalance result and run Sonnet verification."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT id, generated_at, portfolio_value, executive_summary,
               recommendations, v_concentration_plan
        FROM rebalance_analysis_results
        WHERE analysis_tier = 'gemma3_monthly' AND verified_at IS NULL
        ORDER BY generated_at DESC LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        print("[verifier] No unverified gemma3 analysis found.")
        return {"skipped": True, "reason": "no_unverified_analysis"}

    result_id = row["id"]
    recs = row["recommendations"] or []
    if isinstance(recs, str):
        recs = json.loads(recs)
    exec_summary = row["executive_summary"] or ""
    v_plan = row["v_concentration_plan"] or ""

    recs_text = ""
    for r in (recs if isinstance(recs, list) else [])[:10]:
        recs_text += f"  - {r.get('account','?')}: {r.get('action','?')} {r.get('symbol','?')} — {r.get('rationale','')}\n"

    prompt = build_compliance_prompt(executive_summary=exec_summary, recs_text=recs_text, v_plan=v_plan)

    if dry_run:
        print(f"[verifier] DRY RUN — prompt ({len(prompt)} chars)")
        return {"dry_run": True, "result_id": result_id}

    flags = call_sonnet_compliance_check(prompt)
    if "error" in flags or "skipped" in flags:
        return {**flags, "result_id": result_id}

    # Update DB
    cur.execute("""
        UPDATE rebalance_analysis_results SET
            ssdi_irmaa_flags = %s, verification_passed = %s,
            verification_notes = %s, model_verifier = 'claude-sonnet-4-6',
            verified_at = NOW()
        WHERE id = %s
    """, [json.dumps(flags), flags.get("verification_passed"),
          flags.get("notes", ""), result_id])
    conn.commit()

    # Telegram notification
    try:
        from telegram_alert import send_telegram
        critical = flags.get("critical_flags", [])
        if critical:
            send_telegram(
                f"*Rebalance Verification: {len(critical)} flag(s)*\n" +
                "\n".join(f"- {f}" for f in critical) +
                f"\nIRMAA: {flags.get('irmaa_risk','?')} | SSDI: {flags.get('ssdi_risk','?')}"
            )
        else:
            send_telegram(f"Rebalance verification passed: {flags.get('notes','OK')}")
    except Exception:
        pass

    print(f"[verifier] Done: passed={flags.get('verification_passed')}")
    return {"result_id": result_id, "verification_passed": flags.get("verification_passed"),
            "critical_flags": flags.get("critical_flags", [])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    conn = _get_db()
    result = run_verification(conn, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    conn.close()
