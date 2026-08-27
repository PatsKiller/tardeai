# R6 — Append-Only Governance Store

In-process JSONL hash-chain for trial-registry events and decision-use records.

- Append only. Rewrite / truncate / delete of a committed file is a hard fail.
- Each record carries `prev_hash` + HMAC via R1 `ReceiptAuthority`.
- Tampering any line breaks `verify_chain()`.
- Load reconstitutes a `TrialRegistry` / `DecisionUseLedger` for dry replay.
- Not a production database. No network. No broker. No Telegram.

Authority: `READ_ONLY_ADVISORY`. Module: `scripts/lib/research_governance/durable_store.py`
