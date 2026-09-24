# Plan: Options Desk — holdings strategies · open legs · CIO fluency · goals · BUY_READY institutional packet

```
Status: ACTIVE
as_of: 2026-09-24T12:10:00-04:00
Measured at: hub holdings ~11:30 ET · CC paste ~11:15 ET · cio_goals 4/0 options · options_desk_latest V=CC · PR #1215 head 7e02f36eb (1B pushed) · local 590b41d0b (1C/1D wire) · implement approved 12:08 ET
Canonical store path (parent / SoT):
  /home/johnclaw/.local/state/cursor/agent-stores/cursor_agent_stores/bc-5f36c3f9-c05b-4ca3-983d-4b3c5b7889ec/files/docs/plan-options-desk-holdings-strategies-20260924.md
Repo mirror: docs/plan-options-desk-holdings-strategies-20260924.md
Companion skim: docs/options-desk-operator-contract-20260924.md — linked; **this file is authoritative**
Authority: operator product contract (John) + implement approval 2026-09-24 · CreatePlan overview mirrored here (CreatePlan artifact is NOT edited)
Supersedes: 11:55 SoT revision — expands P6 to institutional BUY_READY packet; adds **P8** thesis vs structure indicators; Google Notes roles→module map; production CIO/options prompt
See also: AGENTS.md §2/§6/§17 · scripts/lib/cio_options_fluency.py · scripts/lib/cio_entry_state.py · scripts/options_engine.py · scripts/lib/cio_goals.py · artifacts/plans/buy_ready_options_cio_59a1a12f.plan.md (read-only)
Drive: file 1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z · parent 1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR
```

**One-line verdict.** Path B + Schwab chain are **built**. Funnel (1) + open-leg honesty (1B) are on PR #1215. Gaps that this implement closes: **institutional BUY_READY packet** (equity + options + compare + CIO Approve/Reject/Modify), **P8 indicator split** (PE for thesis; IV/expected-move/Greeks for structure), **CIO fluency + goal lineage**. No new strategy types, no IV widen, no invented margin, no auto-trade.

---

## A · Full product contract (P1–P8)

| # | Operator ask | Status | Stage |
|---|---|---|---|
| **P1** | CC/CSP/puts/spreads + Schwab chain + Path B 2FA | PARTIAL/BUILT — generators+chain+Path B; owned sleeve thin | **1** CLOSED · **2** operator intent |
| **P2** | Open-leg P&L / margins / sell-hold-roll criteria | PARTIAL→1B on PR | **1B** pushed `7e02f36eb` |
| **P3** | CIO knowledgeable on all desk strategies | WIRED local `590b41d0b` (catalog + options_strategy intent) | **1C** |
| **P4** | CIO advises/opines via real desk / `finalize_operator_reply` | WIRED local — house-facts card, no specialist persona | **1C** |
| **P5** | Strategy goals → security / sector / industry | ABSENT goals (0 options); lineage stamp + schema extend | **1C** · **2G** operator mint |
| **P6** | **Institutional BUY_READY packet** — equity sizing **+** capital-efficient options alt **+** comparative table **+** CIO Approve/Reject/Modify **+** Path B | PARTIAL wire (alt line) → expand to full packet | **1D** |
| **P7** | Holdings funnel (named drop reasons) | **CLOSED** | **1** |
| **P8** | **Thesis vs structure indicators** — PE/fundamentals grade thesis; IV/HV/expected-move/Greeks/OI pick structure. PE never picks strikes. Cite drivers. | NOT BUILT | **1D-indicators** |

**Non-goals:** invent strategies · widen IV/intent · invent margin $ · auto-submit · fake specialists · auto-mint goals · Deep ITM paper as live health.

---

## A2 · Google Notes gap analysis vs live V BUY_READY signal

John morning notice (example):

> Entry state BUY_READY for V … price $367.53, zone $364.50–$369.00, stop $357.50, target $410.00, R:R 3.57. Plan source reentry_desk. Confirm or refute…

| Google Notes / institutional expectation | Live today | Gap class |
|---|---|---|
| Equity entry + size + R:R | Zone/stop/target/R:R present; **size often absent** on CIO text | Expand P6 equity packet |
| Capital-efficient options alt mapped to same zone/stop/target | **Absent** on notice (pre-1D); desk cache for V is **covered_call** (wrong class for new buy) | Stage 1D — preferred `long_call` / debit / deep-ITM; honest `WRONG_STRATEGY_CLASS` |
| Comparative stock vs options (capital, max loss, best case) | Absent | Stage 1D comparative block |
| CIO Approve / Reject / Modify both legs | “Confirm or refute” only — no structured CIO verdict | Stage 1D + real desk finalize |
| Thesis indicators (PE, catalyst, RS) | Not on entry notice | **P8** thesis stack |
| Structure indicators (IV, expected move, Greeks, OI) | On proposal cards in Hub, not on BUY_READY Telegram | **P8** structure stack |
| Portfolio risk / heat | Not on entry notice | Attach existing desk risk facts |
| Path B 2FA before submit | Built on Hub; notice must say so | Keep / reinforce in packet chrome |
| Seven parallel “agents” (Signal/Quant/Strategy/Risk/CIO/Compliance/Auth) | Must **map to existing modules** — not spawn personas | See §A3 |

---

## A3 · Meta-prompt roles → Trade-AI module map (locked)

| Meta-prompt role | Trade-AI owner | Notes |
|---|---|---|
| Signal Generation | `reentry_desk` + `cio_entry_state_runner` | BUY_READY / ENTRY_NEAR |
| Quant Validation | `options_engine` + Schwab chain / Greeks | Cache-first on notices; live chain on Hub View Chain |
| Options Strategy | `options_engine` STRATEGY_SLOTS + pipeline matcher | long_call / debit / credit / deep_itm paper when gated |
| Portfolio Risk | holdings + desk risk / heat / concentration | Existing gatherers — do not invent |
| CIO Review | `cio_operator_desk_loop` + `finalize_operator_reply` | Approve / Reject / Modify — **no fake Iris/Alex** |
| Compliance | Path B preflight; advisory chrome; MBI_BEHAVIOR=0 | |
| Operator Authorization | Path B per-order 2FA | Never bypass |

---

## A4 · Production CIO / options prompt (house text)

Use as the deterministic card + Flash wording constraints (numbers only from house facts):

```
You are the Trade-AI CIO desk (READ_ONLY_ADVISORY). Review BOTH:
  (A) equity BUY_READY packet and (B) any options alternative.
Return exactly one of: APPROVE | REJECT | MODIFY_<what>.
Cite Sources from house facts only. Never invent PE, IV, strikes, or margin $.
If options unsuitable, say so with indicator causes (IV/liquidity/DTE/class).
PE/fundamentals grade the equity thesis; IV/expected-move/Greeks grade structure —
do not use PE to pick strikes. Path B 2FA required before any live submit.
No specialist roleplay. No orders from chat.
```

---

## B · Diagnosis receipts (measured)

### B1 Holdings / Path B / funnel
Portfolio sleeve paste **1** (V CC). Size-eligible: XLB/SPCX/WMT/MCD/V/XAR. Intent map V·LMT·SCHD. Schwab chain + Path B **BUILT**. Funnel API **CLOSED** Stage 1.

### B2 Open legs
P&L/% captured / Hold·Close·Roll built. Stage 1B: `PNL_UNKNOWN` · `action_criterion` · `MARGIN_UNKNOWN` — pushed `7e02f36eb`.

### B3 CIO fluency / goals
4 open goals, **0** options-ish. `options_desk` demoted secondary. Local wire: `cio_options_fluency` + `options_strategy` intent (`590b41d0b`, push pending).

### B4 BUY_READY options
`render_cio` was equity-only. Local 1D appends options alt / honest NONE. V cache=CC → `WRONG_STRATEGY_CLASS`. Full institutional packet (compare + CIO verdict + P8) still to finish this implement.

---

## C · Stages

### Stage 0 — Clarity — FIX
Vocabulary: Unprotected≠no CC; Deep ITM≠live; “30 need action”≠option closes.

### Stage 1 — Holdings funnel — **CLOSED** (PR #1215 · `ab2653724`)
Acceptance A1.1–A1.6 (named drop reasons; no gate widen).

### Stage 1B — Open-leg honesty — **CLOSED on remote** (`7e02f36eb`)
Acceptance A1B.1–A1B.5. Design-token funnel fix included.

### Stage 1C — CIO fluency + strategy goals — **WIRED locally** (`590b41d0b`) · extend this implement
- Catalog of desk strategies; `options_strategy` intent; house facts → `finalize_operator_reply`.
- `goal_lineage` LINKED/ABSENT; stamp `linked_sector` / `linked_industry` / `strategy_id` on lineage dict (schema: additive fields on stamp; `create_goal` optional kwargs later — **no auto-mint**).
- Acceptance A1C.1–A1C.6.

### Stage 1D — Institutional BUY_READY packet — **IN PROGRESS**
Must ship on every BUY_READY / ENTRY_NEAR (and reentry symbol reply when inside zone):

1. **Equity packet** — price, zone, stop, target, R:R, size hint when known, plan_source.
2. **Options packet** — preferred capital-efficient class (`long_call` / debit / deep_itm paper); else `OPTIONS_ALT_NONE` with reason (`WRONG_STRATEGY_CLASS` · `NONE_ON_CACHE` · IV/liquidity/DTE).
3. **Comparative block** — stock vs options: capital at risk, max loss, best-case, breakeven.
4. **CIO verdict slot** — APPROVE | REJECT | MODIFY_* via real desk path / finalize (structured chrome on notice; interactive modify on Telegram desk).
5. **Path B chrome** — View Chain → preflight → 2FA; never auto-submit.
6. **P8 stacks** (Stage 1D-indicators) — see §C1D-P8.

Litmus V: zone $364.50–$369 · stop $357.50 · target $410 + defined-risk alt **or** printed unsuitable with causes — not bare “confirm or refute.”

Acceptance A1D.1–A1D.6 plus:
| ID | Check |
|---|---|
| A1D.7 | Comparative capital / max loss / breakeven present when alt OK |
| A1D.8 | CIO verdict token APPROVE\|REJECT\|MODIFY present on packet |
| A1D.9 | Sources/GUID chrome via finalize when desk-path |

### Stage 1D-indicators (P8) — **DEVELOP this implement**

**Equity thesis stack** (confirm/refute BUY_READY): PE / forward PE / PEG when on file · earnings/catalyst · sector RS · house research GUID · confidence · zone/stop/target coherence.

**Options structure stack** (pick strike/expiry/strategy): IV rank / percentile · HV vs IV · expected move vs distance-to-target · DTE vs catalyst · delta/gamma/theta/vega · OI+volume · bid-ask · skew.

**Rule:** PE grades whether the bullish thesis is good enough to express with options; **PE does not pick strikes.** Output cites which indicators drove thesis score, strategy class, strike, expiry, and why neighbors lost.

Acceptance:
| ID | Check |
|---|---|
| A1D.P8.1 | PE (or explicit MISSING) in thesis section only |
| A1D.P8.2 | IV / expected-move / Greeks in structure section |
| A1D.P8.3 | Driver citation lines present |
| A1D.P8.4 | No PE→strike coupling in code (test) |

### Stage 2 / 2G / 3 / 4 / 5
Unchanged: intent map operator-only; mint options goals operator-only; low-VIX policy operator; protective-put funnel; out-of-scope list.

---

## D · Action map

```
Force scan → proposals (no orders)
View Chain → Schwab RO
Sell/Buy/Spread ARMED → preflight → 2FA (Path B)
BUY_READY notice → equity + options packet + compare + CIO verdict chrome → operator chooses → Path B
CIO options ask → house facts + finalize_operator_reply
```

---

## E · Test / acceptance matrix

T1–T6 Stage 1 · T8–T11 Stage 1B · T12–T17 Stage 1C · T18–T23+A1D.7–9 Stage 1D · A1D.P8.* indicators · T24 Path B · T25 Unprotected · T26 Drive SoT.

**V litmus (binding):** notice includes equity + options alt **or** unsuitable with indicator causes; CIO verdict present; comparative capital/max loss/breakeven when alt OK; 2FA required before submit; PE in thesis / IV+Greeks in structure — not swapped.

---

## F · Immediate operator read

1. Schwab + Path B work. 2. Funnel+1B on #1215. 3. BUY_READY must become institutional packet (this implement). 4. P8 splits PE vs IV roles. 5. No IV widen / no invented margin / no fake specialists / no auto goals. 6. Push grant needed for `590b41d0b` (Telegram notify failed — approve out of band: request `01d7687b8caf71df`).

---

## G · Evidence commands

```bash
curl -sS http://127.0.0.1:7777/api/v2/options/holdings-funnel | jq .data.summary
python3 -c "from scripts.lib.cio_options_fluency import select_entry_options_alternative as s; print(s('V'))"
rg -n "OPTIONS_ALT|thesis_indicators|structure_indicators|cio_verdict" scripts/lib/cio_options_fluency.py scripts/lib/cio_entry_state.py
```

---

## H · Develop now vs later

| Work | Now? |
|---|---|
| SoT P6 expand + P8 + Google Notes map + prompt | **This pass** |
| Stage 1D full packet + comparative + CIO verdict | **This pass** |
| Stage 1D-indicators P8 stacks | **This pass** |
| Stage 1C goal lineage sector/industry stamp | **This pass** |
| Push `590b41d0b` + follow-ups | When git-push granted |
| Merge/promote #1215 | When CI green; no --admin |
| Stage 2 / 2G / 3 | Operator |

---

## I · Drive sync

```bash
gog drive upload --replace 1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z \
  <parent-store>/docs/plan-options-desk-holdings-strategies-20260924.md
```

Never `gog drive upload --dry-run`.

---

## J · Stage closure receipts

| Stage | Status | Evidence |
|---|---|---|
| Stage 1 funnel | **CLOSED** | PR #1215 · `ab2653724` |
| Stage 1B open-leg | **CLOSED remote** | `7e02f36eb` · frontend green |
| Stage 1C fluency/goals | **WIRED local → extend** | `590b41d0b` + this implement stamps |
| Stage 1D BUY_READY packet | **IN PROGRESS** | alt line exists; packet/compare/verdict/P8 this implement |
| Stage 1D-indicators P8 | **IN PROGRESS** | |
| Stage 2 / 2G | **OPEN — operator** | |
| Promote | **PENDING** | CI green + merge + release-write |
| Drive SoT | **THIS REVISION** | replace after write |
