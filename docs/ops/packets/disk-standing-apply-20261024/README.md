# Disabled source package and operator review packet

Design-Task: DSN-20261024-disk-standing-apply-P1-T1

No script here performs host cleanup, imports or activates live n8n workflows, or changes host schedules. The operator-only promotion helper can change source configuration in an isolated review worktree after exact approval/digest. `rules.preview.json` is a copy of base rules with **disabled, pending-approval** standing metadata. `standing-apply.proposed.json` is the additive section; `admission.proposed.json` records the native schedule, new command/closure, draft contract, routes and acceptance changes; `activation-diff.json` is an inert operator-only change description. The four configuration scopes were legitimately handed off and source staging is integrated. The fresh accepted-main source union retains frozen C1 unscheduled proposal metadata. Current exact pins must be regenerated if any later integration changes configuration bytes. Never treat the old plan-only reviewed contract as approval of deletion.

After legitimate scope handoff and operator approval review, the operator's first real preview (not executed by this worker) is:

```bash
cd /home/johnclaw/wt-codex-disk-standing-ci-fix-20261024
python3 scripts/disk_hygiene.py --standing --dry-run --report --rules docs/ops/packets/disk-standing-apply-20261024/rules.preview.json
```

This command is read-only but performs real cron/unit/proc/coordination/GitHub GET collection. The earlier agent crontab refusal remains binding: agents must use authorized captured/offline fixtures, not run this host preview. The operator reviews and quotes its complete output before any activation/first cleanup. A missing/refused GitHub, cron, process or coordination source holds the run. Do not replace it with an empty/stale capture.

`activate_reviewed.py` is an operator-only SOURCE promotion packet; default mode writes nothing. It requires the operator-reviewed SHA of the exact current source-config pins document, its exact rules SHA, and the exact draft contract digest and a direct review file with decision `APPROVE_DISK_STANDING_APPLY`, actual approved_by and an aware approved_at. `review.required.json` is pending and cannot write. It promotes schedule, no-retry policy, reviewed contract (preserving original plan review), argv and enabled flag together. It never imports n8n, changes host schedules or runs cleanup. Its file writes are not a multi-file filesystem transaction: use only an isolated, stopped source review worktree, run gates, then publish one coordinator release.

Once the operator has supplied the real review file at the following path, preview the exact source promotion:

```bash
python3 docs/ops/packets/disk-standing-apply-20261024/activate_reviewed.py --review-file /home/johnclaw/.cache/rtc/codex-disk-standing-apply-20261024/operator-review.json
```

The explicit source write additionally requires `--write --plan-sha256` with the exact digest printed by that preview. There is no valid final digest until operator review and union pins exist, so this worker supplies no invented approval/digest or live apply command. Manual per-run grant behavior remains available. No generic grant or credential value is supplied.

`verification.json` records test commands/results and source/proposal digests. Source acceptance is local; CI, deployment, first native run, actual cleanup and operator notification delivery remain unproven.
