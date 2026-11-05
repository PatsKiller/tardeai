# Home v002 — SPEC (PROPOSED): market risk on the home page

Proposed 2026-10-31 (design DSN-20261031-market-risk-ui, engine DSN-20261031-market-risk-engine P3-T2). v000 (as built
2026-10-26) and v001 (the 10-24 approvals) for Home were never captured in this folder; this is the first versioned change
and is numbered v002 per design/README.md rule 1. Mockups show synthetic data only; they live in the private store and are
bound by sha256 in status.json. Data source for everything below: `GET /api/v2/market-risk/latest` (engine P2-T1) and
`POST /api/v2/market-risk/ack` (P3-T7). Until those exist the build renders the fact as "Market risk: not yet evaluated".

## Default Home (`/v3/`, Do-now layout `HomeDoNow.tsx`)

### 1. Header fact "Market" → "MARKET RISK" (rename, same slot)
- Shows: tier word in its colour (GREEN · BLUE · YELLOW · ORANGE · RED, or NOT EVALUATED), score `/100`, and one line: the
  top contributor ("event cluster 88 · QQQ failed retest"). Tap → `/v3/risk?tab=market-risk`.
- Tooltip (desktop) / long-press sheet (phone): as_of, confirming categories count, probability table for 24h/72h/1w.
- The old content of the fact (regime word, VIX, lagging sectors) moves to the "Market in one look" card (section 3).

### 2. Banner (new) — only while the tier is ORANGE or RED
- Full width above the header; phone: one column, the whole page scrolls (not sticky; fixed chrome stays ≤15% of the viewport).
- Line 1: tier pill + "MARKET RISK 83/100 · since Thu 18:15 ET · repeat 3 of 12" (Red) or "since … · repeats hourly" (Orange).
- Line 2–6: the five contributors, each "name · points · the number behind it · as_of" (e.g. "Futures / extended hours +18 ·
  NQ −1.6% · 18:04 ET"). Points sum to the score; an uplift line when portfolio vulnerability raised the tier.
- "Your book": budget breaches ("growth style 85th pct vs 50% budget") and the driving positions as symbol + distance to
  stop only — never a size, dollar amount or instruction.
- De-escalates if: one sentence from the engine.
- Buttons (≥44 px): **Acknowledge** (primary; POST ack; records the operator decision; silences repeats; label becomes
  "Acknowledged 18:31 ET" and the banner stays muted until the tier drops below Orange), **Open Risk**, **Review stops**
  (→ `/v3/risk?tab=exposure`). No order, size or stop control anywhere.
- Hidden entirely at Yellow and below; never shows a stale episode: if `as_of` is older than the policy's stale_after, the
  banner shows "stale — last evaluation HH:MM ET" instead of numbers.

### 3. Card "Market in one look" (extended, nothing removed)
- First block (new): tier + score + the five contributors as a compact list (same data as the banner, no buttons).
- Second block (moved from the header fact): regime word, VIX, sectors leading/lagging with "you hold", hedge state,
  inverse stoplights line — unchanged text.
- Link text "Defense desk" stays; a second link "Market risk" → `/v3/risk?tab=market-risk`.

### 4. Classic Home (`/v3/?view=classic`, `HomeHub.tsx`, kept one release)
- Hero tile "REGIME" → "MARKET RISK" (rename): value = tier + score, sub = top contributor; colour by tier. Same drill.

## States
Not evaluated (engine not yet live) · GREEN · BLUE · YELLOW · ORANGE · RED · stale (as_of past stale_after) · acknowledged ·
load error ("market risk unavailable — Risk page").

## Phone (412 / 390)
One column; banner first, then header facts stacked; tap targets ≥44 px; no sideways scroll; ET times only; the banner's
contributor list is five rows, never truncated to "…".

## Tokens
New tone `elevated` (`--risk-orange-*`) for ORANGE; BLUE = info, YELLOW = warning, RED = danger, GREEN = success.

## Removals / hides / moves (rule 4 — complete list)
- RENAME: header fact "Market" → "MARKET RISK" (content moved to the "Market in one look" card, section 3).
- RENAME: classic hero tile "REGIME" → "MARKET RISK".
- Nothing hidden, deleted, or moved behind a tap that was not behind one before.
