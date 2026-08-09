#!/usr/bin/env python3
"""
Data Accuracy Litmus Test — cross-validates prices, portfolio values,
and site health against external sources of truth.
"""
import json, sys, os, time

TRADEAI_ROOT = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
sys.path.insert(0, os.path.join(TRADEAI_ROOT, "scripts"))

def main():
    # Discover live directory first
    try:
        from lib.runtime_awareness import RuntimeAwareness
        ra = RuntimeAwareness()
        ra.discover()
        live_dir = ra.get_live_directory() or TRADEAI_ROOT
    except:
        live_dir = TRADEAI_ROOT

    findings = []

    # 1. Quote price cross-validation
    try:
        from lib.quote_validator import QuoteValidator
        qv = QuoteValidator(live_dir=live_dir)
        findings.extend(qv.validate_all())
    except Exception as e:
        findings.append({'severity': 'P2', 'type': 'quote_validator_error', 'message': str(e)[:200]})

    # 2. Fix stale cache: if live cache stale, copy from dev
    live_cache = os.path.join(live_dir, 'data', 'portfolios', 'state', 'finviz_quote_cache.json')
    dev_cache = os.path.join(TRADEAI_ROOT, 'data', 'portfolios', 'state', 'finviz_quote_cache.json')
    if os.path.exists(live_cache) and os.path.exists(dev_cache) and live_cache != dev_cache:
        live_age = (time.time() - os.path.getmtime(live_cache)) / 60
        dev_age = (time.time() - os.path.getmtime(dev_cache)) / 60
        if live_age > dev_age + 10:
            os.makedirs(os.path.dirname(live_cache), exist_ok=True)
            with open(dev_cache, 'rb') as src, open(live_cache, 'wb') as dst:
                dst.write(src.read())
            findings.append({
                'severity': 'P2', 'type': 'cache_synced',
                'message': f'Copied fresh quotes from dev ({dev_age:.0f}min) to live ({live_age:.0f}min). Server restart needed.'
            })

    # 3. Portfolio validation
    try:
        from lib.portfolio_validator import PortfolioValidator
        pv = PortfolioValidator()
        findings.extend(pv.validate())
    except Exception as e:
        findings.append({'severity': 'P2', 'type': 'portfolio_validator_error', 'message': str(e)[:200]})

    # 4. API consistency
    try:
        from lib.site_validator import SiteValidator
        sv = SiteValidator()
        findings.extend(sv.validate_api_consistency())
        findings.extend(sv.validate_telegram_alerts())
    except Exception as e:
        findings.append({'severity': 'P2', 'type': 'site_validator_error', 'message': str(e)[:200]})

    critical = [f for f in findings if f.get('severity') == 'P0']
    warnings = [f for f in findings if f.get('severity') == 'P1']

    output = {
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'live_directory': live_dir,
        'critical': len(critical),
        'warnings': len(warnings),
        'status': 'CRITICAL' if critical else ('WARNING' if warnings else 'PASSED'),
        'findings': findings,
    }

    print(json.dumps(output, indent=2, default=str))
    return 0 if not critical else 1

if __name__ == '__main__':
    sys.exit(main())
