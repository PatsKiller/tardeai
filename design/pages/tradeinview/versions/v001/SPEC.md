# TradeInView — v001 (APPROVED 2026-10-24)

Approved boards: TradeInView redesign (Main / Journeys, Calendar, Replay, Holding history).
Approval: operator, 2026-10-24 — "I approved all of your markups. Please make sure that they're implemented per your design." (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- Tabbed page: Journeys · Calendar · Replay · Holding history · Journal (classic tabs); URL ?tab=journeys|calendar|replay|history|classic; /journal?view=classic keeps working.
- Journeys: status "Awaiting fill" (info tone) with a one-line reason; filter chip "Awaiting fill N"; a journey's conflicts listed once in the detail panel as a three-fact strip (Holdings / Stop vs mark / Fills ledger, each with its timestamp); freshness chips "Last closing fill · ledger synced", Stop monitor, Holdings synced, Next broker sync (from the lane registry); detail buttons "Replay this trade" and "All <symbol> history".
- Calendar: month grid Mon–Fri + week total column, heat by magnitude (tokens), filter chips Realized P/L · Earnings · Catalysts · Ex-dividend, Account and Names selects, prev / next month, day click → that day's trades with Replay links. One calendar (reuse the JournalHub logic).
- Replay: trade picker, timeframes the bars store actually has, buy / sell markers from real fills, stop line, CIO stance markers, play / step / scrub / speed, "Compare with a win"; stat strip computed server-side; missing bars shown as a gap.
- Holding history (new): every symbol with ≥ 2 round trips or held in ≥ 2 accounts; detail stats, per-account timeline, every trip row with its source; a data-gaps banner from real checks.
- Zero-hallucination contract: every value traced UI → API field → store → writer; missing data is an explicit gap with its reason, never 0 or a guess; the server computes statistics.

## What stays

- Calendar and Replay are approved tabs: hiding either one is a removal that needs a new approved version.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- remove: badge "per-lot conflict count repeated on every lot" — conflicts listed once in the detail panel
- rename: status "stop_likely_filled" — now "Awaiting fill"
