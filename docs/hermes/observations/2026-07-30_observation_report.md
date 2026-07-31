# Hermes Observation Report — 2026-07-30

**Generated:** 2026-07-30 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 29 21:00:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jul 29 21:00:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jul 29 21:00:52 ms01-openclaw systemd[2924]: Failed to start he

## Searxng Container — PASS
- status: Up 12 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 13503
- staged: 275
- promoted: 3144

## Hermes Embeddings — PASS
- count: 10137

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 457

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**