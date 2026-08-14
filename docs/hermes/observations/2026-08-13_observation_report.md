# Hermes Observation Report — 2026-08-13

**Generated:** 2026-08-13 06:31 UTC
**Checks:** 10/12 passed

---

## Hermes Gateway — WARN
- status: inactive

## Hermes Loop Timer — PASS
- status: active

## Hermes Loop Last Log — WARN
- log: Command 'journalctl --user -u hermes-autonomous-loop.service -n 3 --no-pager 2>/dev/null | tail -3' timed out after 10 seconds

## Searxng Container — PASS
- status: Up 3 days

## Searxng Endpoint — PASS
- http_status: 200

## Research Backlog Count — PASS
- count: 2510

## Hermes Rows — PASS
- total: 20732
- staged: 1249
- promoted: 5892

## Hermes Embeddings — PASS
- count: 16026

## Kill Switch — PASS
- active: False

## Safe Views — PASS
- accessible: True

## Dashboard Health — PASS
- http_status: 200

## Cron Count — PASS
- count: 481

## Warnings
- hermes_gateway
- hermes_loop_last_log

---
**Read-only observation. No DB writes. No alerts. No service changes.**