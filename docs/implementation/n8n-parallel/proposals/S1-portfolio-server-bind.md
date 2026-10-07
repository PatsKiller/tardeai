# Proposal S1 — stop serving the Trade AI API unauthenticated on 0.0.0.0:7777

Status: PROPOSED 2026-10-07. Operator decision (config-write grant). Nothing applied.

Evidence (09-live-audit §6 S1): `portfolio_server.py` treats an unset `API_AUTH_TOKEN` as open access;
`API_AUTH_TOKEN` is absent from the rendered env; `AUTH_EXEMPT_PREFIXES` covers `/v2/`, `/v3/`; the
listener is `0.0.0.0:7777`; the n8n lab bridge reaches it; `tailscale serve` already proxies
`100.66.120.124:443 → localhost:7777` (and `:8443 → localhost:7776`), so the operator UI does not need
the LAN listener.

Recommended order (least behaviour change first):
1. **Bind to loopback.** The UI path stays `tailscale serve → localhost:7777`. LAN, Docker bridges and
   the n8n container lose reach. Implementation: an env-driven bind host in `portfolio_server.py`
   (`PORTFOLIO_SERVER_BIND`, default **unchanged** `0.0.0.0` until the operator flips it) plus a
   systemd drop-in `~/.config/systemd/user/portfolio-server.service.d/30-bind-loopback.conf` with
   `Environment=PORTFOLIO_SERVER_BIND=127.0.0.1`. Rollback = remove the drop-in.
   Check first: anything on the LAN that calls `:7777` directly (the DOF app? OpenClaw? the n8n
   monitor workflow `n8n-monitor-trade-ai` reads `172.19.0.1:7777/v3/build-meta.json` and WILL fail;
   repoint it to the gateway `/healthz` once the gateway is installed, or accept the monitor going red).
2. **Add the token.** Create `API_AUTH_TOKEN` in Bitwarden SM (project trade-ai-prod) so `render_env`
   delivers it; the Command Center reads it from its existing config path. Then change the server so
   unset **fails closed** (a one-line change in the auth block) and narrow `AUTH_EXEMPT_PREFIXES` to the
   static asset prefixes only.

Not proposed: enabling the token while the UI has no way to send it (would lock the operator out).
