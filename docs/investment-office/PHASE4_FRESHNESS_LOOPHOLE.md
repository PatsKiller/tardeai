# PHASE 4 — Freshness loophole closed

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Version:** `freshness_materiality_1.1.0`  
**Scope:** `scripts/lib/cio_freshness_materiality_gate.py` (no frontend)

## Problem

Phase 3 allowed two fail-open paths that let a decision look fresh when it was not:

1. **Undated decision clock treated as now.** Missing `generated_at` / `revalidated_at` was rewritten to `pass=True`, `quality=VERIFIED_CURRENT`, `age_seconds=0`, `detail=evaluated_now`. Acceptance G6 already forbids that string; the gate still minted it.
2. **Holdings + quote from the same `holdings.json` snapshot counted as two evidence sources.** A single book mark could satisfy `min_evidence_sources=2` with no independent thesis, research, or risk clock.

Neither path may produce **ACT NOW**.

## Rules (current)

| Input | Label |
| --- | --- |
| Missing `generated_at` **and** `revalidated_at` | **REVALIDATE** — never ACT NOW |
| Unparseable decision clock | **REVALIDATE** |
| `computed_at` / `plan_computed_at` only | **REVALIDATE** (not a decision clock) |
| Holdings + quote same snapshot, no independent thesis/research/risk | **REVIEW** |
| Required mark stale | **STALE_REFRESH_REQUIRED** |
| FinancialTruthGate conflict / suppressed | **DATA_CONFLICT** |
| HOLD / thin signal | **WATCH** |

`evaluated_now` is not produced. An undated required clock stays `undated` or `missing`.

## Evidence groups

Distinct groups (after collapse):

`financial_state` · `market_price` · `risk` · `fundamental` · `technical` · `sector` · `analyst` · `hermes` · `tax_lot` · `strategy_context`

**Same-snapshot collapse:** if quote / market value rode in on the `holdings.json` snapshot (row `updated_at` / `as_of`, or a holdings-like `price_source`, with no distinct live `quote_as_of` / `price_as_of`), `financial_state` and `market_price` are **one** group: `financial_state`.

Book-derived risk (`risk_as_of` absent or equal to the holdings clock) is **not** independent of the book.

## ACT NOW requires all of

1. FinancialTruthGate: symbol not suppressed; quality not `CONFLICTED` / `DATA_UNAVAILABLE`
2. **Current financial state** — holdings (and cash) freshness PASS
3. **Current market price** — quote / MV freshness PASS (even if collapsed into `financial_state`)
4. **Real decision timestamp** — `generated_at` or `revalidated_at` within 24h
5. **Relevant current risk** when concentration / fire is cited
6. **At least one independent thesis / research / risk source beyond the book** — dated `thesis` / `research`, `hermes`, `analyst`, `sector`, `technical`, or independently dated `risk`
7. Material stance (`TRIM` / `EXIT` / `ADD` / `RE_ENTER`) with non-trivial delta

A live quote that is merely another print of the same snapshot does **not** satisfy (6).

## Account rows

Every contributing non-cash account row for the symbol is checked, not the first row only. The quote clock is the **worst** (oldest) dated mark. Any undated contributing mark fails the quote / MV clock.

## Tests

```
python3 -m pytest -q tests/test_cio_freshness_materiality_gate.py
```

Required dry cases:

- undated decision cannot be `ACT_NOW` → `REVALIDATE`
- `evaluated_now` must not appear as a passing detail (runtime board + source)
- holdings + quote same snapshot does not satisfy independent evidence for ACT NOW
- TRIM + fire + dated decision + dated quote + dated risk + thesis/hermes **can** pass

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  
