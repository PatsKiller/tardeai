# Phase 5 — Command Center Coverage Gap Analysis

Status: ACTIVE
as_of: 2026-09-16T16:35:00-04:00
Measured at: origin/main `940425b73` · CC hub + API reads `[CODE]`; Telegram deep-links `[CODE]`
See also: `01_CHANNEL_INVENTORY_SOURCE_MAP.md` · `02_ROUTING_GOVERNANCE_PROPOSAL.md`

## 1. Surface crosswalk (Telegram → CC, and back)

| Telegram card | Facts carried | CC page with the same facts |
|---|---|---|
| GO / A+ scalp | price, gap, RVOL, float, volume, score, catalyst, criteria | **Trading Hub** (`/v3/trading?tab=Scalp`) — deep-link fixed 09-15 |
| ENTRY (READY/NEAR) | setup, zone, stop, target, R:R, ladder, invalidation | Trading Hub + Rotation entry plans |
| Material change | symbol, kind, magnitude, narrative, open question | Watch Intelligence dossier |
| CIO decision / act-now | decision, reason, invalidation, next review | CioHub (`/v3/cio`) |
| Paper proposal | proposal + approve/reject | Trading Hub Proposals tab |

## 2. What is surfacing (confirmed)

- GO/ENTRY now deep-link to the page that actually shows their numbers
  `[CODE]` `scripts/lib/telegram_rich.py` (lean PR #1032).
- Comms Editor symbol links unify on `/v3/watch/intelligence/<SYM>` `[CODE]`.
- `/v2/` permanently redirects to `/v3/` (no dead legacy surface) `[VERIFIED]` (live 302).

## 3. What should surface but does not (gaps)

| Gap | Detail | Severity |
|---|---|---|
| **Holdings/positions/initiatives never reach Telegram** | CC shows full book, lookthrough, stops, dividends, tax lots; Telegram only surfaces GO/entry/decision events, not the standing book. | Medium |
| **CIO capital plan / cash posture** | full office is in CioHub; Telegram gets only gated IMMEDIATE cards, no scheduled posture digest. | Medium |
| **Thesis / lineage / freshness** | Symbol Intelligence has a freshness matrix + evidence lineage; Telegram cards don't carry it. | Low |
| **Scanner WAIT/AVOID** | suppressed to CC by design — correct, but not discoverable from phone. | Low (by design) |
| **Communications delivery health** | `/v3/communications` is a receipt ledger; never summarized to Telegram. | Low |

## 4. Whether channel output reflects actual holdings vs market noise

- **GO/entry are universe-driven**, not held-driven — they surface the scanner universe, not
  "what you own". Precedence (operator 100 > held 80 > reentry 70 ...) applies to material
  change and research, but the GO scanner is market-noise-shaped by nature.
- **No standing-book push.** There is no scheduled message that says "here is your portfolio,
  exposures, and what changed" — the operator must open CC. This is the largest
  *representation* gap between channels and the actual book.
- **Material change is held-aware** (says "you hold this", universe_reason=held) — good.

## 5. Missing intelligence / enrichment opportunities

1. **Portfolio digest** — a scheduled brief of holdings, exposures, top movers, and open
   initiatives (the 07:30 brief exists; verify it carries book-level facts, not just scanner).
2. **Held-universe bias flag** — mark alerts "held" vs "not held" so the operator can triage.
3. **CC → Telegram backlink completeness** — every actionable CC item (proposal, act-now)
   should have a one-tap Telegram path; already true for proposals and CIO act-now.
4. **Additional sources to consider** — earnings calendar (held names), dividend dates,
   tax-lot/rebalance events — all present in CC but absent from Telegram.

## 6. Summary

Channels accurately reflect **events and decisions**, but under-represent the **standing
portfolio and its priorities**. The fix is a scheduled book-level brief + held/not-held
labels on market alerts — not more scanner traffic.
