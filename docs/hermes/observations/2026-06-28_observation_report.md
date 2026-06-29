# Hermes Observation Report — 2026-06-28

**Generated:** 2026-06-28 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 27 21:04:42 ms01-openclaw python[3806498]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 27 21:04:42 ms01-openclaw python[3806498]: Done in 59.4s: 0 validated, 2 failed/rejected
Jun 27 21:04:42 ms01-openclaw systemd[2973]

## Searxng Container — PASS
- status: Up 3 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2494

## Hermes Rows — PASS
- total: 5733
- staged: 0
- promoted: 1801

## Hermes Embeddings — PASS
- count: 3251

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 357

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**