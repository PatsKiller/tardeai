# Hermes Observation Report — 2026-07-02

**Generated:** 2026-07-02 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 30 21:04:59 ms01-openclaw python[1223077]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 30 21:04:59 ms01-openclaw python[1223077]: Done in 16.5s: 0 validated, 1 failed/rejected
Jun 30 21:04:59 ms01-openclaw systemd[2973]

## Searxng Container — PASS
- status: Up 3 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2495

## Hermes Rows — PASS
- total: 6390
- staged: 0
- promoted: 2107

## Hermes Embeddings — PASS
- count: 3907

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 366

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**