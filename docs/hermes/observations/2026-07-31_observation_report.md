# Hermes Observation Report — 2026-07-31

**Generated:** 2026-07-31 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Jul 30 21:13:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=killed, status=15/TERM
Jul 30 21:13:52 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'timeout'.
Jul 30 21:13:52 ms01-openclaw systemd[2924]: Failed to start hermes

## Searxng Container — PASS
- status: Up 13 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 13706
- staged: 311
- promoted: 2983

## Hermes Embeddings — PASS
- count: 10288

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 459

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**