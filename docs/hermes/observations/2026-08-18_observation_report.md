# Hermes Observation Report — 2026-08-18

**Generated:** 2026-08-18 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 17 21:13:40 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Main process exited, code=killed, status=15/TERM
Aug 17 21:13:40 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Failed with result 'timeout'.
Aug 17 21:13:40 ms01-openclaw systemd[2779]: Failed to start hermes

## Searxng Container — PASS
- status: Up 8 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 24564
- staged: 885
- promoted: 9154

## Hermes Embeddings — PASS
- count: 20096

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 485

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**