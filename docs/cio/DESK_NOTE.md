# Desk note product (synthesis v1.3 — institutional book memo)

**Code:** [`scripts/lib/cio_desk_synthesis.py`](../../scripts/lib/cio_desk_synthesis.py) + [`scripts/lib/cio_desk_depth.py`](../../scripts/lib/cio_desk_depth.py) + [`scripts/lib/cio_evidence_spine.py`](../../scripts/lib/cio_evidence_spine.py)  
**Artifact (host):** `data/cio/cio_desk_note_latest.md` · spine `cio_desk_memo_spine_latest.md`  
**Authority:** READ_ONLY · pins live `desk@vN`  
**API:** `GET /api/v3/cio/desk-note` → same `generate_desk_synthesis_v1()` payload as CLI

**Institutional portfolio advisory memo** under `desk@vN` — one thesis-governed book narrative (cash × concentration × DD), not three siloed S-cards. Not a 40-page PDF clone.

---

## Section schema (v1.3)

| # | Section | Content |
|---|---|---|
| 1 | Executive thesis | Stance, pin, 5–8 line book argument + principles + risk posture |
| 2 | Portfolio state | Book, day P/L, cash $/%, band gap, holdings, heat, stops, quality, cash stage |
| 3 | Allocation & concentration | Top weights, names ≥12%, fire distance, sector tilt |
| 4 | Material situations (**integrated**) | One narrative: cash × SCHD × SPCX + catalyst/RSI micro-context; plan anchors only |
| 5 | What we are doing and why | Named recs with conviction; non-action first-class; disposition-bound |
| 6 | What would change the call | Explicit triggers per cash / SCHD / SPCX / quality |
| 7 | Research agenda | Hermes questions + open jobs + ingested results |
| 8 | Operator loop | Dispositions, plan_ids, ack path, revisit |
| 9 | Evidence map | Domains + as_of; catalyst/technicals/Hermes; DATA_UNAVAILABLE explicit |

Telegram default preference: **memo spine** (`render_memo_spine_telegram`) — exec thesis + 3 material points + recs — not three disconnected detector dumps.

### Cash stage gates (bind re-entry language)

| Stage | When | Language |
|---|---|---|
| STAGE_0 | Missing totals or quality PARTIAL | List candidates; **watch only; no stage** |
| STAGE_1 | Cash > band, quality OK, no opt-in | Sized **paper plan** text; operator ack required |
| STAGE_2 | Opt-in + READY + confirmations + size under max_name + heat OK | Advisory first-slice description only — still READ_ONLY |

Never emit buy-now / order / stop instructions.

---

## Regenerate

```bash
PYTHONPATH=scripts python3 -m scripts.lib.cio_desk_synthesis
# or
PYTHONPATH=scripts python3 scripts/lib/cio_desk_synthesis.py

curl -s http://127.0.0.1:7777/api/v3/cio/desk-note | head -c 2000
```

Persists `data/cio/cio_desk_note_latest.md` on CLI run.

---

## R:R methodology

Engine and desk-note display filters: see [REENTRY_RR.md](./REENTRY_RR.md).

**Engine:** `R:R = (target − price) / (price − stop)` from `reentry_decision_desk` (criterion prefers ≥2:1). **Desk core full card:** `1.5 ≤ R:R ≤ 12` (`CORE_MIN_RR`).

## Quality bar (v1.2)

1. Re-entry section lists real READY/NEAR candidates with zones, R:R, sizing, stage gate  
2. Sector posture has defensive/offensive % and sector weights (lookthrough when available)  
3. SCHD (or deferred names) rec text cites operator prior and does not primary-trim while defer active  
4. Cash-stage explicit STAGE_0/1/2  
5. No mid-sentence truncation; distinct thesis-fit  
6. CLI and API same payload  
7. READ_ONLY preserved  

---

## Related

- [THESIS.md](./THESIS.md) · [SITUATIONS.md](./SITUATIONS.md) · [LEARNING_LOOP.md](./LEARNING_LOOP.md) · [ROADMAP_GAPS.md](./ROADMAP_GAPS.md)  
