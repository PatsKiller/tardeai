# Post-Reboot / OS-Upgrade Recovery (2026-07-02)

Operator runbook after the **Python 3.14 OS upgrade** on `ms01-openclaw`. Documents root causes,
fixes applied on `main`, and verification commands. **No SQL schema migrations were required** —
issues were venv, code paths, and systemd/process ownership.

## Symptoms observed

| Symptom | Root cause |
|---------|------------|
| Stop Management **1/30** active (Schwab stops missing) | Broken `.venv` → `/api/v2/holdings/live-stops` failed; only Fidelity monitored stops showed |
| `regime: unknown` on Stop Management | API queried non-existent `regime_state` table |
| SQL log spam (`signal_score`, `catalyst_quality_score`) | Wrong column names on `trade_ai_scans` / `catalyst_quality_results` |
| RAG embed failures | `import os` trapped inside `rag_retrieval.py` docstring |
| `portfolio-server` orphan (PPID=1, `systemctl inactive`, `:7777` still up) | `fuser` port-guard + `SO_REUSEPORT` allowed twin listeners; overlapping restarts SIGTERM'd each other |
| `psycopg2-binary==2.9.10` pip fail | No cp314 wheel on Python 3.14 |

## Fixes on `main` (commits)

| Commit | What |
|--------|------|
| `18d88962` | Python 3.14 venv (`psycopg2-binary` 2.9.12), `grok_oauth_proxy.py`, RAG `os` import |
| `6e14b73d` | Stop Management broker visibility, regime → `market_regime_snapshots`, watchdog hardening |
| `a27fe808` | Catalyst quality SQL, `cc_v3_site_health_probe.py`, systemd unit template |
| `3749417e` | Remove fuser port-guard; watchdog leaves healthy orphans alone; probe URL fixes |
| `c6a7f253` | `allow_reuse_port=False` — prevents duplicate `:7777` listeners |
| `4fcb9dd1` | `grok-oauth-proxy.service` canonical install docs |
| `844eb814` | `scripts/nous_portal_login_detach.sh` for Nous Portal OAuth |

## SQL / database — nothing to run

- Collation: `ALTER DATABASE trade_ai REFRESH COLLATION VERSION` already applied (`datcollversion` **2.43**).
- Schema matches code: `trade_ai_scans.score`, `catalyst_quality_results.quality_score`, `market_regime_snapshots`.
- Recent migrations verified: `live_submit_path`, `idx_market_quotes_symbol_fetched_at_desc`.

## Systemd services (user units)

Install from repo → `~/.config/systemd/user/`, then `systemctl --user daemon-reload`.

| Unit | Port | ExecStart | Notes |
|------|------|-----------|-------|
| `portfolio-server.service` | 7777 | `.venv/bin/python scripts/portfolio_server.py` | `Restart=on-failure` — **no** `ExecStartPre fuser -k` |
| `grok-oauth-proxy.service` | 8645 | `scripts/grok_oauth_proxy.py` | Canonical name; legacy `hermes-xai-proxy` **disabled** |
| `chatgpt-oauth-proxy.service` | 8646 | `scripts/chatgpt_oauth_proxy.py` | |

```bash
# Portfolio server — clean adopt (if orphan on :7777)
systemctl --user stop portfolio-server.service
pid=$(pgrep -f 'scripts/portfolio_server.py' | head -1)
[ -n "$pid" ] && kill -TERM "$pid" && sleep 2 && kill -9 "$pid" 2>/dev/null
systemctl --user start portfolio-server.service
systemctl --user is-active portfolio-server.service   # expect: active
ss -tlnp | grep 7777   # single listener, MainPID matches

# OAuth proxies
systemctl --user enable --now grok-oauth-proxy.service chatgpt-oauth-proxy.service
curl -s http://127.0.0.1:8645/health | python3 -m json.tool
curl -s http://127.0.0.1:8646/health | python3 -m json.tool
```

## OAuth lanes (live 2026-07-02)

| Lane | Status | Login / service |
|------|--------|-----------------|
| Grok | **ready** | `hermes auth add xai-oauth --type oauth` + `grok-oauth-proxy.service` |
| ChatGPT | **ready** | `hermes auth add openai-codex --type oauth` + `chatgpt-oauth-proxy.service` |
| Hermes/Nous | **ready** | `hermes auth add nous --type oauth` or `scripts/nous_portal_login_detach.sh` |
| Local | **ready** | Ollama |

```bash
curl -s http://127.0.0.1:7777/api/v2/llm/oauth-lanes | python3 -m json.tool
hermes portal status
```

## Site-wide validation

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python scripts/cc_v3_site_health_probe.py   # 94 endpoints, MUST run sequentially
```

Expected: **94 OK, 0 FAIL**. Parallel probing wedges the single-threaded server.

Critical path spot-checks:

```bash
curl -s http://127.0.0.1:7777/api/v2/stops/management | python3 -c \
  "import sys,json; s=json.load(sys.stdin)['data']; print(s['summary']['broker_stops_active'], '/', s['summary']['positions'], 'degraded', s['broker_stops_degraded'])"
# expect: 12 / 30 degraded False (counts vary with live broker state)
```

## Watchdog

`scripts/portfolio_server_watchdog.sh` (cron every 2 min):

- **Healthy orphan** (`systemd inactive` but `/api/health` OK) → log only, do **not** kill.
- **Unresponsive** after 3 probes → kill + `systemctl --user start portfolio-server`.

## Python venv

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
python3.14 -m venv .venv   # if rebuilding from scratch
.venv/bin/pip install -r requirements.txt   # psycopg2-binary>=2.9.12 for cp314
.venv/bin/pip check
```