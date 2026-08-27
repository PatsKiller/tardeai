# Mobile Responsive + Tailscale HTTPS — 2026-05-20

**Status:** COMPLETE

## URLs

| Site | URL | Port Mapping |
|------|-----|-------------|
| v2 Dashboard | `https://ms01-openclaw.tail163d14.ts.net/` | 443 → localhost:7777 |
| DOF Auctions | `https://ms01-openclaw.tail163d14.ts.net:8443/` | 8443 → localhost:7776 |

Both use Tailscale HTTPS with auto-provisioned Let's Encrypt certs (tailnet only, not public).

## Tailscale Serve Config

```
tailscale serve --bg --https=443 http://localhost:7777    # v2 dashboard
tailscale serve --bg --https=8443 http://localhost:7776   # DOF auctions
```

Root `/` redirects to `/v2/` (commit `97d3dc7`).

## v2 Dashboard — Mobile Responsive

### Shell Layout (commits `aa2bcbb`, `b7c46bb`)
- Sidebar collapses to slide-out drawer below 768px
- Hamburger button in header opens drawer
- Drawer closes on route change
- Ticker tape collapses to brand + portfolio + today on mobile
- Desktop nav row hidden on mobile (drawer replaces it)

### Global CSS Overrides
All 43 pages get responsive treatment via CSS attribute selectors:
- `repeat(3-8, ...)` grids → 2-column on phone
- Two-pane layouts (`1.15fr 0.85fr`, `1fr 1fr`, etc.) → single column
- Gaps reduced (24px→12px, 16px→8px)
- Padding reduced (24px→12px, 20px→12px)
- Tables become horizontally scrollable
- Touch targets minimum 44px
- Input font 16px (prevents iOS Safari zoom)
- `#root overflow-x: hidden` prevents horizontal page scroll

### Proposal Alerts
- "Open in Dashboard" button uses `https://{TAILSCALE_HOSTNAME}/v2/paper-proposals?id=N`
- No port number (443 is HTTPS default)
- Only renders when `TAILSCALE_HOSTNAME` env var is set

## DOF Auction Site — Mobile Responsive

### Layout (commits `8db0c9e`, `5d3c39e`)
- Sidebar becomes fixed slide-out drawer on mobile with backdrop
- Hamburger button in header toggles drawer
- Stat grid reflows to 2-col on phone, 3-col on tablet
- Search inputs full-width on mobile
- Modal dialogs 95vw width
- Table cells nowrap + horizontal scroll
- Score bars narrower (40px)
- Export menu right-aligned
- Touch targets 44px, input font 16px

### Tablet (768-1023px)
- Sidebar narrows to 180px
- Stat grid 3-col
- Main content padding reduced

## Callback Poller

`run_telegram_callback_poller.py` runs as a daemon (commit `fb838e8`):
- Long-polls Telegram for callback_query (button presses) and /pt* commands
- Processes approve/reject/half/2x/info with confirmation replies
- Cron keepalive every 2 minutes
- Logs to `logs/telegram_callback_poller.log`

## .env Changes (operator-authorized this session)

- `TAILSCALE_HOSTNAME=ms01-openclaw.tail163d14.ts.net` — added for URL button gate

## Files Changed

### trade-ai-v12-rebuild
| File | Change |
|------|--------|
| `apps/command-center-v2/src/components/Shell.tsx` | Drawer + hamburger |
| `apps/command-center-v2/src/components/Shell.module.css` | Mobile drawer CSS, tape collapse |
| `apps/command-center-v2/src/theme.css` | Global responsive grid/table/touch overrides |
| `scripts/proposal_alerter.py` | HTTPS URL button, correct chat ID env var |
| `scripts/telegram_callback_handler.py` | Callback query handler |
| `scripts/run_telegram_callback_poller.py` | Long-poll daemon |
| `scripts/portfolio_server.py` | Root / → /v2/ redirect |
| `docs/CHEAT_SHEET.md` | URLs, poller status commands |

### nyc-dof-auction
| File | Change |
|------|--------|
| `static/index.html` | Mobile CSS, hamburger, drawer toggle JS |
