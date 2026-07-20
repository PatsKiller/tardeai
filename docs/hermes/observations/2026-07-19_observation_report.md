# Hermes Observation Report — 2026-07-19

**Generated:** 2026-07-19 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 18 21:05:28 ms01-openclaw python[1347567]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 18 21:05:28 ms01-openclaw python[1347567]: Done in 35.7s: 0 validated, 2 failed/rejected
Jul 18 21:05:28 ms01-openclaw systemd[2924]

## Searxng Container — PASS
- status: Up 44 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 11018
- staged: 302
- promoted: 3656

## Hermes Embeddings — PASS
- count: 7953

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 424

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**