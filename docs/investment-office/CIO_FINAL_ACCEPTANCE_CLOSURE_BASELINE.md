# CIO Final Acceptance Closure v2 — baseline

Authority: `READ_ONLY_ADVISORY`. Isolated branch only. No merge, deploy,
Drive write, interdict change, or live Telegram unless the operator gates it.

| Field | Value |
|---|---|
| Worktree | `/home/johnclaw/tradeai-wt-cio-final-closure` |
| Branch | `fix/cio-final-acceptance-closure-v2` |
| BASE_SHA | `faff6ac153c6ac2ea0e59385c26c7368270374f7` |
| REMOTE_MAIN_AT_START | `faff6ac153c6ac2ea0e59385c26c7368270374f7` |
| PR317_HEAD | `31d35dda15fbd7e64cae29db9ab564eeb18f8b2e` |
| PR312_HEAD | `82311077c99ca39bc640f96e9f07f2189a32b7a2` |
| Live content SHA | `7986e923bc29c863a27bf41a40bf1aefca3b1da8` |
| Created (UTC) | `2026-08-14T23:40:00Z` |

## Rules

- Do not merge PR #317 as a standalone runtime-content commit.
- Re-implement its G2 semantic correction here, then supersede #317.
- Do not touch PR #312 / `scripts/lib/research_governance/**`.
- Last G2 PASS from the #317 worktree is diagnostic, not canonical.
- Drive G3 stays fail-closed. No Drive write in this coding phase.
- Do not turn `CIO_TELEGRAM_INTERDICT` off.
