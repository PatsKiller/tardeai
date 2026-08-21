# CIO IIC Arc Session Closeout — 2026-08-21

**CURRENT:** `b04f0016` · release `b04f0016-main-exact-phase2-20260821-103022`  
**Authority:** READ_ONLY_ADVISORY  
**Master architecture record:** `docs/architecture/TRADEAI_SYSTEM_STATE_AND_AUTONOMY_2026-08-20.md`

---

## PR / deploy table

| PR | Title | Merge tip | Promoted |
|----|-------|-----------|----------|
| #422 | IIC Phase A — per-ticker Telegram narrative | (prior) | Yes |
| #423 | IIC Phase B+C — feedback journal + CC thesis card | `1e450393` | Yes |
| #424 | Phase D — SI dossier + Hermes queue open count / oldest wait | `82786253` | Yes (via #425 promote) |
| #425 | Bold HTML IIC + severity emoji + raw BOOK dump kill | `b04f0016` | **Yes** 2026-08-21T14:31Z |

Promote receipt: `~/.local/state/cio-phase2-exact-main/deploy_receipt.json`  
PREV: `1e450393-main-exact-phase2-20260821-095647`

---

## What shipped

### Telegram (push)
- Investment Intelligence Cards replace raw `Material CIO product change · BOOK` dumps
- **Real bold** via `parse_mode=HTML` (was broken: Markdown `*` with `parse_mode=None`)
- Severity emoji: 🔴 HOT · 🟠 WARM · 🟡 COOL · ⚪ COLD · 🔬/📐 provenance
- Lead line + **Do this** + Why now + Levels + Thesis
- Inline buttons: Agree / Disagree / Interested / Defer / Need data / Dismiss / OPEN CIO / Thesis
- Delivery suppress: `SUPPRESSED_RAW_PRODUCT_DUMP` if residual raw bodies appear
- Book fallback subject: `CIO book update · {label}`

### Command Center (pull)
- `GET/POST /api/v3/cio/intelligence/{SYM}` — SIO + journal + `research_queue`
- Symbol Intelligence page: dossier (no SHADOW), queue chip, operator journal, thesis timeline
- SymbolThesisCard / CioHub: feedback intents + optional queue chip

### Research queue age
```text
research_queue.open_count
research_queue.oldest_wait_seconds | oldest_wait_human   # e.g. "3h"
per-job waiting_age_*
```
SI chip: `RESEARCH QUEUE 2 open · oldest 3h` or `idle`

---

## Operator proofs / UX answers

| Ask | Answer after promote |
|-----|----------------------|
| Does SI page show Hermes/research queue amount + how long in queue? | **Yes** — open count + oldest wait |
| Why were Telegram cards flat / asterisks visible? | `parse_mode=None` ate Markdown; fixed with HTML |
| Will BOOK bullet dumps return? | Suppressed at enqueue+delivery; CURRENT runs IIC path |

---

## Explicit non-goals / follow-ups

- **Churn dwell** for UBER↔ARKG↔AUUD membership flip-flops (visual only in #425)
- Always-on financial notify / INTERDICT policy change
- Preference auto-ingest from feedback journal → IPS rewrite
- Broker / orders / stops
- MBI

---

## Operator commands

```bash
# Status
~/tradeai-wt-cio-iic-d/scripts/cio_phase2_exact_main_deploy.sh status

# Dry-render an IIC (from CURRENT)
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
export PYTHONPATH=.:scripts
python3 -c "from scripts.lib.cio_symbol_intelligence import assemble_symbol_intelligence, render_telegram_card as r; \
 print(r(assemble_symbol_intelligence('UBER', change_item={'kind':'reentry_added','symbol':'UBER','to':'NEAR','material':True}, \
 product={'trigger':'RESEARCH_COMPLETED','reentry_book':{'names':[]}}, parent={'symbol':'SPCX'})))"

# Thesis coverage SLA
python3 scripts/cio_held_thesis_coverage.py --report
```

CC routes:
- `/watch/intelligence/UBER` — dossier + queue chip
- `/cio` — hub + thesis cards

---

## Drive sync

- Target: **Trade_AI_Docs_v2** (`1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`)
- Tool: `scripts/sync-docs-to-drive.sh` / `.py`
- SRC: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs` must mirror **`origin/main` docs/** before sync
- Protocol: `git checkout origin/main -- docs/` on dual-root (do **not** sync dirty feature branches)

### Sync verification (2026-08-21 targeted upload → Trade_AI_Docs_v2)

| File | Drive |
|------|-------|
| System state | [link](https://drive.google.com/file/d/1ZDm8K8D1OzO5gU2y8m_KO8n-BxsDPgD6/view) |
| IIC session closeout | [link](https://drive.google.com/file/d/1Lhdah-2yVzRVTEdpgdvsL5lKaBLtn3IA/view) |
| Phase D SI queue | [link](https://drive.google.com/file/d/1ZNdgooUygI7naUNqzrVGD0tcohd54K1s/view) |
| Telegram actionable visual | [link](https://drive.google.com/file/d/1_PZndlXCKGyye8j_qaj1oVh0WX9QSMNF/view) |
| Feedback + CC | [link](https://drive.google.com/file/d/1huE9ZjljQx0OCSiqkQgJglqxtCk-LqAe/view) |
| IIC Phase A | [link](https://drive.google.com/file/d/1sBe9kpQy_3wcjNEF1wC5882nB-_j3KEE/view) |
| Advisor closeout 08-20 | [link](https://drive.google.com/file/d/1h_xtJC467w1sXwmDUY17VXWkFK5VuvyP/view) |

Folder: [Trade_AI_Docs_v2](https://drive.google.com/drive/folders/1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR) → `docs/ops` / `docs/architecture`  
Note: full hourly `sync-docs-to-drive.sh` was aborted mid-archive 404 thrash; key IIC docs uploaded/replaced via `gog` from `origin/main` docs.

---

## Next recommended Builds

1. **Churn dwell / hysteresis** — require sustained NEAR/removed before paging  
2. Preference learning from feedback journal  
3. Catalyst → thesis revise → canary IIC  
4. Held-thesis coverage % toward SLA  

---

*READ_ONLY_ADVISORY — documentation Build 2026-08-21.*
