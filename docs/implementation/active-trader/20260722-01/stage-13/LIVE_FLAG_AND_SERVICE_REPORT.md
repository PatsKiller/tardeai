# Stage 13 — Live Flag & Service Report

**HEAD:** 4e4176ba · Verdict: **all live authority OFF/inactive**

## Feature flags
- `contracts.FLAG_REGISTRY`: 22 flags. `DEFAULTS['production']` → **all 22 OFF**.
- `active_trader_live_canary_enabled` (production) = **OFF** — LIVE_CANARY is unrepresentable.
- `DEFAULTS['test']` → all OFF. `DEFAULTS['development']` → only `active_trader_next_visible=READ_ONLY`.
- No environment default enables any order/broker/canary flag.

## Production API mount
- No production route mounts read_api / dev_write_api / shadow / simulation (grep of apps/backend/server/src → 0 imports).
- read_api is standalone stdlib http.server; dev-write plane is default-disabled + loopback + SHADOW/SIMULATION + test-identity.

## systemd units
| Unit (user scope) | is-enabled | is-active |
|---|---|---|
| trade-ai-lab-moomoo-opend.service | static | inactive |
| trade-ai-lab-moomoo-gateway.service | static | inactive |
| trade-ai-lab-moomoo-replay-writer.service | static | inactive |
| trade-ai-lab-moomoo-feature-engine.service | static | inactive |
| trade-ai-lab-moomoo-health-monitor.service | static | inactive |

`static` = no `[Install]` section → cannot be enabled → will not autostart. All inactive.
- No system-scoped unit installed by this program.
- No user linger enabled by this program.

## Network / infra
- No reverse-proxy route added (SWITCH_RUNBOOK documents the future step; not executed).
- No firewall change.
- All lab/dev listeners are loopback (Moomoo 11112; dev ports 7789/7790; read_api loopback).

## Conclusion
All production Active Trader flags OFF; LIVE_CANARY OFF/unrepresentable; no production API mount; no unit
installed or enabled; no linger; no proxy/firewall change. Dual-operation readiness is **inactive** by
construction.
