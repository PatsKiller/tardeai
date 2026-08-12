# Roadmap gaps — explicit “not yet”

This file is the **only** place aspirational CIO / FA product should live.  
Everything else in `docs/cio/` documents **live** behavior.

If a capability is listed here, **do not** claim it as shipped in README maturity, thesis, or desk notes.

---

## Product gaps

### 1. Re-entry opportunities (standing book)

| Live | Missing |
|---|---|
| S3 fires when reentry desk says READY/NEAR (read-only) | Continuous re-entry **book** product: ranked book, capital allocation, staged ladders, outcome tracking as a first-class FA surface |
| No re-rank inside CIO detector | Operator-facing re-entry program with thesis-linked sizing under cash band |

### 2. Sector defensive posture

| Live | Missing |
|---|---|
| S4 sector rotation signals; S8 defensive regime | Standing multi-sector **defensive posture** OS (target weights, hedge sleeves, regime playbooks beyond detector cards) |
| Owners steph/alex on types | Portfolio construction policy engine for defensive rotation |

### 3. Continuous learning depth

| Live | Missing |
|---|---|
| Disposition → JSONL + thesis learning_log; enrichment can honor recent bias | High-volume closed loop: outcome scoring, automatic prompt/policy improvement, disposition quality metrics, A/B of thesis pins |
| Thin log on hosts | Institutional “lessons learned” library |

### 4. Report-grade analytics (MS / Schwab class)

| Live | Missing |
|---|---|
| Desk note v1.1 multi-section advisory memo | IPS documents, multi-horizon projections, tax-aware lots, household aggregation, compliance-grade narratives, client-ready PDFs |
| Book cash / concentration / heat | Full factor, stress, and liability-matched analytics |

### 5. Plan pin hygiene at scale

| Live | Missing |
|---|---|
| Enrich re-pins when live pin ≠ plan pin (path exists) | Guaranteed batch re-pin of all open plans on every publish; zero stale desk@v1 residue |

### 6. LLM reliability as default narrative

| Live | Missing |
|---|---|
| Flash/bridge path with soft validator; force_template gates; `CIO_LLM_ENRICH=0` soak | Always-on high-quality LLM cards without intermittent empty/fail deferral |

### 7. Cross-channel parity

| Live | Missing |
|---|---|
| Telegram CIO bot primary | Full WhatsApp / multi-channel parity with same notify guard and dispositions |

### 8. Execution bridge (explicit non-goal under current authority)

| Live | Missing by design |
|---|---|
| READ_ONLY_ADVISORY only | Any chat-originated order/stop authority — **not on roadmap without a separate authority redesign** |

---

## How to promote a gap to “live”

1. Ship code on `feature/advisory-desk-v1` (or successor) with tests.  
2. Move description from this file into the relevant live doc (SITUATIONS, DESK_NOTE, LEARNING_LOOP).  
3. Update [README.md](./README.md) maturity paragraph downward-honest still.  
4. Bump external operating packet pin/as_of if thesis or operator-facing behavior changed.

---

## Related

- [README.md](./README.md) maturity  
- [DESK_NOTE.md](./DESK_NOTE.md) quality bar table  
- [ARCHITECTURE.md](./ARCHITECTURE.md)  
