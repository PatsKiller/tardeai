# Hermes Observation Report — 2026-08-15

**Generated:** 2026-08-15 06:30 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 14 21:12:27 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Main process exited, code=killed, status=15/TERM
Aug 14 21:12:27 ms01-openclaw systemd[2779]: hermes-autonomous-loop.service: Failed with result 'timeout'.
Aug 14 21:12:27 ms01-openclaw systemd[2779]: Failed to start hermes

## Searxng Container — PASS
- status: Up 5 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 22332
- staged: 1334
- promoted: 7066

## Hermes Embeddings — PASS
- count: 17456

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