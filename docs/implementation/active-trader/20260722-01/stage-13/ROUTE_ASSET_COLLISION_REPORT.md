# Stage 13 — Route / Asset / Service / Port Collision Report

**HEAD:** 4e4176ba · Verdict: **NO COLLISIONS**

## Routes
| App | Base path | Source |
|---|---|---|
| classic | `/v3/` | `apps/command-center-v3/vite.config.ts` `base:'/v3/'` |
| next | `/v3-next/` | `apps/command-center-v3-next/vite.config.ts` `base:'/v3-next/'` |

`/v3/` and `/v3-next/` are **sibling prefixes**. A prefix rule on `/v3/` (with trailing slash) does not
match `/v3-next/`. Live drill confirmed: v3-next returns **404** for `/v3/`. No route collision.
> Deployment note: a future reverse-proxy rule must match `/v3/` **with the trailing slash** (or exact
> `/v3`), never a bare `/v3` prefix, so it cannot accidentally swallow `/v3-next/`.

## Assets
| App | outDir | Asset base | Example |
|---|---|---|---|
| classic | `apps/command-center-v3/dist` | `/v3/assets/` | `index-BSOUzVSa.js` |
| next | `apps/command-center-v3-next/dist` | `/v3-next/assets/` | `index-C-1uufpS.js` |

Separate `dist` directories under separate app roots; content-hashed filenames under distinct base
paths. No asset path or filename collision.

## Services
- v3-next is a **static front-end bundle** — no backend service of its own.
- `read_api.py` (Stage 4) is a **standalone** app (stdlib http.server), not mounted into any production
  server; default-off/loopback for the dev-write plane.
- No production systemd unit is created or modified. Moomoo lab units exist but are `static` + `inactive`.
- No service-name collision.

## Ports
| Purpose | Port | Bind |
|---|---|---|
| v3 dev | 7789 | loopback |
| v3-next dev | 7790 | loopback |
| dual-run drill (v3 / v3-next preview) | 7789 / 7790 | 127.0.0.1 |
| Moomoo API (lab) | 11112 | 127.0.0.1 (11111 reserved, unused) |
| read_api dev | env-config, loopback | 127.0.0.1 |

All distinct; all loopback for lab/dev. No production port touched. No port collision.
