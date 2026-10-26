# Prospectus v001 — SPEC (DRAFT)

New page; nothing existing is removed, hidden, moved or renamed.

## What it shows

- **List** (`/v3/prospectus`): header strip with totals (ready, queued, writing, failed, not written) and the
  prospectus credit budget (credit left; today used / daily cap with a meter). Filter chips Holdings / Watch / All
  with counts; search by ticker, name or verdict. Each row: ticker, company name, status chip, Stale badge, model chip
  (Opus / Fable), written date (ET), one-line verdict (or the failure reason / "Not written yet — queued").
  Holdings first; failures first within a group.
- **Report** (`/v3/prospectus/:symbol`): ticker and name, model and status chips, written date, version picker,
  Download PDF / Download Word / Open HTML, operator-only "Rewrite now" (asks first). Verdict banner; charts (price
  with stop / entry lines, revenue and EPS bars, valuation vs peers bars, analyst target range); sections in contract
  order, each with its own accent color, inline citation markers and citation pills.
- **States**: loading skeleton, not written yet (queued), queued, writing, failed with reason, stale banner, load error
  with Retry.

## Layout

- Desktop (1440): list column left, report right.
- Phone (412 / 390): one column list; a row opens a full-screen sheet with ← Back; tap targets at least 44 px; no
  sideways scroll; sticky chrome none inside the sheet.

## Additions elsewhere (no removals)

- add: nav item "Prospectus" in Intel, after Communications.
- add: a Prospectus link on the ticker report-link group used by Watch and Portfolio holding cards / table / drawer,
  on the Watch detail panel, and in the shared ticker (opportunity) modal header.

## Fingerprints

Private evidence (fixture screenshots) is referenced from status.json by sha256 only.
