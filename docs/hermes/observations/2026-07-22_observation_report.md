# Hermes Observation Report — 2026-07-22

**Generated:** 2026-07-22 06:30 UTC
**Checks:** 7/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 21 21:01:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jul 21 21:01:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jul 21 21:01:52 ms01-openclaw systemd[2924]: Failed to start he

## Searxng Container — PASS
- status: Up 4 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — WARN
- count: ERROR: [Errno 2] No such file or directory: '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env'

## Hermes Rows — WARN
- total: ERROR: [Errno 2] No such file or directory: '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env'
- staged: ERROR: [Errno 2] No such file or directory: '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env'
- promoted: ERROR: [Errno 2] No such file or directory: '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env'

## Hermes Embeddings — WARN
- count: ERROR: [Errno 2] No such file or directory: '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env'

## Kill Switch — PASS
- active: False

## Safe Views — WARN
- accessible: False

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 449

## Warnings
- hermes_gateway
- research_backlog_count
- hermes_rows
- hermes_embeddings
- safe_views

---
**Read-only observation. No DB writes. No alerts. No service changes.**