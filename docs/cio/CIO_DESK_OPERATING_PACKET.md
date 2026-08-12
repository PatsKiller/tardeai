# Trade AI — CIO Desk Operating Packet

| Field | Value |
|---|---|
| **Document** | Trade AI — CIO Desk Operating Packet |
| **Pin** | `desk@v4` |
| **As of** | 2026-08-12T13:51:01Z |
| **Owner** | Alex desk (`owner_agent: alex`) |
| **Authority** | **READ_ONLY_ADVISORY** |
| **Stance** | `defensive_observe` |
| **Thesis published** | 2026-08-12T02:33:26Z |
| **Last reviewed** | 2026-08-12T02:33:26Z |
| **Branch / tip** | `feature/advisory-desk-v1` @ `09031283` |
| **Source of truth** | Live runtime: `safe_current_pin`, thesis store, `data/cio/*`, `config/cio_situations.yaml`, desk note v1.1 |

> **Hard rule:** This packet mirrors **live** desk state only. It does not invent capabilities. Chat and situations have **no** broker, order, stop, or 2FA authority.

---

## 1. Desk thesis — current pin `desk@v4`

### Summary (full body)

Risk-aware observe-only desk under a living thesis. Prefer Data Broker multi-domain evidence; escalate material drift, concentration, and deep drawdowns to the operator. Cash is a feature — stage deployment; never force fills. Every plan pins desk@vN; recommendations must explain fit or tension with this thesis. No unattended trading. READ_ONLY_ADVISORY.

### Stance & bullets

- **Stance:** `defensive_observe`
- No broker/order/stop authority from chat or situations
- Pin every plan to the exact desk@vN pin used for the advice
- Escalate S1 deep DD, S5 high cash, S6 concentration, S8 regime
- Operator ack/rate/defer/done/reject closes the learning loop
- Synthesize holdings + cash/portfolio (+ risk) — never detector-only
- Material events auto-request Hermes research (READ_ONLY)

### Principles

1. Evidence before narrative — numbers only from Data Broker domains  
2. Thesis is governing context, not a footer tag  
3. Cash buffer is intentional optionality until data quality supports deploy  
4. Concentration and deep drawdowns deserve multi-domain synthesis  
5. Operator disposition is the ground truth for future enrichment  
6. Highest-signal action may be non-action under `defensive_observe`

### Risk posture (structured)

| Threshold | Live value |
|---|---|
| `max_single_name_weight_pct` | **12.0%** |
| `cash_band_min_pct` | **20.0%** |
| `deep_dd_threshold_pct` | **25.0%** |
| `concentration_fire_pct` | **≈16.5%** (notify/review band) |

**Notes:** Defensive observe: preserve optionality; prefer hold/stage over force-deploy; trim concentration only with thesis-aware sizing; no auto stops or orders.

### Escalation rules (live)

1. S1 deep DD ≥25% from basis → full material note + Hermes `research_gap`  
2. S5 cash_pct above band (min 20%) → staged deployment options only; never force fills  
3. S6 single-name weight ≥12% (fire ~16.5%) → Morgan-style size & thesis review  
4. S8 defensive regime → material; Hermes high priority  
5. Operator request for research → material / Hermes path  
6. Thesis drift vs linked symbols (SCHD, SPCX) → material multi-domain review  

### Linked / watch symbols

- **Linked:** SCHD, SPCX  
- **Watch:** SCHD, SPCX  

### Learning log (on thesis)

| Kind | Disposition | Note | Symbols | Pin | When |
|---|---|---|---|---|---|
| seed | — | Migrated from desk@v1 defensive_observe; expanded principles/escalation for desk@v2 | — | — | 2026-08-11T20:00Z |
| plan_disposition | **defer** | wait for price buffer | SCHD | desk@v2 | 2026-08-11T21:33Z (`plan_79fe9e72f2d4`, S6) |

### Pin history

| Pin | Published (UTC) | Change note |
|---|---|---|
| desk@v4 | 2026-08-12T02:33:26Z | Operator publish — refresh last_reviewed; continue desk@v2 intelligence OS under defensive_observe |
| desk@v3 | 2026-08-12T02:31:05Z | Formal desk@v2 intelligence OS: structured risk_posture, Hermes on material, multi-domain notify gate, learning loop |
| desk@v2 | 2026-08-11T21:29:23Z | Intelligence upgrade: principles, risk_posture, escalation_rules, learning_log; multi-domain synthesis contract |
| desk@v1 | 2026-08-11T20:07:36Z | P3 bootstrap living desk thesis |

**Intelligence layer label:** `desk@v2_definition` (structure lives under successive pins; current pin is `desk@v4`).

### Live book snapshot (as of packet `as_of` capture ≈ 2026-08-12T13:49Z)

| Metric | Value |
|---|---|
| Book total | **~$1.28M** (`$1,277,397.94`) |
| Cash | **~$578.1K** (**≈45.3%**) vs band min 20% |
| Holdings | 34 |
| Heat | 0.09% |
| Stops active | 25 |
| Top weights | SCHD **17.5%**, V 9.4%, JEPI 6.7%, DIVI 3.5%, XLI 2.9%, ARKX 2.7%, XAR 2.3%, SPCX 2.1%, BND 2.1% |

Open plans (count): **35** — pins: desk@v4 ×11, desk@v1 ×24. Types: S1×11, S2×9, S6×8, S0×4, S5×2, S4×1.  
*(Many routine plans still carry older pins until re-enrich; material desk note uses desk@v4.)*

---

## 2. Authority model — READ_ONLY_ADVISORY

### What this desk **is**

- **Advisory only.** Situations → plans with options, evidence refs, thesis pin, recommendations.  
- **Operator-final.** Dispositions (ack / rate / defer / done / reject) are first-class.  
- **Evidence-bound.** Numeric claims come from Data Broker domains or are marked `DATA_UNAVAILABLE`.  
- **Pinned.** Every plan and Telegram reply should cite the exact `desk@vN` used for the advice.

### What chat / situations **can** do

- Raise and list situations/plans (`S0`–`S8`)  
- Enrich plans (LLM or template) under policy  
- Notify operator on material types (when notify flags allow; once-per-fingerprint ledger)  
- Deep-link to Command Center `/v3/cio` plan pages  
- Record operator dispositions into learning store + thesis `learning_log`  
- Generate desk synthesis note (v1.1) from thesis + snapshot + material plans  
- Enqueue Hermes research on material path (READ_ONLY research gap; fingerprint de-dupe + TTL reuse)  
- Attach structured **catalyst calendar** on plans (severity gates revisit / warm / Telegram; never orders)

### What chat / situations **cannot** do

- Place, modify, or cancel **orders**  
- Create, move, or cancel **stops**  
- Broker login, **2FA**, or account mutation  
- Auto-execute any recommendation  
- Force cash deployment fills  
- Act outside allowlisted Telegram chat IDs (CIO bot only — not main OpenClaw bot)

### Enforcement language (keep consistent)

> No orders/stops from chat · **READ_ONLY_ADVISORY**

---

## 3. Situation catalog — S0–S8

**Config:** `config/cio_situations.yaml`  
**Detector:** `scripts/lib/cio_situation_detector.py` (`situation-catalog-v1.0.0`)  
**Plans:** `data/cio/cio_plans.jsonl` · projection `cio_plans_projection.json`  
**Policy:** detector may run with notify gated; material notify prefers multi-domain evidence.

| Code | Name | Fire (summary, live thresholds) | Owner | Operator disposition |
|---|---|---|---|---|
| **S0** | OPERATOR_CONVERSE | Free-text / continuity plans from CIO Telegram chat | alex | ack / rate / defer / done / reject |
| **S1** | POSITION_LIFECYCLE | Deep DD from basis ≥**25%**, partial recovery ≥**15%**, reclaim, major catalyst | alex | same |
| **S2** | STOP_GAP | No stop or stop inconsistent with basis/recovery | alex | same |
| **S3** | REENTRY_CANDIDATE | Reentry desk status READY/NEAR (read-only; no re-rank) | alex | same |
| **S4** | SECTOR_ROTATION | Material sector momentum / rotation ladders vs holdings (delta **2pp**) | steph | same |
| **S5** | CASH_DEPLOYMENT | Cash above band (**min 20%**) + constructive rotation/watch; label PARTIAL when data quality incomplete | steph | same |
| **S6** | CONCENTRATION_OR_DISPOSITION | Single-name weight ≥**12%** (fire ~**16.5%**) or long-held material loser (loss ≥**20%**, hold ≥**6 mo**) | morgan | same |
| **S7** | WATCH_PROMOTION | Watch READY/GO/strong NEAR (score ≥**70**) | alex | same |
| **S8** | DEFENSIVE_REGIME | Risk-off / defensive regime labels, heat up, defensive proposals | alex | same |

### Operator dispositions (all situations)

| Disposition | Meaning (live product) |
|---|---|
| **ack** | Acknowledge and monitor; no change forced |
| **rate** | Score the advisory quality / usefulness |
| **defer** | Postpone; note retained (feeds learning, e.g. SCHD “wait for price buffer”) |
| **done** | Operator considers the item closed from their side |
| **reject** | Reject the recommendation / close as not applicable |

Telegram: `/cio ack|rate|defer|done|reject <plan_id>` or reply keywords on plan threads.

### Detector ops knobs (live config)

- `dedup_hours`: 12  
- `max_plans_per_pass`: 5  
- `max_notify_per_pass`: 3  
- Notify situation types (policy): S1 / S2 / S5 / S6 / S8 (see `config/cio_llm_policy.yaml`)  
- Once-per-fingerprint notify ledger: `data/cio/cio_plan_notify_ledger.json`

---

## 4. Desk note product (v1.1)

**Code:** `scripts/lib/cio_desk_synthesis.py`  
**Latest render:** `data/cio/cio_desk_note_latest.md`  
**Authority:** READ_ONLY · pins live `desk@vN`

### 7-section structure

1. **Thesis header** — full summary, structured risk posture, principles  
2. **Portfolio snapshot** — book, cash vs band, heat, stops, top weights  
3. **Material situations** — desk-filtered; distinct thesis-fit per situation; multi-domain evidence; plan_id + pin  
4. **Cross-position view** — concentration cluster, cash runway, correlated sleeves, heat  
5. **Desk recommendations** (+ **5b deeper analysis** — what would change the call)  
6. **Learning log** — operator biases active on this note  
7. **Revisit + ack** — plan ids, revisit triggers, `/cio thesis`, READ_ONLY footer  

### Artifact path

- Working note: `data/cio/cio_desk_note_latest.md`  
- API surface: Command Center **`/v3/cio`** (plans + desk hub when release dist is current)  
- Telegram: dedicated `@tradeai_cio_bot` (not main OpenClaw)

### Regenerate commands

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Full note to stdout (CLI = same generator as API path)
PYTHONPATH=scripts .venv/bin/python scripts/lib/cio_desk_synthesis.py

# Persist latest (example — write generator output)
PYTHONPATH=scripts .venv/bin/python -c "
from scripts.lib.cio_desk_synthesis import generate_desk_synthesis_v1
from pathlib import Path
out = generate_desk_synthesis_v1()
Path('data/cio/cio_desk_note_latest.md').write_text(out['note'] + '\n')
print(out['thesis_version'], out['as_of'], 'ok')
"

# Thesis pin / context check
PYTHONPATH=scripts .venv/bin/python -c "
from scripts.lib.cio_theses import safe_current_pin, safe_context_block
print(safe_current_pin())
print(safe_context_block(full=True).get('stance'))
"
```

### Known limits vs wealth-management reports

| Live desk note does | Does **not** (yet / not product) |
|---|---|
| Thesis-aware multi-situation synthesis | Full MS-grade IPS / multi-scenario Monte Carlo |
| Book-level cash / concentration / heat | Tax-lot optimization, estate, liability matching |
| Distinct thesis-fit per material plan | Continuous auto-rebalance or order tickets |
| Learning-informed hold bias (e.g. SCHD defer) | Guaranteed LLM narrative on every plan (Flash can defer → template) |
| Hermes research counts when domains present | Complete re-entry book coverage on every pass |

v1.1 fixes (live): no mid-sentence truncation; distinct thesis-fit; API/CLI snapshot parity intent; deduped learning log; deeper rec analysis section.

---

## 5. Learning loop

### How it works (live)

1. Operator issues **ack / rate / defer / done / reject** on a `plan_id` (Telegram `/cio …` or thread reply).  
2. Event lands in durable store: `data/cio/cio_operator_learning.jsonl`.  
3. Material dispositions can append to thesis `learning_log` (head of governing doc).  
4. Enrichment / desk note reads recent dispositions so future recs **honor operator bias** (e.g. do not re-push trim SCHD after defer “wait for price buffer”).  

### Current highlights (live)

- **SCHD · S6 · defer** — “wait for price buffer” · `plan_79fe9e72f2d4` · pin at disposition `desk@v2` · 2026-08-11T21:33Z  
- Desk note v1.1 still surfaces this as active bias under `desk@v4`  
- Learning store currently thin (seed + SCHD defer); continuous quality learning is **not** fully closed-loop yet (see §6)

---

## 6. Gaps / roadmap — explicit “not yet”

Do **not** treat these as live product claims:

| Gap | Status |
|---|---|
| **Re-entry book** as first-class continuous desk product | Detector S3 exists; full re-entry book depth / always-on coverage **not yet** |
| **Sector defensive posture** as standing OS | S4 fires on rotation signals; no standing multi-sector defensive posture engine beyond detector + owners |
| **Continuous learning quality** | Disposition path exists; volume and closed-loop enrichment quality still early (few logged dispositions) |
| **MS-grade depth** | Desk note v1.1 is portfolio-aware advisory, **not** Morgan Stanley–grade wealth report |
| **Batch re-pin** of open plans to desk@v4 | Open set still mixed (24× desk@v1, 11× desk@v4 at last count) |
| **LLM on every path** | `CIO_LLM_ENRICH=0` forces template; Flash intermittent empty/fail → soft validator / template; material may force template gates |
| **Orders / stops from chat** | **Never** — permanent non-goal under READ_ONLY_ADVISORY |

---

## 7. Host ops

### Regenerate / inspect

```bash
# Situations detector (via heartbeat / reactive — prefer existing CIO paths)
# Manual list open plans:
PYTHONPATH=scripts .venv/bin/python -c "
from scripts.lib.cio_plans import CIOPlanStore
for p in CIOPlanStore().list_open_plans(limit=20):
    print(p.get('plan_id'), p.get('situation_type'), p.get('thesis_version'), p.get('symbols'))
"

# Enrichment force-template soak
export CIO_LLM_ENRICH=0

# Desk synthesis (see §4)
PYTHONPATH=scripts .venv/bin/python scripts/lib/cio_desk_synthesis.py
```

### Telegram CIO bot (dedicated)

- **Bot:** `@tradeai_cio_bot` only — do **not** wire main OpenClaw bot  
- **Env:** `~/.config/tradeai/cio-telegram.env`  
  - `TELEGRAM_CIO_BOT_TOKEN`  
  - `TELEGRAM_CIO_CHAT_IDS` (allowlist)  
  - `CIO_LLM_ENRICH=1` (or `0` for template-only)  
  - `CIO_SITUATION_NOTIFY=1` when operator wants plan push  
- **Unit:** `tradeai-cio-telegram.service` (user systemd)  
- **Code:** `scripts/cio_telegram_bot.py`, `scripts/lib/cio_telegram_converse.py`  
- **Commands:** `/cio thesis`, `/cio ack|rate|defer|done|reject <plan_id>`, free-text → S0 plans  

### Command Center `/v3/cio`

- Hub route: CC v3 **`/v3/cio`** (and `?plan=<plan_id>` deep links)  
- API: `scripts/api_v3_cio.py` (+ portfolio server release tree when serving dist)  
- Tailscale / LAN base used for absolute deep links when configured  

### Key data paths under `data/cio/`

| Path | Role |
|---|---|
| `cio_theses.jsonl` / `cio_theses_projection.json` | Living thesis store + pin projection |
| `cio_plans.jsonl` / `cio_plans_projection.json` | Plans |
| `cio_operator_learning.jsonl` | Operator dispositions |
| `cio_desk_note_latest.md` | Latest desk note render |
| `cio_plan_notify_ledger.json` | Once-per-fingerprint notify guard |
| `cio_llm_enrich_log.jsonl` | Enrichment audit |
| `cio_events.jsonl` / `cio_wake_*.jsonl` | Events / wakes |
| `cio_goals.jsonl` (+ projection) | Goals |
| `cio_telegram_*.jsonl`, `.cio_telegram_offset` | Telegram continuity / rate / dedup |

### Related in-repo docs (`docs/cio/`)

- `DESK_THESIS_V2.md` — governing thesis OS  
- `SITUATION_CATALOG_V1.md` — S1–S8 freeze + live wiring notes  
- `P2B_PLAN_ENRICHMENT.md` — LLM/template enrichment  
- `THESIS_STORE_P3.md` — pin store  
- `CIO_TELEGRAM_CONVERSE_RUNBOOK.md` — bot ops  
- This file: **`CIO_DESK_OPERATING_PACKET.md`** — operator/architect packet (Drive mirror)

### Drive sync

- Canonical Drive root: **Trade_AI_Docs_v2** (`scripts/sync-docs-to-drive.py` / hourly `.sh`)  
- Folder: `docs/cio/`  
- Refresh this Google Doc header (**pin + as_of**) whenever `desk@vN` advances or material behavior changes  

---

## Appendix A — Live material focus (from last desk note)

As of desk note render **2026-08-12T03:20:12Z** under **desk@v4**:

1. **S6 SCHD** — weight ~17.6% vs fire ≈16.5% · hold_with_thesis · honor defer · `plan_05a414a3d105`  
2. **S1 SPCX** — deep DD ~26.9% from basis · small book weight ~2.1% · awareness-only hold · `plan_51e03253ba2d`  
3. **S5 cash** — ~45% cash · quality PARTIAL · hold_cash / stage · `plan_1b8d534354fb`  

All remain **READ_ONLY_ADVISORY**.

---

## Appendix B — Version discipline for this packet

| Event | Action |
|---|---|
| `desk@vN` publish / pin advance | Bump header **Pin** + **As of**; refresh §1 from `safe_current_pin` / thesis body |
| Material detector threshold change | Update §1 risk_posture + §3 thresholds from `config/cio_situations.yaml` |
| Desk note section contract change | Update §4 |
| New disposition product | Update §2 / §5 only when code is live |

**Do not** write aspirational product language into this packet.

---

*End of packet · generated from live runtime · READ_ONLY_ADVISORY · owner Alex desk · pin desk@v4*
