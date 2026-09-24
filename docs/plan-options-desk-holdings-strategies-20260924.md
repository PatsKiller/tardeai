# Plan: Options Desk — covered calls on holdings + Schwab chain + Path B 2FA + open-leg management

```
Status: ACTIVE
as_of: 2026-09-24T11:40:00-04:00
Measured at: hub holdings.json generated_at 2026-09-24 11:30:01 ET · live pin header 171770b01 · CC paste ~11:15–11:29 ET (8 ideas · 1 open legs · Portfolio sleeve 1 · Live eligible 1 · Blocked 7 · execution ARMED) · [CODE] Open Options / Lifecycle modules
Canonical store path: docs/plan-options-desk-holdings-strategies-20260924.md
Authority: product contract (operator expectation) + live Options Hub paste + options_engine / options_desk_enterprise / options_lifecycle_engine / OptionsHub Path B wiring
Supersedes: prior “gated not broken” take in this same file (10:45 ET); extends 11:35 product-contract rewrite with open-contract P&L / sell-vs-hold
See also: scripts/options_engine.py · scripts/options_lifecycle_engine.py · apps/command-center-v3/src/pages/OptionsHub.tsx · apps/command-center-v3/src/components/OptionPositionCardV4.tsx · apps/command-center-v3/src/components/options/OptionsLifecycleView.tsx · assets/portfolio_intent.yaml · AGENTS.md §2 / §17
```

**Verdict (product contract).** The desk is **partially meeting** six expectations. Schwab chain read + per-order 2FA (Path B) are **built and wired**. Covered-call / put / spread generators exist. Open Options + Lifecycle already compute **unrealized P&L**, **% premium captured**, and **Hold / Close / Roll / Harvest / Defend** — but **margin / buying-power impact is absent**, and sell-vs-hold can look silent when mark/entry is missing or the operator only sits on Proposals. Highest-confidence engineering: **holdings funnel + honest empty states + chain surfacing**, then **attach open-leg economics + criteria surfacing to existing monitor/lifecycle** — **no new strategy product, no unilateral IV/intent gate widening.**

---

## 0 · Product contract vs what ships today

| # | Operator expectation | Status | Evidence class |
|---|---|---|---|
| 1 | **Suggestions for covered calls on holdings John owns** | **PARTIAL** — generator exists; only income-intent + share/IV/edge survivors surface. Today **1** portfolio-sleeve idea (**V** CC). Size-eligible owned names (MCD, WMT, SPCX, XLB, XAR) produce **no** CC cards. | `[CODE]` `generate_covered_call_proposals` · `[VERIFIED]` holdings shares · paste Portfolio sleeve **1** |
| 2 | **Actual option calls from Charles Schwab chains** | **BUILT** — `GET /api/v2/schwab/option-chain` → `schwab_transport.get_option_chain`; Hub **View Chain** drills that endpoint with bid/ask highlight. Enterprise `live_eligible` requires a real chain contract (`require_chain_for_live: true`). | `[CODE]` `api_v2._schwab_option_chain` · OptionsHub `review_chain` |
| 3 | **Execute → per-order 2FA (Path B)** | **BUILT** when execution ARMED — card action → `POST /api/v2/options/preflight` → intent_id → Telegram/email / Broker Orders confirm. Paste: **execution ARMED**. Not auto-submit. | `[CODE]` OptionsHub `runPreflight` · paste |
| 4 | **Same for puts and other stock/options strategies** | **PARTIAL** — CSP / credit spread / protective put / paper deep-ITM exist. Protective puts on holdings often **0** after gates. CSPs are **conviction (non-owned)** by design. Spreads can be live-eligible (paste: SPCX credit spread). | `[CODE]` + paste Puts 5 / Spreads 2 |
| 5 | **On open contracts: show profit + margins** (live P&L, credit/debit economics, margin/BP where Schwab allows) | **PARTIAL** — live unrealized P&L + % captured + credit/debit economics exist on Open Options cards and Lifecycle `strategy_economics`. **Margin / buying-power impact per contract is not on those surfaces** (account BP exists elsewhere for equity sizing only). | `[CODE]` `_monitor_position` · `options_lifecycle_engine.strategy_economics` · OptionPositionCardV4 |
| 6 | **Suggest sell vs hold (and roll if path exists) with clear criteria — not silent positions** | **PARTIAL / BUILT-but-split** — `_monitor_position` emits Hold / Close for Profit / Roll / Cut Loss + `lifecycle_phase` (let_mature / harvest / defend) + rationale. Lifecycle tab adds HARVEST_FULL / HOLD / LET_MATURE / DEFEND / ROLL with why-now. Gaps: dual tabs (operator may never open Lifecycle); P&L “—” when entry/mark missing → looks silent; criteria not always printed as first-class chips on Open Options. | `[CODE]` `_monitor_position` · OptionsLifecycleView · paste **1 open legs** |

**Bottom line:** Path B + Schwab chain are not the gap. Gaps are **#1** (owned-book funnel honesty), **#5 margin/BP**, and **#6 criteria visibility** on the legs John is already trading — attach to existing open-legs / lifecycle, do not invent a seventh strategy product.

---

## 1 · Fresh CC paste (~11:15–11:29 ET) — decoded

| UI line | Meaning | Broken? |
|---|---|---|
| **8 ideas · 1 open legs · gate 62+/sleeve 52+ · 30 need action · execution ARMED** | Desk regenerating; Path B armed; 30 = trading triage / queue surface, not “30 CC ideas missing” | No — Armed is good |
| **Portfolio sleeve only 1** | `_proposal_sleeve`: only `covered_call` + `protective_put` count as portfolio. One CC (V) ⇒ sleeve=1 | **Product miss** on owned book, not a counter bug |
| **Live eligible 1 / Blocked 7** | `enterprise.live_eligible` needs chain contract + liquidity + no earnings blackout. BS-estimate / thin chain → blocked | Mostly **honest enterprise gates**; one live row (SPCX spread) matches paste |
| **SPCX $138/$130 credit spread · Schwab live · 2FA required · live eligible · schwab rollover ira** | Proof of #2+#3 on a **spread**, not on a covered call | Working Path B card |
| **Deep ITM Call PAPER 0/30** | Educational paper model — not live Schwab stock-replacement | **Mislabeled risk** if read as live desk health |
| **Unprotected AMANX·SCHG** | Open-trades **stop** triage — AMANX 63 sh / SCHG 0.23 sh cannot cover a call anyway | **Vocabulary collision**, not CC outage |
| **Near stop MCD·V·SPCX** | Stock stop proximity | Orthogonal to options |
| **Queue blocked 31 · paper pending 31** | Approval / paper lanes | Separate from holdings CC generator |
| **Header 171770b01 vs footer 5f270ee0** | Stale SPA bundle / hard-refresh | Pin/UI mismatch — refresh CC |
| **Finviz 10/11 DEGRADED · PORTFOLIO STALE** | Quote coverage / holdings freshness | Hurts marks & IV proxies; not “chain API dead” |

---

## 2 · Why Portfolio sleeve = 1 while he owns many names

### 2.1 Share floor (correct)

`MIN_HOLDING_SHARES_CC = 100`, `MIN_POSITION_MV = $1k`. Hub book `[VERIFIED]` 2026-09-24 11:30 ET:

| Symbol | Shares (agg) | CC size? |
|---|---|---|
| XLB | 504 | yes |
| SPCX | 400 | yes |
| WMT | 400 | yes |
| MCD | 300 | yes |
| V | ~131 (Roth ~130 + IRA frac) | yes — **the one that slots** |
| XAR | 100 | yes |
| AMANX | 63 | **no** |
| SCHG / SCHD / most dust | ≪100 | **no** |

Unprotected chips naming AMANX/SCHG are stop gaps on names that **cannot** be CC’d at current size.

### 2.2 Intent map is tiny (policy)

`covered_call_candidate`: **V · LMT · SCHD** only. Those get relaxed edge (≥52) and skip strict IV when soft. Comment on V still says “631 shares” — stale vs ~131. LMT not held; SCHD fractional. **Operator-only** to expand (`§17`-adjacent trading policy).

### 2.3 IV / edge / chain (gates firing, not a dead loop)

Non-intent size-eligible names need `iv_rank ≥` settings floor (YAML cites **25**; engine default **20**) and edge ≥ **62** / POP ≥ **52**. Low-VIX tape → most owned names drop **silently** — no card, no reason. That silence is the recurring “is it broke?” failure.

### 2.4 Live eligible = 1 is a different axis

Sleeve counts **strategy family**. Live eligible counts **Schwab-fillable** rows (`contract is not None`, liquidity, no blackout). A BS-estimate CC can appear as an idea but stay blocked. Paste’s single live-eligible card is the SPCX spread with a real chain — consistent with code.

---

## 3 · Broken vs mislabeled vs never built

| Claim | Class | Notes |
|---|---|---|
| Options strategies never built | **False / never-built myth** | CC, CSP, protective put, credit spread, paper deep-ITM all in `options_engine` |
| Schwab chain not connected | **False** | Read-only chain API + View Chain drill |
| Path B 2FA missing | **False** | Preflight → intent → approve; requires ARMED (paste shows ARMED) |
| Covered calls broken for all holdings | **False** | V CC lives; others fail share/IV/intent **silently** |
| Desk meets “suggestions on what I own” | **Product gap (PARTIAL)** | Funnel + empty-state honesty missing; intent map too narrow for operator expectation |
| Unprotected = no CC ideas | **Mislabeled** | Stop triage |
| Deep ITM 0/30 = live desk broken | **Mislabeled** | Paper validation strip |
| Footer SHA ≠ header | **Ops / stale UI** | Hard-refresh |
| Widen IV/intent globally to “fix” empty sleeve | **Out of scope without operator word** | Stage 2/3 only |
| Open legs have no P&L or sell/hold at all | **False** | `_monitor_position` + Lifecycle economics already recommend Hold/Close/Roll/Harvest |
| Open legs show margin / BP impact | **Never built on options surfaces** | Account BP exists for equity sizing; not stamped on option legs |
| Sell vs hold is silent | **Partial / UX** | Logic exists; dual tabs + missing marks make it feel silent |

---

## 3A · Open contracts — what Open Options / Lifecycle already show vs missing

Paste: **1 open legs · 30 need action**. “30 need action” is trading triage (stops / queue), not 30 option closes. The **one** open option leg is the management surface for contract #5/#6.

### Already built (attach here — do not rebuild)

| Surface | What it shows | Module |
|---|---|---|
| **Open Options** tab | Per-leg unrealized P&L, mark vs avg entry, % premium captured (short), moneyness, DTE, POP, `lifecycle_phase` chip (LET MATURE / HARVEST / DEFEND), `recommended_action` + rationale, Action Required strip, Greeks + P&L profile chart, buttons Hold / View Chain / Close·Roll | `options_engine._monitor_position` · `OptionPositionCardV4` · `GET /api/v2/options/open-positions` |
| **Lifecycle** tab | Strategy-level (not loose-leg) economics: unrealized, credit/debit, `pct_max_profit_captured`, max profit/loss; decisions HARVEST_FULL / HOLD / LET_MATURE / DEFEND / ROLL / CLOSE with urgency + rationale + alternatives; close ticket → approve → **2FA** → armed manual ticket | `options_lifecycle_engine.strategy_economics` + decision · `OptionsLifecycleView` · `/api/v2/options/lifecycle/*` |
| **Strategy Overview** | Aggregates: open positions count, needs action, total unrealized P&L, ITM/OTM | `get_overview` / monitor summary |

### Sell vs hold criteria already in code (`_monitor_position`) — `[CODE]`

| Situation | Recommendation |
|---|---|
| Short call ITM + DTE ≤7 | **Roll** to next expiration |
| Short call/put OTM + high POP + unrealized > 0 | **Close for Profit** |
| Short call OTM + POP ≥60 | **Hold** (working) |
| Short call ITM (not expiry week) | **Close / Roll** |
| Short put ITM + DTE ≤10 | **Close** |
| Long option down >50% of entry | **Cut Loss** |
| Long ITM + high finish-ITM prob + profit | **Take Profit** |

Lifecycle engine adds harvest thresholds (% of max profit captured), assignment findings, and **DATA_BLOCKED** when marks/basis insufficient — fail-closed, not invented P&L.

### Missing / weak for product contract #5–#6

| Gap | Class | Fix direction |
|---|---|---|
| **Margin / buying-power impact per open option** | **Never built** on Open Options or Lifecycle economics | Stage 1B: stamp Schwab-sourced BP/margin fields **when the API returns them**; else honest `margin: UNKNOWN — Schwab field not on this feed` — never invent Reg-T |
| **Credit/debit $ at open** not always first-class on Open Options card | **Partial** | Surface entry credit/debit + max profit beside P&L (Lifecycle already has this; mirror onto Open Options from same economics) |
| **Dual tabs** — Proposals vs Open Options vs Lifecycle | **UX / discoverability** | Cross-link: if open legs > 0, Proposals header links “N open — manage on Open Options / Lifecycle”; do not merge into a new product |
| **Silent “—” P&L** when `avg_entry` or chain mark missing | **Honesty gap** | Explicit `PNL_UNKNOWN` reason chip (no fill basis / no chain mark) instead of blank |
| **Roll path** | **Built** | Open Options `roll` button + Lifecycle ROLL + ticket-build; ensure roll action still lands on Path B / manual ticket — do not invent a new roll strategy type |
| **Criteria not printed** | **Partial** | Show the firing rule in plain English on the card (“Close: POP OTM ≥75% and unrealized > 0”) — criteria already in code, just not operator-visible as a checklist |

**Rule:** attach to existing open-legs + proposal lifecycle. **No new strategy product.** No unilateral gate widening.

---

## 4 · Action map: Force scan · View Chain · Sell Credit Spread → 2FA

```
Force scan
  OptionsHub.forceRefresh()
    → GET /api/v2/options/proposals?force=1
    → options_engine.generate_proposals(force=True)
    → regenerates cache; does NOT place orders; does NOT skip enterprise blocks

View Chain
  handleAction('review_chain')
    → drill /api/v2/schwab/option-chain?symbol=SYM&strikes=12
    → schwab_transport.get_option_chain (READ-ONLY)
    → no 2FA

Sell Covered Call / Sell Put / Buy Put / Buy Call / Sell Credit Spread
  (execution_mode auto / Schwab)
    → require execStatus.armed_for_execution
    → POST /api/v2/options/preflight { proposal_id, account_key }
    → on ok: pending intent_id → operator 2FA (Telegram / email / Broker Orders)
    → broker submit only after consume(intent)  [Path B — per-order]
  (Fidelity / manual / auto_eligible=false)
    → ManualTicketSeed modal — no API 2FA path
```

**SPCX paste card** is the end-to-end proof of Sell Credit Spread → Schwab live path · 2FA required · live eligible.

**Open leg Close / Roll / Harvest** (existing Path B attach — do not invent a new product):

```
Open Options card → Close / Roll button
  → same execActions / preflight OR Lifecycle ticket-build → ticket-approve → ticket-2fa → armed manual ticket
  → never auto-closes; UI must keep saying so

Lifecycle tab → ACTION NOW / HARVEST / DEFEND sections
  → decision.recommendation + rationale (criteria) + economics (P&L, % captured)
  → Close ticket modal (hash-bound) → 2FA → manual ticket
```

---

## 5 · Stages — diagnose → fix vs develop

### Stage 0 — Diagnose / clarity (docs + UI copy) — **FIX**

- Document product contract (this file) including open-contract #5/#6.
- Empty-state / triage copy: Unprotected ≠ no CC; Deep ITM = paper; sleeve=1 explained by funnel; “30 need action” ≠ 30 option closes.
- Operator: hard-refresh CC until footer matches `171770b01`.

### Stage 1 — Holdings funnel + honest empty states + chain surfacing — **DEVELOP NOW**

Highest-confidence gap John authorized (“If it needs to be developed, do so”).

1. **`build_holdings_funnel()`** in `options_engine.py` — per holding (non-cash):  
   `CC_ELIGIBLE | NEED_100_SHARES | MV_BELOW | NO_CHAIN | IV_BELOW_FLOOR | EDGE_BELOW | POP_BELOW | INTENT_BYPASS | AEGIS_REJECT | SLOTTED` (+ protective-put twin reasons).  
   **Does not change gates.**
2. **`GET /api/v2/options/holdings-funnel`** — read-only.
3. **OptionsHub** — panel under Ideas: owned-book drop summary; empty portfolio sleeve cites funnel counts; keep View Chain prominent on cards.
4. **Tests** — SCHG/AMANX → NEED_100_SHARES; ≥100 fixture with low IV → IV_BELOW_FLOOR; intent name can show INTENT_BYPASS; register in CI allowlist.

Prove against today’s book: SCHG/AMANX NEED_100; MCD/WMT/SPCX/XLB/XAR named IV/EDGE/NO_CHAIN (not silent); V SLOTTED or INTENT path.

### Stage 1B — Open-leg P&L / criteria / margin honesty — **DEVELOP NEXT** (attach to existing monitor + lifecycle)

Product contract #5/#6. **No new strategy type.**

1. **Open Options card honesty**
   - Always show: unrealized P&L **or** `PNL_UNKNOWN` with reason (missing `avg_entry` / no chain mark).
   - Surface entry credit/debit + max profit beside % captured (mirror Lifecycle `strategy_economics` fields onto the leg card where single-leg).
   - Print the **firing criterion** under recommended action (e.g. “Close for Profit — POP OTM ≥75% and unrealized > 0”).
2. **Cross-link discoverability**
   - When `open_positions ≥ 1`, Proposals strip: “N open legs — Open Options / Lifecycle for sell vs hold.”
3. **Margin / buying-power**
   - Probe Schwab position/balance payloads for any option margin / BP effect fields already returned.
   - If present: stamp on Open Options + Lifecycle economics with `as_of` + source.
   - If absent: render `MARGIN_UNKNOWN — not on Schwab feed used here` — **never invent Reg-T or a guessed requirement**.
4. **Roll**
   - Keep existing Roll button + Lifecycle ROLL + ticket-build; verify Path B / manual ticket still the only execute path. No new roll product.
5. **Tests**
   - Hermetic: missing entry → `PNL_UNKNOWN` not silent dash-only.
   - Hermetic: short OTM + high POP + positive PnL → recommended Close for Profit + criterion string present.
   - Hermetic: margin field absent → UNKNOWN status, never a fabricated dollar.

### Stage 2 — Intent map refresh — **OPERATOR ONLY**

Propose adding size-eligible income names the operator wants (e.g. MCD, WMT, SPCX) to `covered_call_candidate`; remove LMT/SCHD until ≥100 held. Agent proposes list + stops. **No auto-apply.**

### Stage 3 — Optional low-VIX owned-name policy — **OPERATOR DECISION**

Only if Stage 2 is too manual: e.g. shares≥100 & VIX&lt;18 → relaxed IV with explicit `fallback_tier` flag. **Do not ship without word.**

### Stage 4 — Protective-put funnel visibility — **DEVELOP** (can ride Stage 1)

Same reasons for `puts: 0` on large owned names.

### Stage 5 — Out of scope

Broker auto-submit, **new strategy types**, treating Deep ITM paper as live, unilateral gate widening, inventing option margin math without Schwab fields, Finviz quote remediation (separate).

---

## 6 · Test plan

| # | Test | Pass |
|---|---|---|
| T1 | Funnel SCHG/AMANX | `NEED_100_SHARES` |
| T2 | Funnel ≥100 low-IV non-intent fixture | Named `IV_BELOW_FLOOR` or `EDGE_BELOW` — never silent omit |
| T3 | Intent CC path | `INTENT_BYPASS` or `SLOTTED` when gates pass |
| T4 | API route | `GET /api/v2/options/holdings-funnel` returns `rows` + `summary` |
| T5 | Hub empty portfolio | Surfaces funnel summary, not only “edge ≥62” |
| T6 | View Chain / preflight | Unchanged — no gate widen; Path B still ARMED-gated |
| T7 | Unprotected chip | Still Open Trades, never Options |
| T8 | Open leg missing entry/mark | `PNL_UNKNOWN` + reason — not blank “—” only |
| T9 | Open leg sell vs hold | Recommended action + **criterion string** from `_monitor_position` rules |
| T10 | Margin when Schwab field absent | `MARGIN_UNKNOWN` — never invented dollars |
| T11 | Lifecycle close ticket | Still hash-bound → 2FA; no auto-close |

---

## 7 · Immediate operator read

1. **Contract #2 and #3 are met** (Schwab chain + Path B 2FA when ARMED) — SPCX card is the proof.  
2. **Contract #1 is not met at product depth** — one portfolio CC (V) while six+ names are size-eligible; silence is the bug surface.  
3. **Contract #5/#6 are partial** — Open Options + Lifecycle already do P&L and Hold/Close/Roll/Harvest; open the **Open Options** or **Lifecycle** tab for the 1 open leg. Margin/BP per contract is the real miss; dual-tab discoverability makes sell-vs-hold feel silent.  
4. **Do not widen IV/intent to fake fullness** — Stage 1 funnel first; Stage 1B attaches economics/criteria to existing legs; Stage 2 is your call which names are income.  
5. **Hard-refresh** so footer SHA matches `171770b01`. Unprotected AMANX/SCHG is stops, not options. “30 need action” is not 30 option closes.

---

## 8 · Evidence commands

```bash
# holdings share floor (hub)
python3 -c "import json; h=json.load(open('.../holdings.json')); ..."

# after Stage 1
curl -sS http://127.0.0.1:7777/api/v2/options/holdings-funnel | jq '.data.summary'
curl -sS 'http://127.0.0.1:7777/api/v2/schwab/option-chain?symbol=V&strikes=4'
curl -sS http://127.0.0.1:7777/api/v2/options/execution/status

# open legs / lifecycle (contract #5/#6)
curl -sS http://127.0.0.1:7777/api/v2/options/open-positions | jq '.data.positions[0]|{underlying,unrealized_pnl,recommended_action,lifecycle_phase,avg_entry,mark}'
curl -sS http://127.0.0.1:7777/api/v2/options/lifecycle | jq '.data.positions[0]|{decision,economics}' 2>/dev/null || true

grep -n "covered_call_candidate\|MIN_HOLDING_SHARES_CC\|live_eligible\|build_holdings_funnel\|_monitor_position\|strategy_economics" \
  scripts/options_engine.py scripts/options_lifecycle_engine.py scripts/options_desk_enterprise.py assets/portfolio_intent.yaml
```

---

## 9 · Develop now vs later

| Work | Now? |
|---|---|
| This plan (product-contract + open-leg #5/#6) | **Yes** |
| Stage 1 funnel API + Hub panel + tests + PR | **Yes — implement** (authorized) |
| Stage 1B open-leg P&L/criteria/margin honesty | **Next** after Stage 1 lands — attach to existing monitor/lifecycle |
| Stage 2 intent YAML | **Operator** — propose, wait |
| Widen IV/intent globally | **No** |
| Invent option margin without Schwab fields | **No** |
| New options strategy product | **No** |
| Rebuild options subsystem | **No** |

**Authority:** READ_ONLY_ADVISORY for implement PR. No broker orders. MBI_BEHAVIOR = 0. Path B remains per-order 2FA.

---

## 10 · Drive sync

Prefer editing this file in place (agent store + repo `docs/` copy). If Drive sync is blocked from the agent host, run on the keyboard:

```bash
# From the machine that has gog authenticated — search first; do NOT use gog drive upload --dry-run (uploads anyway)
gog drive ls --query "name contains 'plan-options-desk-holdings-strategies-20260924'" 
# then upload/replace once into Trade_AI_Docs_v2 (or the folder John uses for plans)
```

Exact keyboard line once folder id is known:

```bash
gog drive upload --parent "<TRADE_AI_DOCS_FOLDER_ID>" \
  /home/johnclaw/.local/state/cursor/agent-stores/cursor_agent_stores/bc-5f36c3f9-c05b-4ca3-983d-4b3c5b7889ec/files/docs/plan-options-desk-holdings-strategies-20260924.md
```
