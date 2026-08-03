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

    prompt = f"""Review these rebalance recommendations for SSDI/IRMAA/tax compliance.

CONSTRAINTS:
- SSDI: earned income > $1,620/mo risks benefit review (dividends OK)
- IRMAA: MAGI > $103,000 triggers Medicare surcharges. Current MAGI ~$23,600
- MFS filing (married filing separately, lived apart)
- 2026 Roth conversions done: $35,000 (soft cap $50K)
- Age 58+ (no 10% penalty)

EXECUTIVE SUMMARY: {exec_summary[:500]}

RECOMMENDATIONS:
{recs_text or '  No recommendations'}

VISA PLAN: {v_plan[:300]}

Flag ONLY genuine compliance issues. Respond JSON:
{{"verification_passed": true|false, "critical_flags": ["issue"], "warnings": ["concern"],
  "irmaa_risk": "none|low|medium|high", "ssdi_risk": "none|low|medium|high",
  "notes": "1-2 sentence assessment"}}"""

    if dry_run:
        print(f"[verifier] DRY RUN — prompt ({len(prompt)} chars)")
        return {"dry_run": True, "result_id": result_id}

    print(f"[verifier] Calling DeepSeek v4 for verification of id={result_id}...")

    try:
        from llm_lane import generate
        text = generate(prompt, lane="deepseek-flash", timeout=90,
                        process_id="rebalance_verifier", task_summary="rebalance verify")
        print(f"[verifier] Response: {len(text)} chars")
    except Exception as e:
        print(f"[verifier] API error: {e}")
        return {"error": str(e), "result_id": result_id}

    # Parse
    try:
        match = re.search(r"\{.+\}", text, re.DOTALL)
        flags = json.loads(match.group() if match else text)
    except Exception as e:
        flags = {"verification_passed": None, "critical_flags": [],
                 "warnings": [f"Parse error: {e}"], "notes": text[:200]}

    # Update DB
    cur.execute("""
        UPDATE rebalance_analysis_results SET
            ssdi_irmaa_flags = %s, verification_passed = %s,
            verification_notes = %s, model_verifier = 'deepseek-v4-pro',
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
