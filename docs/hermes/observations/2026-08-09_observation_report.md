# Hermes Observation Report — 2026-08-09

**Generated:** 2026-08-09 06:31 UTC
**Checks:** 11/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — PASS
- log: Aug 08 21:00:45 ms01-openclaw systemd[7230]: hermes-autonomous-loop.service: Main process exited, code=exited, status=1/FAILURE
Aug 08 21:00:45 ms01-openclaw systemd[7230]: hermes-autonomous-loop.service: Failed with result 'exit-code'.
Aug 08 21:00:45 ms01-openclaw systemd[7230]: Failed to start he

## Searxng Container — PASS
- status: Up 6 hours

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 16764
- staged: 211
- promoted: 3513

## Hermes Embeddings — PASS
- count: 13156

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 483

## Warnings
- hermes_gateway

---
**Read-only observation. No DB writes. No alerts. No service changes.**