# R14A — Source-to-live closeout

**Date:** 2026-08-25  
**Authority:** READ_ONLY_ADVISORY · MEMORY_BEHAVIOR_INFLUENCE=0

Merged PR #506 onto protected main (`4d0859a5`). Exact-main prepare/promote succeeded. CURRENT SHA equals origin/main. Hybrid feature-branch deploy did **not** occur.

First **natural** `tradeai-cio-material-scan.timer` after promote (13:26:07Z, not `systemctl start`) ran the new scanner: `auditable_result=NOTIFICATION_SUPPRESSED`, `policy_status=POLICY_GAP`, `situation_classes=[POLICY_GAP]`, default 20–25% band flagged `masquerades_as_operator_policy=true`. Canary remains off. Same-brain live `consistent=true`, `telegram_fork=false`.

Maturity **76 → 80**. Not 82+: canary not enabled; no live advisory delivery.

Rollback: `bash scripts/cio_phase2_exact_main_deploy.sh rollback` → `1afb1479-main-exact-phase2-20260824-230917`.
