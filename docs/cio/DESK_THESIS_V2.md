# desk@v2 — CIO governing thesis & operating system

**Authority:** READ_ONLY_ADVISORY  
**Owner:** alex  
**Store:** `scripts/lib/cio_theses.py` · `data/cio/cio_theses.jsonl`  
**Learning:** `data/cio/cio_operator_learning.jsonl` + head `learning_log`  
**Code pin:** live head is `desk@vN` (v2 first intelligence cut; later pins refine structure)

## 1. What desk@v2 is

`desk@v1` was a **guardrail**:

> Risk-aware observe-only. Escalate material events. Never trade. Pin every plan.

`desk@v2` is the **governing investment thesis and operating system** for Alex as CIO.  
It is **not a footer tag** — it is the document the model must reason against on every material situation.

### Core stance (unchanged from v1 spirit)

- **READ_ONLY_ADVISORY** — no broker, order, stop, or 2FA authority from chat or situations.
- **Cash is a feature.** Stage deployment; never force fills.
- **Operator is final decision-maker.** Ack / rate / defer / done / reject are first-class.
- Every plan and Telegram reply cites the **exact** `desk@vN` pin used.

### Intelligence layer (v1 → v2)

| Capability | desk@v1 | desk@v2+ |
|---|---|---|
| Thesis role | Pinned tag | Active governing document |
| Evidence | 1–2 domains | Multi-domain (holdings + cash/portfolio + risk + concentration + Hermes when material) |
| Recommendation | Short card | Thesis-aware judgment + “why this fits desk@vN” |
| Learning | None | Dispositions → learning_log + durable JSONL |
| Depth | Same thin card | Graduated: routine short / material full note |
| Cross-position | Per-symbol | Portfolio view (cash runway, heat, concentration) |
| Research | Optional | Hermes auto-enqueued on material |
| Version discipline | string | Exact pin on every plan/reply |

## 2. Required document structure

```
desk@vN
owner: alex
published: <ISO>
stance: defensive_observe | balanced | opportunistic
summary: 2–4 sentence governing paragraph
principles: [...]
risk_posture:
  max_single_name_weight_pct: 12
  cash_band_min_pct: 20
  deep_dd_threshold_pct: 25
  concentration_fire_pct: ~16.5 (notify/review band)
  notes: free-text risk posture
watch_symbols / linked_symbols: [...]
escalation_rules: [...]
learning_log: (appended on material operator dispositions)
last_reviewed: <ISO>
```

Thresholds align with `config/cio_situations.yaml` unless the operator changes stance/posture.

## 3. Intelligence-gap rules (enforced in code)

1. **Thesis first** — `build_evidence_pack` loads full current desk context before LLM/template.
2. **Multi-domain mandatory for notify** — material notify skipped if `< 2` domains (holdings and/or cash/portfolio preferred).
3. **Graduated depth** — material S1/S5/S6/S8 get thesis_alignment + multi_domain_summary.
4. **Learning loop** — ack/defer/done/reject → learning store; future enrich sees recent dispositions.
5. **No pure regurgitation** — system prompt + template forbid detector-only restatement.
6. **Plumbing preserved** — plan_id, deep links, notify guard, dispositions, READ_ONLY.

## 4. Initial governing paragraph (desk@v2 text)

> Risk-aware observe-only desk under a living thesis. Prefer Data Broker multi-domain evidence;
> escalate material drift, concentration, and deep drawdowns to the operator. Cash is a feature —
> stage deployment; never force fills. Every plan pins desk@vN; recommendations must explain fit
> or tension with this thesis. No unattended trading. READ_ONLY_ADVISORY.

## 5. Operator verification

```bash
PYTHONPATH=scripts python3 -c "
from scripts.lib.cio_theses import safe_current_pin, safe_context_block
print(safe_current_pin())
b=safe_context_block(full=True)
print(b['stance'], b.get('risk_posture_structured') or b.get('risk_posture'))
print(b['principles'][:2])
"
```
