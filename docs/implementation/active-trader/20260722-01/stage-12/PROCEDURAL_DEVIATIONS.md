# Stage 12 — Procedural Deviations (disclosed, not hidden)

## D1 — Stages 6–11 controller start SHA (5c8bc5af vs pinned 69285d4e)
The Stages 6–11 controller started at `5c8bc5af` ("Stage 5 Moomoo device-auth tooling (telnet
method)"), exactly one commit ahead of the originally-pinned `69285d4e` ("Stage 5 drive manifest,
17/17 hash-verified"), because additive Stage 5 device-auth work advanced the branch.
- **Disclosed in-repo:** `STAGES_06_TO_11_DRIVE_MANIFEST.json` (start_head 5c8bc5af),
  `STAGES_06_TO_11_COMMIT_MANIFEST.md` ("one ahead of launcher's 69285d4e, explained"),
  `stage-06-plan.md`, `stage-06-changes.txt`.
- **Scope of the intervening commit:** additive device-auth tooling only. No production boundary,
  DB target, flag default, or live authority expanded.
- **Classification (reviewer):** VISIBLE and BENIGN; owner-accepted retroactively.

## D2 — Stage 5 agreement/smoke premise change (superseded prior controller)
The first Stage 12/13 controller assumed the Moomoo agreement was still pending. Between drafting
and execution the operator completed the agreement and the data-only smoke passed (commit
`fb46d4bd`). That controller was halted and reported (correct per its own §3 gate); the owner
re-issued the Corrected v1.1 controller with accurate facts. Section A of v1.1 recorded the
current state additively without rewriting history (see `stage-05/STAGE5_POST_AGREEMENT_DATA_SMOKE_ADDENDUM.md`).

## D3 — Litmus verdict precision on "no real 2FA" (challenge L, CONCERN)
The reviewer flagged that the literal invariant "no real 2FA anywhere" is imprecise:
`moomoo/device_auth.py` performs a real one-time Moomoo SMS device-verification (`input_phone_verify_code`)
for OpenD **data-gateway device** trust. This confers NO trade/order authority (0 AST trade findings;
LIVE order auth is a separate, inactive, hash-bound session mechanism explicitly not-2FA).
- **Classification:** wording precision, not a boundary breach. Recommended restatement:
  "no real *order/trade* 2FA is wired; the only real 2FA is one-time operator-present data-gateway
  device authorization." Non-blocking; tracked as a documentation-precision item.

## Concurrent production incident work (separate, disclosed)
During this session the operator also directed unrelated production incident fixes in the PRODUCTION
checkout (watchlist connection resilience, Ollama `MAX_LOADED_MODELS=3`, escalation guard). Those are
NOT part of this branch and did not touch the worktree; the worktree precheck confirmed HEAD/clean.
Recorded here only for full disclosure of session activity.
