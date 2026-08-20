# Why Telegram advisories look SCHD-only (2026-08-20)

**Authority:** READ_ONLY_ADVISORY — detect/advise only; no broker writes.
**Audience:** Operator (John) — former holdings + watchlist quiet vs held SCHD.

## Short answer

SCHD notifies because it is a **held concentration** (S6) that crossed the
notify path (including Phase A sticky DIGEST + canary). Names you **sold**
(SCHG, AXTI, FATN, …) and **watch** names are on different rails that either
do not fire a situation yet, or fire a plan **without** Telegram by design.

## Live map (checked ~16:45 ET 2026-08-20)

| Name | Where it lives | Situation | Telegram? |
|------|----------------|-----------|-----------|
| SCHD | Holdings (over fire) | S6 concentration | Yes (IMMEDIATE first flip / DIGEST sticky) |
| AXTI | Reentry desk **NEAR** | S3 candidate | No — need capital `RE_ENTER` + `ACT_NOW` |
| FATN | Reentry desk **NEAR** | S3 candidate | No — same gate (ticker is FATN, not FTAN) |
| ANET | Reentry desk **NEAR** | S3 candidate | No — same gate |
| SCHG | Reentry desk **BLOCK** | No S3 | No — desk blocked |
| CSCO | Reentry desk **BLOCK** | No S3 | No — desk blocked |
| Watch (~80) | Watch intelligence | **0 S7** | No — `promotion_grade=0` (no READY/GO/NEAR) |

Roughly **23** S3 READY/NEAR names exist in the snapshot. Phase A
(`s3_capital_act_now`) pages Telegram **only** when the capital plan already
says governed **RE_ENTER** with freshness **ACT_NOW**. Bare “near reentry”
stays in-app / digest material, not a phone page — otherwise every NEAR would
spam.

## What is working vs what feels broken

| Path | Plumbing | Live | Operator feel |
|------|----------|------|----------------|
| Held concentration (SCHD) | S6 + notify | Over fire; canary msg 202 | “Only SCHD texts me” |
| Reentry (AXTI/FATN/…) | Snapshot + S3 (#414) | ~23 S3 | Desk sees NEAR; phone silent |
| Watch | Projection + S7 (#415) | Domain on; 0 candidates | Watchlist silent |
| Symbol theses | Acquisition cron | DIV/DIVI/JEPI@v1; SCHG/CSCO/ANET RAG-blocked | Research debt ≠ advisory |

## How to get advisories on sold / watch names

1. **Reentry capital plan** advances to **RE_ENTER** + **ACT_NOW** → S3 Telegram allowed.
2. **Watch desk** marks promotion READY/GO/NEAR → S7 candidates appear (notify policy for S7 still separate — today forward-loop / not paged like S3).
3. **Ask CIO** interactively (`/cio` / converse) on the symbol — interactive path is live regardless of proactive gates.
4. Longer term (gap plan Phase B/C): thesis SLA + watch fall-on/off auto-thesis — does not by itself unlock Telegram until status/capital gates fire.

## Related docs

- `docs/ops/CIO_PHASE_A_INTERDICT_NOTIFY_2026-08-20.md` — INTERDICT, S3 gate, S6 DIGEST
- `docs/ops/CIO_ADVISORY_TRUTH_HARDENING_CLOSEOUT_2026-08-20.md` — release + Telegram plumbing closeout
- Plan: autonomous CIO gap diligence (Phases A–E)
