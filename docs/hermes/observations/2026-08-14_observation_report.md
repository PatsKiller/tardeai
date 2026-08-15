# Hermes Observation Report — 2026-08-14

**Generated:** 2026-08-14 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 13 21:00:40 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Aug 13 21:00:40 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Aug 13 21:00:40 ms01-openclaw systemd[2779]: Failed to start he

## Searxng Container — PASS
- status: Up 4 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 21557
- staged: 1335
- promoted: 6494

## Hermes Embeddings — PASS
- count: 16736

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 485

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**