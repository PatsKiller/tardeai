# Situation catalog & plan lifecycle

**Config:** [`config/cio_situations.yaml`](../../config/cio_situations.yaml)  
**Detector:** [`scripts/lib/cio_situation_detector.py`](../../scripts/lib/cio_situation_detector.py)  
**Plans:** [`scripts/lib/cio_plans.py`](../../scripts/lib/cio_plans.py)  
**Enrichment + notify:** [`scripts/lib/cio_plan_enrichment.py`](../../scripts/lib/cio_plan_enrichment.py)  
**Catalog freeze notes:** [SITUATION_CATALOG_V1.md](./SITUATION_CATALOG_V1.md)

**Authority:** READ_ONLY_ADVISORY. Every numeric claim from Data Broker evidence or `DATA_UNAVAILABLE`.

---

## S-class catalog

| Code | Name | Fire (summary) | Default owner |
|---|---|---|---|
| **S0** | OPERATOR_CONVERSE | Free-text / continuity from CIO chat | alex |
| **S1** | POSITION_LIFECYCLE | Deep DD from basis, partial recovery, reclaim, major catalyst | alex |
| **S2** | STOP_GAP | Missing or inconsistent stop vs basis/recovery | alex |
| **S3** | REENTRY_CANDIDATE | Reentry decision desk READY/NEAR (read desk; no re-rank) | alex |
| **S4** | SECTOR_ROTATION | Material sector momentum / rotation ladders vs holdings | steph |
| **S5** | CASH_DEPLOYMENT | Cash above band + constructive rotation/watch cluster; quality may be PARTIAL | steph |
| **S6** | CONCENTRATION_OR_DISPOSITION | High book weight or long-held material loser | morgan |
| **S7** | WATCH_PROMOTION | Watch READY/GO/strong NEAR | alex |
| **S8** | DEFENSIVE_REGIME | Risk-off / defensive regime labels, heat up, defensive proposals | alex |

### Typical threshold keys (config; align with thesis risk_posture)

| Key | Role |
|---|---|
| `basis_drawdown_pct` | S1 deep DD (e.g. 25) |
| `partial_recovery_pct` | S1 recovery band |
| `cash_pct_band_min` | S5 cash floor (e.g. 20) |
| `concentration_weight_pct` | S6 review band (e.g. 12) |
| `disposition_loss_pct` / `disposition_hold_months` | S6 loser disposition |
| `sector_weight_delta_pp` | S4 materiality |
| `reentry_statuses` / `watch_statuses` | S3 / S7 |
| `regime_risk_off_labels` | S8 |

Exact numbers live in config + host thesis; do not hardcode secrets or account-specific weights into git.

---

## Plan lifecycle

```
detector / converse
    → create plan (draft|proposed)
    → enrich_plan (LLM or template; stamp thesis_version)
    → optional notify (Telegram) if policy + fingerprint allow
    → operator disposition (ack|rate|defer|done|reject)
    → supersede | cancel | accept (status model)
```

### Plan fields (conceptually)

- `plan_id`, `situation_type`, `symbols`, `status`  
- `summary`, `recommendation`, `options[]` (id/label/pros/cons)  
- `fire_reasons`, `evidence_refs`, multi-domain fields when material  
- `thesis_version` pin (e.g. `desk@v4`)  
- `owner_agent`, timestamps, notify metadata  

Statuses (store): `draft | proposed | accepted | superseded | cancelled` (see `cio_plans.py`).

### Entry points that raise situations

- `scripts/cio_heartbeat.py` — evidence from snapshot → detector  
- `scripts/cio_reactive_cycle.py` — live broker snapshot path + goal wakes  
- Telegram free-text → S0 via converse core  
- Tests / fixtures for SpaceX-class lifecycle cases  

---

## Notify guard

**Problem:** re-sending the same situation spam on every detector pass.  
**Solution:** once-per-fingerprint ledger in enrichment.

| Piece | Location |
|---|---|
| Ledger file | `data/cio/cio_plan_notify_ledger.json` |
| Fingerprint | `notify_fingerprint(plan)` — situation type, symbols, fire reasons, material content hash |
| Gate | Skip notify if same `plan_id` + same fingerprint already sent |
| Policy | `config/cio_llm_policy.yaml` — `notify_situation_types`, `notify_once_per_fingerprint` |
| Env | Host `CIO_SITUATION_NOTIFY` (0/1) on CIO bot env |

Material notify prefers **≥2 Data Broker domains** (holdings and/or cash/portfolio) so cards are not detector-only.

Default material-ish notify types (policy): **S1, S2, S5, S6, S8** (confirm in `cio_llm_policy.yaml` on branch).

---

## Operator dispositions

| Disposition | Meaning |
|---|---|
| **ack** | Acknowledge and monitor |
| **rate** | Rate advisory quality |
| **defer** | Postpone; note retained for learning |
| **done** | Operator closed from their side |
| **reject** | Reject recommendation |

Surfaced on Telegram as `/cio <disposition> <plan_id>` and thread reply keywords. See [LEARNING_LOOP.md](./LEARNING_LOOP.md).

---

## Non-goals (catalog v1 spirit)

- Auto orders/stops  
- Second ranking system vs Watch/Reentry desks  
- Invented numbers when Data Broker is empty  
- Treating S3/S7 as full productized re-entry/watch books (detectors exist; depth limited — see [ROADMAP_GAPS.md](./ROADMAP_GAPS.md))

---

## Related

- [AUTHORITY.md](./AUTHORITY.md)  
- [ARCHITECTURE.md](./ARCHITECTURE.md) Track A  
- [P2B_PLAN_ENRICHMENT.md](./P2B_PLAN_ENRICHMENT.md)  
