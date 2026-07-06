# Hermes Observation Report — 2026-07-05

**Generated:** 2026-07-05 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 04 21:01:22 ms01-openclaw python[1762134]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 04 21:01:22 ms01-openclaw python[1762134]: Done in 33.5s: 0 validated, 1 failed/rejected
Jul 04 21:01:22 ms01-openclaw systemd[2949]

## Searxng Container — PASS
- status: Up 38 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2495

## Hermes Rows — PASS
- total: 6794
- staged: 6
- promoted: 2135

## Hermes Embeddings — PASS
- count: 4305

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 379

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**