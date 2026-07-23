# /v3-next Route & Bundle Report — Stage 6

- Separate app: `apps/command-center-v3-next` with its own package.json, tsconfig, vite config.
- Route base: `/v3-next/` (vite `base`), router basename `/v3-next`. `/v3` (base `/v3/`) untouched
  (0 changed files under apps/command-center-v3).
- Dev server: 127.0.0.1:7790 (loopback), distinct from /v3 dev (7789). Proxies `/api/v3` to the
  Stage 4 read API at 127.0.0.1:8134 (which is itself manual/off by default) — but Stage 6 runs
  entirely on fixtures, so no server is required.
- Build: `tsc && vite build` → `dist/` (gitignored). Verified: 35 modules, ~177 kB JS, built OK.
- Not mounted into the production portfolio server; not a systemd unit; no reverse-proxy change.
