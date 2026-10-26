## Remote approval by Telegram — RETIRED (23.0.0)

**Status: RETIRED under AGENTS.md 23.0.0 (ACTIVE).** Telegram
may never issue a guard grant. Code: `scripts/lib/guard_remote_approval.py`
`TELEGRAM_REMOTE_GRANT_STATUS = "RETIRED"`.

- **Mint refuses.** `mint_request` and `scripts/guard_request_approval.py` raise / exit 2 with the
  retirement message. No PENDING remote request is created.
- **Approve refuses.** `/approve <CODE>` and Telegram Approve buttons return `TELEGRAM_GRANT_RETIRED`
  and grant nothing. Deny may still settle a stale prompt.
- **Keyboard and Ops stay.** `bin/guard grant` / `bin/guard request` at the host, and Ops → Controls
  (passkey), remain. Agents still never type, pipe, simulate, automate, or infer the confirmation
  word.
- **Train publication needs no grant.** Queue the PR → Ops → Controls approve (passkey) → next train
  window or Run now (`release_train.run_now`). Do not ask for `git-push` or `release-write` over
  Telegram for train work.

HISTORICAL (pre-23.0.0): this section described how `/approve <CODE>` and Approve buttons moved the
*typing* of APPROVE to Telegram without moving the *deciding*. That path is closed. Do not re-enable
without a new MAJOR amendment. Legacy store mechanics remain testable under
`TELEGRAM_REMOTE_GRANT_STATUS = "LEGACY_TEST"` (tests only). Pins:
`tests/test_guard_remote_approval.py`, `tests/test_agents_policy_23_0_0_no_telegram_grants.py`.
