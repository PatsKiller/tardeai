# Research Intelligence v2.1 — Narrative Quality + Editorial UI

**Status:** Implemented · **Date:** 2026-07-15  
**Parent:** `RESEARCH_INTELLIGENCE_V2.md`  
**Inspiration:** Seeking Alpha (article structure), Benzinga (scannable headlines + action), Yahoo Finance (desk balance), StockTwits (sentiment chip), The Information (premium tone)

---

## Problem

v2 delivered taxonomy, freshness, archive, and retirement seeding, but the UI still felt like a
database browser: harsh chips, thin cards, little narrative. Operators need **briefings**, not rows.

---

## Content layer

### Module
`scripts/lib/research_intelligence_narrative.py` → `enrich_narrative()`

Every feed item now includes:

| Field | Role |
|-------|------|
| `lede` | One-sentence dek under the headline |
| `executive_summary[]` | 2–3 readable paragraphs |
| `key_takeaways[]` | Scannable bullets |
| `bull_case` / `bear_case` | Balanced framing |
| `why_it_matters` | Portfolio / retirement / risk context |
| `next_action` | `{ label, detail, href_hint }` CTA |
| `reading_minutes` | Soft UX cue |
| `narrative_source` | `synthesized` \| `stored_llm` |

### Cost model
- **Default path is deterministic** (no LLM on every GET) — free, fast, always on.
- Optional batch LLM: `scripts/research_intelligence_narrative_enrich.py --apply --lane local`
  writes `evidence_json.narrative` on Hermes rows; feed prefers stored LLM copy when present.

### Actionability
`next_action` maps category + holdings + freshness to operator CTAs, e.g.:
- Retirement → “Review Roth / tax plan”
- Holdings ticker → “Review {SYM} position”
- Stale → “Refresh coverage”
- Topic monitor → “Run topic research”

---

## UI redesign

`apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx`

### Layout
1. **Masthead** — editorial header, soft gradient, live/fresh/due/retirement stats  
2. **Controls** — soft pills (not harsh badges), Article/Cards/Wire views, search + filters  
3. **Featured briefing** — full article card (lede, body, takeaways, bull/bear, why, CTA)  
4. **Latest briefings** — list default (best narrative density)  
5. **Right rail** — Retirement pillar, freshness breakdown, desk links  

### Design system (page-local)
Soft dark editorial palette (`C` tokens): muted slate surfaces, soft violet retirement accent,
mint income, sky freshness — **not** wall-to-wall amber/red alarms.

### Views
| Mode | Use |
|------|-----|
| **Article (list)** | Default — SA/Yahoo style reading |
| **Cards** | Grid scan |
| **Wire (compact)** | Benzinga density |

---

## Retirement pillar
Unchanged seed/monitor infrastructure from v2; UI elevates retirement as **featured desk** when
lane = Retirement. Rail shows freshest age + needs-refresh count from freshness API.

---

## Verify
```bash
curl -sS 'http://127.0.0.1:7777/api/v2/research-intelligence?limit=1&category=retirement_tax' \
  | python -c "import sys,json; i=json.load(sys.stdin)['data']['items'][0]; print(i.get('lede')); print(i.get('next_action')); print(len(i.get('executive_summary') or []))"
# UI: /v3/research-intelligence  (hard refresh after npm run build)
```

---

## Files
- `scripts/lib/research_intelligence_narrative.py`
- `scripts/lib/research_intelligence.py` (integrates narrative into `_item_base`)
- `scripts/research_intelligence_narrative_enrich.py` (optional LLM batch)
- `apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx`
- this doc
