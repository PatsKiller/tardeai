# /v3 ↔ /v3-next Parity Baseline — Stage 6

Parity state: **BASELINE_ONLY**. /v3-next now exists as a separate bundle but no UI parity is
claimed: /v3 remains the authoritative operator surface, /v3-next is read-only on fixtures.
The Stage 1 `active_trader_parity_checks` table + Stage 4 `/parity` endpoint are the machinery
for later comparison (quote/candidate/session/account/order/position/P&L/risk/authorization-hash/
kill-switch/journal-count). Cross-surface parity measurement begins only when /v3-next reads the
same live server-side truth as /v3 (post-Stage-5 data + a later authorized step) — at which point
a parity mismatch must block live activation from the new surface. Nothing here changes /v3.
