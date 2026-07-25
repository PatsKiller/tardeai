# Hermes Observation Report — 2026-07-24

**Generated:** 2026-07-24 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 23 21:01:24 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jul 23 21:01:24 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jul 23 21:01:24 ms01-openclaw systemd[2924]: Failed to start he

## Searxng Container — PASS
- status: Up 6 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 12556
- staged: 362
- promoted: 3380

## Hermes Embeddings — PASS
- count: 9340

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 451

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**