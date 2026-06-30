# Hermes Observation Report — 2026-06-29

**Generated:** 2026-06-29 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: failed

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jun 28 21:04:52 ms01-openclaw python[1364870]:     VALIDATION FAILED: ['MISSING required column: summary', 'evidence_json has only 1 substantive keys (need >= 2)']
Jun 28 21:04:52 ms01-openclaw python[1364870]: Done in 69.9s: 0 validated, 2 failed/rejected
Jun 28 21:04:52 ms01-openclaw systemd[2973]

## Searxng Container — PASS
- status: Up 4 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2494

## Hermes Rows — PASS
- total: 5865
- staged: 0
- promoted: 1922

## Hermes Embeddings — PASS
- count: 3383

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 361

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**