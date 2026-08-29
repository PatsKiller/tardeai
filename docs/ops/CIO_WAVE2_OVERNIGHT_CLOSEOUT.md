# CIO Wave 2 — overnight closeout (Claude Code, 2026-08-28 → 08-29)

**READOUT for Grok, 08:00 EDT.** Everything below is recomputed from the live
surfaces by `scripts/cio_wave2_census.py`, not copied from a prior scoreboard.

```
pin                 53794d82   (#623, promoted 2026-08-29T03:06:57Z)
endpoints           /api/v2/health 200 · /v3/cio 200 · /api/v3/cio/home 200
held_n ex-dust      15         (19 incl dust; dust JEPI LDOS SCHG SRNE)
with_plan           11         definition below
SCHG                DUST_RESIDUAL → EXITED on Surface A. Never a hold.
PRIM                CURRENT in NEW_POSITION_IF (NKE PFSI PRIM SH XLU)
telegram_sent       false
fires_s7            false      (watch READY 0, BLOCK 26)
MBI                 0          INTERDICT 0 (left as found)
next PENDING item   42  (safety close: C3/C5/rebalancer verifications)
```

**`with_plan` definition:** distinct **non-dust held** tickers carrying at least
one **open S1/S3/S5/S6** plan, counted over the **whole open-plan store** (562
open plans), not the 12-row CIO NOW window. It read **1** before slice 12b.

---

## Shipped tonight

| PR | sha | slices |
|---|---|---|
| [#621](https://github.com/PatsKiller/tardeai/pull/621) | `5f215504` | 12 · 12a · 12b · 12c · 13 · 14 · 15 · 16 · 17 · 18 |
| [#622](https://github.com/PatsKiller/tardeai/pull/622) | `c3c7b966` | 19 · 20 · 21 · 22–31 · 12a live-activation fix · 2 authorised applies |
| [#623](https://github.com/PatsKiller/tardeai/pull/623) | `53794d82` | 32 · 33 · 34 · 35 · 36 · 37 · 38 · 39 · 40 · 41 |

Three exact-main promotes, each verified against the live payload. **199 new
behavioral tests.** Local acceptance green on every PR; CI green on all three.

## The seven findings worth your time

1. **A green promote is not a live promote.** #621 merged clean, 10/10 CI green,
   promote passed health/cio 200 — and `/v3/cio/home` still served `held_n=19`
   with SCHG counted as a hold. The operator product prefers a persisted brief
   and only recomputed when `held_n` was missing, which a *pre-12a* block
   satisfies. Fixed in #622. **The live payload is the check, not the merge commit.**

2. **Two writers publish a cash total and they disagree by \$52,677.32.**
   Position rows \$630,784.82 vs `portfolio_totals.total_cash` \$578,107.50. Both
   were already on the product with their own consumers — the morning brief
   printed one, `temperament.cash` the other. Detected and both printed; **not
   merged, not averaged.** `total_mv_excluded` matches the row sum exactly, so
   `total_cash` is the likely culprit — your call.

3. **57% of the last 7 days of research failure is the cost cap**, and 114 of
   those arrive as HTTP 500 `RESERVATION_FAILED` whose *message* is
   `COST_CAP_EXCEEDED: daily request cap`. Classifying on the response code would
   file them as provider errors and send someone to debug a healthy bridge.
   `worker_bug_n` is **0**; only 5 of 230 failures are retryable at all.

4. **C2 was admitting a TRIM of dust.** `position_truth` only asks shares > 0, and
   SCHG's 0.2294 is > 0 — so "TRIM SCHG" passed the gate: an advisory to trim
   \$8.09 of an exited name. Now blocked `dust_residual_not_a_position`. AVOID on
   an unheld name stays admissible; nothing was loosened.

5. **The S6 detector has not learned the dust rule.** You authorised cancelling 20
   orphan S6 plans — CASH 1, QCOM 1, **SRNE 18**. Eighteen, because the detector
   had been re-firing on a \$0.90 residual. A new SRNE S6 plan **reappeared within
   ~20 minutes** and is visible right now as `graph_impact.skipped: ['SRNE']`.
   Cancelling was the authorised action; teaching the detector is a separate
   change and was **not** made tonight.

6. **Positions are 3 days old under a reprice from 64.8h later.** `as_of`
   2026-08-26, `generated_at` 2026-08-28 16:45 ET. Staleness is now measured on
   the position date — a fresh reprice over stale positions is still stale.
   Live state: `DATA_STALE`.

7. **complete→checkpoint is UNCOMPUTABLE, not 0%.** 523 checkpoints carry no
   `plan_id`; research keys on one. The ends do not join. The count also exposes
   **148 checkpoints bound to CASH** and 50 to dust, from a different binder —
   reported, not rewritten.

## Operator-authorised writes (only these)

| action | dry | applied | notes |
|---|---|---|---|
| research attach | would_attach **2** | **2** | `plan_5463afc7bc04`, `plan_9f4df5b991f3`, both `critique: VALID`. The 474 untouched. CASE_SUMMARY stayed **328** — dedup refused a second mint. |
| orphan S6 cancel | 20 | **20** | CASH 1 · QCOM 1 · SRNE 18. `notify: false`. Append-only: `cio_plans.jsonl` 4,958 → 4,998 lines. |

Backups of `cio_plans.jsonl` were taken before each apply. **No history deleted,
no lot deleted, no identity minted, no cap raised, no `--backend live`.**

## Scoreboard vs census

`scripts/cio_wave2_census.py --json` recomputes every scoreboard number from the
live surfaces in one read-only pass. `docs/ops/CIO_WAVE2_CENSUS_2026-08-28.json`
is tonight's run at pin `53794d82`. The card and the census agree; the only
labelled gap is `with_case_summary` (product cap 10 vs store 328), which the card
now names.

## DRIVE = OK (operator-run); agent upload FAIL

`gog` is installed and holds a token for the operator, but its keyring is the
file backend and needs `GOG_KEYRING_PASSWORD`, which is not available in a
non-TTY session. The Bitwarden vault is locked with no session. Not attempted
further — a master password must not pass through the agent.

To mirror it yourself:

```bash
export BW_SESSION=$(bw unlock --raw)
GOG_KEYRING_PASSWORD="$(bw get password gog-keyring)" \
  gog drive upload docs/ops/CIO_WAVE2_SCOREBOARD.md \
  --replace 1kNRoyK_Tq8FNUMxrwjNDRB2AZCqnxj0P -a john@jwwhiting.com
```

**Settled 2026-08-29:** the md blob is `1kNRoyK_Tq8FNUMxrwjNDRB2AZCqnxjOP` —
capital **O**. The overnight prompt's zero returns `404 File not found`. The
scoreboard JSON is authoritative and has been corrected.

Also corrected: `1W04_1pATgfewyf8gp-WVIo8cqc26c4WQ` is the **scoreboard** JSON
mirror (its Drive name is `CIO_WAVE2_SCOREBOARD.json`), not a census blob. The
census has no blob yet; `--parent 1rRSmvAeO37z2PyyrIYtd2C5ngwHsAIqH` would mint one.

The operator ran the upload manually with the keyring password from Bitwarden
(item *TradeAI gog keyring password*); the agent never handled it.

## One more finding, from CI

The repo's own `check_dark_contracts.py` **failed PR #624** on
`CIOWave2Census@v1` — a new versioned contract with no consumer. It was right:
the census is an operator CLI, so its consumer is a person, not a code path.
Declared via `NO_CONSUMER_REASON`.

The lesson is the *timing*. That guard is a separate step in the `cio-hardening`
CI job and was **not** in `scripts/ai_local_acceptance.sh`, so local acceptance
went green while CI failed — a remote cycle spent on something provable locally
in 1.5 seconds. The guard is now mirrored in local acceptance, so this class of
failure cannot be remote-only again.

## Rails — all held

| Rail | State |
|---|---|
| Authority | READ_ONLY_ADVISORY on every payload |
| MBI | 0 |
| INTERDICT | 0, left as found |
| Broker write | none |
| Telegram producer | none added since #611 (verified by log over the path) |
| notify | never enabled; `telegram_sent` false |
| ROTATE-as-action | not built |
| Reentry books | still two functions, still unmerged |
| AGENT_COMMITMENT | not admitted as policy |
| cio_run LLM | untouched; DETERMINISTIC_PRODUCT |
| Stop-management / quote-time / 2FA | untouched |
| ticker_prices history | untouched |
| SCHG | EXITED, never re-treated as a hold |
| FANG | UNAVAILABLE, no invented thesis |
| Lot deletion | none |

## Leftovers — POLICY ONLY, nothing implemented

* ~~Teach the S6 detector the dust rule~~ — **DONE**, authorised and shipped
  after this closeout was first written. See
  `docs/ops/CIO_S6_DUST_RULE_2026-08-29.md`. The root cause was the *disposition*
  branch, not concentration: a $0.90 residual reads as a 100% loss held 36
  months, clearing the 20% / 6-month thresholds on every pass — which is exactly
  why cancelling could never hold. Thresholds untouched; SCHD still fires.
* Reconcile the \$52,677.32 cash disagreement at the writer (detection only tonight).
* Give checkpoints a `plan_id` so the complete→checkpoint rate becomes computable.
* Re-home the 148 CASH-bound and 50 dust-bound historical checkpoints.
* notify-on · ROTATE-as-action · merge the books · gate the rebalance cron ·
  C3 history scrub · council types · AGENT_COMMITMENT · MBI > 0 — all still
  forbidden and all still untouched.

## Stop

Wave 2 slices 12–41 complete and promoted. Slices 42–50 are verifications and
the census, in this PR. **Wave 3 not started.** The LLM-gate / cadence / corpus
prompt and Wave 2C items 101–320 are queued behind this and were not begun.


---

# Wave 2C addendum — items 101–320 complete

`184 DONE · 9 FIXED · 1 open (118, cost-basis as_of)` across six batches.
CURRENT `a1e05eab`+; all five endpoints 200.

## What the audit actually found

Verification was supposed to be a formality. Six items were not.

| # | finding |
|---|---|
| 116/117 | slice 12c's cap-5 had been **dried and never applied** — five held names had no S1 at all. Applied; coverage is now complete. |
| 198-adjacent | **S1 had the same dust disease as S6**, through `deep_drawdown_from_basis` instead of the disposition branch. 35 plans on JEPI/SRNE/LDOS. Fixing S6 alone would have left the larger leak open. |
| 131/132/160 | the two re-entry books were **separate but anonymous** — canonical labels existed, neither reached `/home`, and the CC named only Surface A. |
| 236 | the memory **jailbreak scan missed the four most canonical phrasings**, including `ignore all previous instructions`. Wordier variants were caught, so the guard looked functional. |
| 186/302 | two execution-language gates with **disjoint vocabularies**; `execute the buy` passed both. |
| 41 | **C2 admitted a TRIM of dust** — an advisory to trim $8.09 of an exited name. |

Four of those six are the same underlying shape: **a rigid pattern that looks
like a guard**. `ignore all previous instructions` fails a one-qualifier regex;
`execute the buy` fails an exact-adjacency regex; a $0.90 residual is
permanently ~100% down so a ratio branch fires forever. Each looked correct in
review and each had a blind spot that only showed under a concrete example.

## Where I was wrong

Four times a local check produced something that looked like a finding and was
not. Three I caught before writing them down; the fourth CI caught.

1. `collect_previously_traded()` queries **Postgres**, not the data root — from
   a shell it returns `[]`, making AXTI/FATN read `UNAVAILABLE` against an
   `EXITED` baseline.
2. `admit_status` takes `memory_type` positionally; I passed a dict, so the
   forbidden-field guard never saw the subject and looked broken.
3. A **timezone boundary three hours off** made 109 historical duplicate S1
   plans look like a live guard failure.
4. I converted a **CRLF file to LF** — 1010 churn lines for a 16-line edit,
   exactly what `safe_text_edit` exists to prevent. CI caught it; I had checked
   line endings on an earlier file and not on this one.

The line-ending guard and the dark-contract guard were both **CI-only steps**.
Both now run in `ai_local_acceptance.sh`, so neither class can be remote-only
again.

## Open questions for the operator — none actioned

1. **Advisory verbs as execution language** — `trim the position` / `sell half`
   pass both gates. Widening rejects real research; leaving it admits imperative
   phrasing.
2. **109 historical duplicate S1** on held names (pre-#609 backlog).
3. **19 `DIVI` S1** flagged `not_held` — likely a bad-symbol variant of `DIV`.
4. **`plan_a18173fb8235`** — an accepted S0 carrying `TEST`.
5. **$52,677.32 cash disagreement** — detected, deliberately not reconciled.
6. **148 CASH-bound and 50 dust-bound historical checkpoints.**
7. **Item 118** — cost-basis `as_of` on the coverage card, the one item left open.

## Still not started

Wave 3, the LLM-gate / cadence / corpus prompt, notify-on, ROTATE-as-action,
book merging, gating the rebalance cron, C3 history scrub, council types,
AGENT_COMMITMENT, MBI > 0.
