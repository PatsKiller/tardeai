# Desk note product (synthesis v1.2)

**Code:** [`scripts/lib/cio_desk_synthesis.py`](../../scripts/lib/cio_desk_synthesis.py) + [`scripts/lib/cio_desk_depth.py`](../../scripts/lib/cio_desk_depth.py)  
**Artifact (host):** `data/cio/cio_desk_note_latest.md`  
**Authority:** READ_ONLY · pins live `desk@vN`  
**API:** `GET /api/v3/cio/desk-note` → same `generate_desk_synthesis_v1()` payload as CLI

Portfolio-grade advisory memo under `desk@vN` — not a full wealth-management report.

---

## Section schema (v1.2)

| # | Section | Content |
|---|---|---|
| 1 | Thesis header | Full summary, structured risk posture, principles |
| 2 | Portfolio snapshot | Book, cash vs band, heat, stops, top weights, **cash STAGE_0/1/2** |
| 3 | Sector posture | Defensive vs offensive share, lookthrough sectors, correlated sleeves |
| 4 | Material situations | Distinct thesis-fit; **disposition-aware Rec** |
| 5 | Re-entry book | `build_decision_desk` READY/NEAR/OVERSOLD; zone/R:R/size; stage gate; desk fit |
| 6 | Cross-position | Concentration, cash runway, industrial/aero sleeve |
| 7 | Desk recommendations | Disposition-bound holds; re-entry top under stage |
| 7b | Deeper analysis | What would change cash / SCHD / SPCX calls |
| 8 | Learning log | Only entries that biased this note |
| 9 | Revisit + ack | Plan ids, revisit triggers, READ_ONLY footer |

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
