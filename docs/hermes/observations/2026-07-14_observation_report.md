# Hermes Observation Report — 2026-07-14

**Generated:** 2026-07-14 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 13 21:03:09 ms01-openclaw python[2113671]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 13 21:03:09 ms01-openclaw python[2113671]: Done in 13.7s: 0 validated, 1 failed/rejected
Jul 13 21:03:09 ms01-openclaw systemd[2949]

## Searxng Container — PASS
- status: Up 10 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2509

## Hermes Rows — PASS
- total: 9475
- staged: 305
- promoted: 3162

## Hermes Embeddings — PASS
- count: 6670

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 393

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**