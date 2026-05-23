# Dashboard Visual Audit — Operator Workflow

## When to use
- After any significant frontend change (V3+ sessions)
- Before market open Monday if Friday touched UI
- Investigating a "page looks wrong" report
- Quarterly architecture review

## How to run

### Full crawl (auto-refreshes route list from live sidebar)
```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate
python3 scripts/audit/dashboard_crawler.py --bases http://localhost:7777
```

### Manual route refresh only
```bash
python3 scripts/audit/extract_routes.py
```

## Output
- `docs/playwright/audit_<port>_<timestamp>.tgz` — one tarball per base URL
- Each tarball contains `<port>/*.png` (full-page screenshots) + `<port>/manifest.json`

## Retention
Each crawl deletes the previous tarball for that port, then creates a new one. Only the latest run per port is kept.

## Auditing with Claude
1. Extract the tarball: `tar xzf docs/playwright/audit_7777_*.tgz`
2. Check manifest: `cat audit_7777_*/7777/manifest.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['totals'],indent=2))"`
3. Upload interesting PNGs (e.g. ones with console errors) into a Claude chat
4. Ask: "audit these — what's broken?"

## What the manifest tells you
- `totals.console_error_routes` — pages with JS errors. Investigate.
- `totals.network_failure_routes` — pages with failed API calls. Backend issue.
- `totals.timeout` — pages that didn't finish loading in 25s. Performance or backend hang.

## Side-effect routes
Routes marked with `"skip_in_crawler": true` are skipped automatically.
Currently skipped: `/v2/morning-brief`, `/v2/bot-morning-brief` (trigger Telegram sends).

## Port 7776
Port 7776 runs the NYC DOF Auction Intelligence app (separate project), not a v2 dashboard. Do not crawl it with this tool.
