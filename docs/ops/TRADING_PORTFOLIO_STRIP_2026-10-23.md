# Trading page portfolio strip restored (2026-10-23)

**Operator report (2026-10-23 08:54 ET):** "I'm missing my portfolio information on the top on
the trading page; it seems to work on the other pages."

**Cause.** Commit `adcaf5998` (2026-10-13, "page diligence") made the global header
(`apps/command-center-v3/src/components/MetricStrip.tsx`) hide PORTFOLIO, TODAY, TRADING,
REALIZED and REGIME behind a `▸ PORTFOLIO drawer` toggle on `/trading` and `/active-trader`
only. The drawer was closed by default (localStorage `cc_trading_metric_drawer_open`), so
those routes showed only the SETUPS and VIX tiles. The Trading hub redesign (#1949) did not
cause this; it only made the gap more visible.

**Fix.** The drawer is gone. The header is app-shell chrome and renders the same tiles on
every route. Phones (≤ 820 px) are unchanged: the compact line shows PORT and TODAY, and the
`▾` toggle opens the full strip, as it does on every other page. The stale localStorage key
is now ignored.

**Guard.** `apps/command-center-v3/e2e/trading-portfolio-strip.spec.ts` (hermetic; it stubs
every API call and fails on any non-GET request) checks:

- at 1440 px, all five tiles render on `/`, `/trading` and `/active-trader`, and the drawer
  toggle is absent;
- at 412 px, the compact line shows PORT and TODAY, expanding it shows PORTFOLIO, and the
  page does not scroll horizontally.

Against the old code the spec fails three times (`/trading`, `/active-trader`, phone). It runs
in `.github/workflows/cc-surface-agreement-ci.yml`.

Authority: READ_ONLY_ADVISORY presentation change. No API, broker, Telegram or DB effect.
