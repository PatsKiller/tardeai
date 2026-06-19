# Hermes Observation Report — 2026-06-13

**Generated:** 2026-06-13 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 12 21:04:43 ms01-openclaw python[1295251]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 12 21:04:43 ms01-openclaw python[1295251]: Done in 60.8s: 0 validated, 1 failed/rejected
Jun 12 21:04:43 ms01-openclaw systemd[2973]

## Searxng Container — PASS
- status: Up 12 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2486

## Hermes Rows — PASS
- total: 3878
- staged: 0
- promoted: 1404

## Hermes Embeddings — PASS
- count: 12

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 252

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**