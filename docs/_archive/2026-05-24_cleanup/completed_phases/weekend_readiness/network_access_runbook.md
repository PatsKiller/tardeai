# Network Access Runbook

## Primary Access (Tailscale)
- **FQDN:** ms01-openclaw.tail163d14.ts.net
- **Tailscale IP:** 100.66.120.124
- **SSH:** `ssh johnclaw@ms01-openclaw.tail163d14.ts.net`
- **Dashboard:** http://ms01-openclaw.tail163d14.ts.net:7777/v2/
- **ATM page:** http://ms01-openclaw.tail163d14.ts.net:7777/v2/automated-trade-mode

## LAN Access
- **LAN IP:** 192.168.50.16
- **Dashboard:** http://192.168.50.16:7777/v2/
- **API:** http://192.168.50.16:7777/api/v2/overview

## Troubleshooting
```bash
tailscale status                    # check peer connectivity
ping ms01-openclaw                  # test Tailscale DNS
curl -s http://localhost:7777/api/v2/atm/status | python3 -m json.tool
systemctl status tradeai-portfolio-server.service
```
