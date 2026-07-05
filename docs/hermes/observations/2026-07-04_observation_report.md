# Hermes Observation Report — 2026-07-04

**Generated:** 2026-07-04 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 03 21:01:34 ms01-openclaw systemd[2949]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jul 03 21:01:34 ms01-openclaw systemd[2949]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jul 03 21:01:34 ms01-openclaw systemd[2949]: Failed to start he

## Searxng Container — PASS
- status: Up 14 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2495

## Hermes Rows — PASS
- total: 6699
- staged: 8
- promoted: 2170

## Hermes Embeddings — PASS
- count: 4208

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 375

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**