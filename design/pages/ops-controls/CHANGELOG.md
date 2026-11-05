# Ops Controls — changelog

- 2026-10-27 OPERATOR-DIRECTED REMOVAL (no mockup required; the operator directed it): "Remove everything about the
  old train from the AGENTS.md, and from the Command Center and from the code." Changes on
  `/v3/system/ops-controls?tab=jobs` (`OpsControls.tsx`):
  - Removed: the **Pause** button (`release_train.pause`), Run now (`release_train.run_now`, already hidden), and the
    arm / scope / revoke kinds from the server's kind list.
  - Renamed: the panel "Deploy hold & kill switch" is now **Deploys & kill switch**; the row "Deploy hold" is
    **Deploys** with **STOP** (`deploy.stop`, one click) and **Resume (passkey)** (`deploy.resume`).
  - Checked in `apps/command-center-v3/e2e/deploys-train-removal.spec.ts` at 1440 / 412 / 390.
