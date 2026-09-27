# ApprovalPackage@v1 — one consolidated approval per wave

```
Status:      ACTIVE (Wave 1 tranche 1 — SHADOW; emitted by scripts/lib/intelligence_client.py)
as_of:       2026-09-27T19:30:00-04:00
Measured at: cbf603526 (origin/main) / not measured at runtime yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); approval pkg-20260927-cogx-w1-d9e1
```

Append-only, hash-chained JSONL (`data/governance/approval_packages.jsonl`, `TRADEAI_APPROVAL_LEDGER_PATH`) written only by
`approval_package.Ledger`. Rows are events: PACKAGE_CREATED {package}, SUBMITTED {telegram}, DECIDED {item_no, state, decided_by, reason}, STATE, NOTE.
Each row carries `hash_prev` and `hash_self`; `Ledger.verify_chain()` checks the chain.

Package: package_id (pkg-YYYYMMDD-<wave>-<4hex>), campaign, wave, summary, created_at, expires_at (24 h), reviews {architecture, infrastructure, security: ref|MISSING},
binds {pr, sha}, items[], state (DRAFT · SUBMITTED · PARTIAL · APPROVED · EXECUTING · VALIDATED · DENIED · EXPIRED), telegram {message_ids, chat_id}, does_not_touch[].

Item: item_no, item_id, category (OPERATOR · SECURITY · INFRA · SOFTWARE · BUDGET — never broker), title, why, rule, reversible, rollback, depends_on[], scopes_needed[],
state (PENDING · APPROVED · DENIED · DEFERRED · EXPIRED · NEEDS_LOCAL · EXECUTED · VALIDATED · ROLLED_BACK), decided_by {who, from_id, via, message_id}, reason.
An item needing a remotely-forbidden guard scope (sudo, destructive, file-delete, frozen-v2, guard-config) is NEEDS_LOCAL from birth and is never approved remotely.

Typed reply grammar (recorded verbatim): `APPROVE <pkg> all|1,3,5` · `DENY <pkg> [items] ["reason"]` · `DEFER <pkg> <hours>h`.
Buttons: `pkgapprove:<pkg>[:items]` · `pkgdeny:<pkg>[:items]` · `pkgshow:<pkg>` — the sender's from_id must be in the operator allowlist
(`TRADEAI_OPERATOR_FROM_IDS`, else the allowed chat ids).
