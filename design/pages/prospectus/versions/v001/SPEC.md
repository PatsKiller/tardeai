# Prospectus v001 — SPEC (approved mockup, IMPLEMENTING)

Approved by the operator 2026-10-26 ("approved push live"). The five approved boards (list desktop, report desktop,
phone list, phone report, PDF/Word page 1) are private (they show real tickers) and bound in status.json by sha256.
New page; nothing existing is removed, hidden, moved or renamed.

## List (`/v3/prospectus`)

- Title and one-line purpose; stat tiles: Ready (n / N), Queued, Anthropic credit (left; today used of the daily cap).
- Chips: All / Holdings / Watch / Needs rewrite (stale or failed), with counts on desktop; search (ticker or company).
- Desktop: a table — ticker + name, one-line verdict, type (Holding / Watch), model (Opus / Fable), written, next
  rewrite (Overdue when stale), status (Ready, Partial, Needs rewrite, Writing, Queued, Failed, Missing).
- Phone: cards — ticker + status, verdict, "type · model · date". A card opens the report as a full-screen sheet.

## Report (`/v3/prospectus/:symbol`)

1. "← All prospectuses" (desktop) / "← Back" (phone sheet).
2. Header: ticker, name, type, "Written by <model>", written time and version, next rewrite; Download PDF,
   Download Word, Open HTML, version picker, operator-only "Rewrite now" (asks first; phone: full-width at the end).
3. Verdict tiles: verdict + CIO conviction, price + day, your position (+ P/L on cost), stop + distance, yield ·
   expense (desktop only, as approved).
4. Summary (verdict line + summary section, citations).
5. Charts: price 1 year with entry and stop lines, revenue / earnings, valuation vs peers (ticker highlighted),
   analyst targets range. Phone: inside a tap-to-open "Charts" block.
6. Relative performance: rebased-100 lines (ticker, sector ETF, industry group, S&P 500, Nasdaq-100) with
   3M / YTD / 1Y / 3Y; returns table 1W / 1M / 3M / YTD / 1Y / 3Y (phone 1M / YTD / 1Y / 3Y) + excess vs S&P;
   rank in industry, relative strength, sector trend.
7. Peer comparison table (ticker highlighted, peer median row; scrolls sideways inside its card on a phone).
8. Estimates and earnings surprises, ownership and flows, risk and technicals.
9. Scenarios bear / base / bull (price, probability, narrative) with "Analysis, not an order".
10. Narrative sections (desktop two columns; phone tap-to-open).
11. Macro sensitivity (FRED, next CPI / FOMC), SEC filings (form, filed, what changed, EDGAR link), earnings call,
    options / sentiment / dividends.
12. Source coverage chips (green used, amber stale with as-of, grey not applicable, red failed); a missing key source
    makes the report "Partial" with the gap named. Sources list (desktop).

Any block the backend has not supplied renders a compact "not available yet" row.

## States

Loading, not written yet (queued), queued, writing, failed with reason, partial, needs rewrite (stale), load error.

## Additions elsewhere (no removals)

- add: nav item "Prospectus" in Intel, after Communications.
- add: a Prospectus link on the ticker report-link group used by Watch and Portfolio holding cards / table / drawer,
  on the Watch detail panel, and in the shared ticker (opportunity) modal header.
