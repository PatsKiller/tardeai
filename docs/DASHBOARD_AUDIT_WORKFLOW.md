# Dashboard Visual Audit — Operator Workflow

## When to use
- After any significant frontend change (V3+ sessions)
- Before market open Monday if Friday touched UI
- Investigating a "page looks wrong" report
- Quarterly architecture review

## How to run

### Refresh route list (only when sidebar changes)
```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate
python3 scripts/audit/extract_routes.py
```

### Full crawl
```bash
python3 scripts/audit/dashboard_crawler.py --bases http://localhost:7777 --out /tmp
```

## Output
- `/tmp/audit_<timestamp>/7777/*.png` — full-page screenshots (one per route)
- `/tmp/audit_<timestamp>/manifest.json` — timing, console errors, network failures
- `/tmp/audit_<timestamp>.tgz` — bundled tarball for upload

## Auditing with Claude
1. Check manifest for problems: `cat /tmp/audit_<ts>/manifest.json | python3 -c "import sys,json; d=json.load(sys.stdin); t=d['totals']; print(json.dumps(t,indent=2))"`
2. Extract interesting PNGs (e.g. ones with console errors per manifest)
3. Upload them individually into a Claude chat
4. Ask: "audit these — what's broken?"

## What the manifest tells you
- `totals.<base>.console_error_routes` — pages with JS errors. Investigate.
- `totals.<base>.network_failure_routes` — pages with failed API calls. Backend issue.
- `totals.<base>.timeout` — pages that didn't finish loading in 25s. Performance or backend hang.

## Side-effect routes
Routes marked with `"skip_in_crawler": true` in `routes.json` are skipped automatically.
Currently skipped: `/v2/morning-brief`, `/v2/bot-morning-brief` (trigger Telegram sends).

## Cleanup
Old audits (>7 days) can be cleaned with: `bash scripts/audit/cleanup_old_audits.sh`

## Port 7776
Port 7776 runs the NYC DOF Auction Intelligence app (separate project), not a v2 dashboard. Do not crawl it with this tool.
