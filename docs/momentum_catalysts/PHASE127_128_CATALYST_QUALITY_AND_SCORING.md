# Phase 127-128 — Catalyst Quality Scoring and Advisory Overlay Design

Status:      HISTORICAL
as_of:       2026-06-01T17:36:28-04:00
Measured at: efcc51365 / not measured

## Pilot Inventory (Phase 127A)

| Ticker | Catalyst Type | Confidence | Sources | Domains |
|--------|--------------|------------|---------|---------|
| ABTS | news_momentum | 0.6 | 3 | reuters, sandiegouniontribune, stockanalysis |
| AIRJ | news_momentum | 0.6 | 3 | msn, stockanalysis, yahoo |
| ANY | regulatory | 0.6 | 3 | seekingalpha, msn, reuters |
| CRE | news_momentum | 0.6 | 3 | seekingalpha, commercialobserver, investopedia |
| ELMT | news_momentum | 0.6 | 3 | aol, yahoo, yahoo.sg |

## Quality Scorecard (Phase 127B)

| Dimension | ABTS | AIRJ | ANY | CRE | ELMT |
|-----------|------|------|-----|-----|------|
| Recency | Medium | Medium | Medium | Medium | Medium |
| Source quality | Good (reuters) | Medium | Good (reuters, SA) | Good (SA) | Low (aol) |
| Source count | 3 | 3 | 3 | 3 | 3 |
| Catalyst specificity | Low (generic news) | Low | Medium (regulatory) | Low | Low |
| Scalp relevance | Low | Low | Medium | Low | Low |
| Hype/noise risk | Low | Low | Low | Low | Low |
| Confidence calibration | Appropriate | Appropriate | Should be higher | Appropriate | Appropriate |
| Operator usefulness | Low | Low | **Medium** | Low | Low |

**Assessment**: 4/5 are generic "news_momentum" without specific catalyst. Only ANY has a typed catalyst (regulatory). The researcher needs better catalyst specificity — currently just finding any news, not identifying WHY the stock is moving.

## Catalyst Thresholds (Phase 127E)

| Level | Confidence | Action |
|-------|------------|--------|
| High confidence catalyst | >= 0.7 + specific type (earnings/regulatory/contract) | Telegram alert + dashboard highlight |
| Medium confidence | 0.5-0.7 | Dashboard only |
| Low / generic news | < 0.5 or type=news_momentum | SIEM log only |
| Stale (>4h old) | any | Mark stale, do not highlight |
| Conflict/contradiction | any | Flag for operator review |

## Advisory Overlay Model (Phase 128B)

### Inputs
- catalyst_type (from SearXNG classification)
- source_count (number of unique sources)
- source_quality (domain reputation scoring)
- catalyst_recency (hours since published)
- sentiment (positive/negative/neutral from source text)

### Output
- catalyst_context_score: 0.0-1.0
- catalyst_label: STRONG / MEDIUM / WEAK / NONE / STALE
- advisory_note: human-readable one-liner
- no_trade_signal: true (always)

### Display Integration (Phase 128C)
Add to momentum candidate detail view:
- Catalyst: [STRONG/MEDIUM/WEAK/NONE]
- Source count: N
- Age: Xh
- Summary: one-liner
- View sources: link to JSONL

**Does NOT change GO/WAIT/NO GO.** Advisory context only.

## Safety (Phase 128E)
- GO/WAIT/NO GO mutation: ZERO
- Proposal writes: ZERO
- Trades: ZERO
- Journal mutation: ZERO
- Holdings mutation: ZERO
- Level 7: PROHIBITED
