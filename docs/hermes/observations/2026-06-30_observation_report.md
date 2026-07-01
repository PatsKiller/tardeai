# Hermes Observation Report — 2026-06-30

**Generated:** 2026-06-30 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 29 21:01:25 ms01-openclaw systemd[2973]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jun 29 21:01:25 ms01-openclaw systemd[2973]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jun 29 21:01:25 ms01-openclaw systemd[2973]: Failed to start he

## Searxng Container — PASS
- status: Up 4 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2495

## Hermes Rows — PASS
- total: 6064
- staged: 0
- promoted: 2019

## Hermes Embeddings — PASS
- count: 3581

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 363

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**