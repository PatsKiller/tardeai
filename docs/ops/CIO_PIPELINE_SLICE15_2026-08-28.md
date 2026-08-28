# CIO Pipeline Slice 15 — subject_guid on S3 / watch / NEW_POSITION_IF

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What this slice did

Stamp `subject_guid` from the identity registry (lookup only). **No noisy mint.**
Missing registry rows stay `UNRESOLVED`.

Applied to S3 reentry candidates, S7 watch rows, and NEW_POSITION_IF.

## Live (after promote)

SOURCE *(filled)*
