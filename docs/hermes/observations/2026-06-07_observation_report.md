# Hermes Observation Report — 2026-06-07

**Generated:** 2026-06-07 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 06 21:01:05 ms01-openclaw python[3566678]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 06 21:01:05 ms01-openclaw python[3566678]: Done in 22.6s: 0 validated, 2 failed/rejected
Jun 06 21:01:05 ms01-openclaw systemd[2973]

## Searxng Container — PASS
- status: Up 6 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 1227

## Hermes Rows — PASS
- total: 1837
- staged: 0
- promoted: 1837

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