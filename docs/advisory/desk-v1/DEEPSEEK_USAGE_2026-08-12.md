# DeepSeek usage + prompt curation — 2026-08-12

Status:      HISTORICAL
as_of:       2026-08-12T14:39:24-04:00
Measured at: efcc51365 / not measured

Read-only assessment of how DeepSeek is wired into the Advisory Desk opinion
layer. No LLM behavior was changed this sprint (git diff confirms the three
LLM files are untouched).

---

## 1. Routing (who is primary)

From `config/advisory_desk.yaml`:

| Order | Lane | Model | Purpose | Thinking |
|---|---|---|---|---|
| 1 | `deepseek-flash` | `deepseek-v4-flash` | per-row opinions | **disabled** |
| 2 | `deepseek-pro` | `deepseek-v4-pro` | desk synthesis + material rows | **disabled** |
| 3 | `local` (fallback) | `gemma3:12b` | fallback | n/a |

- DeepSeek is the **primary** provider; Ollama `gemma3:12b` is the fallback lane
  only (verified present on `localhost:11434`).
- `never_escalate_to` blocks `deepseek-v4-pro-think` and `deepseek-v4-pro-max`.

## 2. Key path (correctness)

```
Bitwarden SM (deepseek_tradeai)
  → /run/user/1000/tradeai/env   (tmpfs render)
  → cio_governed_model_bridge.py (port 8766)
  → deepseek API
```

- Config explicitly warns: **"NEVER call api.deepseek.com from the opinion
  engine — caps live on the bridge only."**
- The `thinking: disabled` setting on both DeepSeek lanes is required and
  correct: without it, DeepSeek returned empty content with
  `finish_reason: length`.
- Bridge reachability re-verified this session: `localhost:8766` is up
  (returns 501 for an unsupported GET on `/health` — the POST-only
  `/v1/chat/completions` server is live).

## 3. Cost controls

| Control | Value |
|---|---|
| `max_model_rows_per_run` | 20 |
| `daily_usd_cap` | $0.05 |
| `per_row_usd_estimate` | $0.001 |
| `min_provider_cache_hit_rate` | 0.70 |

These live on the **governed bridge**, not the opinion engine.

## 4. Prompt curation

The stable system prompt enforces:
- `READ_ONLY_ADVISORY` — never invent prices/percentages/dates/share counts.
- **Every number in prose must appear verbatim in the evidence bundle.**
- `evidence_cited` may only reference `ref_id`s present in the bundle.
- `key_risk` (strongest argument *against* the verdict) is **required**.
- Conviction measures **thesis confidence (evidence quality), not position
  size** — consistent with the documented conviction rule.
- A stable system prefix (no timestamp/run_id/symbol) preserves the provider
  prefix cache.

The synthesis prompt leads with the **largest dollars-at-stake item**, names
exactly three items, cites symbols, and names one blind spot.

This curation is adequate for the current tier. The prompt templates are
deliberately anti-hallucination and cost-shaped.

## 5. What was NOT changed this sprint

`git diff` shows modifications only to `advisory_desk.py`, `api_v3_advisory.py`,
and `shadow_session.py`. These are untouched:

- `scripts/lib/advisory/advisory_opinion_engine.py`
- `config/advisory_desk.yaml`
- `scripts/lib/cio_governed_model_bridge.py`

Per the operator's instruction, the LLM layer is left as-is.

## 6. Open concern (carried from prior session — not re-verified live)

The prior live run reported **"port 8766 not listening, but calls reaching
api.deepseek.com directly"** — i.e. DeepSeek working while bypassing the
governed bridge. If the bridge is where the `$0.05/day` cap and cost accounting
are enforced, then the direct path is outside those controls. This session
confirmed the bridge is now up, but the shadow-run track should still verify:
1. spend is being recorded on the governed path, and
2. the `$0.05` cap would actually stop a runaway.

This is a governance-verification item, not a code change.
