# /v3-next Architecture — Stage 6

```text
apps/command-center-v3          apps/command-center-v3-next   (NEW, separate)
  served at /v3 (UNCHANGED)       base '/v3-next/', dev :7790 (loopback)
                                   consumes Stage 4 read contract via src/fixtures/readApi.ts
                                   (real API is manual/off; proxy /api/v3 -> 127.0.0.1:8134)
```
- React 18 + Router 6 + Vite 5 (mirrors /v3 stack; no new framework).
- `App.tsx` BrowserRouter basename `/v3-next`; classic/next nav is a plain link to `/v3/`
  (navigation, not a client-side replacement) + a router link to next.
- `src/panels/panels.tsx`: all 18 panels; `ReadOnlyAction` renders disabled buttons only;
  `Unavailable` renders explicit unavailable markers; `Warnings` renders typed warning lists.
- `src/fixtures/readApi.ts`: deterministic envelopes mirroring the Stage 4 schema
  (api_version/service/environment/sources/freshness/warnings/data); MOOMOO_STATUS carries
  the three blocked badges and live_badge=false.
- Build output `dist/` and `node_modules/` are gitignored; only source is tracked.
