# Hermes Observation Report — 2026-07-17

**Generated:** 2026-07-17 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 16 21:03:37 ms01-openclaw python[1170268]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 16 21:03:37 ms01-openclaw python[1170268]: Done in 41.6s: 0 validated, 2 failed/rejected
Jul 16 21:03:37 ms01-openclaw systemd[2949]

## Searxng Container — PASS
- status: Up 13 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 10572
- staged: 331
- promoted: 3573

## Hermes Embeddings — PASS
- count: 7578

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 412

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**