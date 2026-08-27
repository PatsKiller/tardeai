# Full Lifecycle Gap Register

## P0 — Safety / Data Integrity

1. **No recurring exit_time backfill** — ghost positions can re-accumulate if exit_reason is set but exit_time stays NULL
2. **Classifier gate at 0.0** — all strategies pass regardless of performance; burn-in with no auto-restore

## P1 — Operator Actionability

3. **No prospect-to-signal trace** — candidates are ephemeral, no persistent candidate_id
4. **No signal-to-research link** — enrichment data not linked to specific signals
5. **Proposal table has 29 duplicates** — same symbol/strategy submitted multiple times
6. **No per-proposal gate pass/fail breakdown** — operator can't see which gates blocked
7. **TCA timing fields mostly null** — order_submitted_at, order_filled_at, time_to_fill_seconds empty
8. **No broker stop proof panel** — can't verify broker has the stop the DB thinks it placed
9. **No backtest vs paper/live comparison** — strategies run without historical validation visible

## P2 — UX / Design

10. **82 frontend routes** — too many pages, no unified workspace
11. **Proposal pages scattered** — PaperProposals, ProposalAlerts, Approvals, ATM Control Room all show proposals differently
12. **Journal/Learning pages fragmented** — AutomatedTradeJournal, JournalHub, JournalReports, JournalAnalytics, WeeklyLearning
13. **No single-trade lifecycle inspector** across all pages
14. **Stop/trailing state not visible on most pages** — only ATM Control Room shows it

## P3 — Cleanup / Refactor

15. **api_v2.py is 1MB+ monolith** — 19,000+ lines, all endpoints in one file
16. **64 direct Telegram senders** — alert routing migration incomplete
17. **Agent RACI not enforced** — config-only, no code gates
18. **Strategy config split** — YAML + code define stops/trailing separately
