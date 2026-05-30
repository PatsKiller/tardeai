# System Access & Applications Pages Report — Trade AI v12

**Date:** 2026-05-30
**Status:** COMPLETE (pending server restart to serve live)

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added `_system_access_links()`, `_system_applications()`, 2 route entries |
| `apps/command-center-v2/src/pages/SystemAccess.tsx` | New page |
| `apps/command-center-v2/src/pages/SystemApplications.tsx` | New page |
| `apps/command-center-v2/src/App.tsx` | Added lazy imports + 2 routes |
| `apps/command-center-v2/src/components/Shell.tsx` | Added 2 nav items to System & Pipeline group |

## Routes Added

| Route | Page | Nav Group |
|-------|------|-----------|
| `/v2/system-access` | SystemAccess | System & Pipeline |
| `/v2/system-applications` | SystemApplications | System & Pipeline |

## API Endpoints Added

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v2/system/access-links` | GET | Service links, health, Tailscale, Drive |
| `GET /api/v2/system/applications` | GET | Software inventory, versions, drift |

No POST endpoints. No command execution. No upgrade execution.

## Services Detected

| Service | Health | URL |
|---------|--------|-----|
| Portfolio Server | healthy | localhost:7777 |
| Command Center | healthy | localhost:7777/v2/ |
| OpenClaw Gateway | healthy | localhost:18789 |
| Ollama | healthy | localhost:11434 |
| Hermes Sidecar | unknown (CLI only) | No web dashboard |
| Tailscale links | not health-checked (remote) | ms01-openclaw.tail163d14.ts.net |

## Tailscale FQDN

- FQDN: `ms01-openclaw.tail163d14.ts.net`
- IP: `100.66.120.124`
- SSH: `ssh johnclaw@ms01-openclaw.tail163d14.ts.net`

## Application Inventory (23 total)

| Category | Count |
|----------|-------|
| Core (Python, Node, npm, PostgreSQL, Git, Ollama) | 7 |
| Ollama Models | 6 |
| AI/Agent (Hermes, Claude Code, OpenClaw) | 3 |
| Integrations (Tailscale, GOG) | 2 |
| Frontend (React, Vite, TypeScript, Chart.js, React Router) | 5 |

## Version Detection Strategy

- Fixed command allowlist only (no shell=True, no user input)
- 5-second timeout per command
- Output sanitized — no secrets returned
- Latest versions: currently Unknown (conservative default)
- Drift: computed via semver comparison when both installed/latest available

## Safety Model for Update Commands

- Update commands shown in detail modal as copy-only text
- No execution from the page
- Claude Code note: "Auto-update may lack permission. Handle as separate operator maintenance."
- Hermes note: "requires backup + approval"
- All system packages: "Manual OS package review required"

## Test Results

| Test | Result |
|------|--------|
| TypeScript check (new pages) | PASS — zero errors |
| Python syntax check | PASS |
| `_system_access_links()` direct test | PASS — 8 services, health checks work |
| `_system_applications()` direct test | PASS — 23 apps detected |
| No secrets in output | PASS — checked PASSWORD, API_KEY, SECRET, TOKEN, COOKIE |
| No POST endpoints | PASS |
| Buttons copy-only (no execution) | PASS (by design) |
| Links open in new tab | PASS (target="_blank") |
| Full build | BLOCKED by pre-existing Backtesting.tsx type errors (unrelated) |

## Known Issues

1. **Server restart needed**: The portfolio server (pid 4703) runs the old code. New endpoints will be available after `systemctl restart tradeai-portfolio-server`. Not done in this session per safety rules.
2. **Latest versions Unknown**: Conservative default. Could be enhanced with `pip index versions`, `npm view`, or `apt-cache policy` in a future phase.
3. **Pre-existing build error**: Backtesting.tsx has type errors on `classification_classified`, `classification_total`, `run_type` fields. Unrelated to this task.

## Next Recommended Enhancements

1. Add latest-version detection for key packages (pip, npm, apt)
2. Add last-checked timestamp per application
3. Add "Mark Reviewed" workflow for version drift
4. Add Hermes dashboard card once Hermes has research output
5. Fix pre-existing Backtesting.tsx type errors to unblock full build
