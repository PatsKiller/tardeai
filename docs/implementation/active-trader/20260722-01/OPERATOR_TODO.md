# Active Trader — Operator TODO (after Stage 0)

**Run ID:** 20260722-01 · **Date:** 2026-07-22

---

## CURRENT STATE (updated 2026-07-23 — Corrected Stage 12/13 v1.1 §A)

Moomoo credential/agreement gate is **CLEARED**; data-only smoke **PASSED**. Items A.1–A.5 below
(Stage-1 prerequisites) are historical and were satisfied during Stages 1–5. The **open** operator
actions now are:

1. **Run the five-RTH observation** (0 of 5). Requires: (a) the Stage 5 observation launcher to be
   built + checked in (not yet present — see `STAGE5_RESUME_REQUIREMENTS.md`), then (b) ≥30-min
   continuous open-RTH capture, then (c) five qualifying sessions. This is the hard gate for Stage 9
   acceptance / Stage 10 promotion.
2. **BF-1** (item 6 below) — still required before any Moomoo live canary (Stage 14).
3. **Stage 14** — needs a separate exact-SHA owner authorization; do not merge PR #150.

The A–D sections below are **retained as history** and reflect the state after Stage 0.

---


## A. Required before Stage 1 can start
1. **Decide the wedged production checkout.** `config/hermes_score_weights.yaml` and
   `scripts/watchlist_entry_planner.py` sit in an unresolved UU index state (no MERGE_HEAD) in
   `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`. Stage 0 deliberately did not touch
   them. Resolve manually (choose ours/theirs per file), then optionally `git pull --ff-only`
   to bring local main to 87c2fa09. Stages 1-13 can run entirely in the worktree either way.
2. **Provision a test database** (none exists): e.g. `createdb trade_ai_test` with role
   `trade_ai_lab`, and record the DSN as a lab secret. Required for Stage 1 migration
   forward/rollback proof.
3. **Create Bitwarden `trade-ai-lab` project** + lab machine account (read/write to lab only),
   store its token at `~/.openclaw/credentials/bws_lab_token` (never in SM). Then Stage 1 may
   create `UNSET__OPERATOR_REQUIRED` placeholders.
4. **Gmail send path decision** for night-run emails: either (a) authorize use of existing
   `gog gmail send` (account john@jwwhiting.com — already proven by `email_notifier.py`), or
   (b) provision a dedicated Gmail API credential with minimum send scope and record
   `GMAIL_NOTIFICATION_CREDENTIAL_SLOT` + `GMAIL_SEND_AS`. The connected claude.ai Gmail
   integration can only create drafts, not send — insufficient alone for §16K.10 preflight.
5. **Confirm** `OPERATOR_NOTIFICATION_EMAIL=john@jwwhiting.com` and
   `ACTIVE_TRADER_DRIVE_FOLDER_ID=1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR` (Trade_AI_Docs_v2).

## B. Architecture-owner decisions raised by the litmus review (CONDITIONAL_PASS)
6. **BF-1 (blocks Stage 14 only):** obtain broker documentation + (later) runtime probe proof of
   whether Moomoo supports broker-resident, disconnect-surviving protective stops for US equities.
   If not, per §16.8/ADR-015 Moomoo live scalp stays disabled and the canary broker choice must be revisited.
7. **BF-2 (must be resolved in Stage 5/10 design):** approve a dual-ceiling rate-governor spec —
   separately enforced place (15/30s) and modify (20/30s) budgets with explicit emergency reserve
   carve-outs — before simulation acceptance.
8. Reconcile the canonical litmus-reviewer schema (§16J.3 vs prompt v1.0) before Stage 12.
9. Decide tastytrade scope (adapter exists in repo but is outside the v3.3 broker plane).
10. Add AGENTS.md at repo root (or amend program §0 step 2) — currently a mandated input that does not exist.
11. Verify the FINRA/PDT intraday-margin citation independently before any account-rule logic depends on it.

## C. Operational hygiene noted during Stage 0 (not blocking)
12. `pilot_caps.MAX_PILOT_ORDERS_TOTAL=9999` vs docstring "cap 5" — confirm intended value.
13. `canary_gate.GATES_REMOVED=True` — confirm this remains the intended standing posture.
14. OPERATIONS.md documents user-scoped `portfolio-server.service`; live host runs system-scoped
    `tradeai-portfolio-server.service` — align docs or units.
15. `.env DEFAULT_PAPER_ACCOUNT=alpaca_paper` vs yaml/example `tradeai_automated` — confirm.
16. `config/snaptrade_accounts.json` referenced but absent — confirm runtime-generated.
17. pgvector is not installed although the KB/embedding design assumes it — plan install in the
    upgrade lab (P1/P2), not in place.
18. Future-dated migration filenames (2026_07_23..26) exist at the 2026-07-22 commit — cosmetic; consider renaming policy.

## D. Stage 1 start
Re-issue the authorization prompt for STAGE 1 against branch `feat/active-trader-next`
(Stage 0 commit recorded in the closeout). Item A.1-A.3 must be complete for Stage 1's
migration-rollback and placeholder work; A.4-A.5 may land any time before Stage 11.
