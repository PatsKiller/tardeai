# Hermes Observation Report — 2026-07-12

**Generated:** 2026-07-12 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 11 21:03:22 ms01-openclaw python[671051]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 11 21:03:22 ms01-openclaw python[671051]: Done in 38.9s: 0 validated, 2 failed/rejected
Jul 11 21:03:22 ms01-openclaw systemd[2949]: 

## Searxng Container — PASS
- status: Up 8 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2509

## Hermes Rows — PASS
- total: 9149
- staged: 270
- promoted: 3135

## Hermes Embeddings — PASS
- count: 6379

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 393

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**