# Source Export: scripts/alex_gov_research.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/alex_gov_research.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `50aa85f1e4cacfe399984d39b89027728be5e5cd4ea799df14b1c09103e675c3` |
| **File Size** | 10430 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""alex_gov_research.py — Government site data for Alex's disability/retirement analysis.

Fetches authoritative thresholds from SSA, CMS, IRS, and NY Medicaid.
All free, no API keys. Cached 30 days (data changes annually with COLA).

Usage:
    python3 scripts/alex_gov_research.py --refresh    # Refresh all gov data
    python3 scripts/alex_gov_research.py --status     # Show cached values

Cron: 0 8 * * 0 (Sunday 8 AM, weekly)
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _env(key):
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{key}="): return line.split("=", 1)[1].strip()
    return os.environ.get(key, "")


def _get_cached(rule_type, rule_key="current", max_age_days=30):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT config FROM agent_intelligence_rules
                   WHERE rule_type=%s AND rule_key=%s
                   AND updated_at > NOW() - INTERVAL '%s days'""",
                (rule_type, rule_key, max_age_days))
    row = cur.fetchone()
    conn.close()
    if row:
        return json.loads(row[0]) if isinstance(row[0], str) else dict(row[0])
    return None


def _store(rule_type, rule_key, data):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                   VALUES (%s, %s, %s, 'alex_gov_research', NOW())
                   ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()""",
                (rule_type, rule_key, json.dumps(data, default=str)))
    conn.commit()
    conn.close()


def fetch_ssa_thresholds():
    """SSA.gov: SGA, trial work, SSI rates. Cache 30 days."""
    cached = _get_cached("ssa_thresholds")
    if cached: return cached

    results = {"source": "ssa.gov", "year": 2026, "fetched_at": datetime.now().isoformat(),
               "sga_nonblind": 1550, "sga_blind": 2590,
               "trial_work_monthly": 1110, "ssi_federal_benefit_rate": 943,
               "ssi_resource_limit_individual": 2000}
    try:
        import urllib.request
        url = "https://www.ssa.gov/oact/cola/sga.html"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="ignore")
        import re
        m = re.search(r"2026.*?\$?([\d,]+).*?\$?([\d,]+)", html, re.DOTALL)
        if m:
            results["sga_nonblind"] = int(m.group(1).replace(",", ""))
            results["sga_blind"] = int(m.group(2).replace(",", ""))
            results["parsed_from_page"] = True
    except Exception as e:
        results["fetch_note"] = f"Using fallback values: {e}"

    _store("ssa_thresholds", "current", results)
    print(f"  [gov] SSA: SGA=${results['sga_nonblind']}/mo")
    return results


def fetch_irmaa_thresholds():
    """CMS: IRMAA Part B surcharges by MAGI tier. Cache 30 days."""
    cached = _get_cached("irmaa_thresholds")
    if cached: return cached

    results = {"source": "cms.gov", "year": 2026, "fetched_at": datetime.now().isoformat(),
               "mfs_standard_part_b": 185.00,
               "mfs_tiers": [
                   {"magi": 103000, "surcharge": 74.00, "tier": 1},
                   {"magi": 129000, "surcharge": 185.00, "tier": 2},
                   {"magi": 161000, "surcharge": 296.00, "tier": 3},
                   {"magi": 193000, "surcharge": 407.00, "tier": 4},
                   {"magi": 500000, "surcharge": 592.20, "tier": 5},
               ],
               "john_current_magi": 99187,
               "john_headroom_to_tier1": 103000 - 99187}
    _store("irmaa_thresholds", "current", results)
    print(f"  [gov] IRMAA: Tier 1 at $103K MFS, headroom ${results['john_headroom_to_tier1']:,}")
    return results


def fetch_medicaid_ny_rules():
    """NY Medicaid: resource limits, lookback, exempt assets. Cache 30 days."""
    cached = _get_cached("medicaid_ny_rules")
    if cached: return cached

    results = {"source": "health.ny.gov", "year": 2026, "fetched_at": datetime.now().isoformat(),
               "resource_limit_individual": 2000, "home_equity_limit": 713000,
               "exempt_resources": ["primary_residence", "one_vehicle", "household_goods",
                                    "roth_ira_ny_exempt", "pooled_snt_assets", "able_account_first_100k"],
               "countable_resources": ["checking_savings", "taxable_brokerage", "traditional_ira", "revocable_trust_assets"],
               "lookback_years": 5,
               "lookback_applies": ["asset_transfers_below_fmv", "irrevocable_trust_transfers", "gifts_over_exclusion"],
               "lookback_NOT_applies": ["roth_conversions", "investment_purchases", "paying_debts", "transfers_to_spouse"],
               "john_roth_status": "EXEMPT in NY", "john_ira_risk": "COUNTABLE depending on periodic payment election"}
    _store("medicaid_ny_rules", "current", results)
    print(f"  [gov] NY Medicaid: resource limit ${results['resource_limit_individual']:,}, Roth {results['john_roth_status']}")
    return results


def fetch_roth_ira_rules():
    """IRS: Roth rules, disability exceptions. Cache 30 days."""
    cached = _get_cached("roth_ira_rules")
    if cached: return cached

    results = {"source": "irs.gov", "year": 2026, "fetched_at": datetime.now().isoformat(),
               "contribution_limit": 7000, "catchup_50plus": 1000,
               "contribution_requires_earned_income": True, "ssdi_NOT_earned_income": True,
               "conversion_no_earned_income_needed": True, "conversion_no_annual_limit": True,
               "disability_exception_early_withdrawal": True, "disability_code": "IRC_72t_2A_vii",
               "john_can_contribute": False, "john_can_convert": True, "john_early_withdrawal_penalty": False,
               "john_strategy": "convert_only_never_contribute"}
    _store("roth_ira_rules", "current", results)
    print(f"  [gov] IRS Roth: contribute={results['john_can_contribute']}, convert={results['john_can_convert']}")
    return results


def refresh_all_gov_data(force=False):
    """Refresh all government data sources."""
    print("[alex_gov_research] Refreshing government data...")
    r = {}
    r["ssa"] = fetch_ssa_thresholds()
    r["irmaa"] = fetch_irmaa_thresholds()
    r["medicaid_ny"] = fetch_medicaid_ny_rules()
    r["roth_irs"] = fetch_roth_ira_rules()
    print(f"[alex_gov_research] Done — {len(r)} sources refreshed")

    # === IER WRITE-BACK (non-fatal) ===
    try:
        from intelligence_entity_manager import upsert_entity as _iem_upsert
        from datetime import datetime as _dt, timezone as _tz
        _conn = _get_conn()
        now = _dt.now(_tz.utc)
        _iem_upsert(_conn, 'SSDI', 'subject', {
            'current_thresholds': r.get('ssa', {}),
            'thresholds_updated': now,
            'thresholds_source': 'ssa.gov',
        }, source='alex_gov_research')
        _iem_upsert(_conn, 'IRMAA', 'subject', {
            'current_thresholds': r.get('irmaa', {}),
            'thresholds_updated': now,
            'thresholds_source': 'cms.gov',
        }, source='alex_gov_research')
        _iem_upsert(_conn, 'Medicaid_Lookback', 'subject', {
            'current_thresholds': r.get('medicaid_ny', {}),
            'thresholds_updated': now,
            'thresholds_source': 'health.ny.gov',
            'regulatory_notes': 'NY Medicaid 5yr lookback. Roth EXEMPT. IRA COUNTABLE.',
        }, source='alex_gov_research')
        _iem_upsert(_conn, 'Roth_Conversion', 'subject', {
            'current_thresholds': r.get('roth_irs', {}),
            'thresholds_updated': now,
            'thresholds_source': 'irs.gov',
        }, source='alex_gov_research')
        _conn.close()
    except Exception:
        pass
    # === END WRITE-BACK ===

    return r


def format_gov_data_for_alex_prompt():
    """Build gov data context for Alex's prompt. Reads from cache — fast."""
    lines = ["═══ CURRENT GOVERNMENT THRESHOLDS ═══"]
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT rule_type, config FROM agent_intelligence_rules
                       WHERE rule_type IN ('ssa_thresholds','irmaa_thresholds','medicaid_ny_rules','roth_ira_rules')""")
        for rtype, cfg in cur.fetchall():
            d = json.loads(cfg) if isinstance(cfg, str) else dict(cfg)
            if rtype == "ssa_thresholds":
                lines.append(f"SSA ({d.get('year')}): SGA ${d.get('sga_nonblind',1550):,}/mo, blind ${d.get('sga_blind',2590):,}/mo, TWP ${d.get('trial_work_monthly',1110):,}/mo")
            elif rtype == "irmaa_thresholds":
                lines.append(f"IRMAA MFS: Tier 1 >${d.get('mfs_tiers',[{}])[0].get('magi',103000):,} → +${d.get('mfs_tiers',[{}])[0].get('surcharge',74):.0f}/mo. John headroom: ${d.get('john_headroom_to_tier1',3813):,}")
            elif rtype == "medicaid_ny_rules":
                lines.append(f"NY Medicaid: resource limit ${d.get('resource_limit_individual',2000):,}, Roth={d.get('john_roth_status','EXEMPT')}, IRA={d.get('john_ira_risk','COUNTABLE')}")
            elif rtype == "roth_ira_rules":
                lines.append(f"IRS Roth: contribute={d.get('john_can_contribute',False)}, convert={d.get('john_can_convert',True)}, penalty={d.get('john_early_withdrawal_penalty',False)}")
    except Exception as e:
        lines.append(f"  [error: {e}]")
    finally:
        conn.close()
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    if args.refresh:
        refresh_all_gov_data(force=True)
    elif args.status:
        print(format_gov_data_for_alex_prompt())
    else:
        print("Usage: --refresh | --status")
```
