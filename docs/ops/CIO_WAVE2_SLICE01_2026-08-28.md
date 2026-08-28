# CIO Wave 2 Slice 01 — held-universe thesis coverage

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What this slice did

`holdings_thesis_coverage` on investment product, operator product, and `/v3/cio/home`.

Every currently held **equity ticker** is CURRENT or UNAVAILABLE with a reason. No fake thesis text.

CUSIP-only and CASH rows are not in this universe (`held_equity_symbols`).

## Live dry (production holdings)

held_n **19** · current **19** · unavailable **0**
CURRENT: PFLT NOC SCHG RTX LDOS SCHD SPCX DIV BAH CSWC V SRNE XLB ARKX XLI BND JEPI XAR AMANX

No invented why_owned_or_watched on UNAVAILABLE (none in this pass).
