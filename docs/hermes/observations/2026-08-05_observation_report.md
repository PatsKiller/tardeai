# Hermes Observation Report — 2026-08-05

**Generated:** 2026-08-05 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 04 21:14:43 ms01-openclaw systemd[3075]: hermes-autonomous-loop.service: Main process exited, code=killed, status=15/TERM
Aug 04 21:14:43 ms01-openclaw systemd[3075]: hermes-autonomous-loop.service: Failed with result 'timeout'.
Aug 04 21:14:43 ms01-openclaw systemd[3075]: Failed to start hermes

## Searxng Container — PASS
- status: Up 35 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 14910
- staged: 233
- promoted: 2930

## Hermes Embeddings — PASS
- count: 11453

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 472

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**