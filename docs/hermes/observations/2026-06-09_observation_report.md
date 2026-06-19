# Hermes Observation Report — 2026-06-09

**Generated:** 2026-06-09 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 08 21:02:42 ms01-openclaw systemd[2973]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jun 08 21:02:42 ms01-openclaw systemd[2973]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jun 08 21:02:42 ms01-openclaw systemd[2973]: Failed to start he

## Searxng Container — PASS
- status: Up 8 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 1806

## Hermes Rows — PASS
- total: 2583
- staged: 1
- promoted: 2582

## Hermes Embeddings — PASS
- count: 12

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 222

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**