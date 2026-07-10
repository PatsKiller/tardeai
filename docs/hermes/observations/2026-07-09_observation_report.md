# Hermes Observation Report — 2026-07-09

**Generated:** 2026-07-09 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 08 21:05:22 ms01-openclaw python[1927943]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jul 08 21:05:22 ms01-openclaw python[1927943]: Done in 34.6s: 0 validated, 2 failed/rejected
Jul 08 21:05:23 ms01-openclaw systemd[2949]

## Searxng Container — PASS
- status: Up 5 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2503

## Hermes Rows — PASS
- total: 8610
- staged: 168
- promoted: 3348

## Hermes Embeddings — PASS
- count: 5951

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 392

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**