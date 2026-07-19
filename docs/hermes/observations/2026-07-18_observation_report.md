# Hermes Observation Report — 2026-07-18

**Generated:** 2026-07-18 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 17 21:05:13 ms01-openclaw python[621860]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 17 21:05:13 ms01-openclaw python[621860]: Done in 20.6s: 0 validated, 1 failed/rejected
Jul 17 21:05:13 ms01-openclaw systemd[2924]: 

## Searxng Container — PASS
- status: Up 20 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 10922
- staged: 305
- promoted: 3702

## Hermes Embeddings — PASS
- count: 7904

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 417

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**