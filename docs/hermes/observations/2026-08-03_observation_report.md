# Hermes Observation Report — 2026-08-03

**Generated:** 2026-08-03 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 02 21:00:12 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Aug 02 21:00:12 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Aug 02 21:00:12 ms01-openclaw systemd[2924]: Failed to start he

## Searxng Container — PASS
- status: Up 2 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 14289
- staged: 237
- promoted: 2803

## Hermes Embeddings — PASS
- count: 10846

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 469

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**