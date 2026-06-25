# Hermes Observation Report — 2026-06-24

**Generated:** 2026-06-24 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 23 21:05:49 ms01-openclaw python[587647]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 23 21:05:49 ms01-openclaw python[587647]: Done in 67.4s: 0 validated, 2 failed/rejected
Jun 23 21:05:50 ms01-openclaw systemd[2973]: 

## Searxng Container — PASS
- status: Up 3 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2486

## Hermes Rows — PASS
- total: 4957
- staged: 0
- promoted: 2483

## Hermes Embeddings — PASS
- count: 1591

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 315

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**