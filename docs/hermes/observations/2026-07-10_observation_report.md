# Hermes Observation Report — 2026-07-10

**Generated:** 2026-07-10 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 09 21:02:17 ms01-openclaw python[3078452]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 09 21:02:17 ms01-openclaw python[3078452]: Done in 13.7s: 0 validated, 1 failed/rejected
Jul 09 21:02:17 ms01-openclaw systemd[2949]

## Searxng Container — PASS
- status: Up 6 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2504

## Hermes Rows — PASS
- total: 8814
- staged: 218
- promoted: 3322

## Hermes Embeddings — PASS
- count: 6104

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 392

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**