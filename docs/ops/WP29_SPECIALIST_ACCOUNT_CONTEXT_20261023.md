# WP-29 item d: grounded account location in specialist context

Status: DRAFT source candidate; historical tax cards unchanged
as_of: 2026-10-24T03:13:02.555763+00:00
Measured at: main 325ff34f2; task DSN-20261023-handoff-v3-P6-T294

The specialist context read only the first matching holding and printed `account_name` directly from it, defaulting to `?`. It did not use the shared account-name registry. Missing or stale labels could leave a tax narrative treating a taxable holding as an IRA.

`account_display.location_facts` now returns the shared human name, declared account type, metadata status and source. The existing context builder puts every matching held account into `position_accounts`, uses the same metadata in its first-position snapshot and human prompt, and separates current held-account facts from a strategy card's suggested account fit. Unknown types remain unknown and proposed metadata keeps its proposed status. Number-like or masked account identifiers are omitted from the position snapshot.

No tax-treatment inference comes from the ticker, older research or a friendly label. The added facts use existing holdings and registry readers; no new store, writer, financial rule, provider, sizing, broker, order or stop behavior is added. Existing position amounts, prices and risk context retain their existing meanings. The original holdings file is not changed.

## Verification

**77 tests passed**, including the actual context builder with scratch holdings and a SELECT-only injected cursor, the shared account library, number grounding, worker scheduling/retry compatibility and the canonical CI-gate registry. The five new regressions cover a moomoo taxable holding with a stale IRA label, multiple held accounts, unknown/numbered identifiers, no holding and unconfirmed registry metadata. Ruff and compilation checks passed.

Evidence: `/home/johnclaw/.cache/rtc/codex-wp29d-20261023/final-regression.log`. Fixtures execute no model, provider, credential or production database call. No financial recommendation was generated or sent.

Historical stored narratives still need an authorized future regeneration before their text can be claimed corrected. Operator account-name confirmations and actual source freshness remain independent evidence. Publication, exact-head remote checks, coordinator merge/release and live acceptance are pending.
