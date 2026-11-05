# Releases & Schedules — changelog

- 2026-10-27 OPERATOR-DIRECTED REMOVAL (no mockup required; the operator directed it): "Remove everything about the
  old train from the AGENTS.md, and from the Command Center and from the code." Changes on
  `/v3/system/releases` (`ReleasesSchedules.tsx`):
  - Removed: the **Release train** tab label, the "Next windows" panel (`rs-windows`), the "Queue · what rides next"
    panel with the PR census (`rs-queue`, `rs-census-alert`), the "Next train window" KPI (`rs-kpi-next_window`).
  - Renamed: the default tab is now **Deploys** (`rs-tab-deploys`): serving pin, main HEAD with exact-SHA CI, release
    history and release errors — unchanged content. The n8n & schedules and Jobs tabs are unchanged.
  - Moved: open PRs waiting to merge are on the Mergify dashboard (linked from Home → Deploys).
  - The page stays read-only. Checked in `apps/command-center-v3/e2e/deploys-train-removal.spec.ts` at 1440 / 412 / 390.
