# G5 — Duplication cluster recommendations (from Census Part 3)

```
Status:      ACTIVE
as_of:       2026-08-31T05:40Z
Measured at: origin/main @ 51da7a4a0 (docs tip); Part 3 classify pin c3e98d4d…;
             Part 3 live reads 2026-08-31T03:22Z from persistent-state
```

**Wave:** Overnight G5  
**Authority:** `READ_ONLY_ADVISORY` · behaviour rail = unconditional raise  
**Branch:** `docs/overnight-g5-duplication-recommendations`  
**FILE SET:** this document only  
**Deploy:** none  
**Hard rule:** **Do not merge any implementations.** Recommendations only.

**Source:** Census Part 3 — Duplication & Supersession (Wave A1 classify-only,
as_of 2026-08-30 / live reads 2026-08-31T03:22Z, pin
`c3e98d4d-main-exact-phase2-20260830-210312`). Reconcile summary in
`/tmp/overnight_wave_a_reconcile.md` and Census Part 5 §9. Adjacent cash-writer
note from overnight B4 (not a Part 3 cluster id — see §Adjacent).

**Urgency rule (from the overnight brief):** the **only** urgent class is
**same quantity computed two ways** (CORRECTNESS). Two different quantities
under one name are LABELING — keep labeled; do not collapse tonight.

---

## Summary matrix

| # | Cluster | LABELING vs CORRECTNESS | Can disagree? | Urgent? | Recommend (no merge tonight) |
|---|---------|-------------------------|---------------|---------|------------------------------|
| C1 | Two reentry books (A / B) | **LABELING** | Yes — by design | No | Keep separate; keep `population` / question / scope stamps (B6). Never merge books. |
| C2 | Home dual reentry pipes | **LABELING** | Yes (different populations) | No | Keep `reentry_pipes.merged=false`; bind counts to named surface. |
| C3 | Identity mint schemes | **CORRECTNESS risk** + naming **LABELING** | Yes if treated as one spine | **Partial** | Separate entity GUID vs event id in language; prefer registry GUID; do not unify algorithms blindly. |
| C4 | ~37 id/memory/lineage modules | **Mixed** (helpers + dark contracts) | Varies | No | Inventory / supersede dark contracts later; not one merge target. |
| C5 | Memory shadow vs live | **CORRECTNESS** | Yes | **YES** | One durability contract; finish or abandon cutover; stop calling both “the memory.” |
| C6 | Lineage `workflow_id` fork | **CORRECTNESS** | Yes — structural | **YES** | One id generator per completion predicate, or explicit crosswalk + health alarm. |
| C7 | Dual lineage products | **LABELING** | Parallel keyspaces | No | Keep `CIOWorkflowLineage` ≠ `IntelligenceLineage` in names and docs. |
| C8 | IP vs OP | **LABELING** if conflated | Derived OP over IP | No | Say “operator view of investment product,” not “two CIO products.” |
| C9 | Quote dual pipes | **CORRECTNESS** | Yes (Alpaca-primary vs Schwab-fresher) | **YES** | One quote quantity for money paths; staged side-by-side before any swap (scoping already exists). |
| C10 | OpenFIGI vs UUIDv5 | **LABELING** (+ join hazard) | Different namespaces | No | Publish join policy before any cross-namespace equality. |

**Urgent this programme (same quantity, two ways):** **C5, C6, C9** (and residual C3 subject-join hazard). Everything else is label hygiene or later inventory.

---

## Per-cluster detail

### C1 — Two `build_reentry_book`s (Surface A / B) → LABELING

| | A | B |
|---|---|---|
| **What it does** | Former holdings vs exit trigger → NEAR / WAIT / AVOID | Desk cash-stage candidates vs R:R under desk thesis → core/micro cards |
| **Producer** | `cio_investment_product.build_reentry_book` | `cio_desk_depth.build_reentry_book` |
| **Surfaces** | Investment brief / operator product / Telegram / Aegis | Desk note / `get_cio_desk_note` / desk telegram |
| **Can disagree?** | **Yes — by design.** Different questions and populations. | |
| **Ever disagreed?** | Expected always; overlap historically thin (e.g. CSCO/AVAV) `[CODE]/DOC-CLAIM]` P93 / Part 3. Live A count **70** (NEAR25/WAIT32/AVOID13) at 2026-08-31T03:22Z `[VERIFIED]` Part 3. | |

**Class:** LABELING (two quantities, one historical name). B6 stamped `population` + question + scope; home `reentry_books.merged=false`.

**Recommend:** Keep both. Do not introduce a precedence winner. Any UI that still says “reentry” without A/B scope is the remaining defect — label, don’t merge.

---

### C2 — Dual reentry pipes on home → LABELING (controlled)

| | Queue chips | Surface A book |
|---|---|---|
| **What it does** | `opportunities.reentry` queue-shaped chips | Stamped Surface A book on home |
| **Surfaces** | `/api/v3/cio/home` via `cio_command_center.build_office_home` | same payload `reentry_books` |
| **Can disagree?** | **Yes** — different populations; `reentry_total` historically confused them. | |

**Class:** LABELING. G-DUAL-01 treated CLOSED by design (`merged=false`) `[DOC-CLAIM]` P1-WS1 / Part 3.

**Recommend:** Keep pipes labeled and unmerged. Counts must name which pipe. No consolidation PR.

---

### C3 — Two identity-minting / id schemes → CORRECTNESS risk + LABELING

| Scheme | What it mints | Algorithm | Authoritative for |
|--------|---------------|-----------|-------------------|
| Spine | `issuer/security/listing/ticker_alias` → registry `subject_guid` | UUIDv5 | Entity durability |
| Canonical event | `evt_*` / optional `wf_*` | SHA-256 trunc 20 | Cross-arc event join |
| (Adjacent) OpenFIGI | `InstrumentIdentity@v1` | FIGI intersect | FS instrument resolve (see C10) |
| (Adjacent) Agent resolver | alias map | string map | Agent fleet IDs only |

**Surfaces:** mint + registry → product stamps / lineage `_stamp_identity`; `cio_canonical_identity.event_id_for` on lineage arcs. Live registry populated `[VERIFIED]` Part 3.

**Can disagree?** **Yes** if code treats entity GUID and event id as one spine. Entity GUID ≠ event id (different quantities → **LABELING** when both called “canonical identity”). Residual **CORRECTNESS** hazard: using ticker as event subject when registry misses.

**Recommend:**  
1. Language: never say “canonical identity” for both.  
2. Prefer `resolve_entity` → registry GUID before ticker.  
3. **Do not merge** UUIDv5 and SHA digests into one mint.  
4. Urgent only for the **ticker-as-subject** miss path (same join key computed two ways) — instrument a miss counter; do not auto-remediate divergent ids.

---

### C4 — ~37 identity / memory / lineage modules → Mixed inventory

**What it is:** Overlapping domain helpers, not 37 peer sources of truth. Part 3 inventory (~12 identity, ~16 memory, ~10 lineage/graph). Many wrap one spine; some are dark contracts (`event_identity` historically, `cio_disposition_identity`, unused `memory_fact` production writers).

**Surfaces:** varies by module; see Part 3 module map.

**Can disagree?** Only where a dark contract and a live path claim the same role — then it is a C5/C6-class problem, not a bulk merge.

**Recommend:** No mega-merge. Future archive / supersession rows (Part 4 / G4) for true dark contracts after a second observation. Keep helpers.

---

### C5 — Memory: `memory_fact` shadow vs `agent_durable_memory` live → CORRECTNESS · **URGENT**

| | Shadow | Live |
|---|---|---|
| **What it does** | Designed bitemporal `MemoryFact@v2` spine | JSONL durable AIF memory |
| **Writers / readers** | Consolidator / M2 / tests; docstring “SHADOW…not cut over” `[CODE]` | Admission → `data/cio/aif_memory.jsonl` `[VERIFIED]` present |
| **Can disagree?** | **Yes** — different schemas (`subject_guid` live vs unused bitemporal shadow). | |

**Class:** CORRECTNESS — one durability quantity, two stores/writers. Also LABELING on the word “memory.” Influence remains 0 on both `[DOC-CLAIM]` Part 3.

**Recommend (urgent, still no merge tonight):**  
1. Pick **one** durability contract for production admission.  
2. Either finish cutover to `MemoryFact@v2` with a dual-write+compare window, or formally abandon shadow writers and stop scheduling them.  
3. Never auto-merge divergent rows; report both.  
4. Operator decision required before deleting either path.

---

### C6 — Lineage arcs / `workflow_id` fork → CORRECTNESS · **URGENT**

| | Arc A | Arc B |
|---|---|---|
| **What it does** | Research + checkpoint ids (`wf_` + digest) | CIO + notification run UUID |
| **Surfaces** | `cio_lineage`, `cio_lineage_health`; one completion predicate `is_complete_to_checkpoint` | |
| **Can disagree?** | **Yes — structural.** Completion can stay false without a stage failure when ids don’t join. | |

**Class:** CORRECTNESS — one completion quantity, two id generators. Completion baseline 406/752 (54%) `[DOC-CLAIM]` P1-WS1 / Part 3 (not re-run this pass).

**Recommend (urgent):**  
1. Single `workflow_id` mint at the start of any arc that the completion predicate reads, **or**  
2. Explicit crosswalk table + health finding when arcs cannot join.  
3. Do not “fix” completion by OR-ing unrelated ids.  
4. Ship measurement (disagree rate) before any id-rewrite migration.

---

### C7 — Two lineage products → LABELING

| | `cio_lineage` | `intelligence_lineage` |
|---|---|---|
| **What it does** | CIO workflow envelopes (`CIOWorkflowLineage@v1`) | Intelligence closed-loop statuses (`IntelligenceLineage@v1`) |
| **Can disagree?** | Parallel — not the same keyspace. | |

**Recommend:** Keep both names distinct in APIs and docs. Not urgent. Not a merge candidate.

---

### C8 — Operator product vs investment product → LABELING if conflated

| | IP | OP |
|---|---|---|
| **What it does** | Four-books producer (`build_product` / investment brief) | 25-section CC view over `cio.product.current` (`build_operator_product`) |
| **Surfaces** | Brief / books | CC home / OP JSON; OP **reads** IP |
| **Can disagree?** | Derived projection — disagreement means OP is stale or bypassing IP, not a second book. | |

**Note:** Part 1 Finding C-13 — `refresh_operator_product.py` is `LIVE_UNCONSUMED` (writes OP stores nobody reads; consumers re-derive). That is consumption debt, not twin producers of one number.

**Recommend:** Naming hygiene (“operator view of IP”). Wire or stop the unconsumed refresh (separate from duplication merge). Do not collapse IP into OP.

---

### C9 — Quote dual pipes → CORRECTNESS · **URGENT**

| | Watch pipe | Trading / proposals pipe |
|---|---|---|
| **What it does** | Writes `market_quotes` | Writes `market_quote_snapshots` via `get_best_quote` / `store_quote` |
| **Provider bias** | Alpaca-primary | Schwab-primary-when-fresher |
| **Surfaces** | Watch enrichment / watch canonical quote | Proposal sizing, gates, execution readiness (Tier 1 consumers) |
| **Can disagree?** | **Yes** — structural provider preference, no reconciliation step `[DOC-CLAIM]` `QUOTE_PIPELINE_UNIFICATION_SCOPING_2026-08-27.md`. | |

**Class:** CORRECTNESS — **same quantity (price) computed / selected two ways.**

**Recommend (urgent):**  
1. Follow existing scoping: side-by-side compare logging before any blind swap.  
2. Money paths (Tier 1) must read **one** declared pipe; display may keep watch freshness if labeled.  
3. Do not average quotes. Escalate divergences.  
4. Operator-gated migration; out of scope for this docs PR.

---

### C10 — OpenFIGI FS vs UUIDv5 spine → LABELING (+ join hazard)

| | OpenFIGI FS | UUIDv5 registry |
|---|---|---|
| **What it does** | `InstrumentIdentity@v1` via FIGI intersect | `subject_guid` spine |
| **Surfaces** | `financial_senses/identity.py` | `security_identity.py` / registry |
| **Can disagree?** | Different namespaces — equality without a join policy is a bug. | |

**Recommend:** Document join policy (FIGI → listing → subject_guid) before any code assumes equality. Not urgent until a cross-namespace join ships without a map.

---

## Adjacent (not Part 3 cluster ids — still same-quantity CORRECTNESS)

Called out so G5 does not pretend Part 3 was the whole urgency set:

| Finding | Source | Class | Urgent? | Note |
|---|---|---|---|---|
| **Cash dual writers** (`position_rows` vs `portfolio_totals` / temperament.cash) | Overnight B4 separate finding; Part 5 §3 | **CORRECTNESS** (~$52.7k historical disagree) | **YES** | Labelling of `as_of` fixed in B4/B5; **dollars not reconciled**. Operator-only to collapse/merge writers. |
| **Two holdings copies** (hub vs release `holdings.json`, same size / different hash) | Part 1 §7; G1 brief | **CORRECTNESS** | **YES** when both treated authoritative | G1: fix at resolution layer; **never auto-remediate**; collapsing copies is operator-only. |

These are not new Part 3 rows; they meet the same urgency rule.

---

## What G5 deliberately does **not** do

- No code merges, no store collapses, no archive moves.  
- No averaging of cash, quotes, holdings, or memory.  
- No inventing SUPERSEDED verdicts for modules Part 3 left as helpers.  
- No deploy.

---

## Evidence index

| Tag | What |
|---|---|
| `[DOC-CLAIM]` Part 3 / A1 | Cluster table and classify-only verdicts, pin `c3e98d4d…`, live 2026-08-31T03:22Z |
| `[DOC-CLAIM]` Part 5 §9 | A1 reconcile LABELING vs CORRECTNESS summary |
| `[DOC-CLAIM]` B4 | Cash writer disagree ~$52.7k; as_of labelling only |
| `[DOC-CLAIM]` B6 | Reentry population/question/scope stamps |
| `[DOC-CLAIM]` Quote scoping 2026-08-27 | Two quote tables / provider biases |
| `[VERIFIED]` in Part 3 | Surface A count 70; OP stamped A; desk note Surface B banner; identity registry live; `aif_memory.jsonl` present |

---

## Operator-only (unchanged)

Collapsing dual holdings copies · merging divergent authoritative stores · quote-pipe cutover · memory cutover · cash dollar reconciliation · any broker work · raising the behaviour rail · archiving without G4 mechanism + approval.
