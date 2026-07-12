# Hermes Observation Report — 2026-07-11

**Generated:** 2026-07-11 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 10 21:04:20 ms01-openclaw python[4181446]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 10 21:04:20 ms01-openclaw python[4181446]: Done in 66.9s: 1 validated, 1 failed/rejected
Jul 10 21:04:20 ms01-openclaw systemd[2949]

## Searxng Container — PASS
- status: Up 7 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2509

## Hermes Rows — PASS
- total: 9047
- staged: 262
- promoted: 3321

## Hermes Embeddings — PASS
- count: 6285

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