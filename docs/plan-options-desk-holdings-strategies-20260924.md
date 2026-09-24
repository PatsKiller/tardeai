# Plan: Options Desk — holdings strategies · open legs · CIO fluency · goals · BUY_READY options alts

```
Status: ACTIVE
as_of: 2026-09-24T11:55:00-04:00
Measured at: hub holdings.json ~11:30 ET · CC paste ~11:15–11:29 ET · cio_goals_projection 4 open / 0 options-ish · options_desk_latest by_symbol (V CC, SPCX credit_spread, …) · cio_entry_state.render_cio has zero options hook · PR #1215 Stage 1 head ab2653724 (+ Stage 1B dirty on branch)
Canonical store path (parent / SoT):
  /home/johnclaw/.local/state/cursor/agent-stores/cursor_agent_stores/bc-5f36c3f9-c05b-4ca3-983d-4b3c5b7889ec/files/docs/plan-options-desk-holdings-strategies-20260924.md
Repo mirror: docs/plan-options-desk-holdings-strategies-20260924.md
Companion (operator skim): docs/options-desk-operator-contract-20260924.md (same folders) — linked; this file is authoritative
Authority: operator product contract (John) + live Options Hub / reentry_desk / cio_goals measurements + options_engine / options_lifecycle_engine / cio_entry_state / cio_operator_desk_loop
Supersedes: thinner “gated not broken” take; 11:35 product-contract rewrite; 11:48 open-leg addendum — this revision folds CIO fluency, strategy goals, and BUY_READY options alternatives into one SoT
See also: AGENTS.md §2 / §6 / §7A / §17 · assets/portfolio_intent.yaml · scripts/options_engine.py · scripts/options_lifecycle_engine.py · scripts/lib/cio_entry_state.py · scripts/cio_entry_state_runner.py · scripts/lib/cio_goals.py · scripts/lib/cio_operator_desk_loop.py · apps/command-center-v3/src/pages/OptionsHub.tsx
```

**One-line verdict.** Path B + Schwab chain are **built**. The remaining product gaps are: **owned-book silence** (funnel), **open-leg honesty** (P&L/criteria/margin), **CIO options fluency + goal lineage** (desk is demoted; 0 options goals), and **BUY_READY notices that only offer equity** (no capital-efficient options alternative). **Do not invent strategy types or widen IV/intent gates** without operator word.

---

## A · Full product contract (every ask in one table)

| # | Operator ask | Status today | Stage | Evidence |
|---|---|---|---|---|
| **P1** | Covered-call / put / CSP / spread **suggestions on book + conviction**, with **live Schwab chains** and **Path B per-order 2FA** | **PARTIAL / BUILT mix** — generators + chain API + Path B exist; owned CC sleeve often =1 (V); many size-eligible names silent | **1** (funnel CLOSED on PR) · **2** intent map (operator) · **4** protective-put funnel | `[CODE]` `options_engine` · `[VERIFIED]` paste Portfolio sleeve **1** · Path B **ARMED** · SPCX live spread |
| **P2** | **Open legs:** live P&L, credit/debit economics, **margins/BP**, **sell vs hold / roll** with **printed criteria** — not silent “—” | **PARTIAL** — monitor + Lifecycle already recommend Hold/Close/Roll/Harvest; margin **absent**; criteria often not chip-visible; dual tabs | **1B** CLOSED in code on branch (pending push/CI) | `[CODE]` `_monitor_position` · `strategy_economics` · OptionPositionCardV4 |
| **P3** | **CIO knowledgeable** on every strategy the desk supports (CC, CSP, protective put, credit/debit spreads, deep ITM paper, …) — not silent/generic | **GAP** — desk has generators + strategy_matcher; CIO Telegram path **demotes** `options_desk` research (`_SECONDARY_RESEARCH`); no fluency catalog on desk replies; evidence contract says option_chain “belongs to Options desk” not Telegram | **1C** | `[CODE]` `cio_operator_desk_loop._SECONDARY_RESEARCH` · `config/operator_evidence_contract.json` `never_needed.option_chain` · Visa litmus history |
| **P4** | CIO **advises/opines** on option strategies (fit vs book, regime, why this name/structure **now**) via **real CIO desk paths** / `finalize_operator_reply` — **no fake specialist roleplay** | **GAP** — no `options_strategy` intent; no house-facts gatherer for desk strategies; replies either drown in identical CC rows or ignore options | **1C** | `[CODE]` `analyze_operator_intent` · `finalize_operator_reply` · `format_subject_brief` |
| **P5** | Option strategies have **goals** tied to **securities / sectors / industries** (cio_goals or equivalent predicates) — not orphan ideas | **ABSENT** — hub `cio_goals_projection`: **4** open goals, **0** options-ish. Live titles: Desk morning thesis · Telegram curation · Allocation practicality · Cash concentration cost. `create_goal` has `linked_symbols` only — **no sector/industry/strategy fields** on the goal schema today | **1C** (stamp lineage + templates) · **2G** (operator mint goals) | `[VERIFIED]` 2026-09-24 hub projection · `[CODE]` `cio_goals.create_goal` |
| **P6** | **BUY_READY / reentry_desk / entry notices** show **equity sizing plan AND** a **capital-efficient options alternative** when thesis/confidence warrant (e.g. V: defined-risk call / debit / spread / stock-replacement mapped to same zone/stop/target) — honest when unsuitable | **ABSENT** — `cio_entry_state.render_cio` / `render_operator` are equity-only (“Confirm or refute the entry”). `format_reentry_symbol_reply` is equity zone/gates only. **No options hook.** Desk cache for V today is **covered_call** (income on held shares), not a long-call/debit stock-replacement for a new entry | **1D** | `[CODE]` `cio_entry_state.py:188` · `[VERIFIED]` `options_desk_latest` V→CC only · John morning notice example |
| **P7** | **Holdings funnel** — name why each holding is/ isn’t a CC/put idea (no silent drop) | **CLOSED** (PR #1215 Stage 1) | **1** | `build_holdings_funnel` · `GET /api/v2/options/holdings-funnel` · OptionsHub panel · tests |

**Non-goals (Stage 5 / operator-only):** invent new strategy types · unilateral IV/intent widen · invent Reg-T / margin dollars · broker auto-submit · fake “options specialist” agent · auto-mint cio_goals without operator grant · treat Deep ITM paper strip as live desk health.

---

## B · Diagnosis receipts (measured, not assumed)

### B1 · Holdings / Path B / chain (P1, P7)

| Fact | Value | Tag |
|---|---|---|
| Portfolio sleeve on paste | **1** (V CC) | `[VERIFIED]` paste |
| Size-eligible owned (≥100 sh) | XLB 504 · SPCX 400 · WMT 400 · MCD 300 · V ~131 · XAR 100 | `[VERIFIED]` hub holdings ~11:30 ET |
| `covered_call_candidate` intent | **V · LMT · SCHD** only | `[CODE]` portfolio_intent.yaml |
| Schwab chain | `GET /api/v2/schwab/option-chain` + Hub View Chain | `[CODE]` |
| Path B | preflight → intent → 2FA when ARMED | `[CODE]` + paste ARMED |
| Funnel API | Stage 1 on PR #1215 | `[CODE]` |

### B2 · Open legs (P2)

| Fact | Value | Tag |
|---|---|---|
| Unrealized P&L / % captured / Hold·Close·Roll | Built in `_monitor_position` + Lifecycle | `[CODE]` |
| Margin/BP on option surfaces | **Never stamped** (Stage 1B → `MARGIN_UNKNOWN` unless Schwab field present) | `[CODE]` |
| Silent “—” when mark/entry missing | Honesty gap → `PNL_UNKNOWN` + reason (1B) | `[CODE]` |

### B3 · CIO fluency + goals (P3–P5)

| Fact | Value | Tag |
|---|---|---|
| Open cio_goals | **4** | `[VERIFIED]` hub `cio_goals_projection.json` |
| Options-ish goals | **0** | `[VERIFIED]` blob scan option/CC/CSP/spread/wheel/IV |
| Goal schema links | `linked_symbols` only — no strategy / sector / industry columns | `[CODE]` `create_goal` |
| Desk research demotion | `options_desk ∈ _SECONDARY_RESEARCH` (correct vs Visa drowning; wrong as sole CIO options channel) | `[CODE]` |
| Strategies desk actually supports | covered_call · cash_secured_put · protective_put · credit_spread · long_call · (+ paper deep ITM / earnings verticals in pipeline registry) | `[CODE]` `STRATEGY_SLOTS` · strategy_matcher |
| Evidence contract | `option_chain` listed under `never_needed` for Telegram desk | `[DOC-CLAIM]`/`[CODE]` — **revise carefully**: live chain stays Hub; **house strategy facts** must still reach CIO replies |

### B4 · BUY_READY options alternative (P6)

| Fact | Value | Tag |
|---|---|---|
| Morning notice shape | “Entry state BUY_READY for V … zone … stop … target … Plan source reentry_desk. Confirm or refute…” | John example + `[CODE]` `render_cio` |
| Options text in render_cio / render_operator | **None** | `[CODE]` |
| Reentry symbol reply options block | **None** | `[CODE]` `format_reentry_symbol_reply` |
| Desk cache for V (hub runtime) | **covered_call** only — income on shares already held, **not** a capital-efficient way to express a new BUY_READY thesis | `[VERIFIED]` `options_desk_latest` |
| Existing generators usable as alts | `long_call` · credit/debit spreads · deep ITM paper / proxy stock-replacement — **exist**, not wired into entry notices | `[CODE]` |

---

## C · Stages (diagnose → fix vs develop)

### Stage 0 — Clarity / copy — **FIX** (docs)

- Empty-state vocabulary: Unprotected ≠ no CC; Deep ITM paper ≠ live; “30 need action” ≠ 30 option closes.
- This SoT documents P1–P7 end-to-end.

### Stage 1 — Holdings funnel + honest empty states + chain surfacing — **CLOSED** (PR #1215)

**Implements P7 + honesty for P1.**

1. `build_holdings_funnel()` — per holding named drop reason (`NEED_100_SHARES` · `IV_BELOW_FLOOR` · `EDGE_BELOW` · `INTENT_BYPASS` · `SLOTTED` · …). **Does not change gates.**
2. `GET /api/v2/options/holdings-funnel`
3. OptionsHub panel under Ideas
4. Tests `tests/test_options_holdings_funnel.py`

**Acceptance**

| ID | Check | Pass |
|---|---|---|
| A1.1 | SCHG/AMANX | `NEED_100_SHARES` |
| A1.2 | ≥100 low-IV non-intent | Named `IV_BELOW_FLOOR` / `EDGE_BELOW` — never silent omit |
| A1.3 | Intent CC path | `INTENT_BYPASS` or `SLOTTED` |
| A1.4 | API | `rows` + `summary` |
| A1.5 | Hub empty sleeve | Surfaces funnel counts |
| A1.6 | No gate widen | IV/intent floors unchanged |

### Stage 1B — Open-leg P&L / criteria / margin honesty — **CLOSED in branch code** (push/CI/merge with #1215)

**Implements P2.** Attach only — no new strategy product.

1. `PNL_UNKNOWN` + reason when entry/mark missing  
2. `action_criterion` plain-English under recommended action  
3. Entry credit/debit + max profit on Open Options card  
4. Proposals strip → “N open legs — Open Options / Lifecycle”  
5. Margin: Schwab field → stamp; else `MARGIN_UNKNOWN` — **never invent dollars**  
6. Tests `tests/test_options_open_leg_honesty.py`

**Acceptance**

| ID | Check | Pass |
|---|---|---|
| A1B.1 | Missing entry/mark | `PNL_UNKNOWN` not blank “—” only |
| A1B.2 | Short OTM + high POP + +PnL | Close for Profit + criterion string |
| A1B.3 | No Schwab margin field | `MARGIN_UNKNOWN`, `margin_usd is None` |
| A1B.4 | Lifecycle close | Still hash-bound → 2FA; no auto-close |
| A1B.5 | Design guard | OptionsHub / cards use BB/T tokens — no raw hex / font &lt;10 regressions |

### Stage 1C — CIO options fluency + strategy goals (security / sector / industry) — **DEVELOP**

**Implements P3–P5.** Real CIO paths only.

#### Diagnosis (done)

- CIO is **not** fluent on the operator surface: options research is secondary; no strategy catalog in replies.  
- **0** `GOAL_CREATED` rows are options/sleeve/strategy goals.  
- Goal store can link **symbols**, not yet sector/industry/strategy predicates as first-class fields.

#### High-confidence wiring (no new strategy types, no auto-mint goals)

1. **`scripts/lib/cio_options_fluency.py`** (new, thin)  
   - Catalog = strategies the desk **already** supports (`STRATEGY_SLOTS` + pipeline registry ids) with one-line CIO meaning (income / hedge / defined-risk directional / paper educational).  
   - `gather_options_house_facts(symbols)` reads **cached** `options_desk_latest` / proposals + holdings funnel summary — **not** live Schwab chain at Telegram time.  
   - `goal_lineage_for_proposal(symbol, strategy)` → `LINKED` if an open goal’s `linked_symbols` matches **and** title/description/thesis mentions options/strategy terms; else `ABSENT` with honest reason.  
   - **Does not** call `create_goal`. Templates for operator mint only.
2. **Desk intent** — detect options-strategy questions (`covered call`, `CSP`, `protective put`, `credit spread`, `debit`, `LEAP`, `options play`, …) → `intent=options_strategy` / need `options_strategy`.  
3. **Gather + reply** — inject house facts into `available`; format opinion (fit vs book, why now, Path B pointer); exit via **`finalize_operator_reply`**.  
4. **Evidence contract** — add `options_strategy` intent (state files: options_desk_latest, holdings). Keep live `option_chain` Hub-only.  
5. **Proposal stamp** — each desk proposal carries `goal_lineage: {status, goal_id?, subject_key?, sector?, industry?}` (ABSENT until goals exist).  
6. **Optional sector/industry on lineage** — read from `symbol_profiles` (already used by entry runner) when stamping; still no schema migration required for Stage 1C.

#### Operator-only follow-on (Stage 2G)

Propose minting goals such as:

- “Income sleeve: covered calls on held ≥100 sh in **Financials** / **V**”  
- “Defined-risk expression for BUY_READY names in **Technology**”  

with `linked_symbols` + success_criteria naming strategy + sector/industry. **Agent proposes; operator grants** (§17-adjacent). Predicate terms may reuse `all_terms_true@v1` with new term names only after evaluator exists — until then success_criteria prose + linked_symbols is enough.

**Acceptance**

| ID | Check | Pass |
|---|---|---|
| A1C.1 | Catalog lists every desk-supported strategy id currently generated | Hermetic unit test vs `STRATEGY_SLOTS` ∪ registry enabled set |
| A1C.2 | “What’s a covered call on V?” path | House facts from desk cache + Sources via `finalize_operator_reply` — no specialist persona |
| A1C.3 | Live goals scan | Report `options_goals_open: 0` until operator mints — never fake LINKED |
| A1C.4 | Proposal without matching goal | `goal_lineage.status == ABSENT` |
| A1C.5 | No IV/intent widen · no `create_goal` from this stage | AST / test guards |
| A1C.6 | Live option_chain not called from Telegram gather | Same |

### Stage 1D — BUY_READY / reentry entry notices include options alternative — **DEVELOP**

**Implements P6.** Attach to **existing** entry render + existing generators/cache — not a new product.

#### Diagnosis (done)

- `render_cio` / `render_operator` / `format_reentry_symbol_reply` are **equity-only**.  
- For **V BUY_READY**, a covered_call on the desk is the **wrong** alternative class if the question is “don’t lay out full equity capital” — need **long_call / debit spread / deep-ITM stock-replacement** mapped to zone/stop/target.  
- Those generators exist; they are **not** invoked from the entry notice path. Cache may be empty for that class → must say so honestly.

#### High-confidence wiring

1. **`format_entry_options_alternative(symbol, entry_low, entry_high, stop, target, *, state)`** in `cio_options_fluency` (or thin helper next to `cio_entry_state`):  
   - Prefer cached proposals for symbol where `strategy ∈ {long_call, credit_spread, debit_spread, …}` **and** structure is directional/defined-risk (exclude covered_call unless already held and notice is “add”).  
   - Map strike/breakeven to zone/target when numbers exist; cite `max_loss` / debit as capital vs buying 100 sh.  
   - Point to Options Hub Path B (View Chain → preflight → 2FA) — never imply auto-submit.  
   - If none suitable: **`OPTIONS_ALT_NONE`** with reason (`NO_DESK_PROPOSAL` · `IV/LIQUIDITY` · `WRONG_STRATEGY_CLASS` · `PAPER_ONLY`).  
2. Append block to **`render_operator`** and **`render_cio`** (and optionally `format_reentry_symbol_reply` when state is BUY_READY / inside zone).  
3. **Thesis/confidence gate:** only attach when entry state is `BUY_READY` (or `ENTRY_NEAR` with soft “if you want defined-risk expression”). Do not spam options on blocked/wash names.  
4. **CIO confirm path:** CIO message asks confirm/refute **equity entry and, when present, the options alternative** — still advisory.  
5. Tie to Stage 1C: if a security-level options goal exists for the ticker, cite `goal_id` in the alt block.

**Acceptance**

| ID | Check | Pass |
|---|---|---|
| A1D.1 | BUY_READY fixture with long_call in cache | Notice contains options alt + debit/max_loss + Path B pointer |
| A1D.2 | BUY_READY with only covered_call in cache (V-like) | Honest `OPTIONS_ALT_NONE` / wrong-class — **not** “sell CC” as stock-replacement |
| A1D.3 | No proposals | Honest none + “check Options Hub” — equity block unchanged |
| A1D.4 | render still advisory | No order language; MBI_BEHAVIOR=0 |
| A1D.5 | Existing entry tests | Still pass; new tests for alt block |
| A1D.6 | No live Schwab call inside alert render | Cache/read-only only (chain stays Hub) |

### Stage 2 — Intent map refresh — **OPERATOR ONLY**

Propose size-eligible income names for `covered_call_candidate` (e.g. MCD, WMT, SPCX); remove LMT/SCHD until ≥100 held. **Propose and stop.**

### Stage 2G — Mint options strategy goals — **OPERATOR ONLY**

After 1C templates exist: operator grants GOAL_CREATED rows linking symbols (± sector/industry in success_criteria). Agent never auto-mints.

### Stage 3 — Optional low-VIX owned-name policy — **OPERATOR DECISION**

Only if Stage 2 is too manual. Explicit `fallback_tier`. No ship without word.

### Stage 4 — Protective-put funnel visibility — **DEVELOP** (can ride Stage 1 patterns)

### Stage 5 — Out of scope

New strategy types · invent margin math · auto-submit · fake specialists · Deep ITM as live health · unilateral gate widening · Finviz remediation (separate).

---

## D · Action map (unchanged truth)

```
Force scan → regenerate proposals (no orders)
View Chain → Schwab RO chain (no 2FA)
Sell / Buy / Spread (ARMED) → preflight → intent → 2FA (Path B)
Open leg Close/Roll → same Path B / Lifecycle ticket-2fa
BUY_READY notice → equity plan + (Stage 1D) options alt from cache → operator/CIO confirm — still no auto place
CIO options question → house facts + finalize_operator_reply (Stage 1C) — not a specialist bot
```

---

## E · Test / acceptance matrix (all asks)

| ID | Area | Pass criterion |
|---|---|---|
| T1–T6 | Stage 1 funnel | See A1.* |
| T8–T11 | Stage 1B open legs | See A1B.* |
| T12–T17 | Stage 1C CIO fluency/goals | See A1C.* |
| T18–T23 | Stage 1D BUY_READY options alt | See A1D.* |
| T24 | Path B | Unchanged ARMED-gated preflight |
| T25 | Unprotected chip | Still Open Trades, never Options |
| T26 | Drive SoT | Parent-store plan uploaded; repo mirror byte-synced |

---

## F · Immediate operator read

1. **Schwab chain + Path B work** (SPCX live spread is proof).  
2. **Owned CC suggestions remain thin** — funnel (Stage 1) names why; Stage 2 is your intent-map call.  
3. **Open Options / Lifecycle already manage legs** — Stage 1B makes P&L/criteria/margin honest.  
4. **CIO is not yet options-fluent on Telegram** and **no options goals exist** — Stage 1C.  
5. **BUY_READY notices are equity-only today** (your V example) — Stage 1D attaches capital-efficient alts from existing generators/cache, honest when absent.  
6. **No IV widen / no invented margin / no fake specialists / no auto goals.**

---

## G · Evidence commands

```bash
# holdings / funnel
curl -sS http://127.0.0.1:7777/api/v2/options/holdings-funnel | jq '.data.summary'

# open legs
curl -sS http://127.0.0.1:7777/api/v2/options/open-positions \
  | jq '.data.positions[0]|{pnl_status,action_criterion,margin_status,recommended_action}'

# cio goals (options lineage)
python3 -c "import json; g=json.load(open('data/cio/cio_goals_projection.json')); print(g['goal_count'], list(g['goals']))"

# desk cache vs BUY_READY alt class
python3 -c "import json; d=json.load(open('data/runtime/options_desk_latest.json')); print(d.get('by_symbol',{}).get('V'))"

# entry render has no options today (pre-1D)
rg -n "options|long_call|OPTIONS_ALT" scripts/lib/cio_entry_state.py
```

---

## H · Develop now vs later

| Work | Now? |
|---|---|
| This SoT (all asks P1–P7) | **Yes — this revision** |
| Stage 1 funnel | **CLOSED** PR #1215 |
| Stage 1B open-leg honesty | **Code on branch** — push, green CI, merge |
| Stage 1C CIO fluency + goal lineage stamps | **High-confidence develop** (no auto goals) |
| Stage 1D BUY_READY options alt | **High-confidence develop** (cache attach + honest none) |
| Stage 2 / 2G / 3 | **Operator** |
| Widen gates / invent margin / new strategies | **No** |

**Authority:** READ_ONLY_ADVISORY for implement PRs. MBI_BEHAVIOR = 0. Path B remains per-order 2FA.

---

## I · Drive sync

Prefer edit **this parent-store path** in place; keep repo `docs/` mirror identical.

```bash
# Search first — never `gog drive upload --dry-run` (uploads anyway)
gog drive ls --query "name contains 'plan-options-desk-holdings-strategies-20260924'"

# Upload/replace once into Trade_AI_Docs_v2 (folder id from prior sync):
gog drive upload --parent "1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z" \
  /home/johnclaw/.local/state/cursor/agent-stores/cursor_agent_stores/bc-5f36c3f9-c05b-4ca3-983d-4b3c5b7889ec/files/docs/plan-options-desk-holdings-strategies-20260924.md

# Companion skim (optional):
gog drive upload --parent "1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z" \
  /home/johnclaw/.local/state/cursor/agent-stores/cursor_agent_stores/bc-5f36c3f9-c05b-4ca3-983d-4b3c5b7889ec/files/docs/options-desk-operator-contract-20260924.md
```

If gog cannot see the folder from this host, run the same lines on the keyboard machine and paste the file id back into §J.

---

## J · Stage closure receipts

| Stage | Status | Evidence |
|---|---|---|
| Stage 1 holdings funnel | **CLOSED** | https://github.com/PatsKiller/tardeai/pull/1215 · head `ab2653724` · funnel API + Hub + tests |
| Stage 1B open-leg honesty | **CODE COMPLETE / PUSH PENDING** | `_monitor_position` pnl/criterion/margin · cards · `test_options_open_leg_honesty.py` |
| Stage 1C CIO fluency + goals | **PLANNED** (wire next) | Diagnosis: 0 options goals; demoted options_desk; templates + house facts + finalize_operator_reply |
| Stage 1D BUY_READY options alt | **PLANNED** (wire next) | Diagnosis: render_cio equity-only; V cache=CC wrong class for capital-efficient entry |
| Stage 2 intent map | **OPEN — operator** | Propose list; do not auto-apply |
| Stage 2G options goals mint | **OPEN — operator** | After 1C templates |
| Promote | **PENDING** | After CI green + merge — exact SHA; `release-write` if needed |
| Drive SoT | **THIS REVISION** | `drive_file_id: 1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z` · parent `1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR` · companion skim uploaded beside it |
