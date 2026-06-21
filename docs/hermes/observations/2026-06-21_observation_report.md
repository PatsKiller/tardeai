# Hermes Observation Report — 2026-06-21

**Generated:** 2026-06-21 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 20 21:06:00 ms01-openclaw python[328682]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 20 21:06:00 ms01-openclaw python[328682]: Done in 17.9s: 0 validated, 1 failed/rejected
Jun 20 21:06:00 ms01-openclaw systemd[2973]: 

## Searxng Container — PASS
- status: Up 2 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2486

## Hermes Rows — PASS
- total: 4647
- staged: 0
- promoted: 2173

## Hermes Embeddings — PASS
- count: 12

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 287

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**