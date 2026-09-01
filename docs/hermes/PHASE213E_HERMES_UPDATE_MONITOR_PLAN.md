# PHASE 213E — Hermes Update Monitor Plan (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T16:47:53-04:00
Measured at: efcc51365 / not measured

`scripts/check_hermes_update_available.py` — READ-ONLY. Compares installed hermes-agent vs published pip
versions; writes `data/runtime/hermes_update_status.json`; if a newer build exists, flags
`codex_headless_retest_recommended` + marks the chatgpt capability `retest_recommended` (quietly). **Never
auto-upgrades.** No alert storm when nothing is new.

Verified now: installed 0.16.0, no newer → "Hermes is up to date; no action."

## Schedule — ENABLED (operator-approved 2026-06-07)
Weekly, read-only: systemd user `hermes-update-check.timer` (OnCalendar=Mon 03:00, Persistent, RandomizedDelaySec=600)
→ oneshot `hermes-update-check.service` running the checker. **enabled=enabled, active=active**; next run Mon 2026-06-08 03:02; first run success. Units in ~/.config/systemd/user (untracked, per convention). Operate: `systemctl --user status|disable hermes-update-check.timer`. When a newer build appears, the operator re-runs
PHASE212E (one command); the chatgpt lane auto-recovers if the headless fix lands.
