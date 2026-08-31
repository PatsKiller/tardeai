# Night Three Wave 5 — Search / cost proofs (5a–5d)

**Status:** PROOFS COMPLETE (with findings)  
**Authority:** `READ_ONLY_ADVISORY` · behaviour rail = unconditional raise · MBI=0  
**as_of:** 2026-08-31T14:21:23Z  
**Measured at:** live pin `CURRENT` → `373a82078-main-exact-phase2-20260831-101330` (`git_sha=373a82078ea04f5238cd6662adb6810142dabcb9`); persistent-state `/home/johnclaw/trade-ai-releases/persistent-state`  
**Store set:** none mutated for production. Scratch proofs used `/tmp/w5_budget_proof__*`. No credentials/broker/cron installs. No secrets printed.  
**Prefer:** prove-without-code — **no code PR** this wave (findings documented; proofs hold on shipped F1–F5).

F merges on `main` (hub):

| wave | PR | commit | merged (local) |
|---|---|---|---|
| F3 | #750 | `a7995b729` | 2026-08-31 01:11:45 -0400 |
| F1+F2 | #751 | `816a69ed9` | 2026-08-31 01:14:38 -0400 |
| F5 | #752 | `988c00294` | 2026-08-31 01:17:30 -0400 |
| F4 | #753 | `51da7a4a0` | 2026-08-31 01:30:09 -0400 |

First release pin containing F4/F5 modules: `51da7a4a0-main-exact-phase2-20260831-013037` (mtime 2026-08-31 01:31:34 -0400). Live `CURRENT` retargeted 2026-08-31 10:14 -0400 to `373a82078-…`.

---

## Summary

| slice | proof status | tag |
|---|---|---|
| **5a** Search bounding | Bound news/catalyst callers **quiet** in ledger; residual projection intact; **legacy-bulk aegis still fires** and exhausted Brave daily | `[VERIFIED]` + finding |
| **5b** Budget persistence | Scratch set→new-process re-read survives; corrupt ledger **DENY** `fail_open=false`, file not reset | `[VERIFIED]` |
| **5c** Cost accounting | Real `ProviderCostEvent` with `calculated_cost_usd` + `rate_tier` + `cache_hit`; schedule-derived (not literal) | `[VERIFIED]` + finding (partial emitter coverage) |
| **5d** Degradation surfacing | Live impaired pool + scratch degrade → research `what` **says** thinner/impaired (+ CAPTCHA) | `[VERIFIED]` + note (no durable `search_health.json` yet) |

---

## 5a — Search bounding (re-measure since deploy)

### Bounded projection (dry, no store writes) `[VERIFIED]`

```bash
cd "$(readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT)"
python3 -c "from scripts.lib.cio_residual_web import projected_search_volume; \
  from datetime import datetime, timezone; import json; \
  print(json.dumps(projected_search_volume(as_of=datetime.now(timezone.utc)), indent=2))"
```

Quoted (`as_of=2026-08-31T14:17:48+00:00`):

| lane | monthly_projection | notes |
|---|---|---|
| `residual_web` (searxng) | **63** | `3 subjects × 1 hop × 21 weekdays` · `cost_usd_month=0.0` |
| `news_catalyst_brave_under_bound` | **0** | named callers re-pointed → RSS/Finviz/Yahoo |
| `remaining_legacy_bulk_brave` | **672** | aegis_social 420 + aegis_transcript 252 (still budget-gated) |

News/catalyst bound callers (projection list): `portfolio_news`, `catalyst_intelligence`, `web_news_fetcher`, `portfolio_weekly_report`, `symbol_enrichment`, `topic_ingestion`.

### Actual call volume (live ledger) `[VERIFIED]`

`production_state_root` → `/home/johnclaw/trade-ai-releases/persistent-state`  
`budget_path` → `…/data/runtime/search_budget.json`  
`all_status()` at `as_of=2026-08-31T14:17:48+00:00`:

| provider | daily_used / limit | monthly_used / limit | denied_today | alert |
|---|---|---|---|---|
| **brave** | **25 / 25** | **25 / 850** (2.9%) | **3** | ok |
| tavily | 0 / 20 | 0 / 500 | 0 | ok |
| searxng | 0 / 10000 | 0 / 300000 | 0 | ok |

Ledger callers for `2026-08` (Brave only):

| caller | count | class vs F2 intent |
|---|---|---|
| `aegis_social_sentiment` | 10 | **legacy-bulk — still fires** |
| `aegis_transcript_discovery` | 13 | **legacy-bulk — still fires** |
| `web_research` | 2 | on-demand legacy-bulk |
| *(news/catalyst named set)* | **0** | bound → **absent from ledger** `[VERIFIED]` |

`last_call`: `2026-08-31T12:00:03.488827+00:00`.

Code stubs on CURRENT confirm news paths are off the Search API `[CODE]`:

- `scripts/web_news_fetcher._brave_search` → `return []`
- `scripts/symbol_enrichment.pull_brave_aplus` → retired no-op (`retired_bulk_news_use_rss_finviz`)
- `scripts/portfolio_news._brave_search` → Finviz/Yahoo enrich alias (no Brave URL)

Cron still schedules `aegis_social_sentiment` (`0 11,15 * * 1-5`) and `aegis_transcript_discovery` (`0 9 * * 1-5`) plus overnight aegis — consistent with ledger burn. Overnight 2026-08-30 20:44 ET logged `brave_hits: 10` for social (pre/near F deploy window; UTC day rolls into 2026-08-31 counters).

### Compare to projection

- **News/catalyst Brave = 0 actual vs 0 bound** — holds.  
- **Residual searxng projection 63/mo vs ledger `searxng.daily_used=0`** — residual-web does **not** call `search_budget.try_consume` `[CODE]` (subject caps live inside `cio_residual_web` legality, not the provider ledger). Metering gap, not a silent Brave reopen.  
- **Remaining legacy-bulk still fires** — **FINDING** (explicitly left on Brave by F1/F2; observed exhausting daily 25/25 + 3 DENY).

### What did not work / findings (5a)

1. **`[VERIFIED]` FINDING — legacy-bulk callers still fire.** `aegis_social_sentiment` + `aegis_transcript_discovery` (+ `web_research`) are the only Brave spenders since deploy and hit the daily ceiling. Bound projection’s “remaining_legacy_bulk_brave=672” is the intended residual risk; daily cap + never-fail-open is the brake (3 denials today prove the brake engaged).  
2. **`[VERIFIED]`** SearXNG provider counters stay 0 — residual-web volume is not visible in `search_budget.json`. Operator cannot reconcile “63 projected searxng/month” against this ledger.  
3. Legacy file `data/portfolios/state/brave_search_budget.json` still exists (`date=2026-08-10`) — stale parallel sensor; authoritative ledger is `data/runtime/search_budget.json` `[VERIFIED]`.

**5a proof status:** **PASS with findings** — F2 news bound holds; legacy-bulk fire is the named finding.

---

## 5b — Budget persistence + never fail-open

Scratch root only (production ledger unread-mutated).

### Survives process restart `[VERIFIED]`

Process 1 — `try_consume("tavily", …)` ×2 under scratch root → `daily_used=2` written to  
`/tmp/w5_budget_proof__aa78f41/data/runtime/search_budget.json`.

Process 2 — **new interpreter**, `status("tavily")` → `daily_used=2`, `"survived": true`.

### Budget-check error does **not** fail open `[VERIFIED]`

Process 3 — overwrite ledger with `{not-json`, then:

| API | result |
|---|---|
| `check` | `allowed=false`, `fail_open=false`, reason `BUDGET_UNAVAILABLE: BudgetUnavailable: …` |
| `try_consume` | `allowed=false`, `fail_open=false` |
| `guard` | `false` |
| ledger after | still `{not-json` (`still_corrupt=true`) — **no reset rewrite** |

Quoted check payload:

```json
{"allowed": false,
 "reason": "BUDGET_UNAVAILABLE: BudgetUnavailable: budget ledger unreadable at …/search_budget.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
 "fail_open": false,
 "status": null}
```

Live corroboration: Brave at ceiling → `denied_today=3` (unbudgeted calls refused) `[VERIFIED]`.

### What did not work (5b)

Nothing blocking. Scratch proof is the process-survival evidence; live pin was not restarted for this slice (authority READ_ONLY_ADVISORY / no service bounce).

**5b proof status:** **PASS**.

---

## 5c — Cost accounting (measured cost + rate tier + cache hit)

### Real recorded call with all three fields `[VERIFIED]`

Source: `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/provider_cost/events.jsonl`  
Whole-file count: **19** lines with `"rate_tier":` / `"cache_hit":` (all on 2026-08-31, post-F5). Total events in file: **3089**.

**Cache-miss example** (schedule-derived):

```json
{
  "event_id": "pce_c191a8acf7290028def748da",
  "usage_start": "2026-08-31T10:00:05.987815+00:00",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "calculated_cost_usd": 2.97e-05,
  "rate_tier": "off_peak",
  "cache_hit": false,
  "cached_input_tokens": 0,
  "input_tokens": 75,
  "output_tokens": 20,
  "price_schedule_id": "deepseek-v4-flash-peakoff-2026-08-16",
  "cost_source": "LOCAL_CALCULATED",
  "source_lane": "fast",
  "source_process": "watchlist_maria_flash_narrative",
  "outcome": "success",
  "is_test": false,
  "schema_version": "ProviderCostEvent@v1"
}
```

**Cache-hit example:**

```json
{
  "event_id": "pce_9407b419115b5335cdec93cc",
  "usage_start": "2026-08-31T14:11:24.507182+00:00",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "calculated_cost_usd": 0.00266489,
  "rate_tier": "off_peak",
  "cache_hit": true,
  "cached_input_tokens": 256,
  "input_tokens": 6777,
  "output_tokens": 1776,
  "price_schedule_id": "deepseek-v4-flash-peakoff-2026-08-16",
  "cost_source": "LOCAL_CALCULATED",
  "source_lane": "deepseek-flash",
  "is_test": false
}
```

### Not a hardcoded cost literal `[VERIFIED]`

```python
from datetime import datetime, timezone
from scripts.lib.provider_cost.pricing import calculate_usd
at = datetime(2026, 8, 31, 10, 0, 5, tzinfo=timezone.utc)
calculate_usd(provider="deepseek", model="deepseek-v4-flash", at=at,
              cache_hit_input=0, cache_miss_input=75, output=20)
# → calculated_cost_usd=2.97e-05, band='off_peak',
#   price_schedule_id='deepseek-v4-flash-peakoff-2026-08-16',
#   cost_source='LOCAL_CALCULATED'
```

Matches the recorded event exactly. Rates come from `config/provider_pricing_schedules.json` `[CODE]`.

Emitters that **do** populate all three (observed): `watchlist_maria_flash_narrative` (18), `deepseek-flash` lane (1).

### What did not work / findings (5c)

**`[VERIFIED]` FINDING — partial emitter coverage.** In the post-F5 tail (`usage_start >= 2026-08-31T05:17Z`): **19** events with all three fields vs **84** with `calculated_cost_usd` but `rate_tier=null` and `cache_hit=null`. Dominant missing emitter: `source_process=advisory_desk_opinion` / `source_lane=FAST`. Example:

```json
{"event_id": "pce_ed3d46cfd6f9001de6b58904",
 "usage_start": "2026-08-31T05:22:18.550135+00:00",
 "model": "deepseek-v4-flash",
 "calculated_cost_usd": 0.0007233,
 "rate_tier": null,
 "cache_hit": null,
 "cost_source": "LOCAL_CALCULATED",
 "source_process": "advisory_desk_opinion"}
```

F5 schema/emit path works when the client goes through the wired DeepSeek cost path; advisory-desk opinion still records cost without tier/cache. **Proof of F5 fields: PASS on real calls; coverage incomplete.** No code PR this wave (prove-without-code); track as follow-up.

**5c proof status:** **PASS with finding** (real triple-populated events exist; not all lanes emit them).

---

## 5d — Degradation surfacing

### Scratch: degrade pool → output changes `[VERIFIED]`

Healthy pool → `narrative_suffix == ""`; `what` unchanged.  
Impaired pool (1 serving engine) → suffix:

> `Search pool impaired — this answer is thinner than a full result set of this size would imply.`

`what` differs; `search_thinner_than_full=true`; `search_pool_impaired=true`.

### Live probe (read-only GET, no durable write) `[VERIFIED]`

`pool_health()` at `as_of=2026-08-31T14:20:27+00:00`:

- `impaired=true`, `serving_engines=["bing"]`
- unresponsive: brave `Suspended: too many requests`; duckduckgo `CAPTCHA`; startpage `Suspended: CAPTCHA`
- stamp `search_captcha_suspended=["duckduckgo","startpage"]`

Attached to research-shaped output:

```
Residual web found 10 results for NVDA. Search pool impaired — this answer is thinner than a full result set of this size would imply (Search pool impaired: 1 engine(s) served results (bing); 3 unavailable (brave: Suspended: too many requests; duckduckgo: CAPTCHA; startpage: Suspended: CAPTCHA). Coverage is narrower than a normal result set of this size.).
```

`[CODE]` `cio_residual_web` live transport → `attach_degradation`; narrative → `narrative_suffix`.

### What did not work (5d)

1. **No durable `…/data/runtime/search_health.json`** on persistent-state (`durable_present=false` in dry monitor). Dry `python3 -m scripts.lib.search_health_degradation` reports `impaired=null` / empty `per_source` until a probe persists — by design (“never invent CAPTCHA”), but the monitor lane alone does not yet leave a durable CAPTCHA trail between residual hops.  
2. Scratch pools that pass `unresponsive_engines` as a **plain dict of name→reason** lose reasons (`dict` iterates keys only in `per_source_state`) — CAPTCHA then absent from stamp. Live `pool_health` returns `[{engine, reason}, …]` and works. Documented so future tests use the live shape.

**5d proof status:** **PASS** (research output says when pool impaired; live pool currently impaired and message carries CAPTCHA).

---

## Rails check

| rail | evidence |
|---|---|
| News/catalyst off Search API | Ledger callers ∩ bound set = ∅; stubs `[VERIFIED]`/`[CODE]` |
| Budget persists across process | Scratch process1→process2 `[VERIFIED]` |
| Never fail open on budget error | Corrupt → DENY + `fail_open=false` + no rewrite `[VERIFIED]`; live denials=3 |
| Measured cost ≠ hardcoded literal | `calculate_usd` ↔ event `2.97e-05` `[VERIFIED]` |
| Rate tier + cache hit recorded | Real events `[VERIFIED]` |
| Impaired pool spoken in research output | Live + scratch narrative `[VERIFIED]` |

---

## PRs

- **None this wave** (prove-without-code). Prior ship PRs: #750 F3, #751 F1+F2, #752 F5, #753 F4.
- Suggested follow-ups (not opened here): (1) wire `rate_tier`/`cache_hit` on `advisory_desk_opinion` emit path; (2) decide whether aegis legacy-bulk should share residual-web discipline or keep burning the Brave daily cap; (3) meter residual-web/searxng into `search_budget` **or** document a separate residual counter as the reconciliation surface; (4) persist `search_health.json` from the monitor/residual probe so dry status is not empty.

---

## Reproduction commands

```bash
LIVE=$(readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT)
cd "$LIVE"

# 5a
python3 -c "from scripts.lib.cio_residual_web import projected_search_volume; from scripts.lib.search_budget import all_status; from datetime import datetime, timezone; import json; print(json.dumps(projected_search_volume(as_of=datetime.now(timezone.utc)),indent=2)); print(json.dumps(all_status(),indent=2))"

# 5b — see scratch block in this audit (tmp root; do not point root at persistent-state for writes)

# 5c
python3 -c "from pathlib import Path; import json; p=Path('/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/provider_cost/events.jsonl');
[print(l) for l in p.open() if '\"rate_tier\":' in l][:2]"

# 5d
python3 -c "from scripts.lib.search_health import pool_health; from scripts.lib.search_health_degradation import attach_degradation, narrative_suffix; pool=pool_health(); hop=attach_degradation({'what':'Residual web found 10 results for NVDA.'}, pool=pool, probe=False, persist=False); print(hop['what']+narrative_suffix(hop))"
```
