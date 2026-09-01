# Maria Watchlist Fabrication — Audit & Fix (2026-06-19)

Status:      HISTORICAL
as_of:       2026-06-19T21:51:53-04:00
Measured at: efcc51365 / not measured

The OpenClaw personal-assistant agent **Maria** fabricated watchlist responses. This documents the audit,
root cause, fix, and verification. (Maria's SOUL lives in `~/.openclaw/` — outside this repo — and is
backed up by `scripts/full_system_backup.py` ("OpenClaw configs … SOULs, workspaces"). This note is the
in-repo, version-controlled record of the fix.)

## What happened
Over several Telegram messages ("maria watch BULL", "maria watch HOOD", "maria, watch DIVI") Maria replied
with **"✅ Added to your Data Center watch"** and printed a categorized **"Data Center watchlist"**
(Core / Facilities / High-Upside / Trends) — all invented.

## Audit findings (system truth vs. Maria's claims)
- **No watch was created.** BULL and DIVI had **zero `watch_directive`** rows — the skill was not run, or
  its failure was not relayed. ("✅ Added" was false.)
- **Wrong list.** The `tradeai-watchlist` skill `add` defaults to the general **"Watchlist"**; HOOD was
  already directive #56 under "Watchlist", **not** "Data Center."
- **Miscategorized + embellished.** BULL (a brokerage), DIVI (a dividend ETF), HOOD (Robinhood) are not
  data-center names. The "Core/High-Upside" tiers **mutated between consecutive messages** (HOOD bounced
  Core↔High-Upside) — a tell-tale hallucination. The tier structure does not exist; the watchlist is flat
  items optionally tagged with operator-named lists.

## Root cause
The skill itself is fine (`add BULL DIVI` correctly created directives #78/#79 under "Watchlist"). The bug
was the agent not running it and inventing structure. The active SOUL already had the label rule + a
"paste the skill's raw output" rule, but **lacked a rule against inventing list tiers / printing a
categorized snapshot from memory** — exactly the failure mode.

## Fix
1. Added a **"NEVER INVENT LIST STRUCTURE"** block to Maria's SOUL:
   - No "Core / Facilities / High-Upside / Trends" tiers — not real, not the agent's to assign.
   - Do not categorize a ticker into a tier/theme it wasn't told to (e.g. HOOD/BULL/DIVI → "Data Center").
   - Do not print a categorized watchlist from memory — run `watchlist` and relay the real items.
   - A symbol is not a sector; an on-theme ticker still doesn't get filed under a list John didn't name.
2. **Dual-SOUL gotcha:** `openclaw.json` sets both `workspace` (`workspace-maria/SOUL.md`, was the generic
   default) and `agentDir` (`agents/maria/agent/SOUL.md`, the good custom one). Which loads is ambiguous,
   so **both were synced to the corrected version.** Backup: `workspace-maria/SOUL.md.bak_pre_watchlist_discipline_20260619`.
3. SOUL loads fresh per session (no gateway restart needed). Maria model = `xai/grok-3-mini`.
4. Honored intent: actually added **BULL (#78), DIVI (#79)** under "Watchlist" (HOOD already #56).

## Verification (live, via `openclaw agent --agent maria` — no `--deliver`, nothing sent to Telegram)
| Path | Test | Result |
|---|---|---|
| Read | "show my watchlist" | relayed the real flat 200-item list, no invented tiers ✓ |
| Default add | "watch ORCL" (no list, data-center-adjacent) | filed under default **"Watchlist"** ✓ |
| Named add | "add SNOW to my Data Center list" | filed under **"Data Center"** ✓ |

In every case she ran the skill and pasted its raw output. Both test directives (ORCL #80, SNOW #81) were
removed afterward; pre-existing watchlist items for those symbols were preserved (their `directive_id`
reverted). John's real adds (BULL/DIVI/HOOD) intact.

## How to re-verify
```bash
openclaw agent --agent maria --message "show my watchlist"        # expect raw flat list, no tiers
openclaw agent --agent maria --message "watch <TICKER>"           # expect label "Watchlist"
openclaw agent --agent maria --message "add <TICKER> to my <Name> list"  # expect label "<Name>"
```
Then confirm server-side: `SELECT label FROM watch_directives WHERE spec->>'symbol'='<TICKER>'`. Remember
to remove any test directive afterward (directive + its `watch_directive_hits` + `strategy_watchpool` rows;
revert `directive_id` on any pre-existing `watchlist_items`).
