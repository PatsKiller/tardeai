# Hermes Observation Report — 2026-08-02

**Generated:** 2026-08-02 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 01 21:15:42 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Main process exited, code=killed, status=15/TERM
Aug 01 21:15:42 ms01-openclaw systemd[2924]: hermes-autonomous-loop.service: Failed with result 'timeout'.
Aug 01 21:15:42 ms01-openclaw systemd[2924]: Failed to start hermes

## Searxng Container — PASS
- status: Up 2 weeks

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 14180
- staged: 212
- promoted: 2811

## Hermes Embeddings — PASS
- count: 10762

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 463

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**