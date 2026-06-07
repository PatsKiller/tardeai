# PHASE 213E — Hermes Update Monitor Plan (2026-06-07)
`scripts/check_hermes_update_available.py` — READ-ONLY. Compares installed hermes-agent vs published pip
versions; writes `data/runtime/hermes_update_status.json`; if a newer build exists, flags
`codex_headless_retest_recommended` + marks the chatgpt capability `retest_recommended` (quietly). **Never
auto-upgrades.** No alert storm when nothing is new.

Verified now: installed 0.16.0, no newer → "Hermes is up to date; no action."

## Schedule (PLAN ONLY — not enabled without operator approval)
Weekly, read-only: a systemd user timer `hermes-update-check.timer` (OnCalendar weekly) → oneshot service
running the checker. Not created/enabled in this phase. When a newer build appears, the operator re-runs
PHASE212E (one command); the chatgpt lane auto-recovers if the headless fix lands.
