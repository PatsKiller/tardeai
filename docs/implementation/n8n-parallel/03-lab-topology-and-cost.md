# Phase 2 — lab topology, credentials, and cost

This describes the instance that is already running. No container was recreated. Queue mode was not added. No credential was stored.

## Topology

```text
cron / systemd / flock  ---- live owner ----> Trade AI :7777 and DOF :7776
                                              |
n8n 127.0.0.1:5678 (lab) -- read-only GET --> build-meta and /api/run-scope
        |
        +-- n8n Postgres (container only, port not published)

No Redis. No second main. No webhook registered.
```

| Piece | Observed |
|---|---|
| Compose project | `m8m-n8n`. File `/home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml`. |
| n8n | `n8nio/n8n:2.43.0`, running, memory cap 805306368 bytes (768 MiB), port `127.0.0.1:5678` only |
| n8n database | `postgres:16.15-alpine`, running, no published port, database `n8n`. Postgres 16 is outside n8n's supported major range and was left as-is. |
| Other containers seen | `tradeai-m2-shadow-v2` and `searxng`. They were not inspected and not changed. Kestra is not running. |
| Docker socket | Not mounted |
| Network | Lab bridge is not internal-only, so a workflow can route to `172.19.0.1`. It cannot open host `127.0.0.1`, including the model bridge on `:8766`. |
| Restart | `unless-stopped` is a process restart, not a second host |

Dev and production triggers are not separated inside n8n because there is no production n8n. The two active workflows are lab monitors. They do not own cron.

## Credential gate

Bitwarden remains the credential store named by the architecture. Community n8n would encrypt any native credential in its own database. External secret stores are an enterprise feature and do not list Bitwarden. That conflict is unresolved.

Decision for this program: BLOCKED_POLICY for Gmail, Telegram, Drive, GitHub, DeepSeek, OpenRouter, broker, and database credentials inside n8n. The monitors call two unauthenticated GETs. Those routes are already auth-exempt in Trade AI or are the DOF run-scope read. Localhost is not treated as authorization for anything beyond that.

A narrow request gateway, with short-lived signed claims, nonce replay defense, and scoped routes, is the only shape that could unblock a later integration. It was not built. If it cannot be authenticated under current policy, external integrations stay blocked and only fixture workflows with no secrets are allowed.

No financial or provider credential is in n8n (credential count 0). The control surface is bound to localhost, not a public interface. An independent monitor that still reports when n8n, its database, or this host is down was not built. Docker restart policy does not meet that test. Gate item: NOT_MET.

## Restore

Lab restore drill, OBSERVED_LAB, file `/home/johnclaw/m8m-bakeoff-lab/artifacts/n8n-restore-drill.json`:

- Started 2026-10-06T22:11:01Z, finished 2026-10-06T22:12:06Z.
- Dump 550,052 bytes. Source tables 157, restore tables 157, counts equal.
- Restore database was dropped. Production Postgres was not touched.

That drill is not on a schedule. Trade AI and DOF backup freshness were not remeasured. Label: NOT_MEASURED.

## Cost

| Item | Figure | Label |
|---|---|---|
| n8n subscription | $0. Community, self-hosted. | OBSERVED_LAB |
| Extra host capacity | 768 MiB plus 256 MiB caps, already running | OBSERVED_LAB |
| Lab executions | 66 since this database was created | OBSERVED_LAB |
| Model spend caused by this program | 0. No provider call. | OBSERVED_LAB |
| Weekday cron CMD lines | about 9,547–9,565 then about 10,154–10,200 on completed weekdays in the retained journal | OBSERVED_SERVED as syslog lines, not n8n executions |
| Cloud Starter price and 2,500-execution quota | Not re-quoted this pass. The discovery text is not a purchase quote. | NOT_MEASURED |
| Operator ceiling | About $20, from the work order, not from an invoice | DESIGN_ONLY |

Moving weekday cron volume onto Cloud Starter would pass a 2,500-execution month on the first morning. That comparison uses syslog command lines as a stand-in for executions. It is enough to reject Cloud as the destination. It is not a bill. No paid tier and no cloud database move is proposed. A cloud-hybrid database latency model was not measured.

## Watchdog

The external watchdog, host backups, and cron continue without n8n. That is the property this phase keeps. It does not detect an n8n outage. Building that detector is later work and has to live outside n8n.
