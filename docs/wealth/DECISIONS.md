# Wealth decisions log (append-only; times UTC, ET in parentheses)

- 20261114T2326Z — lead — Runbook adopted (docs/wealth/IMPLEMENTATION-RUNBOOK.md). No slice is APPROVED_FOR_WIRING; no operator approval has been received for any backend slice.
- 20261114T2326Z — lead — Preview publication PASSED on operator's live receipt; scope = preview only, not backend.
- 20261114T2326Z — lead — cc-deepseek-4 granted read-only GET on 127.0.0.1:7777 for /api/v2/{home/cio-card,market-risk/latest,overview,home/since-close}, ≤6 requests each, no other path, no writes — needed for Home BEFORE timing/bytes. Reason: same class of loopback reads already used by -6/-9; no broker call path.
- 20261114T2326Z — lead — Valuation: file cache = current value, ticker_snapshot_daily = history, under -6's four conditions (DECISION-valuation-store). P/E shown only with governed basis ("TTM (vendor-defined)", per-record cached_at).
- 20261114T2326Z — lead — cio@1 is a backend GET route (patch to opus-3, reviewer -9); not wired.
- 20261114T2328Z — operator via lead — ADMIN modal is REQUIRED PARITY for /wealth: connections & expiry (Schwab 7-day reauth lifecycle, Finviz/other cookie expiry alerts), allowlisted non-Bitwarden configuration, change history & diagnostics. New bounded slice admin@1; no frozen candidate expanded. n8n owns reminders/health/alert dedupe; existing cron/timers kept until parity proven.
- 20261114T2328Z — lead — Schwab: code states refresh tokens ~7 days, not renewable without manual browser OAuth; Wealth will never imply background renewal, never call token-health ?probe=1, never alter broker/order locks. Reauth handoff stays the sanctioned operator path.
