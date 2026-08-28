# CIO Pipeline Slice 17 — /v3/cio/home + briefs expose 2B+2C

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What this slice did

`/api/v3/cio/home` and operator briefs now carry:

- earnings
- NEW_POSITION_IF
- cash / temperament
- case_summaries (or pointers)

Dashboard-only briefs **must not** print `Telegram sent`. `telegram_sent=false`, `delivery=dashboard`.

No notify enable.

## Live (after promote)

SOURCE *(filled)*
