# Hermes Observation Report — 2026-08-12

**Generated:** 2026-08-12 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 11 21:13:54 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Aug 11 21:13:54 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Aug 11 21:13:54 ms01-openclaw systemd[2779]: Failed to start he

## Searxng Container — PASS
- status: Up 2 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 19841
- staged: 1114
- promoted: 5244

## Hermes Embeddings — PASS
- count: 15306

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 481

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**