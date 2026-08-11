# Phase P2b — Plan enrichment (brain depth)

**Authority:** READ_ONLY_ADVISORY  
**Branch:** `feature/advisory-desk-v1`  
**Code:** `scripts/lib/cio_plan_enrichment.py`  
**Policy:** `config/cio_llm_policy.yaml`  
**Detector:** `scripts/lib/cio_situation_detector.py` + `config/cio_situations.yaml`  
**Telegram format:** `scripts/lib/cio_telegram_converse.py::format_structured_reply`

## Decision path: LLM vs template

```
CIOSituationDetector.persist_candidate
  → enrich_plan(source=S*, force_template=CIO_LLM_ENRICH in {0,false,off})
       ├─ non-material source → llm=skipped_non_material (no change)
       ├─ enrich_dedup hit → llm=skipped_dedup
       ├─ force_template / llm.enabled=false → narrative_source=template
       ├─ local hour cap (max_calls_per_hour) → blocked_cap → template
       ├─ call_governed_llm (bridge :8766, Flash default)
       │     caller=advisory_desk task=advisory_opinion process=advisory_desk_opinion
       │     model=deepseek-v4-flash  (Pro: alex / cio_synthesis when source in pro_for)
       ├─ empty_content / non_json → retry compact_user_prompt(minimal=True)
       ├─ validate_narrative (soft numeric match) → on fail one repair call
       └─ success → narrative_source=llm, status=proposed
  → maybe_notify_plan (if CIO_SITUATION_NOTIFY=1 + allowlist + notify type allowlist)
       └─ notify ledger: same plan_id + fingerprint → skip (re-enrich does NOT re-push)
          force via maybe_notify_plan(..., force=True) or CIO_SITUATION_NOTIFY_FORCE=1
```

**Notify spam guard:** `data/cio/cio_plan_notify_ledger.json` keys by `plan_id`.  
Fingerprint = hash(plan_id + evidence_hash + fire_reasons). Policy:
`notify_once_per_fingerprint`, `notify_cooldown_hours` (12), `notify_min_gap_minutes` (5).

**Host keys (dedicated CIO bot only — not OpenClaw main):**

| Key | Location | Role |
|---|---|---|
| `CIO_LLM_ENRICH=1` | `~/.config/tradeai/cio-telegram.env` | Allow LLM path (default on if unset) |
| `CIO_SITUATION_NOTIFY=1` | same | Telegram notify on new plans |
| `CIO_TELEGRAM_CONVERSE=1` | same | Free-text converse loop |
| `TELEGRAM_CIO_BOT_TOKEN` | Bitwarden SM → unit EnvironmentFile | `@tradeai_cio_bot` only |
| `TELEGRAM_CIO_CHAT_IDS` | cio-telegram.env | Allowlist |
| `llm.max_tokens_flash` | `config/cio_llm_policy.yaml` | 1200 (reasoning headroom) |
| `llm.caller_flash` / `task_type_flash` | policy | `advisory_desk` / `advisory_opinion` |
| `dedup_hours` / `max_plans_per_pass` / `max_notify_per_pass` | `config/cio_situations.yaml` | 12h / 5 / 3 |

## Why “LLM deferred” appeared (2026-08-11)

1. **forced_template** — soak/tests set `CIO_LLM_ENRICH=0`; detector logs show `llm=forced_template` at ~20:04 UTC.  
2. **empty_content / non_json** — large indented JSON evidence packs caused Flash to spend `max_tokens` on reasoning with empty `content`. Fixed via `compact_user_prompt` + minimal retry + higher `max_tokens_flash`.  
3. **validation_failed:invented_numbers** — model rounded % (e.g. 26.9) not exact token. Softened validator (relative/abs match + pairwise % from evidence floats).  
4. **Not** DeepSeek API key missing — traffic always goes through governed bridge `http://127.0.0.1:8766` (never direct `api.deepseek.com` from CIO).

## What “material” means

LLM budget may be spent only for material sources, e.g.:

- Situation types S1–S8 / `situation.raised`
- `OPERATOR_MESSAGE` / `S0_OPERATOR_CONVERSE`
- Optional high-priority goal wakes

**Non-material (no LLM):** pure heartbeat no-change, deterministic `/cio` status, `system.heartbeat_ok`.

## Flags

| Flag / config | Default | Effect |
|---|---|---|
| `llm.enabled` / `CIO_LLM_ENRICH` | on / unset=on | `0` forces template-only enrichment |
| `max_calls_per_hour` | 12 | Soft local cap (+ bridge global cap) |
| `enrich_dedup_hours` | 6 | Skip re-LLM same plan_id if evidence hash unchanged |
| `situation_notify_telegram` / `CIO_SITUATION_NOTIFY` | false / 0 | Optional Telegram on new plan |
| Flash vs Pro | Flash default | Pro for OPERATOR_MESSAGE, S0, S8 |
| `max_tokens_flash` | 1200 | Completion budget for Flash JSON |

## narrative_source

| Value | Meaning |
|---|---|
| `llm` | Governed bridge returned validated JSON |
| `template` | Cap/provider/validation blocked — deterministic view + “LLM deferred” |

Telegram badge: `✨ Alex (LLM)` vs `📋 template` (markers stripped from body text).

## Evidence contract

- Pack built from `plan.evidence_refs` + detector summary numbers  
- User prompt is **compact** (not full JSON dump) — see `compact_user_prompt`  
- Model output JSON schema: summary, options, recommendation, risks, revisit_hint, cited_fields  
- Validator soft-matches numbers; one repair call; then template fail-closed

## Situation detector — why S5 / S1 / S6 fired

| Type | Rule (config thresholds) | Observed fire |
|---|---|---|
| **S5_CASH_DEPLOYMENT** | `cash_pct >= cash_pct_band_min` (now **20%**, was 15%) | cash ~45% → `cash_pct_above_band` |
| **S1_POSITION_LIFECYCLE** | deep DD ≥25% from basis **or** partial recovery **or** catalyst; pure `basis_reclaim_zone` alone **dropped** | SPCX ~26.9% DD; XLB reclaim-only was historical noise |
| **S6_CONCENTRATION** | single-name weight ≥ `concentration_weight_pct` (**12%**) | SCHD ~16.5% → `weight_16.5pct` |

**Spam controls:** `dedup_hours=12`, `max_plans_per_pass=5`, `max_notify_per_pass=3`, priority order S5→S6→S8→S1→S2→…, S1 reclaim-only filter.

## Disable LLM on wakes

```bash
export CIO_LLM_ENRICH=0
# or config/cio_llm_policy.yaml llm.enabled: false
```

## Verification sequence (LLM-enriched reply)

```bash
# 1) Host env
grep -E 'CIO_LLM_ENRICH|CIO_SITUATION_NOTIFY' ~/.config/tradeai/cio-telegram.env
# expect CIO_LLM_ENRICH=1  CIO_SITUATION_NOTIFY=1

# 2) Bridge up
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8766/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-TradeAI-Agent: advisory_desk' \
  -H 'X-TradeAI-Task-Type: advisory_opinion' \
  -H 'X-TradeAI-Process-Id: advisory_desk_opinion' \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"{}"}],"max_tokens":8}'
# expect 200

# 3) Force re-enrich an existing material plan
cd /path/to/trade-ai-v12-rebuild
PYTHONPATH=scripts python3 - <<'PY'
from scripts.lib.cio_plans import CIOPlanStore
from scripts.lib.cio_plan_enrichment import enrich_plan, maybe_notify_plan
store = CIOPlanStore()
# pick a real plan_id from /cio plans or data/cio
pid = "plan_79fe9e72f2d4"  # example S6 SCHD
p = store.get_plan(pid)
r = enrich_plan(p, source=p["situation_type"], wake_id="verify:llm", force_llm=True, plan_store=store)
print(r["narrative_source"], r["llm"], r.get("llm_error"))
assert r["narrative_source"] == "llm"
# Re-enrich must NOT re-push Telegram (ledger skip). Force only when intentional:
print("notify_default", maybe_notify_plan(r["plan"]))          # False if already notified
print("notify_force", maybe_notify_plan(r["plan"], force=True))  # True when ops want a re-push
PY
# Telegram should show ✨ Alex (LLM), plan_id unchanged, /cio ack <plan_id> footer
# Second default maybe_notify_plan on same plan_id → False (no spam)


# 4) Unit tests
python3 -m pytest tests/test_cio_plan_enrichment_p2b.py tests/test_cio_telegram_converse.py -q
```

## Honest autonomy language

This is an **advisory colleague**: event/situation/chat → optional governed narrative under cap → plan fields.  
Not an autonomous trader. No orders/stops/2FA. Heartbeat remains the safety net.

## Tests

```bash
python3 -m pytest tests/test_cio_plan_enrichment_p2b.py tests/test_cio_telegram_converse.py -q
```

## Wake traces (P5)

Enrichment sets `llm=` on the wake trace (`blocked_cap`, `invoked`, `template`, …).  
See [WAKE_TRACES_P5.md](WAKE_TRACES_P5.md) and `data/cio/cio_wake_traces.jsonl`. Log: `data/cio/cio_llm_enrich_log.jsonl`.
