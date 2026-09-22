# Single-letter ticker `S` — link bleed / regex / research-gap auto-enqueue

```
Status:      ACTIVE
as_of:       2026-09-22T14:38:00-04:00
Measured at: origin/main 466c781d0 · served build-meta source_commit 466c781d0 ·
             fix SHA ed957509d on draft PR #1187 only
Canonical repo path: docs/audits/SINGLE_LETTER_TICKER_S_FIX_2026-09-22.md
Authority:   live lifecycle measurement 2026-09-22 (AGENTS.md §8)
Supersedes:  none (focused note; does not replace OPERATOR_REPLY_ROUTING.md)
See also:    docs/OPERATOR_REPLY_ROUTING.md ·
             docs/audit/message-identity-audit-2026-09-21.md §4 ·
             AGENTS.md §7 "Operator replies…" · §9.1 rich layout
```

## Live verdict: **PR_ONLY** (not LIVE)

Per AGENTS.md: live means merged to `main` **and** promoted to the served CURRENT release,
observed from that pin — not a PR, not a green suite.

| check | result | evidence tag |
|---|---|---|
| PR #1187 | **OPEN · DRAFT · not merged** | `[VERIFIED]` `gh pr view 1187` → `state=OPEN`, `isDraft=true`, `mergedAt=null`, `headRefOid=ed957509d…` |
| Fix on `origin/main`? | **no** | `[VERIFIED]` `git merge-base --is-ancestor ed957509d origin/main` → not ancestor; tip `466c781d0` Merge #1186 |
| Served pin | `466c781d0…` (`main-exact-phase2`) | `[VERIFIED]` `curl http://127.0.0.1:7777/v3/build-meta.json` → `source_commit`/`git_sha`/`build_sha` = `466c781d0a212d162d7d4868eb7ab8a454e14ee1` |
| portfolio-server cwd | `…/466c781d0-main-exact-phase2-20260922-135909` | `[VERIFIED]` `readlink /proc/<MainPID>/cwd` |
| telegram bot cwd | older pin `f14dbdfee-…-20260919-210329` | `[VERIFIED]` same probe — desk transport not on the fix either |
| Claim OBSERVED_LIVE? | **no** | Fix SHA ≠ served SHA; not on main |

**Do not call this OBSERVED_LIVE, DOCKED-as-live, or promoted.** Lifecycle state is **PR_ONLY**.

## What broke

Three related defects on the operator Telegram path (desk / rich chrome / subject extract):

1. **Link-chrome bleed (TROW class).** Outbound cards and footers built Command Center / Finviz /
   Yahoo links from **every** symbol the body extractor found — including incidental registry
   matches — so a card about one subject carried another name's deep-links and GUID tags.
   Same family as the live CBC/LOMA + TROW contamination recorded in
   `docs/audit/message-identity-audit-2026-09-21.md` §4 (`comms_editor.subjects(body)` → links
   and ID tags).
2. **Single-letter ticker `S` dropped / mishandled.** Bare letter extraction with loose word
   boundaries missed or over-matched single-letter tickers; `$S` / book / registry binding was
   not enforced consistently across `operator_subject_resolver`, `cio_telegram_converse.extract_symbols`,
   and rich link builders.
3. **Research-gap prompt-only.** Soft / freeform gaps told the operator to type `research S`
   instead of **auto-enqueueing** a deduped research-gap row on the desk path.

## What the fix changes (on the PR branch — `[CODE]` / branch evidence, not served)

Branch `cursor/fix-single-letter-ticker-s-667c` · SHA
`ed957509def15cb8db9c3efd2372b71e7c8ba59c` · draft PR
https://github.com/PatsKiller/tardeai/pull/1187

| area | change |
|---|---|
| `scripts/lib/telegram_rich.py` | `SINGLE_LETTER_TICKERS`, `scope_primary_symbols`, `build_outbound_links`; `RichMessage` scopes symbols |
| `scripts/lib/comms_editor.py` | `primary_symbols` / contextvar; footer uses `build_outbound_links` only for primary |
| `scripts/telegram_transport.py` | passes `primary_symbols` into `edit` |
| `scripts/lib/cio_converse_core.py` | sets primary symbols from desk intent before send |
| `scripts/lib/operator_subject_resolver.py` | single-letter requires cashtag or book/registry |
| `scripts/lib/cio_telegram_converse.py` | `extract_symbols` allows listed single-letter tickers |
| `scripts/lib/cio_operator_desk_loop.py` | `enqueue_research_gap` (deduped once); freeform + soft gaps auto-queue |
| `scripts/run_cio_hardening_ci.py` | registers the new test file |

**Tests:** `tests/test_single_letter_tickers.py` (plus regression suite green on the fix branch —
see prior receipt `internal/fix-ticker-s-20260922.md`). Hermetic PASS on the PR worktree is
**not** OBSERVED from CURRENT.

## Honesty bar

- Hermetic / CI green on #1187 ≠ LIVE.
- Draft PR ≠ merged.
- Served `466c781d0` = alerts-tranche integrate (#1186), not this fix.
- Promoting requires a separate `release-write` grant and operator intent — **out of scope** for
  this docs/sync pass.

## Next lifecycle steps (operator / release — not this note)

1. Land #1187 (mark ready when CI green; merge to `main`).
2. Promote exact merge SHA; restart desk/telegram units that bind cwd to an old release if needed.
3. Re-measure: ask about `S` / a single-letter subject from Telegram on the **served** pin; confirm
   primary-only links and an auto-enqueued gap row — then promote this note's verdict to
   `OBSERVED_LIVE` with quoted commands.
