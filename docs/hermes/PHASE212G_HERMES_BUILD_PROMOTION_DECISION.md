# PHASE 212G — Hermes Build Promotion Decision (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T15:33:32-04:00
Measured at: efcc51365 / not measured

- **Promote newer Hermes: NO.** Reason: 0.16.0 is already the latest published build — there is nothing newer
  to promote. No upgrade can fix headless Codex today.
- Tests passed: version discovery (latest confirmed), alternative-command-shape tests (all fail).
- Rollback: N/A (no change made).
- Risk: none (no prod change; venv + ~/.hermes + OAuth + services untouched).
- **Operator approval required for promotion: NO** (no promotion to perform).
- Action: monitor for a future Hermes release > 0.16.0 with a headless/non-interactive Codex fix; re-run 212E then.
