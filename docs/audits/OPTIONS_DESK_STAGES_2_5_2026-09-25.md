# Options desk stages 2–5

**Status:** code on branch `wt/options-decision-truth-20260925`. Not served. Not a CIO approval. Not an outcome study.

**Authority:** READ_ONLY_ADVISORY

## What these stages are

- Stage 2. `OptionsDecisionPacket@v1` wraps the comparison. `cio_approved` is always false. A credit under the existing 0.25 floor is `REVIEW_REQUIRED` with no trade button.
- Stage 3. A lifecycle position has one primary bucket. Other matches are labeled “also noted.”
- Stage 4. The Options desk title states how many rows need a person, how many are refused, how many are blocked, and that outcomes are not validated from the screen.
- Stage 5. The scorecard reports `outcome_validated: false` and `learning: not_validated` when there are no independently replayed closes. `0/30` stays `0/30`. `MEMORY_BEHAVIOR_INFLUENCE` is recorded as 0 and is not flipped.

## What is still unproved

Served pass, natural alert fire, and outcome validation. Open-leg count was 0 on the operator paste at 16:45 ET on 2026-09-25. This document does not claim a later count.
