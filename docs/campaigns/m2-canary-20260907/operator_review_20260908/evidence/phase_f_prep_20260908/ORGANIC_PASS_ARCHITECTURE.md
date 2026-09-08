# Organic PASS architecture — 8 Stage-3 IDs

Campaign: `m2-canary-20260907`  
Prepared: `2026-09-08T22:48Z`  
Pin / release: `aaa9115cbc2745b34a6d0a48cbdbd012c0ac6816` / `aaa9115cb-main-exact-phase2-20260908-171709`  
Activated: `~2026-09-08T22:35Z`  
Policy: **ORGANIC_ONLY** (`OPERATOR_DECISIONS` #6; controlled canary does **not** pad)  
Deadline: organic non-none by `2026-09-10T21:08:30Z`  
**No M2 PASS claimed. No organic rows manufactured.**

---

## 1. What honest Phase F PASS requires

Operator bar (Q9) = **Stage-3 organic soak seal**, not Stage-2 controlled proofs alone.

| Layer | Requirement |
|---|---|
| Identity | API / CURRENT / seal agree on pin + release `171709` |
| Non-organic | Prior A–D IDs adjudicated; `I-SCHEMA-V2` cleared via DT-09 |
| Collector READY | `scheduled_wakes≥3`, `selector_disposition`, `research_consumption`, `gateway_canary_delivery`, `inbound_operator_consumption`, `organic_commitment`, no dups / unexplained legacy fallbacks |
| Stage-3 organic | Post-**activate** evidence on CURRENT pin for the 8 IDs below |
| Separation | Controlled SETTLED / inbound OK stay labeled controlled; never pad research/commitment |

Collector `scheduled_wakes≥3` from `since=collector START` (21:18Z) **must not** be confused with Stage-3 “≥3 consecutive known-trigger wakes **post-activate on 171709**.”

---

## 2. Per-ID: waiting vs structurally broken

| ID | Gate meaning | Status @ ~22:45Z | Class | Notes |
|---|---|---|---|---|
| **I-SOAK-ORGANIC-TRIGGER** | ≥3 consecutive hourly slots with known `selection_source` (`material_change` / `unconsumed_research`), post-activate on `171709` | **Waiting** | Wall-clock | Last wake `22:00Z` was pre-activate / not on `171709` feed. Next CURRENT-resolved slot expected `23:00` then `00:00`/`01:00`. Cron already CURRENT-resolving. |
| **I-WAKE-EVENT** | Organic wake → `CommunicationEvent` → gateway SETTLED | **Structurally broken (ops + code)** | Fixable | Wake cron sets `PERSISTENT_WAKE_ENABLED` + schedule only — **not** `PERSISTENT_WAKE_GATEWAY_OUTBOUND=1` / `PERSISTENT_WAKE_GATEWAY_DELIVER=1`. Even when controlled proof sends, `settle_delivery` dropped `delivery_owner` from delivery coords (see §3). |
| **I-RES-INGEST** | Organic research ingest/store advancement after epoch | **Waiting** (path OK if feed healthy) | Wall-clock + feed | Feed @:55 must write under `171709` (last write `21:55Z` → `170443`). Research proxy comes from `agent_wake_receipts` (`wake_selection_feed.export_research_proxies`). Counts alone ≠ non-none. |
| **I-RES-MENTION** | research → stored → subject/mention edge | **Waiting** | Wall-clock | Depends on dossier/mention evidence in organic research; cannot force under ORGANIC_ONLY. |
| **I-RECEIPT-SUPPRESS** | Organic receipt with `effect_kind != none` | **Collector blind + waiting** | Fixable observability + wall-clock | Inbound apply log is correctly `effect_kind=none` (ordinary inbound). Lane A `default_decide` emits `changed_question` + commitment on selection wakes into **JSONL**, not Postgres. Collector previously only queried Postgres → false-negative `research_consumption`. |
| **I-MEM-CONSUME** | Memory/commitment consumer edge organically | **Waiting** (path present) | Wall-clock | `default_decide` memory path → `changed_commitment` / `MEMORY_SALIENCE`. Empty memory + selection still acts via `allow_empty_memory`. |
| **I-COMMIT-CREATE** | Organic commitment create on pin | **Collector blind + waiting** | Fixable observability + wall-clock | Lane A writes `commitments.jsonl` (`SELECTION_OBSERVATION` / `MEMORY_SALIENCE`). Collector previously only scanned Postgres `agent_commitments`. |
| **I-COMMIT-EVAL** | Commitment eval/outcome organically | **Waiting** | Wall-clock | Needs create first + later eval/settle path; not inventable. |

### Collector tick snapshot (not PASS)

Last tick `2026-09-08T22:33:33Z`: present = `scheduled_wakes≥3`, `selector_disposition`, `inbound_operator_consumption`; missing = `research_consumption`, `gateway_canary_delivery`, `organic_commitment_or_outcome`.  
`ORGANIC_TRACES.json` empty until collector DONE (expected while soak running).

### `effect_kind=none` pattern (inbound apply)

`/home/johnclaw/logs/agent_consume_inbound_apply.log` shows `source_kind=comm_event`, `effect_kind=none`, `persisted=db`. That is **contract-correct** for ordinary inbound (`test_ordinary_traffic_records_effect_kind_none`). It does **not** prove research maturity and must not be padded by controlled canary.

---

## 3. Concrete fixes (code / config / cron)

### A. Code — stamp `delivery_owner` on settle (**PR-needed**)

**Bug:** `settle_delivery(..., delivery_owner="gateway")` mirrored owner onto the in-memory event only; DB/memory `provider_coordinates` kept transport coords without `delivery_owner`. Soak READY requires `provider_coordinates.delivery_owner == "gateway"` + pmid + SENT/SETTLED.

**Fix (implemented in dry worktree):**  
`/home/johnclaw/trade-ai-worktrees/m2-remediation-dry-20260908/scripts/lib/comms/delivery.py`  
- `_merge_settlement_coordinates` merges `delivery_owner` / `gateway_mode` into coords before persist (memory + DB).  
- Test: `tests/test_comms_delivery_ledger.py::test_settle_merges_delivery_owner_into_provider_coordinates`

**Promote:** PR → build → serve on canary pin → **one** controlled re-send (`ops/canary_gateway_outbound_proof.py`) so soak sees stamped row. Do not re-send without the stamp.

### B. Ops — soak collector JSONL research/commitment scan (**ops-only**, campaign tree)

**Bug:** Lane A organic effects/commitments live under `data/persistent_wake/state/{receipts,commitments}.jsonl`; collector ignored them for READY gates.

**Fix (implemented):**  
`/home/johnclaw/trade-ai-campaigns/m2-canary-20260907/ops/m2_canary_soak_collector.py`  
- Shared `_jsonl_store_rows` + since-filter  
- Append non-none `research_object` receipts → `research_consumptions`  
- Append JSONL commitments → `commitments_outcomes`  
- Wake since-filter now actually applies (was previously a no-op `pass`)

**Restart:** running collector (PID from Phase E status) still has old code in memory — restart soak collector after ops edit so ticks use the new probes. No DB mutation.

### C. Cron / env — wake → gateway path (**ops-only**, needs cron grant)

Hourly wake line currently injects wake/schedule flags + selection feed paths only. For `I-WAKE-EVENT` / organic gateway from wakes, also need (per `SFR_G_003_CONFIG.md`):

```text
PERSISTENT_WAKE_GATEWAY_OUTBOUND=1
PERSISTENT_WAKE_GATEWAY_DELIVER=1
```

(plus existing CANARY mode / allowlist / Telegram auth already used by controlled proof).  
**Not applied here** (no cron grant; prefer operator-approved crontab edit).

### D. Not a code bug

- Inbound `effect_kind=none` under apply cron — by design.  
- Pre-activate `22:00Z` SETTLED wakes — real, but do not count for Stage-3 consecutive-on-`171709`.  
- `ORGANIC_ONLY` — no synthetic research/commitment inserts.

---

## 4. What cannot be fixed without wall-clock organic events

1. Three consecutive **post-activate** known-trigger slots on `171709` (`23:00` / `00:00` / `01:00` earliest if feed@:55 + wake@:00 stay healthy).  
2. True organic research content that yields mention edges (`I-RES-MENTION`) and non-none effects that are not just collector false-negatives.  
3. Commitment **eval**/outcome after create (`I-COMMIT-EVAL`).  
4. Claiming READY / M2 PASS before soak archive seals under ORGANIC_ONLY.  
5. Padding with controlled Telegram canary (forbidden by policy #6).

If after deadline organic non-none never appears: honest `AWAITING` / F **FAIL** with residual E-IDs — or operator may lock path-proof-only (still not Stage-3 organic seal).

---

## 5. Mapping: collector READY ↔ organic IDs

| Collector present key | Primary organic IDs unblocked when true (honestly) |
|---|---|
| `scheduled_wakes≥3` + known sources post-activate | `I-SOAK-ORGANIC-TRIGGER` (need consecutive-on-pin adjudication beyond raw count) |
| `research_consumption` (non-none) | `I-RECEIPT-SUPPRESS`, supports `I-RES-INGEST` |
| `organic_commitment` | `I-COMMIT-CREATE` (eval separate) |
| `gateway_canary_delivery` | Necessary for soak READY; organic wake→event still needs wake gateway flags (`I-WAKE-EVENT`) |
| `inbound_operator_consumption` | Already present (controlled/inbound); does **not** clear research IDs |

---

## 6. PR-needed vs ops-only

| Change | Class | Path |
|---|---|---|
| `settle_delivery` owner stamp | **PR-needed** (then promote to served pin) | dry worktree `scripts/lib/comms/delivery.py` + test |
| Soak collector JSONL probes | **Ops-only** (campaign ops; restart collector) | `ops/m2_canary_soak_collector.py` |
| Wake cron GATEWAY_* flags | **Ops-only** (crontab grant) | user crontab wake @:00 line |
| Controlled re-send after stamp promote | **Ops** (telegram grant) | after PR on CURRENT |
| Organic waits | **Neither** — wall-clock | — |

---

## 7. Attestation

- Read-only diagnosis preferred; code/config fixes only for clear broken CURRENT-resolving path.  
- No organic DB row inserts. No M2 PASS. No `.env` secret dumps.  
- Release-path shell reads were guard-blocked; live wake/feed/cron evidence taken from prior Phase E status + logs under `~/logs` + campaign evidence.
