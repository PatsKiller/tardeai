# Home — changelog

- 2026-10-27 OPERATOR-DIRECTED REMOVAL (no mockup required; the operator directed it): "Remove everything about the
  old train from the AGENTS.md, and from the Command Center and from the code." Changes on Home (`/v3/`, Do-now layout
  `HomeDoNow.tsx`; classic view `HomeHub.tsx`):
  - Removed: the release-train summary source (`/api/v2/coordination/release-train`), the "Deploy on main" drawer
    (`home-drawer-release`) and its "Deploy hold…" shortcut, the `DeployHoldStrip` / `ReleaseTrainCard` components.
  - Renamed / replaced: the System pulse tile "Deploy hold" is now **Deploys** — one status line from
    `GET /api/v2/ops/deploys` (latest `DeployOnMainReceipt@v1` outcome + main SHA, and the deploy STOP latch).
  - Kept (renamed): the STOP control. The drawer is now **Deploys** (`home-drawer-deploys`) with the shortcut
    **STOP deploys…** (`home-deploys-stop-shortcut`); the drawer body is `DeploysPanel` (latest + last five receipts,
    the set-only **STOP DEPLOYS** control, links to Ops → Controls, Releases & schedules and the Mergify dashboard).
  - Phone (412 / 390): the drawer still opens a full-screen sheet with ← Back; checked in
    `apps/command-center-v3/e2e/deploys-train-removal.spec.ts` and `e2e/home-do-now.spec.ts` at 1440 / 412 / 390.
