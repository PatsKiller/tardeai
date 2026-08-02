# Hermes Observation Report — 2026-08-01

**Generated:** 2026-08-01 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 31 21:00:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jul 31 21:00:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jul 31 21:00:52 ms01-openclaw systemd[2924]: Failed to start he

## Searxng Container — PASS
- status: Up 2 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 14085
- staged: 235
- promoted: 2992

## Hermes Embeddings — PASS
- count: 10688

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 459

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**