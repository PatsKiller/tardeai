# Hermes autonomous loop — output quality assessment (2026-07-26)

## Question

When the loop prints `VALIDATED` / `COMMITTED`, is the research **thorough and conclusive**, or only **structurally complete**?

## Honest answer

**Staging-complete and schema-gated — not promotion-grade by itself.**

`COMMITTED` means the payload passed `validate_payload()` and was inserted into `hermes_research_intelligence` with `status=staged`. It does **not** mean a human or librarian promoted it, and it does **not** mean the thesis is investment-ready.

### What the gate actually enforces (real curation)

From `scripts/hermes_staging_ingest.py` + `hermes_research_prompt.py`:

| Check | Effect |
|-------|--------|
| Required fields | `summary`, `topic`, `research_type`, `model_used`, agent name, freshness |
| Evidence depth | ≥2 substantive `evidence_json` keys (beyond limitations/source_views/challenge_points) |
| Limitations | non-empty |
| Source views | non-empty |
| High confidence | score >0.85 requires ≥3 evidence refs |
| Challenge points | findings, not “analyze whether…” questions |
| Forbidden language | no place/buy/sell/order/approve mutation phrases |
| External claims | no “live market / real-time quote” fabrication flags |
| Advisory framing | prompt forces facts vs inferences, missing data, confidence explanation |

Empty/sparse model output (typical `gemma3:4b`) is **rejected**. That is positive selection pressure, not rubber-stamping.

### What the gate does **not** guarantee

| Gap | Reality |
|-----|---------|
| Depth of analysis | Context is truncated to ~4k chars in the prompt; one pass, no multi-source web research in this loop |
| Factual correctness | Model can mis-read supplied context; no second model adjudicator on this path |
| Confidence calibration | Code may `setdefault(confidence_score, 0.5)`; models sometimes emit optimistic 0.85 |
| Promotion | Rows stay **staged** until librarian / promotion governance |
| Trading action | Explicitly forbidden; staging only |

### Operator interpretation

| Signal | Meaning |
|--------|---------|
| `VALIDATION FAILED` | Model did not meet structural bar — **good** (not completing for its own sake) |
| `VALIDATED` + conf 0.6 | Schema-ok advisory draft; treat as **research candidate** |
| `COMMITTED id=N` | Durable staged row for librarian / embeddings / review UI |
| Home “Research staged” count rising | Pipeline is writing; **not** a quality score |

### Recommendation

1. Keep **12b + 300s** defaults for fewer empty-summary rejects.
2. Spot-check recent ids (e.g. 12983 HRL, 12984 KMB) in Hermes UI or SQL for summary substance weekly.
3. Do not treat staged confidence as a trade signal.
4. Promotion remains a separate, explicit step.
