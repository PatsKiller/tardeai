# Hermes Observation Report — 2026-06-19

**Generated:** 2026-06-19 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 18 21:03:06 ms01-openclaw python[1957445]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 18 21:03:06 ms01-openclaw python[1957445]: Done in 24.1s: 0 validated, 1 failed/rejected
Jun 18 21:03:06 ms01-openclaw systemd[2973]

## Searxng Container — PASS
- status: Up 2 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2486

## Hermes Rows — PASS
- total: 4381
- staged: 0
- promoted: 1907

## Hermes Embeddings — PASS
- count: 12

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 276

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**