# Hermes Observation Report — 2026-08-22

**Generated:** 2026-08-22 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 21 20:20:49 ms01-openclaw systemd[7039]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Aug 21 20:20:49 ms01-openclaw systemd[7039]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Aug 21 20:20:49 ms01-openclaw systemd[7039]: Failed to start he

## Searxng Container — PASS
- status: Up 14 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 27964
- staged: 1198
- promoted: 10665

## Hermes Embeddings — PASS
- count: 22636

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 491

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**