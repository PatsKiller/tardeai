# Hermes Observation Report — 2026-07-16

**Generated:** 2026-07-16 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 15 21:05:19 ms01-openclaw python[398]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 15 21:05:19 ms01-openclaw python[398]: Done in 24.0s: 0 validated, 2 failed/rejected
Jul 15 21:05:19 ms01-openclaw systemd[2949]: Finish

## Searxng Container — PASS
- status: Up 12 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 10104
- staged: 294
- promoted: 3301

## Hermes Embeddings — PASS
- count: 7198

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 397

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**