# Hermes Observation Report — 2026-08-28

**Generated:** 2026-08-28 06:31 UTC
**Checks:** 10/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — WARN
- status: inactive

## Hermes Loop Last Log — PASS
- log: Aug 22 13:10:16 ms01-openclaw systemd[7039]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Aug 22 13:10:16 ms01-openclaw systemd[7039]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Aug 22 13:10:16 ms01-openclaw systemd[7039]: Failed to start he

## Searxng Container — PASS
- status: Up 6 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2511

## Hermes Rows — PASS
- total: 31375
- staged: 1411
- promoted: 8939

## Hermes Embeddings — PASS
- count: 22636

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 494

## Warnings
- hermes_gateway
- hermes_loop_timer

---
**Read-only observation. No DB writes. No alerts. No service changes.**