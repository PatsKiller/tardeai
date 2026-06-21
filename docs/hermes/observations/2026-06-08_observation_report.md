# Hermes Observation Report — 2026-06-08

**Generated:** 2026-06-08 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 07 21:03:52 ms01-openclaw python[543601]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 07 21:03:52 ms01-openclaw python[543601]: Done in 28.2s: 0 validated, 2 failed/rejected
Jun 07 21:03:52 ms01-openclaw systemd[2973]: 

## Searxng Container — PASS
- status: Up 7 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 1518

## Hermes Rows — PASS
- total: 2180
- staged: 0
- promoted: 2180

## Hermes Embeddings — PASS
- count: 12

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 209

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**