# WP-29 item b: account-name chips in the Home do-now queue

Status: DRAFT source candidate, runtime acceptance NOT_MEASURED
as_of: 2026-10-24T03:09:00Z
Measured at: main 8ed8a2464; task DSN-20261023-handoff-v3-P6-T292

The HomeDoNow projection already includes scoped account keys and human labels in each item's evidence. The frontend discarded these fields, so account information was buried in prose and absent from the queue's structured display.

The UI model now carries those existing account references and renders the shared AccountChip component beside each applicable item. It deduplicates identical references, preserves account-name aliases, suppresses number-like keys and masked digits, and shows safe server labels when a key is absent. An item without account evidence gets no inferred account chip. The chip list belongs to the actual item's evidence, including only the accounts the producer identified.

Queue order, risk amounts, source freshness, filters and action links retain their existing meanings. The change touches no backend risk, broker, order, stop, policy or account-name configuration code.

## Verification

- 54 pure UI model checks pass, including names-only privacy, duplicate references, missing evidence and preserved action/risk values.
- Full npm build, TypeScript and UI standards pass using a copied dependency tree with a byte-identical lockfile. The existing Vite large-chunk advisory is nonblocking.
- Five fixture Playwright tests pass, including the new desktop1440/phone412 account-chip, width and action checks; all API routes are fulfilled locally. Fixtures pin the clock. One stale assertion expecting "Ira" was corrected to the existing canonical "IRA" name.
- Screenshots: [desktop](packets/home-account-chips-20261023/do-now-accounts-1440.png), [phone](packets/home-account-chips-20261023/do-now-accounts-412.png).

Durable raw logs: `/home/johnclaw/.cache/rtc/codex-wp29b-20261023/{model.log,frontend-build.log,browser.log}`. The browser uses an isolated static fixture server without a live proxy; it is stopped when the test completes. No production requests or writes occurred.

This worker queues publication only. Exact-head remote checks, coordinator merge/release and served-UI acceptance remain separate evidence.
