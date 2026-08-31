# Engineering Hard Rules (enforced)

> Cited by `AGENTS.md` §13. `AGENTS.md` is the single source of truth for agent behaviour;
> this file is the mechanically enforced subset.

Non-negotiable operator standards. The first two are **mechanically enforced** by a git hook so they
cannot regress through review oversight. Install hooks once after clone: `bash scripts/install_git_hooks.sh`.

## 1. No secrets in git (enforced)
`scripts/check_no_secrets.py` (pre-commit + pre-push) **blocks** any commit/push containing:
- an API-key pattern (Anthropic `sk-ant-…`, OpenAI `sk-…`, xAI `xai-…`, AWS, GitHub, Slack, private keys);
- a secret FILE (`.env`, `*.key`, `*.pem`, `config/broker_credentials.env`, `secrets_admin_audit.jsonl`, `*/credentials/*`);
- any literal VALUE of a `.env` secret key (`*_KEY/_TOKEN/_SECRET/_PASSWORD`).

Secrets live in `.env` (gitignored) and are read via `os.environ`. The Drive sync excludes `.env`/keys/
credentials. Rotate via **System → Admin → API Keys & Secrets** (`secrets_admin.py`, write-only, masked).

## 2. No hardcoded values — broker/account-agnostic, config from a source (enforced)
Nothing hardcoded; every name/value is a variable from a source (env, `.env`, DB, config). The hook also
**blocks**:
- **Hardcoded chat IDs** — any `.env` `TELEGRAM_CHAT_ID` / `TRADEAI_PROPOSAL_ALERT_CHAT_ID` value appearing
  as a literal in `.py`. Use **`tg_chat_ids.chat_ids()`** (resolves all configured chats from env).
- **Broker-name fallbacks** — the anti-pattern `or "alpaca_paper"` / `or "schwab_x")` at end of expression.
  (Membership tests like `or "fidelity" in source` are NOT flagged.) Add `# hardcode-ok` to opt out a
  genuinely legitimate case.

Apply: drive broker/account logic off the **record's own account** (e.g. the trade's `account`),
normalized to the interlock's `accounts` table keys (lowercase). A missing account **fails closed** — never
assume a broker. The broker-agnostic gate is `live_trading_interlock.assert_writable(conn, account)` (paper
passes, live/unknown refused) — pass it a **positional-cursor** conn (`db_adapter._get_conn`), NOT a dict-
cursor conn, or `account_mode`'s `r[0]` raises `KeyError 0` and it refuses everything. Default paper account
comes from `DEFAULT_PAPER_ACCOUNT` (`.env` / `.env.example`), never a code literal.

## 3. holdings.json never wiped (enforced in code)
Every holdings/current-state writer routes through `protected_holdings_write()` (neutral home
`scripts/holdings_guard.py`): empty/zero/catastrophic-drop (< 50% of last-good) ⇒ **NO-OP** (prior snapshot
kept + alert); backup → atomic write → post-assert (`>$1M & >0 positions`) → restore-on-fail. Tax-grade
basis is `protect_basis`-opt-in (Schwab only). Does NOT close the deploy-zip vector (tracked follow-up).

## Verification
`python3 scripts/check_no_secrets.py --tree` → "no secrets or hardcoded values" (scans the whole tree).
Pre-commit scans the staged change; pre-push scans the tree. Both fail the build on any violation.
