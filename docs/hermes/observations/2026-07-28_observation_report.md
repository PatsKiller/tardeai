# Hermes Observation Report — 2026-07-28

**Generated:** 2026-07-28 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 27 21:03:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Jul 27 21:03:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Jul 27 21:03:52 ms01-openclaw systemd[2924]: Failed to start he

## Searxng Container — PASS
- status: Up 10 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 13215
- staged: 227
- promoted: 3427

## Hermes Embeddings — PASS
- count: 9963

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 454

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**