# Stage 13 — Local Dual-Run Drill Report

**Run:** 20260722-01 · **HEAD:** 4e4176ba · **Date:** 2026-07-23 · Loopback-only, fixture/replay, no broker network.

## Setup
- Served the two **already-built** production bundles via `vite preview`, loopback only, distinct nonproduction ports.
- v3 (classic): `127.0.0.1:7789`, base `/v3/`, dir `apps/command-center-v3/dist`.
- v3-next: `127.0.0.1:7790`, base `/v3-next/`, dir `apps/command-center-v3-next/dist`.
- No production server, DB, service, proxy, or broker involved.

## Results

| Check | Result |
|---|---|
| DUAL-RUN — v3 `/v3/` while v3-next running | **HTTP 200** |
| DUAL-RUN — v3-next `/v3-next/` while v3 running | **HTTP 200** |
| Asset base (v3) | `/v3/assets/index-BSOUzVSa.js` |
| Asset base (v3-next) | `/v3-next/assets/index-C-1uufpS.js` (distinct base + distinct hash) |
| Route isolation — v3-next answering `/v3/` | **HTTP 404** (does not serve classic routes) |
| ROLLBACK — kill v3-next, v3 `/v3/` | **HTTP 200** (classic unaffected) |
| TEARDOWN — vite preview processes remaining | **0** |
| TEARDOWN — listeners on 7789/7790 | **0** |
| Production process touched | **none** |

## Interpretation
Classic /v3 and new /v3-next run **concurrently** without interfering, serve from **distinct base paths**
and **distinct hashed assets**, and v3-next does not answer classic routes. Killing v3-next (the rollback
motion) leaves /v3 fully serving. All local processes and listeners were torn down (0 leftovers). This is
**fixture/transport parity only** — NOT live Moomoo parity (see parity matrix).
